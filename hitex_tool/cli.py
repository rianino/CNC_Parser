"""CLI for the vectorization file parser (HITEX + EFAB)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gcode_parser import TuftMode
from .normalize import normalize
from .zip_reader import read_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hitex_tool",
        description="Parse tufting robot vectorization exports (HITEX .zop.zip, EFAB .brt).",
    )
    sub = parser.add_subparsers(dest="command")

    # --- extract command (HITEX only) ---
    extract_p = sub.add_parser("extract", help="Extract and normalize a HITEX export")
    extract_p.add_argument("zip_path", type=str, help="Path to the .zop.zip file")
    extract_p.add_argument("-o", "--output", type=str, help="Output JSON file path")
    extract_p.add_argument(
        "--stdout", action="store_true", help="Print JSON to stdout"
    )
    extract_p.add_argument(
        "--summary",
        action="store_true",
        help="Omit per-segment data (stats and layer info only)",
    )
    extract_p.add_argument(
        "--tuft-mode",
        choices=["mcode", "g0g1"],
        default="mcode",
        help="Tuft detection mode (default: mcode)",
    )
    extract_p.add_argument(
        "--tuft-on", default="M1", help="M-code for tuft on (default: M1)"
    )
    extract_p.add_argument(
        "--tuft-off", default="M2", help="M-code for tuft off (default: M2)"
    )

    # --- info command (HITEX only) ---
    info_p = sub.add_parser("info", help="Show summary info about a HITEX export")
    info_p.add_argument("zip_path", type=str, help="Path to the .zop.zip file")

    # --- production command (HITEX + EFAB) ---
    prod_p = sub.add_parser(
        "production",
        help="Extract production data (colours, areas, yarn lengths) from any vectorization file",
    )
    prod_p.add_argument(
        "file_path", type=str, help="Path to .zop.zip (HITEX) or .brt (EFAB)"
    )
    prod_p.add_argument("-o", "--output", type=str, help="Output JSON file path")
    prod_p.add_argument(
        "--stdout", action="store_true", help="Print JSON to stdout"
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "info":
        return _cmd_info(args)
    if args.command == "extract":
        return _cmd_extract(args)
    if args.command == "production":
        return _cmd_production(args)

    return 1


def _cmd_info(args: argparse.Namespace) -> int:
    export = read_zip(args.zip_path)
    print(f"File: {Path(args.zip_path).name}")
    print(f"Design size: {export.width_mm} x {export.height_mm} mm")
    print(f"Layers: {len(export.layers)}")
    for layer in export.layers:
        lines = len(layer.gcode_text.splitlines()) if layer.gcode_text else 0
        print(
            f"  [{layer.production_order}] {layer.name} "
            f"({layer.loop_cut_mode}, {layer.layer_color}, "
            f"{lines} G-code lines)"
        )
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    export = read_zip(args.zip_path)
    tuft_mode = TuftMode.MCODE if args.tuft_mode == "mcode" else TuftMode.G0G1

    result = normalize(
        export,
        tuft_mode=tuft_mode,
        tuft_on_mcode=args.tuft_on,
        tuft_off_mcode=args.tuft_off,
        include_segments=not args.summary,
    )

    json_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(json_str, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)

    if args.stdout or not args.output:
        print(json_str)

    return 0


def _cmd_production(args: argparse.Namespace) -> int:
    from .production import auto_detect, to_dict

    pd = auto_detect(args.file_path)
    result = to_dict(pd)
    json_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(json_str, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)

    if args.stdout or not args.output:
        print(json_str)

    return 0


if __name__ == "__main__":
    sys.exit(main())
