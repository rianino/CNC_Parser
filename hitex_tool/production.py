"""Extract production-relevant data from vectorization files.

This module bridges the gap between raw vectorization exports (HITEX/EFAB)
and the production data Daniela needs: colour areas, yarn consumption
estimates, and design dimensions.

It replaces the manual Excel calculation step in the production flow.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .gcode_parser import TuftMode, parse_gcode


@dataclass
class ColourInfo:
    """Production data for a single colour/layer."""

    name: str
    colour_hex: str | None
    loop_cut_mode: str  # "Loop", "Cut", or "" if unknown
    area_mm2: float
    area_m2: float
    percentage: float  # of total design area
    tuft_length_mm: float  # total tufting path length for this colour
    tuft_length_m: float
    stitch_count: int  # number of stitches (tuft moves or pixels)


@dataclass
class FileParams:
    """Machine/stitch parameters extracted from the vectorization file."""

    escala_mm: float = 0.0  # stitch gauge/scale in mm
    densidade_10cm: float = 0.0  # stitch density per 10cm (derived from escala)


@dataclass
class ProductionData:
    """Unified production data extracted from any vectorization file."""

    source_file: str
    source_type: str  # "hitex" or "efab"
    # Design dimensions
    width_mm: float
    height_mm: float
    width_m: float
    height_m: float
    # Total stats
    total_design_area_mm2: float
    total_design_area_m2: float
    total_tuft_length_mm: float
    total_tuft_length_m: float
    # Per-colour breakdown
    colours: list[ColourInfo] = field(default_factory=list)
    # Extracted file parameters
    file_params: FileParams = field(default_factory=FileParams)


def _extract_hitex_escala(export) -> float:
    """Extract stitch scale (mm) from HITEX G-code row spacing.

    Uses the fill layer with the most tuft length (the background zigzag)
    and measures the median Y-spacing between consecutive rows.
    """
    best_layer = None
    best_length = 0.0

    for layer in export.layers:
        parsed = parse_gcode(
            text=layer.gcode_text,
            tuft_mode=TuftMode.MCODE,
            layer_feed_mm_min=layer.machine_speed,
        )
        if parsed.tuft_length_mm > best_length:
            best_length = parsed.tuft_length_mm
            best_layer = parsed

    if not best_layer or best_layer.tuft_moves < 10:
        return 0.0

    tuft_segs = [s for s in best_layer.segments if s.tuft]
    ys = sorted(set(round(s.start.y, 2) for s in tuft_segs))
    if len(ys) < 3:
        return 0.0

    spacings = [round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)]
    # Filter out outliers (spacings that are too small or too large)
    spacings = [s for s in spacings if 0.5 < s < 20]
    if not spacings:
        return 0.0

    return round(statistics.median(spacings), 2)


def from_hitex(zip_path: str | Path) -> ProductionData:
    """Extract production data from a HITEX .zop.zip export."""
    from .zip_reader import read_zip

    export = read_zip(zip_path)
    colours: list[ColourInfo] = []
    total_tuft_length = 0.0

    for layer in export.layers:
        parsed = parse_gcode(
            text=layer.gcode_text,
            tuft_mode=TuftMode.MCODE,
            layer_feed_mm_min=layer.machine_speed,
        )

        tuft_length = parsed.tuft_length_mm
        stitch_count = parsed.tuft_moves
        total_tuft_length += tuft_length

        colours.append(
            ColourInfo(
                name=layer.name,
                colour_hex=layer.layer_color,
                loop_cut_mode=layer.loop_cut_mode,
                area_mm2=0.0,
                area_m2=0.0,
                percentage=0.0,
                tuft_length_mm=round(tuft_length, 2),
                tuft_length_m=round(tuft_length / 1000, 3),
                stitch_count=stitch_count,
            )
        )

    # Percentage based on tuft length
    total_carpet_area_mm2 = export.width_mm * export.height_mm
    if total_tuft_length > 0:
        for c in colours:
            c.percentage = round(c.tuft_length_mm / total_tuft_length * 100, 2)
            c.area_mm2 = round(total_carpet_area_mm2 * c.percentage / 100, 2)
            c.area_m2 = round(c.area_mm2 / 1e6, 6)

    # Extract stitch parameters from G-code
    escala = _extract_hitex_escala(export)
    file_params = FileParams(
        escala_mm=escala,
        densidade_10cm=round(100 / escala, 1) if escala > 0 else 0.0,
    )

    return ProductionData(
        source_file=Path(zip_path).name,
        source_type="hitex",
        width_mm=export.width_mm,
        height_mm=export.height_mm,
        width_m=round(export.width_mm / 1000, 3),
        height_m=round(export.height_mm / 1000, 3),
        total_design_area_mm2=round(total_carpet_area_mm2, 2),
        total_design_area_m2=round(total_carpet_area_mm2 / 1e6, 6),
        total_tuft_length_mm=round(total_tuft_length, 2),
        total_tuft_length_m=round(total_tuft_length / 1000, 3),
        colours=colours,
        file_params=file_params,
    )


def from_efab(brt_path: str | Path) -> ProductionData:
    """Extract production data from an EFAB .brt export."""
    from .efab_reader import read_brt

    export = read_brt(brt_path, load_images=False)
    colours: list[ColourInfo] = []
    total_tuft_length = 0.0

    for ec in export.colours:
        tuft_length = ec.pixel_count * export.stitch_pitch_x_mm
        total_tuft_length += tuft_length

        colours.append(
            ColourInfo(
                name=f"Colour {ec.index}",
                colour_hex=ec.hex,
                loop_cut_mode="",
                area_mm2=round(ec.area_mm2, 2),
                area_m2=round(ec.area_mm2 / 1e6, 6),
                percentage=ec.percentage,
                tuft_length_mm=round(tuft_length, 2),
                tuft_length_m=round(tuft_length / 1000, 3),
                stitch_count=ec.pixel_count,
            )
        )

    escala = export.stitch_pitch_x_mm
    file_params = FileParams(
        escala_mm=round(escala, 2),
        densidade_10cm=round(100 / escala, 1) if escala > 0 else 0.0,
    )

    return ProductionData(
        source_file=Path(brt_path).name,
        source_type="efab",
        width_mm=export.width_mm,
        height_mm=export.height_mm,
        width_m=round(export.width_mm / 1000, 3),
        height_m=round(export.height_mm / 1000, 3),
        total_design_area_mm2=round(export.design_area_mm2, 2),
        total_design_area_m2=round(export.design_area_mm2 / 1e6, 6),
        total_tuft_length_mm=round(total_tuft_length, 2),
        total_tuft_length_m=round(total_tuft_length / 1000, 3),
        colours=colours,
        file_params=file_params,
    )


def auto_detect(file_path: str | Path) -> ProductionData:
    """Auto-detect file type and extract production data."""
    path = Path(file_path)
    name = path.name.lower()

    if name.endswith(".zop.zip") or name.endswith(".zip"):
        return from_hitex(path)
    elif name.endswith(".brt"):
        return from_efab(path)
    else:
        raise ValueError(
            f"Unknown vectorization file type: {path.suffix}. "
            "Supported: .zop.zip (HITEX), .brt (EFAB)"
        )


def to_dict(pd: ProductionData) -> dict:
    """Convert production data to a JSON-serializable dict."""
    return {
        "source_file": pd.source_file,
        "source_type": pd.source_type,
        "dimensions": {
            "width_mm": pd.width_mm,
            "height_mm": pd.height_mm,
            "width_m": pd.width_m,
            "height_m": pd.height_m,
        },
        "totals": {
            "design_area_mm2": pd.total_design_area_mm2,
            "design_area_m2": pd.total_design_area_m2,
            "tuft_length_mm": pd.total_tuft_length_mm,
            "tuft_length_m": pd.total_tuft_length_m,
            "colour_count": len(pd.colours),
        },
        "file_params": {
            "escala_mm": pd.file_params.escala_mm,
            "densidade_10cm": pd.file_params.densidade_10cm,
        },
        "colours": [
            {
                "name": c.name,
                "colour_hex": c.colour_hex,
                "loop_cut_mode": c.loop_cut_mode,
                "area_mm2": c.area_mm2,
                "area_m2": c.area_m2,
                "percentage": c.percentage,
                "tuft_length_mm": c.tuft_length_mm,
                "tuft_length_m": c.tuft_length_m,
                "stitch_count": c.stitch_count,
            }
            for c in pd.colours
        ],
    }
