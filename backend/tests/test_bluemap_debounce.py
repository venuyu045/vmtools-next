"""Test BlueMap leave-debounce logic: transient empty polls must NOT
fire offline/online notifications."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from vmtools_next.core import bluemap_monitor as bm


def _make_player(name: str) -> dict:
    return {
        "name": name, "uuid": f"uuid-{name}", "world": "world",
        "foreign": False, "position": {"x": 0, "y": 64, "z": 0},
        "rotation": None, "residence": None, "region": None,
    }


class FakeResp:
    def __init__(self, players):
        self.status_code = 200
        self._players = players

    def json(self):
        return {"players": [
            {"name": p["name"], "uuid": p["uuid"], "foreign": False,
             "position": p["position"], "rotation": None}
            for p in self._players
        ]}


def _run_poll(monitor, players_by_world):
    """Run one poll cycle with a fake httpx client."""
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            for world, players in players_by_world.items():
                if f"/maps/{world}/" in url:
                    if players is None:
                        raise RuntimeError("network down")
                    return FakeResp(players)
            raise RuntimeError("unknown world")

    class FakeCfg:
        class bluemap:
            enabled = True
            api_base_url = "http://fake"
            worlds = list(players_by_world.keys())
            poll_interval_seconds = 5

    with patch.object(bm, "get_config", return_value=FakeCfg), \
         patch.object(bm.httpx, "AsyncClient", lambda **kw: FakeClient()), \
         patch.object(bm.sio, "emit", new=AsyncMock()) as emit, \
         patch.object(monitor, "_notify_tracked", new=AsyncMock()) as nt, \
         patch.object(monitor, "_notify_bot_player", new=AsyncMock()) as nb:
        asyncio.get_event_loop().run_until_complete(monitor._poll_players_once())
        return nb


@pytest.fixture
def monitor():
    return bm.BlueMapMonitor()


def test_transient_empty_poll_no_leave_notify(monitor):
    p = [_make_player("Venus_Yu001"), _make_player("Venus_Yu002")]
    _run_poll(monitor, {"world": p})  # initial: both join
    # BlueMap glitches: empty list for a few polls (< MASS threshold)
    for _ in range(10):
        nb = _run_poll(monitor, {"world": []})
        leave_calls = [c for c in nb.call_args_list if c.args[1] == "leave"]
        assert not leave_calls, "transient empty poll must not fire leave"
    # players still tracked as online
    assert set(monitor._previous_players) == {"Venus_Yu001", "Venus_Yu002"}
    # recovery: no join events either (they never "left")
    nb = _run_poll(monitor, {"world": p})
    join_calls = [c for c in nb.call_args_list if c.args[1] == "join"]
    assert not join_calls, "recovery must not fire join"
    assert monitor._miss_counts == {}


def test_mass_glitch_confirms_after_long_window(monitor):
    p = [_make_player("A"), _make_player("B")]
    _run_poll(monitor, {"world": p})
    fired = False
    for i in range(bm.BlueMapMonitor.MASS_LEAVE_CONFIRM_POLLS):
        nb = _run_poll(monitor, {"world": []})
        if any(c.args[1] == "leave" for c in nb.call_args_list):
            fired = True
            assert i + 1 == bm.BlueMapMonitor.MASS_LEAVE_CONFIRM_POLLS
    assert fired, "a real server-wide disconnect must eventually notify"
    assert monitor._previous_players == {}


def test_single_player_leave_confirms_after_3_polls(monitor):
    p = [_make_player("A"), _make_player("B")]
    _run_poll(monitor, {"world": p})
    only_a = [p[0]]
    for i in range(bm.BlueMapMonitor.LEAVE_CONFIRM_POLLS):
        nb = _run_poll(monitor, {"world": only_a})
        leaves = [c for c in nb.call_args_list if c.args[1] == "leave"]
        if i < bm.BlueMapMonitor.LEAVE_CONFIRM_POLLS - 1:
            assert not leaves
        else:
            assert len(leaves) == 1
    assert set(monitor._previous_players) == {"A"}


def test_network_failure_skips_diff(monitor):
    p = [_make_player("A")]
    _run_poll(monitor, {"world": p})
    for _ in range(30):
        nb = _run_poll(monitor, {"world": None})  # all requests fail
        assert not nb.call_args_list, "network outage must not fire any event"
    assert set(monitor._previous_players) == {"A"}
    assert monitor._miss_counts == {}
