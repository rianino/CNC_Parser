"""Normalize parsed HITEX data into the output JSON structure."""

from __future__ import annotations

from pathlib import Path

from .gcode_parser import ParseResult, TuftMode, parse_gcode
from .zip_reader import HitexExport, HitexLayer


def _summarize_unknown(lines: list[str]) -> dict[str, int]:
    """Summarize unknown G-code lines as {command: count}."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for line in lines:
        cmd = line.strip().split()[0] if line.strip() else line
        counts[cmd] += 1
    return dict(counts)


def _layer_to_dict(layer: HitexLayer, parsed: ParseResult) -> dict:
    """Convert a parsed layer into the normalized output dict."""
    segments = []
    for seg in parsed.segments:
        segments.append(
            {
                "type": seg.type,
                "tuft": seg.tuft,
                "start": {"x": round(seg.start.x, 2), "y": round(seg.start.y, 2)},
                "end": {"x": round(seg.end.x, 2), "y": round(seg.end.y, 2)},
                "feed_mm_min": seg.feed_mm_min,
                "gcode": {"cmd": seg.gcode_cmd, "raw": seg.gcode_raw},
            }
        )

    return {
        "name": layer.name,
        "gcode_file": layer.gcode_path,
        "production_order": layer.production_order,
        "loop_cut_mode": layer.loop_cut_mode,
        "layer_color": layer.layer_color,
        "yarn_color": layer.yarn_color,
        "machine_speed": layer.machine_speed,
        "units": "mm",
        "bounds_mm": {
            "min_x": round(parsed.bounds["min_x"], 2),
            "min_y": round(parsed.bounds["min_y"], 2),
            "max_x": round(parsed.bounds["max_x"], 2),
            "max_y": round(parsed.bounds["max_y"], 2),
        },
        "segments": segments,
        "stats": {
            "total_moves": parsed.total_moves,
            "tuft_moves": parsed.tuft_moves,
            "travel_moves": parsed.travel_moves,
            "total_length_mm": round(parsed.total_length_mm, 2),
            "tuft_length_mm": round(parsed.tuft_length_mm, 2),
            "travel_length_mm": round(parsed.travel_length_mm, 2),
        },
        "unknown_commands": _summarize_unknown(parsed.unknown_lines),
    }


def normalize(
    export: HitexExport,
    tuft_mode: TuftMode = TuftMode.MCODE,
    tuft_on_mcode: str = "M1",
    tuft_off_mcode: str = "M2",
    include_segments: bool = True,
) -> dict:
    """Produce the full normalized output from a HitexExport.

    Args:
        export: Parsed HITEX export from zip_reader.
        tuft_mode: Tuft detection strategy.
        tuft_on_mcode: M-code for tuft on.
        tuft_off_mcode: M-code for tuft off.
        include_segments: If False, omit per-segment data (summary only).
    """
    layers_output = []
    total_stats = {
        "total_moves": 0,
        "tuft_moves": 0,
        "travel_moves": 0,
        "total_length_mm": 0.0,
        "tuft_length_mm": 0.0,
        "travel_length_mm": 0.0,
    }

    for layer in export.layers:
        parsed = parse_gcode(
            text=layer.gcode_text,
            tuft_mode=tuft_mode,
            tuft_on_mcode=tuft_on_mcode,
            tuft_off_mcode=tuft_off_mcode,
            layer_feed_mm_min=layer.machine_speed,
        )

        layer_dict = _layer_to_dict(layer, parsed)
        if not include_segments:
            layer_dict.pop("segments", None)

        layers_output.append(layer_dict)

        total_stats["total_moves"] += parsed.total_moves
        total_stats["tuft_moves"] += parsed.tuft_moves
        total_stats["travel_moves"] += parsed.travel_moves
        total_stats["total_length_mm"] += parsed.total_length_mm
        total_stats["tuft_length_mm"] += parsed.tuft_length_mm
        total_stats["travel_length_mm"] += parsed.travel_length_mm

    # Round totals
    for k in ("total_length_mm", "tuft_length_mm", "travel_length_mm"):
        total_stats[k] = round(total_stats[k], 2)

    return {
        "source": {
            "zip": Path(export.zip_path).name,
            "file_format_version": export.file_format_version,
        },
        "design": {
            "width_mm": export.width_mm,
            "height_mm": export.height_mm,
            "layer_count": len(export.layers),
            "raw": export.design_json,
        },
        "layers": layers_output,
        "stats": total_stats,
    }
