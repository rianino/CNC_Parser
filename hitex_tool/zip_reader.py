"""Read and extract contents from HITEX .zop.zip exports."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HitexLayer:
    """A single layer (colour/yarn pass) from the HITEX export."""

    name: str
    gcode_path: str
    gcode_text: str
    machine_speed: float
    loop_cut_mode: str  # "Loop" or "Cut"
    layer_color: str | None
    yarn_color: str | None
    production_order: int
    layer_id: str
    stitch_density_loop: float = 1.0
    stitch_density_cut: float = 1.0
    z_for_loop: float = 0.0
    z_for_cut: float = 0.0
    z_mode: str = "Fixed"
    notes: str = ""


@dataclass
class HitexExport:
    """Complete parsed HITEX export."""

    zip_path: str
    design_json: dict | None
    layers: list[HitexLayer] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    file_format_version: int = 0


# Safety limits
_MAX_ZIP_ENTRIES = 100
_MAX_ENTRY_SIZE = 100 * 1024 * 1024  # 100 MB uncompressed per entry


def _safe_entry_name(name: str) -> bool:
    """Reject ZIP entry names with path traversal or absolute paths."""
    return ".." not in name and not name.startswith("/") and not name.startswith("\\")


def _safe_read(zf: zipfile.ZipFile, name: str) -> bytes:
    """Read a ZIP entry with a size check to prevent decompression bombs."""
    info = zf.getinfo(name)
    if info.file_size > _MAX_ENTRY_SIZE:
        raise ValueError(
            f"ZIP entry {name} too large: {info.file_size} bytes "
            f"(max {_MAX_ENTRY_SIZE})"
        )
    return zf.read(name)


def read_zip(path: str | Path) -> HitexExport:
    """Open a HITEX .zop.zip and extract design metadata + G-code layers."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HITEX export not found: {path}")

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()

        if len(names) > _MAX_ZIP_ENTRIES:
            raise ValueError(f"ZIP has too many entries: {len(names)}")

        # Reject entries with path traversal
        for name in names:
            if not _safe_entry_name(name):
                raise ValueError(f"Unsafe ZIP entry name: {name}")

        # Read design.json
        design_json = None
        if "design.json" in names:
            design_json = json.loads(_safe_read(zf, "design.json").decode("utf-8"))

        # Find all .gc files
        gc_files = {
            n: _safe_read(zf, n).decode("utf-8")
            for n in names
            if n.endswith(".gc")
        }

        if design_json is None and not gc_files:
            raise ValueError(f"No design.json or .gc files found in {path}")

        export = HitexExport(
            zip_path=str(path),
            design_json=design_json,
            width_mm=design_json.get("width", 0) if design_json else 0,
            height_mm=design_json.get("height", 0) if design_json else 0,
            file_format_version=design_json.get("fileFormatVersion", 0)
            if design_json
            else 0,
        )

        if design_json and "layers" in design_json:
            for layer_meta in design_json["layers"]:
                gc_path = layer_meta.get("gCodePath", "")
                gc_text = gc_files.get(gc_path, "")
                export.layers.append(
                    HitexLayer(
                        name=layer_meta.get("name", ""),
                        gcode_path=gc_path,
                        gcode_text=gc_text,
                        machine_speed=layer_meta.get("machineSpeed", 0),
                        loop_cut_mode=layer_meta.get("loopCutMode", ""),
                        layer_color=layer_meta.get("layerColor"),
                        yarn_color=layer_meta.get("yarnColor"),
                        production_order=layer_meta.get("productionOrder", 0),
                        layer_id=layer_meta.get("id", ""),
                        stitch_density_loop=layer_meta.get("stitchDensityForLoop", 1),
                        stitch_density_cut=layer_meta.get("stitchDensityForCut", 1),
                        z_for_loop=layer_meta.get("zForLoop", 0.0),
                        z_for_cut=layer_meta.get("zForCut", 0.0),
                        z_mode=layer_meta.get("zMode", "Fixed"),
                        notes=layer_meta.get("notes", ""),
                    )
                )
        else:
            # No design.json layers — create one layer per .gc file found
            for i, (gc_path, gc_text) in enumerate(sorted(gc_files.items())):
                export.layers.append(
                    HitexLayer(
                        name=gc_path,
                        gcode_path=gc_path,
                        gcode_text=gc_text,
                        machine_speed=0,
                        loop_cut_mode="",
                        layer_color=None,
                        yarn_color=None,
                        production_order=i,
                        layer_id="",
                    )
                )

        return export
