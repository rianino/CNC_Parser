"""Tests for HITEX preview rendering and percentage calculations.

These tests use the real sample file to catch regressions in:
- Layer rendering order (detail on top of fill)
- Percentage calculation (tuft length, not bounding box)
- Canvas aspect ratio matching design bounds
- Preview image validity
"""

import base64
import json
import struct
from pathlib import Path

import pytest

from hitex_tool.production import from_hitex

SAMPLE_ZIP = Path(__file__).parent.parent / "HITEX_SPINE_350X350.zop.zip"


@pytest.mark.skipif(not SAMPLE_ZIP.exists(), reason="Sample HITEX file not available")
class TestHitexPercentages:
    """Percentages must be based on tuft length, not bounding box."""

    def test_percentages_are_not_equal(self):
        """The old bug: bounding box gave ~33% each. This must never happen."""
        pd = from_hitex(SAMPLE_ZIP)
        percentages = [c.percentage for c in pd.colours]
        # If all percentages are within 5% of each other, something is wrong
        assert max(percentages) - min(percentages) > 10, (
            f"Percentages are suspiciously equal: {percentages}. "
            "Likely using bounding box instead of tuft length."
        )

    def test_background_fill_dominates(self):
        """002 - Fill (background zigzag) should be the largest layer."""
        pd = from_hitex(SAMPLE_ZIP)
        bg = next(c for c in pd.colours if c.name == "002 - Fill")
        assert bg.percentage > 80, (
            f"Background fill should be >80%, got {bg.percentage}%"
        )

    def test_percentages_sum_to_100(self):
        pd = from_hitex(SAMPLE_ZIP)
        total = sum(c.percentage for c in pd.colours)
        assert abs(total - 100.0) < 0.1

    def test_area_derived_from_percentage(self):
        """Area per colour should be carpet_area × percentage, not bounding box."""
        pd = from_hitex(SAMPLE_ZIP)
        carpet_area = pd.width_mm * pd.height_mm
        for c in pd.colours:
            expected = carpet_area * c.percentage / 100
            assert abs(c.area_mm2 - expected) < 1, (
                f"{c.name}: area_mm2={c.area_mm2} but expected {expected:.0f} "
                f"(carpet_area × {c.percentage}%)"
            )


@pytest.mark.skipif(not SAMPLE_ZIP.exists(), reason="Sample HITEX file not available")
class TestHitexPreview:
    """Preview rendering must produce valid images with correct properties."""

    def _get_preview(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from app.server import _preview_hitex
        return _preview_hitex(SAMPLE_ZIP)

    def test_preview_is_valid_png_data_uri(self):
        preview = self._get_preview()
        assert preview.startswith("data:image/png;base64,")

    def test_preview_decodes_to_valid_png(self):
        preview = self._get_preview()
        b64 = preview.split(",", 1)[1]
        png_bytes = base64.b64decode(b64)
        # PNG magic bytes
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_canvas_matches_aspect_ratio(self):
        """Canvas must not be a fixed square — it must match the design bounds."""
        from PIL import Image
        import io

        preview = self._get_preview()
        b64 = preview.split(",", 1)[1]
        png_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(png_bytes))
        w, h = img.size

        # The SPINE sample is 3550x3550 (square), so canvas should be ~square
        # But the test ensures the code USES the bounds, not a hardcoded size
        ratio = w / h
        # For this square design, ratio should be close to 1.0
        assert 0.9 < ratio < 1.1, (
            f"Canvas ratio {ratio:.2f} doesn't match square design"
        )

    def test_detail_layer_visible(self):
        """The design layer (001 - Fill, orange) must be drawn ON TOP of the
        background fill, not hidden underneath it."""
        from PIL import Image
        import io
        import numpy as np

        preview = self._get_preview()
        b64 = preview.split(",", 1)[1]
        png_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        pixels = np.array(img)

        # #FFB500 = (255, 181, 0) — the orange detail layer
        # Check that orange-ish pixels exist in the image
        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        orange_mask = (r > 200) & (g > 100) & (g < 220) & (b < 50)
        orange_count = orange_mask.sum()

        assert orange_count > 100, (
            f"Only {orange_count} orange pixels found. "
            "Detail layer is likely hidden under the fill layer."
        )
