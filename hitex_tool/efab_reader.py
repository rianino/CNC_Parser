"""Read and parse EFAB .brt tufting robot exports from eDesigner.

The .brt format is a proprietary binary file containing:
  1. A structured header with design dimensions and colour count
  2. A 24-bit BMP thumbnail image (256x256)
  3. A 4-byte gap
  4. An 8-bit paletted TIFF image (LZW compressed) — the stitch map
     where each pixel = one stitch position, palette index = colour

Colour area and coverage percentages are derived from pixel counts
in the stitch map.
"""

from __future__ import annotations

import io
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
import numpy as np

# Guard against decompression bombs — allow up to 100 megapixels
Image.MAX_IMAGE_PIXELS = 100_000_000

# Maximum raw file size to read (50 MB)
_MAX_BRT_SIZE = 50 * 1024 * 1024


@dataclass
class EfabColour:
    """A single colour in the EFAB design."""

    index: int
    r: int
    g: int
    b: int
    hex: str
    pixel_count: int
    area_mm2: float
    percentage: float  # percentage of total design area (excluding background)


@dataclass
class EfabExport:
    """Parsed EFAB .brt export."""

    file_path: str
    # Header fields
    header_version: int
    num_colours: int  # includes background
    grid_width: int  # stitch grid width
    grid_height: int  # stitch grid height
    width_mm: float  # physical width
    height_mm: float  # physical height
    header_value_f64: float  # unknown metric at offset 8 (possibly yarn-related)
    # Derived data
    colours: list[EfabColour] = field(default_factory=list)
    background_pixels: int = 0
    design_pixels: int = 0
    design_area_mm2: float = 0.0
    stitch_pitch_x_mm: float = 0.0  # mm per stitch horizontally
    stitch_pitch_y_mm: float = 0.0  # mm per stitch vertically
    # Raw images (optional, not serialized)
    thumbnail: Image.Image | None = field(default=None, repr=False)
    stitch_map: Image.Image | None = field(default=None, repr=False)


def read_brt(path: str | Path, load_images: bool = True) -> EfabExport:
    """Parse an EFAB .brt file.

    Args:
        path: Path to the .brt file.
        load_images: If True, keep PIL Image objects for thumbnail and stitch map.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EFAB file not found: {path}")

    file_size = path.stat().st_size
    if file_size > _MAX_BRT_SIZE:
        raise ValueError(f"File too large: {file_size} bytes (max {_MAX_BRT_SIZE})")

    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 95:
        raise ValueError(f"File too small to be a valid EFAB .brt: {len(data)} bytes")

    # --- Parse header (bytes 0-94) ---
    header_version = struct.unpack_from("<I", data, 0)[0]
    header_value_232 = struct.unpack_from("<I", data, 4)[0]
    header_f64 = struct.unpack_from("<d", data, 8)[0]
    num_colours = struct.unpack_from("<I", data, 24)[0]
    grid_width = struct.unpack_from("<I", data, 40)[0]
    grid_height = struct.unpack_from("<I", data, 44)[0]
    width_mm = struct.unpack_from("<f", data, 48)[0]
    height_mm = struct.unpack_from("<f", data, 52)[0]

    # --- Locate BMP ---
    bmp_offset = 95
    if data[bmp_offset : bmp_offset + 2] != b"BM":
        raise ValueError(f"Expected BMP at offset {bmp_offset}, got {data[bmp_offset:bmp_offset+2]!r}")

    bmp_size = struct.unpack_from("<I", data, bmp_offset + 2)[0]

    # --- Locate TIFF ---
    # 4-byte gap after BMP, then TIFF
    tiff_search_start = bmp_offset + bmp_size
    tiff_offset = None
    for i in range(tiff_search_start, min(tiff_search_start + 16, len(data) - 4)):
        if data[i : i + 4] in (b"II\x2a\x00", b"MM\x00\x2a"):
            tiff_offset = i
            break

    if tiff_offset is None:
        raise ValueError("Could not locate TIFF stitch map in .brt file")

    # --- Decode images ---
    bmp_data = data[bmp_offset : bmp_offset + bmp_size]
    tiff_data = data[tiff_offset:]

    thumbnail = Image.open(io.BytesIO(bmp_data))

    # PIL needs a seekable file for TIFF LZW
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp.write(tiff_data)
        tmp_path = tmp.name

    try:
        stitch_map = Image.open(tmp_path)

        # --- Analyse stitch map ---
        palette = stitch_map.getpalette()
        pixels = np.array(stitch_map)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    stitch_pitch_x = width_mm / grid_width if grid_width else 0
    stitch_pitch_y = height_mm / grid_height if grid_height else 0
    stitch_area = stitch_pitch_x * stitch_pitch_y

    unique_vals, counts = np.unique(pixels, return_counts=True)

    background_pixels = 0
    design_pixels = 0
    colours: list[EfabColour] = []

    # First pass: count design pixels
    for val, cnt in zip(unique_vals, counts):
        if val == 0:
            background_pixels = int(cnt)
        else:
            design_pixels += int(cnt)

    # Second pass: build colour info
    for val, cnt in zip(unique_vals, counts):
        if val == 0:
            continue
        cnt_int = int(cnt)
        r = palette[val * 3] if palette else 0
        g = palette[val * 3 + 1] if palette else 0
        b = palette[val * 3 + 2] if palette else 0
        area = cnt_int * stitch_area
        pct = (cnt_int / design_pixels * 100) if design_pixels > 0 else 0

        colours.append(
            EfabColour(
                index=int(val),
                r=r,
                g=g,
                b=b,
                hex=f"#{r:02x}{g:02x}{b:02x}",
                pixel_count=cnt_int,
                area_mm2=area,
                percentage=round(pct, 2),
            )
        )

    # Sort colours by production order (palette index)
    colours.sort(key=lambda c: c.index)

    export = EfabExport(
        file_path=str(path),
        header_version=header_version,
        num_colours=num_colours,
        grid_width=grid_width,
        grid_height=grid_height,
        width_mm=width_mm,
        height_mm=height_mm,
        header_value_f64=header_f64,
        colours=colours,
        background_pixels=background_pixels,
        design_pixels=design_pixels,
        design_area_mm2=design_pixels * stitch_area,
        stitch_pitch_x_mm=stitch_pitch_x,
        stitch_pitch_y_mm=stitch_pitch_y,
        thumbnail=thumbnail if load_images else None,
        stitch_map=stitch_map if load_images else None,
    )

    return export
