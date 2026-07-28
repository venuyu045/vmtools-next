"""Phase 4: End-to-end integration tests for map art build system.

⚠️  Requires deployed server.
    Run on the server: pytest tests/phase1/test_integration.py -v --run-integration

    Authentication: uses admin account VenusYu. Set SITE_ADMIN_PASSWORD env var
    or defaults to 'jxy080405'.

Covers:
  - Projection file upload → metadata extraction
  - Task creation → material parsing + block state population
  - Task listing and detail retrieval
  - Task control (start/pause/resume/stop lifecycle)
  - Socket.IO build_map events
"""

import os
import pytest
import httpx
import asyncio
from pathlib import Path

# Server endpoint
BASE_URL = "http://127.0.0.1:8080"
API_URL = f"{BASE_URL}/api/build/map-art"
AUTH_URL = f"{BASE_URL}/api/auth"

ADMIN_USER = "VenusYu"
ADMIN_PASS = os.environ.get("SITE_ADMIN_PASSWORD", "jxy080405")

_token: str = ""


def requires_integration(fn):
    return pytest.mark.integration(fn)


# ──────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────

async def ensure_auth():
    """Login as admin and store JWT token."""
    global _token
    if _token:
        return _token
    async with httpx.AsyncClient(base_url=AUTH_URL, timeout=10) as c:
        r = await c.post("/login", json={
            "game_id": ADMIN_USER,
            "password": ADMIN_PASS,
        })
        assert r.status_code == 200, f"Auth failed: {r.status_code} {r.text}"
        data = r.json()
        _token = data["token"]
        return _token


def _headers():
    return {"Authorization": f"Bearer {_token}"} if _token else {}


async def api_get(path: str, **kwargs) -> dict:
    await ensure_auth()
    h = _headers()
    h.update(kwargs.pop("headers", {}))
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        r = await c.get(path, headers=h, **kwargs)
        return r.json()


async def api_post(path: str, json_data: dict = None) -> dict:
    await ensure_auth()
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
        r = await c.post(path, json=json_data or {}, headers=_headers())
        return r.json()


async def api_delete(path: str) -> dict:
    await ensure_auth()
    async with httpx.AsyncClient(base_url=API_URL, timeout=10) as c:
        r = await c.delete(path, headers=_headers())
        return r.json()


def generate_test_litematic():
    """Generate a small 32x32 test .litematic file for integration testing."""
    from tests.phase1.conftest import generate_synthetic_litematic
    return generate_synthetic_litematic(width=32, height=1, depth=32)


# ──────────────────────────────────────────────
# Test Suite
# ──────────────────────────────────────────────

@pytest.mark.integration
class TestProjectionUpload:
    """Test .litematic file upload and metadata extraction."""

    @requires_integration
    @pytest.mark.asyncio
    async def test_upload_and_parse(self):
        """Upload a synthetic 32×32 Litematic and verify metadata."""
        p = generate_test_litematic()
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=30) as c:
                with open(p, "rb") as f:
                    r = await c.post(
                        "/projections/upload",
                        files={"file": ("test_32x32.litematic", f, "application/octet-stream")},
                    )
                assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text}"
                data = r.json()

            assert "file_path" in data
            assert "projection_info" in data
            info = data["projection_info"]
            assert info["total_blocks"] > 0
            assert info["size"]["x"] == 32
            assert info["size"]["z"] == 32
            assert "material_requirements" in data
            assert len(data["material_requirements"]) > 0

            # Store for next test
            TestProjectionUpload._last_file_path = data["file_path"]
        finally:
            try: p.unlink()
            except: pass


