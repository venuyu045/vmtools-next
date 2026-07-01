# AGENTS.md

## Project Overview

VMTools v3: Minecraft Fabric 1.21.11 client mod that automates building from Litematica projections. Orchestrates material restocking from warehouses, travel (Baritone + teleport), and block placement (Printer adapter). A Python backend provides web-based warehouse management and material sync.

Two independent codebases in one repo:
- `VMTools-v3/` — Fabric mod (Java 21, Gradle + fabric-loom)
- `vmtools-backend/` — FastAPI + SQLAlchemy backend (Python 3.12)

Reference/dependency sources (read-only, not built as part of VMTools):
`baritone-1.21.11/`, `litematica-LTS-1.21.11/`, `malilib-LTS-1.21.11/`, `minihud-LTS-1.21.11/`, `litematica-printer3-master-master/`, `superwy-master/`

## Build & Run

### Mod (VMTools-v3/)
```bash
cd VMTools-v3
./gradlew build          # Build JAR → build/libs/vmtools-fabric-1.21.11-*.jar
./gradlew runClient      # Launch Minecraft with mod in dev
./gradlew genSources      # Decompile Minecraft sources for reference
```
Java 21 required. Gradle daemon disabled (`org.gradle.daemon = false`). Uses official Mojang mappings (`loom.officialMojangMappings()`).

### Backend (vmtools-backend/)
```bash
cd vmtools-backend
pip install -r requirements.txt
python main.py           # Starts on http://0.0.0.0:8080 (DEBUG mode with reload)
```
SQLite auto-created on first run. Config via env vars: `VMT_DATABASE_URL`, `VMT_API_TOKEN`, `VMT_PORT`, `VMT_SECRET_KEY`, `VMT_DEBUG`.

Docker: `docker compose up -d` (uses Alibaba PyPI mirror in Dockerfile). See `deploy.sh` for full deployment with Nginx + Let's Encrypt.

## Architecture

### Mod Layers (top → bottom)

1. **User Interaction** — MaLiLib GUI screens (`config/`, `gui/`), HUD overlay (`hud/`), hotkeys (`hotkey/`), client commands (`command/`)
2. **Scheduling Core** — `BuildStateMachine` (main orchestrator), `WarehouseManager`, `TravelManager`, `SafetyManager`
3. **Adapter Layer** — `BaritoneAdapter` (reflection API or `#goto` fallback), `LitematicaAdapter` (projection/material data), `PrinterAdapter` (block placement), `MiniHudAdapter` (container reading)
4. **External** — Litematica, Baritone, Printer mods

### BuildStateMachine — The Core Loop

```
ANALYZE_PROJECTION → ANALYZE_MATERIALS → CHECK_INVENTORY → SELECT_WAREHOUSE
  → CHECK_WAREHOUSE_CACHE → SCAN_WAREHOUSE → NEED_RESTOCK
  → DECIDE_TRAVEL_MODE → [PATH|TELEPORT]_TO_WAREHOUSE → TAKE_MATERIALS
  → DECIDE_TRAVEL_MODE → [PATH|TELEPORT]_TO_BUILD_SITE
  → BUILD_LAYER → VERIFY_LAYER → NEXT_LAYER → (loop) → DONE
```

`TAKE_MATERIALS` is a nested state machine: `IDLE → NAVIGATING → OPENING → READING → EXTRACTING → CLOSING → DONE`.

### Baritone Integration

`BaritoneAdapter` uses **reflection** to access `baritone.api.*` — no compile-time dependency. Two modes:
- **API mode** — `GoalNear` pathing, `PathEvent` arrival detection
- **Command mode** — falls back to `#goto x y z` chat commands

### Backend Architecture

- FastAPI app with **Socket.IO** (`python-socketio`) for real-time updates
- SQLite via SQLAlchemy ORM, auto-migrations in `database/db.py`
- SPA frontend served from `static/` with catch-all route
- Auth: JWT + bcrypt, site admin auto-created from env vars
- Tables: `warehouses`, `material_items`, `container_items`, `scan_status`, `storage_zones`, `users`, `organizations`

### Tick Handlers

Three MaLiLib tick handlers run every game tick (20/s):
- `SafetyTickHandler` — manual takeover detection, nearby player pause
- `TravelTickHandler` — delegates to `TravelManager.onTick()`
- `BuildTickHandler` — delegates to `BuildStateMachine.onTick()`

## Key Patterns

- **Singleton managers** — all core managers use `INSTANCE` pattern
- **MaLiLib integration** — configs use `IConfigHandler`, hotkeys use `IHotkeyCallback`, GUI uses MaLiLib's screen framework
- **Async warehouse scanning** — `WarehouseScanner` runs on background thread with `ScanProgressListener` callbacks; state machine pauses until scan completes
- **Server profiles** — warehouses and configs scoped to server profiles (`ServerProfileManager`), auto-loaded on server join
- **Client-only mod** — entrypoint is `ClientModInitializer`, not `ModInitializer`; all code under `@Environment(EnvType.CLIENT)`
- **Printer indirect control** — no direct API; controlled via config value exchange (`Configs.Core.WORK_SWITCH.setBooleanValue()`)
- **Aisle positions** — `Warehouse.aislePositions` stores walkable points for scan/restock navigation; bot paths to nearest aisle point, not directly to container

## Important Files

- `BuildStateMachine.java` — core orchestrator state machine
- `WarehouseScanner.java` — async container scanning with shulker recursion
- `BaritoneAdapter.java` — reflection-based Baritone API access
- `VMToolsConfigs.java` — 31 config options across 7 tabs
- `database/db.py` — DB init, SQLite migrations, site admin seeding
- `VMTools-v3-architecture.md` — detailed Chinese architecture doc (424 lines)
- `development-plan.md` — full design spec with all data models and algorithms

## Dev Environment

Minecraft game folder: `D:\pcl2\.minecraft\versions\投影bot` (PCL2 launcher)

## Gotchas

- Baritone is in the repo as source (`baritone-1.21.11/`) but is **not** built as part of VMTools. The mod uses reflection to call its API.
- Printer has no public API — `PrinterAdapter` controls it via config value exchange only.
- Backend uses `python-socketio` (async mode), not `python-engineio`. The Socket.IO server is the ASGI app, not FastAPI directly.
- `main.py` uses `"main:sio_app"` string form for uvicorn reload (DEBUG mode) vs the actual `sio_app` object.
- Gradle uses `org.gradle.daemon = false` — don't expect persistent daemon.
- No test suite exists for either codebase.
- Documentation files (`VMTools-v3-architecture.md`, `development-plan.md`, `overview.md`, `superwy-analysis.md`) are design docs, not current-state docs. Verify claims against actual source.
