"""Tests for the production data extractor."""

import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from hitex_tool.production import auto_detect, from_hitex, from_efab, to_dict

SAMPLE_ZIP = Path(__file__).parent.parent / "HITEX_SPINE_350X350.zop.zip"
SAMPLE_BRT = Path(__file__).parent.parent / "EFAB_Simone_100cm_Round.brt"

SAMPLE_DESIGN = {
    "fileFormatVersion": 1,
    "width": 1000,
    "height": 2000,
    "layers": [
        {
            "name": "Fill",
            "gCodePath": "gcode/layer1.gc",
            "machineSpeed": 60,
            "loopCutMode": "Loop",
            "layerColor": "#FF0000",
            "yarnColor": None,
            "productionOrder": 0,
            "id": "test",
        }
    ],
}

SAMPLE_GCODE = """\
M2
G0 X0 Y0
M1
G1 X100 Y0
G1 X100 Y100
G1 X0 Y100
G1 X0 Y0
M2
"""


def _make_test_zip():
    tmp = tempfile.NamedTemporaryFile(suffix=".zop.zip", delete=False)
    with zipfile.ZipFile(tmp, "w") as zf:
        zf.writestr("design.json", json.dumps(SAMPLE_DESIGN))
        zf.writestr("gcode/layer1.gc", SAMPLE_GCODE)
    tmp.close()
    return Path(tmp.name)


class TestFromHitexSynthetic:
    def test_basic_extraction(self):
        path = _make_test_zip()
        pd = from_hitex(path)
        assert pd.source_type == "hitex"
        assert pd.width_mm == 1000
        assert pd.height_mm == 2000
        assert len(pd.colours) == 1
        assert pd.colours[0].name == "Fill"
        assert pd.colours[0].loop_cut_mode == "Loop"
        assert pd.colours[0].stitch_count == 4  # 4 G1 tuft moves
        path.unlink()

    def test_tuft_length_calculated(self):
        path = _make_test_zip()
        pd = from_hitex(path)
        # Square 100x100: 100 + 100 + 100 + 100 = 400mm
        assert abs(pd.total_tuft_length_mm - 400.0) < 0.1
        path.unlink()

    def test_to_dict_structure(self):
        path = _make_test_zip()
        pd = from_hitex(path)
        d = to_dict(pd)
        assert "source_file" in d
        assert "dimensions" in d
        assert "totals" in d
        assert "colours" in d
        assert d["totals"]["colour_count"] == 1
        path.unlink()


@pytest.mark.skipif(not SAMPLE_ZIP.exists(), reason="Sample HITEX file not available")
class TestFromHitexReal:
    def test_real_hitex_parsing(self):
        pd = from_hitex(SAMPLE_ZIP)
        assert pd.source_type == "hitex"
        assert pd.width_mm == 3550
        assert pd.height_mm == 3550
        assert len(pd.colours) == 3
        assert pd.total_tuft_length_m > 0

    def test_colour_names_match_layers(self):
        pd = from_hitex(SAMPLE_ZIP)
        names = [c.name for c in pd.colours]
        assert "001 - Fill" in names
        assert "002 - Fill" in names
        assert "002 - Outline" in names


@pytest.mark.skipif(not SAMPLE_BRT.exists(), reason="Sample EFAB file not available")
class TestFromEfabReal:
    def test_real_efab_parsing(self):
        pd = from_efab(SAMPLE_BRT)
        assert pd.source_type == "efab"
        assert pd.width_mm == 1012.0
        assert pd.height_mm == 1012.0
        assert len(pd.colours) == 3

    def test_colour_percentages(self):
        pd = from_efab(SAMPLE_BRT)
        total_pct = sum(c.percentage for c in pd.colours)
        assert abs(total_pct - 100.0) < 0.2

    def test_design_area(self):
        pd = from_efab(SAMPLE_BRT)
        assert 0.74 < pd.total_design_area_m2 < 0.86

    def test_to_dict_serializable(self):
        pd = from_efab(SAMPLE_BRT)
        d = to_dict(pd)
        # Should be JSON-serializable
        json_str = json.dumps(d)
        assert len(json_str) > 0


class TestAutoDetect:
    def test_hitex_auto(self):
        path = _make_test_zip()
        pd = auto_detect(path)
        assert pd.source_type == "hitex"
        path.unlink()

    @pytest.mark.skipif(not SAMPLE_BRT.exists(), reason="Sample EFAB file not available")
    def test_efab_auto(self):
        pd = auto_detect(SAMPLE_BRT)
        assert pd.source_type == "efab"

    def test_unknown_extension(self):
        with pytest.raises(ValueError, match="Unknown vectorization"):
            auto_detect("/some/file.xyz")
