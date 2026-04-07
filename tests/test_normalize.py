"""Tests for the normalizer."""

import json
import tempfile
import zipfile
from pathlib import Path

from hitex_tool.normalize import normalize
from hitex_tool.zip_reader import read_zip


SAMPLE_DESIGN = {
    "fileFormatVersion": 1,
    "width": 3550,
    "height": 3550,
    "layers": [
        {
            "name": "001 - Fill",
            "gCodePath": "gcode/layer1.gc",
            "machineSpeed": 60,
            "loopCutMode": "Loop",
            "layerColor": "#FFB500",
            "yarnColor": None,
            "productionOrder": 0,
            "id": "test-id",
        }
    ],
}

SAMPLE_GCODE = """\
M2
G0 X100 Y-10
G0 X110 Y0
M1
G1 X120 Y0
G1 X130 Y10
M2
"""


def _make_export():
    tmp = tempfile.NamedTemporaryFile(suffix=".zop.zip", delete=False)
    with zipfile.ZipFile(tmp, "w") as zf:
        zf.writestr("design.json", json.dumps(SAMPLE_DESIGN))
        zf.writestr("gcode/layer1.gc", SAMPLE_GCODE)
    tmp.close()
    return read_zip(tmp.name), tmp.name


class TestNormalize:
    def test_output_structure(self):
        export, path = _make_export()
        result = normalize(export)
        assert "source" in result
        assert "design" in result
        assert "layers" in result
        assert "stats" in result
        assert result["design"]["width_mm"] == 3550
        assert result["design"]["height_mm"] == 3550
        Path(path).unlink()

    def test_layer_stats(self):
        export, path = _make_export()
        result = normalize(export)
        layer = result["layers"][0]
        assert layer["stats"]["total_moves"] == 4
        assert layer["stats"]["tuft_moves"] == 2
        assert layer["stats"]["travel_moves"] == 2
        assert layer["stats"]["tuft_length_mm"] > 0
        Path(path).unlink()

    def test_summary_mode_no_segments(self):
        export, path = _make_export()
        result = normalize(export, include_segments=False)
        assert "segments" not in result["layers"][0]
        assert result["layers"][0]["stats"]["total_moves"] == 4
        Path(path).unlink()

    def test_total_stats_aggregation(self):
        export, path = _make_export()
        result = normalize(export)
        total = result["stats"]
        layer = result["layers"][0]["stats"]
        assert total["total_moves"] == layer["total_moves"]
        assert total["tuft_moves"] == layer["tuft_moves"]
        Path(path).unlink()

    def test_bounds_correct(self):
        export, path = _make_export()
        result = normalize(export)
        bounds = result["layers"][0]["bounds_mm"]
        assert bounds["min_y"] == -10.0
        assert bounds["max_x"] == 130.0
        Path(path).unlink()