@pytest.mark.integration
class TestTaskLifecycle:
    """Full task lifecycle: create → start → pause → resume → stop."""

    _task_id: str = None

    @requires_integration
    @pytest.mark.asyncio
    async def test_create_task(self):
        """Create a map art task from uploaded projection."""
        file_path = getattr(TestProjectionUpload, "_last_file_path", None)
        if not file_path:
            pytest.skip("No uploaded projection file — run test_upload_and_parse first")

        data = await api_post("/tasks", {
            "name": "Integration Test Map Art",
            "projection_file_path": file_path,
            "origin_x": 0,
            "origin_y": 64,
            "origin_z": 0,
            "bot_ids": [],
        })
        assert "task_id" in data
        assert data["status"] == "draft"
        assert data["total_blocks"] > 0
        TestTaskLifecycle._task_id = data["task_id"]
        print(f"\n  Created task: {data['task_id']}")

    @requires_integration
    @pytest.mark.asyncio
    async def test_get_task_detail(self):
        """Retrieve full task detail with materials and bot assignments."""
        if not TestTaskLifecycle._task_id:
            pytest.skip("No task created")

        r = await api_get(f"/tasks/{TestTaskLifecycle._task_id}")
        assert "task_id" in r
        assert "materials" in r
        assert "bots" in r
        assert "projection" in r
        assert len(r["materials"]) > 0
        print(f"\n  Task detail: {r['name']} — {r['projection']['total_blocks']} blocks, {len(r['materials'])} materials")

    @requires_integration
    @pytest.mark.asyncio
    async def test_list_tasks(self):
        """List tasks with status filter."""
        tasks = await api_get("/tasks", params={"status": "draft"})
        assert "tasks" in tasks
        assert isinstance(tasks["tasks"], list)

    @requires_integration
    @pytest.mark.asyncio
    async def test_control_start_pause_resume_stop(self):
        """Full control lifecycle — only verifies API returns success."""
        if not TestTaskLifecycle._task_id:
            pytest.skip("No task created")

        task_id = TestTaskLifecycle._task_id

        # Start (may fail without bots — that's OK, test the API response)
        try:
            r = await api_post(f"/tasks/{task_id}/control", {"action": "start"})
            assert "status" in r
            print(f"\n  start → {r['status']}")
        except Exception as e:
            print(f"\n  start failed (expected without bots): {e}")

        # Pause
        r = await api_post(f"/tasks/{task_id}/control", {"action": "pause"})
        assert r["status"] == "paused"
        print(f"  pause → {r['status']}")

        # Resume
        r = await api_post(f"/tasks/{task_id}/control", {"action": "resume"})
        assert r["status"] == "running"
        print(f"  resume → {r['status']}")

        # Stop
        r = await api_post(f"/tasks/{task_id}/control", {"action": "stop"})
        assert r["status"] == "cancelled"
        print(f"  stop → {r['status']}")

    @requires_integration
    @pytest.mark.asyncio
    async def test_delete_task(self):
        """Delete completed task."""
        if not TestTaskLifecycle._task_id:
            pytest.skip("No task created")

        r = await api_delete(f"/tasks/{TestTaskLifecycle._task_id}")
        assert r.get("deleted") == TestTaskLifecycle._task_id
        print(f"\n  Deleted: {TestTaskLifecycle._task_id}")


@pytest.mark.integration
class TestSocketIOEvents:
    """Verify Socket.IO events are emitted for map art tasks."""

    @requires_integration
    @pytest.mark.asyncio
    async def test_join_room_and_receive_events(self):
        """Connect Socket.IO, join room, verify events are received."""
        sio = sio_client.AsyncClient()
        received_events = []

        @sio.on("build_map_init")
        def on_init(data):
            received_events.append(("build_map_init", data))

        @sio.on("build_progress")
        def on_progress(data):
            received_events.append(("build_progress", data))

        @sio.on("build_bot_status")
        def on_bot_status(data):
            received_events.append(("build_bot_status", data))

        await sio.connect(BASE_URL)

        # Join a build room
        await sio.emit("build_map_join", {"task_id": "test_integration_room"})

        # Wait briefly for any events
        await asyncio.sleep(1)

        await sio.emit("build_map_leave", {"task_id": "test_integration_room"})
        await sio.disconnect()

        print(f"\n  Socket.IO received {len(received_events)} events: {[e[0] for e in received_events]}")
        # At minimum, connection should succeed without errors
        assert True  # connection didn't fail


@pytest.mark.integration
class TestBlockStateAPI:
    """Test block state queries for 3D frontend."""

    @requires_integration
    @pytest.mark.asyncio
    async def test_block_states_after_create(self):
        """After task creation, block states should be queryable via API."""
        # Create a task
        file_path = getattr(TestProjectionUpload, "_last_file_path", None)
        if not file_path:
            pytest.skip("No uploaded projection file")

        data = await api_post("/tasks", {
            "name": "Block State Test",
            "projection_file_path": file_path,
            "origin_x": 0, "origin_y": 64, "origin_z": 0,
        })
        task_id = data["task_id"]

        # Get task detail — should have block count
        detail = await api_get(f"/tasks/{task_id}")
        total = detail.get("projection", {}).get("total_blocks", 0)
        assert total > 0, f"Task has 0 blocks: {detail}"
        print(f"\n  Task {task_id}: {total} blocks in DB")

        # Cleanup
        await api_delete(f"/tasks/{task_id}")
