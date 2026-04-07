"""Tests for the G-code parser."""

import math

from hitex_tool.gcode_parser import ParseResult, Point, TuftMode, parse_gcode

# --- Fixtures ---

SIMPLE_HITEX_GCODE = """\
M2
G0 X100.0 Y-10.0
G0 X110.0 Y0.0
M1
G1 X120.0 Y0.0
G1 X130.0 Y10.0
G1 X140.0 Y0.0
M2
G0 X200.0 Y-5.0
G0 X210.0 Y0.0
M1
G1 X220.0 Y5.0
M2
"""

MINIMAL_GCODE = """\
G0 X10 Y20
G1 X30 Y40
"""


class TestMCodeTuftDetection:
    def test_m1_m2_toggles(self):
        result = parse_gcode(SIMPLE_HITEX_GCODE, tuft_mode=TuftMode.MCODE)
        tuft_flags = [s.tuft for s in result.segments]
        # G0, G0 (travel), G1, G1, G1 (tuft), G0, G0 (travel), G1 (tuft)
        assert tuft_flags == [
            False, False,   # G0 travel before M1
            True, True, True,  # G1 after M1
            False, False,   # G0 travel after M2
            True,           # G1 after second M1
        ]

    def test_segment_count(self):
        result = parse_gcode(SIMPLE_HITEX_GCODE, tuft_mode=TuftMode.MCODE)
        assert result.total_moves == 8
        assert result.tuft_moves == 4
        assert result.travel_moves == 4

    def test_segment_coordinates(self):
        result = parse_gcode(SIMPLE_HITEX_GCODE, tuft_mode=TuftMode.MCODE)
        # First segment: from origin to (100, -10)
        s0 = result.segments[0]
        assert s0.start.x == 0.0
        assert s0.start.y == 0.0
        assert s0.end.x == 100.0
        assert s0.end.y == -10.0

    def test_bounds(self):
        result = parse_gcode(SIMPLE_HITEX_GCODE, tuft_mode=TuftMode.MCODE)
        assert result.bounds["min_x"] == 0.0
        assert result.bounds["min_y"] == -10.0
        assert result.bounds["max_x"] == 220.0
        assert result.bounds["max_y"] == 10.0


class TestG0G1TuftDetection:
    def test_g0g1_mode(self):
        result = parse_gcode(MINIMAL_GCODE, tuft_mode=TuftMode.G0G1)
        assert result.segments[0].tuft is False  # G0
        assert result.segments[1].tuft is True  # G1

    def test_mcode_mode_no_toggle(self):
        """Without M1, no G1 should be marked as tufting in MCODE mode."""
        result = parse_gcode(MINIMAL_GCODE, tuft_mode=TuftMode.MCODE)
        assert result.segments[0].tuft is False
        assert result.segments[1].tuft is False  # No M1 seen, so G1 is not tufting


class TestSegmentLength:
    def test_horizontal_move(self):
        gcode = "M1\nG1 X100 Y0"
        result = parse_gcode(gcode)
        seg = result.segments[0]
        assert abs(seg.length_mm - 100.0) < 0.01

    def test_diagonal_move(self):
        gcode = "M1\nG1 X30 Y40"
        result = parse_gcode(gcode)
        seg = result.segments[0]
        assert abs(seg.length_mm - 50.0) < 0.01  # 3-4-5 triangle

    def test_total_length(self):
        result = parse_gcode(SIMPLE_HITEX_GCODE)
        assert result.total_length_mm > 0


class TestFeedRate:
    def test_layer_feed_rate(self):
        gcode = "M1\nG1 X100 Y0"
        result = parse_gcode(gcode, layer_feed_mm_min=60)
        assert result.segments[0].feed_mm_min == 60

    def test_inline_feed_overrides(self):
        gcode = "M1\nG1 X100 Y0 F120\nG1 X200 Y0"
        result = parse_gcode(gcode, layer_feed_mm_min=60)
        assert result.segments[0].feed_mm_min == 120
        assert result.segments[1].feed_mm_min == 120  # Inherited

    def test_g0_has_zero_feed(self):
        gcode = "G0 X50 Y0"
        result = parse_gcode(gcode)
        assert result.segments[0].feed_mm_min == 0.0


class TestUnitsAndModes:
    def test_inch_conversion(self):
        gcode = "G20\nM1\nG1 X1 Y0"
        result = parse_gcode(gcode)
        seg = result.segments[0]
        assert abs(seg.end.x - 25.4) < 0.01

    def test_relative_mode(self):
        gcode = "G91\nG0 X10 Y20\nG0 X5 Y5"
        result = parse_gcode(gcode)
        assert result.segments[0].end.x == 10.0
        assert result.segments[0].end.y == 20.0
        assert result.segments[1].end.x == 15.0
        assert result.segments[1].end.y == 25.0


class TestRobustness:
    def test_comments_skipped(self):
        gcode = "; comment\n(another comment)\nG0 X10 Y20"
        result = parse_gcode(gcode)
        assert len(result.segments) == 1

    def test_unknown_commands_stored(self):
        gcode = "G0 X10 Y20\nG28\nG0 X20 Y30"
        result = parse_gcode(gcode)
        assert len(result.segments) == 2
        assert "G28" in result.unknown_lines[0]

    def test_empty_input(self):
        result = parse_gcode("")
        assert result.total_moves == 0
        assert result.bounds == {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0}

    def test_raw_gcode_preserved(self):
        gcode = "G0 X10.5 Y20.3"
        result = parse_gcode(gcode)
        assert result.segments[0].gcode_raw == "G0 X10.5 Y20.3"
        assert result.segments[0].gcode_cmd == "G0"


class TestCustomMCodes:
    def test_custom_tuft_mcodes(self):
        gcode = "M3\nG1 X100 Y0\nM5\nG1 X200 Y0"
        result = parse_gcode(
            gcode,
            tuft_mode=TuftMode.MCODE,
            tuft_on_mcode="M3",
            tuft_off_mcode="M5",
        )
        assert result.segments[0].tuft is True
        assert result.segments[1].tuft is False
