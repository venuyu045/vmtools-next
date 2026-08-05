"""Test BlueMap 5.16 markers parsing — all 6 marker sets must be handled.

Covers the newly added sets (landmarks, metro lines, metro stations) plus
regression for the original three (residences, regions, markers).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from vmtools_next.core import bluemap_monitor as bm


def _mk(detail: str = "", **extra) -> dict:
    base = {"label": "x", "position": {"x": 1, "y": 2, "z": 3}}
    base.update(extra)
    if detail:
        base["detail"] = detail
    return base


def _markers_payload() -> dict:
    """A realistic BlueMap 5.16 markers.json payload with all 6 marker sets."""
    return {
        "Residences": {"markers": {
            "main.xinbiao": _mk(
                detail='<div class="regioninfo"><span>所有者: <span style="font-weight:bold">Venus_Yu</span></span></div>',
                shape=[{"x": 0, "z": 0}, {"x": 10, "z": 0}, {"x": 10, "z": 10}, {"x": 0, "z": 10}],
                shapeMinY=60, shapeMaxY=70,
            ),
        }},
        "folia-regions": {"markers": {
            "Region@overworld[0,0]": _mk(
                detail="Sections: 4\nChunks: 16\nEntities: 57\nPlayers: 2\nTPS: 20.00\nMSPT: 3.29",
                shape=[{"x": 0, "z": 0}, {"x": 100, "z": 0}, {"x": 100, "z": 100}, {"x": 0, "z": 100}],
            ),
        }},
        "markers": {"markers": {
            "area_1": _mk(detail="三城区"),
        }},
        "mangopassport-landmarks": {"markers": {
            "legacy_marker_1": _mk(
                detail="<div><strong>P1停车场</strong><br>类型：停车场<br>坐标：7132, 62, 5086</div>",
                label="P1停车场",
            ),
            "legacy_marker_2": _mk(
                detail="<div><strong>圣路易斯路</strong><br>类型：道路与交通设施<br>坐标：7592, 64, 105</div>",
                label="圣路易斯路",
            ),
        }},
        "folia-metro-lines": {"markers": {
            "line-line_1": _mk(
                detail="<b>测试线路</b><br>Line 1<br><br><b>正常运营 / In service</b>",
                label="测试线路 / Line 1 · 全长 21537 格",
                line=[{"x": 0, "y": 64, "z": 0}, {"x": 100, "y": 64, "z": 0}],
                lineColor="#ff0000",
            ),
        }},
        "folia-metro-stations": {"markers": {
            "station_1": _mk(detail="站台 A", label="站台A"),
        }},
    }


@pytest.fixture
def monitor():
    return bm.BlueMapMonitor()


def test_parses_all_six_marker_sets(monitor):
    (res, regions, markers,
     landmarks, metro_lines, metro_stations) = monitor._parse_markers_data(
        _markers_payload(), "world"
    )

    # Original sets still work
    assert len(res) == 1
    assert res[0]["owner"] == "Venus_Yu"
    assert res[0]["area"] == 100.0  # 10x10 square
    assert len(regions) == 1
    assert regions[0]["tps"] == 20.00
    assert regions[0]["mspt"] == 3.29
    assert regions[0]["entities"] == 57
    assert regions[0]["players_in_region"] == 2
    assert len(markers) == 1
    assert markers[0]["label"] == "x"

    # New sets
    assert len(landmarks) == 2
    lm_by_label = {lm["label"]: lm for lm in landmarks}
    assert lm_by_label["P1停车场"]["type"] == "停车场"
    assert lm_by_label["圣路易斯路"]["type"] == "道路与交通设施"
    assert landmarks[0]["world"] == "world"

    assert len(metro_lines) == 1
    assert metro_lines[0]["line_color"] == "#ff0000"
    assert len(metro_lines[0]["line"]) == 2

    assert len(metro_stations) == 1
    assert metro_stations[0]["label"] == "站台A"


def test_parse_empty_payload(monitor):
    """Empty / missing marker sets must not crash."""
    (res, regions, markers,
     landmarks, metro_lines, metro_stations) = monitor._parse_markers_data({}, "world")
    assert res == [] and regions == [] and markers == []
    assert landmarks == [] and metro_lines == [] and metro_stations == []


def test_landmark_type_handles_missing_detail(monitor):
    """Landmark without 类型 line gets empty type, not a crash."""
    payload = {"mangopassport-landmarks": {"markers": {
        "legacy_marker_9": _mk(detail="<div><strong>无名</strong><br>坐标：1, 2, 3</div>", label="无名"),
    }}}
    (_, _, _, landmarks, _, _) = monitor._parse_markers_data(payload, "world")
    assert len(landmarks) == 1
    assert landmarks[0]["type"] == ""
