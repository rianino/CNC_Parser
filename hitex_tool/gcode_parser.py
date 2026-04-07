"""G-code parser for HITEX tufting robot exports.

The HITEX G-code dialect uses:
  - G0 / G00: rapid travel moves
  - G1 / G01: linear interpolation (tufting moves)
  - M1: tuft enable (needle on)
  - M2: tuft disable (needle off)
  - X, Y: absolute coordinates (mm)
  - No F (feed rate) in G-code — speed is set per-layer in design.json

Tuft detection: M1/M2 toggles are the primary signal. G0 moves are always
non-tufting regardless of M-state. G1 moves tuft only when M1 is active.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum


class TuftMode(Enum):
    """How to detect tuft on/off in G-code."""

    MCODE = "mcode"  # M1=on, M2=off (HITEX default)
    G0G1 = "g0g1"  # G0=off, G1=on (generic CNC heuristic)


@dataclass
class Point:
    x: float = 0.0
    y: float = 0.0


@dataclass
class Segment:
    """A single motion segment."""

    type: str  # "move" or "arc"
    tuft: bool
    start: Point
    end: Point
    feed_mm_min: float = 0.0
    gcode_cmd: str = ""
    gcode_raw: str = ""

    @property
    def length_mm(self) -> float:
        dx = self.end.x - self.start.x
        dy = self.end.y - self.start.y
        return math.sqrt(dx * dx + dy * dy)


@dataclass
class ParseResult:
    """Result of parsing a single G-code layer."""

    segments: list[Segment] = field(default_factory=list)
    unknown_lines: list[str] = field(default_factory=list)
    bounds: dict = field(default_factory=lambda: {
        "min_x": float("inf"),
        "min_y": float("inf"),
        "max_x": float("-inf"),
        "max_y": float("-inf"),
    })
    units: str = "mm"
    is_absolute: bool = True

    @property
    def total_moves(self) -> int:
        return len(self.segments)

    @property
    def tuft_moves(self) -> int:
        return sum(1 for s in self.segments if s.tuft)

    @property
    def travel_moves(self) -> int:
        return sum(1 for s in self.segments if not s.tuft)

    @property
    def total_length_mm(self) -> float:
        return sum(s.length_mm for s in self.segments)

    @property
    def tuft_length_mm(self) -> float:
        return sum(s.length_mm for s in self.segments if s.tuft)

    @property
    def travel_length_mm(self) -> float:
        return sum(s.length_mm for s in self.segments if not s.tuft)


# Regex to extract coordinates and parameters from a G-code line
_PARAM_RE = re.compile(r"([A-Z])(-?\d+\.?\d*)")


def _parse_params(line: str) -> dict[str, float]:
    """Extract letter-value pairs from a G-code line."""
    return {m.group(1): float(m.group(2)) for m in _PARAM_RE.finditer(line)}


def parse_gcode(
    text: str,
    tuft_mode: TuftMode = TuftMode.MCODE,
    tuft_on_mcode: str = "M1",
    tuft_off_mcode: str = "M2",
    layer_feed_mm_min: float = 0.0,
) -> ParseResult:
    """Parse HITEX G-code text into segments.

    Args:
        text: Raw G-code text.
        tuft_mode: Detection strategy for tuft on/off.
        tuft_on_mcode: M-code that enables tufting (default M1 for HITEX).
        tuft_off_mcode: M-code that disables tufting (default M2 for HITEX).
        layer_feed_mm_min: Feed rate from design.json machineSpeed (applied to all G1).
    """
    result = ParseResult()
    pos = Point(0.0, 0.0)
    tuft_active = False
    current_feed = layer_feed_mm_min
    inches_to_mm = 25.4

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("("):
            continue

        params = _parse_params(line)
        cmd_match = re.match(r"([GM]\d+)", line)
        if not cmd_match:
            result.unknown_lines.append(raw_line)
            continue

        cmd = cmd_match.group(1)

        # Unit commands
        if cmd in ("G20",):
            result.units = "inches"
            continue
        if cmd in ("G21",):
            result.units = "mm"
            continue

        # Absolute / relative
        if cmd in ("G90",):
            result.is_absolute = True
            continue
        if cmd in ("G91",):
            result.is_absolute = False
            continue

        # Tuft M-code toggles
        if tuft_mode == TuftMode.MCODE:
            if cmd == tuft_on_mcode:
                tuft_active = True
                continue
            if cmd == tuft_off_mcode:
                tuft_active = False
                continue

        # Motion commands
        if cmd in ("G0", "G00", "G1", "G01"):
            # Feed rate
            if "F" in params:
                current_feed = params["F"]

            # Target position
            if result.is_absolute:
                nx = params.get("X", pos.x)
                ny = params.get("Y", pos.y)
            else:
                nx = pos.x + params.get("X", 0.0)
                ny = pos.y + params.get("Y", 0.0)

            # Unit conversion
            if result.units == "inches":
                nx *= inches_to_mm
                ny *= inches_to_mm

            start = Point(pos.x, pos.y)
            end = Point(nx, ny)

            # Tuft logic
            if tuft_mode == TuftMode.G0G1:
                is_tuft = cmd in ("G1", "G01")
            else:
                # MCODE mode: G0 is always travel, G1 tufts only if M1 active
                is_tuft = cmd in ("G1", "G01") and tuft_active

            seg = Segment(
                type="move",
                tuft=is_tuft,
                start=start,
                end=end,
                feed_mm_min=current_feed if cmd in ("G1", "G01") else 0.0,
                gcode_cmd=cmd,
                gcode_raw=raw_line.strip(),
            )
            result.segments.append(seg)

            # Update bounds
            for p in (start, end):
                result.bounds["min_x"] = min(result.bounds["min_x"], p.x)
                result.bounds["min_y"] = min(result.bounds["min_y"], p.y)
                result.bounds["max_x"] = max(result.bounds["max_x"], p.x)
                result.bounds["max_y"] = max(result.bounds["max_y"], p.y)

            pos = end
            continue

        # Unknown command
        result.unknown_lines.append(raw_line)

    # Fix bounds if no segments
    if not result.segments:
        result.bounds = {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0}

    return result
