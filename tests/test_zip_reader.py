"""Tests for the ZIP reader."""

import io
import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from hitex_tool.zip_reader import read_zip


def _make_zip(files: dict[str, str]) -> Path:
    """Create a temporary zip file with the given name->content mapping."""
    tmp = tempfile.NamedTemporaryFile(suffix=".zop.zip", delete=False)
    with zipfile.ZipFile(tmp, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    tmp.close()
    return Path(tmp.name)


SAMPLE_DESIGN = {
    "fileFormatVersion": 1,
    "width": 1000,
    "height": 2000,
    "layers": [
        {
            "name": "Layer 1",
            "gCodePath": "gcode/layer1.gc",
            "machineSpeed": 60,
            "loopCutMode": "Loop",
            "layerColor": "#FFB500",
            "yarnColor": None,
            "productionOrder": 0,
            "id": "abc-123",
        }
    ],
}

SAMPLE_GCODE = "M2\nG0 X10 Y0\nM1\nG1 X100 Y0\nM2\n"


class TestReadZip:
    def test_reads_design_and_gcode(self):
        path = _make_zip(
            {
                "design.json": json.dumps(SAMPLE_DESIGN),
                "gcode/layer1.gc": SAMPLE_GCODE,
            }
        )
        export = read_zip(path)
        assert export.width_mm == 1000
        assert export.height_mm == 2000
        assert len(export.layers) == 1
        assert export.layers[0].name == "Layer 1"
        assert export.layers[0].gcode_text == SAMPLE_GCODE
        assert export.layers[0].loop_cut_mode == "Loop"
        Path(path).unlink()

    def test_gcode_only_no_design(self):
        path = _make_zip({"gcode/layer1.gc": SAMPLE_GCODE})
        export = read_zip(path)
        assert export.design_json is None
        assert len(export.layers) == 1
        assert export.layers[0].gcode_text == SAMPLE_GCODE
        Path(path).unlink()

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_zip("/nonexistent/path.zop.zip")

    def test_empty_zip_raises(self):
        path = _make_zip({})
        with pytest.raises(ValueError):
            read_zip(path)
        Path(path).unlink()

    def test_multiple_layers(self):
        design = {
            **SAMPLE_DESIGN,
            "layers": [
                {**SAMPLE_DESIGN["layers"][0], "name": "Fill", "gCodePath": "gcode/layer1.gc", "productionOrder": 0},
                {**SAMPLE_DESIGN["layers"][0], "name": "Outline", "gCodePath": "gcode/layer2.gc", "productionOrder": 1},
            ],
        }
        path = _make_zip(
            {
                "design.json": json.dumps(design),
                "gcode/layer1.gc": SAMPLE_GCODE,
                "gcode/layer2.gc": "G0 X0 Y0\n",
            }
        )
        export = read_zip(path)
        assert len(export.layers) == 2
        assert export.layers[0].name == "Fill"
        assert export.layers[1].name == "Outline"
        Path(path).unlink()
