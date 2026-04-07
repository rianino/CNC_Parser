"""Tests for the EFAB .brt reader."""

import struct
import tempfile
from pathlib import Path

import pytest

from hitex_tool.efab_reader import read_brt

# The real sample file path (relative to test runner cwd)
SAMPLE_BRT = Path(__file__).parent.parent / "EFAB_Simone_100cm_Round.brt"


@pytest.mark.skipif(not SAMPLE_BRT.exists(), reason="Sample .brt file not available")
class TestReadBrtRealFile:
    def test_basic_parsing(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        assert export.grid_width == 1012
        assert export.grid_height == 1012
        assert export.width_mm == 1012.0
        assert export.height_mm == 1012.0
        assert export.num_colours == 4  # bg + 3 design colours

    def test_colour_count(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        assert len(export.colours) == 3  # 3 design colours (bg excluded)

    def test_colour_percentages_sum_to_100(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        total_pct = sum(c.percentage for c in export.colours)
        assert abs(total_pct - 100.0) < 0.1

    def test_design_area_reasonable(self):
        """100cm round carpet should have area ~0.785 m2 (pi*0.5^2)."""
        export = read_brt(SAMPLE_BRT, load_images=False)
        # Allow 5% tolerance for pixel grid rounding
        assert 0.74 < export.design_area_mm2 / 1e6 < 0.86

    def test_stitch_pitch(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        # 1012mm / 1012 stitches = 1.0 mm/stitch
        assert abs(export.stitch_pitch_x_mm - 1.0) < 0.01
        assert abs(export.stitch_pitch_y_mm - 1.0) < 0.01

    def test_colour_hex_format(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        for c in export.colours:
            assert c.hex.startswith("#")
            assert len(c.hex) == 7

    def test_background_pixels_counted(self):
        export = read_brt(SAMPLE_BRT, load_images=False)
        assert export.background_pixels > 0
        total = export.background_pixels + export.design_pixels
        assert total == export.grid_width * export.grid_height


class TestReadBrtErrors:
    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            read_brt("/nonexistent/file.brt")

    def test_too_small_file(self):
        with tempfile.NamedTemporaryFile(suffix=".brt", delete=False) as f:
            f.write(b"\x00" * 50)
            f.flush()
            with pytest.raises(ValueError, match="too small"):
                read_brt(f.name)
            Path(f.name).unlink()
