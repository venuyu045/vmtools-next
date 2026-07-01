"""Build State Machine — 18-state state machine for projection-based construction.

Ported from VMTools-v3 BuildStateMachine.java. Drives the complete lifecycle:
  ANALYZE_PROJECTION → ANALYZE_MATERIALS → CHECK_INVENTORY → SELECT_WAREHOUSE
  → CHECK_WAREHOUSE_CACHE → SCAN_WAREHOUSE → NEED_RESTOCK
  → DECIDE_TRAVEL_MODE → [PATH|TELEPORT]_TO_WAREHOUSE → TAKE_MATERIALS
  → DECIDE_TRAVEL_MODE → [PATH|TELEPORT]_TO_BUILD_SITE
  → BUILD_LAYER → VERIFY_LAYER → NEXT_LAYER → DONE

TAKE_MATERIALS is a nested state machine with 7 sub-phases.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Optional

from vmtools_next.core.dataclasses import (
    ProjectionInfo, ProjectionMaterialRequirement, MaterialCompareResult,
    CheckResult, TravelTarget,
)
from vmtools_next.core.safety_manager import SafetyManager
from vmtools_next.core.travel_manager import TravelManager, TeleportManager
from vmtools_next.core.material_calculator import MaterialCalculator
from vmtools_next.core.warehouse_manager import WarehouseManager
from vmtools_next.core.warehouse_scanner import WarehouseScanner
from vmtools_next.core.inventory_scanner import InventoryScanner
from vmtools_next.core.operation_logger import OperationLogger, OperationType
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.mcc.mcc_baritone import MccBaritoneAdapter
from vmtools_next.adapters.mcc.mcc_printer import MccPrinterAdapter
from vmtools_next.adapters.mcc.mcc_litematica import MccLitematicaAdapter
from vmtools_next.adapters.mcc.mcc_minihud import MccMiniHudAdapter

logger = logging.getLogger("vmtools.build_sm")


class BuildState(Enum):
    IDLE = auto()
    ANALYZE_PROJECTION = auto()
    ANALYZE_MATERIALS = auto()
    CHECK_INVENTORY = auto()
    SELECT_WAREHOUSE = auto()
    CHECK_WAREHOUSE_CACHE = auto()
    SCAN_WAREHOUSE = auto()
    NEED_RESTOCK = auto()
    DECIDE_TRAVEL_MODE = auto()
    PATH_TO_WAREHOUSE = auto()
    TELEPORT_TO_WAREHOUSE = auto()
    TAKE_MATERIALS = auto()
    PATH_TO_BUILD_SITE = auto()
    TELEPORT_TO_BUILD_SITE = auto()
    BUILD_LAYER = auto()
    VERIFY_LAYER = auto()
    NEXT_LAYER = auto()
    DONE = auto()
    ERROR = auto()
    PAUSED = auto()


class RestockPhase(Enum):
    IDLE = auto()
    NAVIGATING = auto()
    OPENING = auto()
    READING = auto()
    EXTRACTING = auto()
    CLOSING = auto()
    DONE = auto()


class BuildStateMachine:
    """18-state build state machine."""

    def __init__(
        self,
        bot_id: str,
        mcc: MccMcpClient,
        litematica: MccLitematicaAdapter,
        baritone: MccBaritoneAdapter,
        printer: MccPrinterAdapter,
        minihud: MccMiniHudAdapter,
        scanner: WarehouseScanner,
        warehouse_mgr: WarehouseManager,
        safety: SafetyManager,
        travel: TravelManager,
        teleport: TeleportManager,
        material_calc: MaterialCalculator,
        inventory_scanner: InventoryScanner,
        op_logger: OperationLogger,
        layer_height: int = 6,
    ):
        self._bot_id = bot_id
        self._mcc = mcc
        self._litematica = litematica
        self._baritone = baritone
        self._printer = printer
        self._minihud = minihud
        self._scanner = scanner
        self._warehouse_mgr = warehouse_mgr
        self._safety = safety
        self._travel = travel
        self._teleport = teleport
        self._material_calc = material_calc
        self._inventory_scanner = inventory_scanner
        self._op_logger = op_logger
        self._layer_height = layer_height

        self._state = BuildState.IDLE
        self._previous_state = BuildState.IDLE
        self._projection: Optional[ProjectionInfo] = None
        self._requirements: list[ProjectionMaterialRequirement] = []
        self._compare_results: list[MaterialCompareResult] = []
        self._total_layers: int = 0
        self._current_layer: int = 0
        self._selected_warehouse_id: str = ""
        self._restock_phase = RestockPhase.IDLE
        self._container_positions: list[tuple[int, int, int]] = []
        self._container_index: int = 0
        self._restock_list: list[tuple[str, str, int]] = []  # (item_id, name, count)
        self._restock_index: int = 0
        self._current_inv_id: int = 0
        self._state_ticks: int = 0
        self._running = False
        self._paused = False
        self._error_message: str = ""
        self._loop_task: Optional[asyncio.Task] = None
        self._travel_purpose: str = ""

    @property
    def state(self) -> BuildState:
        return self._state

    @property
    def current_layer(self) -> int:
        return self._current_layer

    @property
    def total_layers(self) -> int:
        return self._total_layers

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, projection: ProjectionInfo) -> bool:
        """Start a build task with the given projection."""
        if self._running:
            logger.warning("Build already running")
            return False

        safety = await self._safety.check()
        if safety == CheckResult.EMERGENCY_STOP:
            logger.error("Cannot start: emergency stop active")
            return False

        self._projection = projection
        self._state = BuildState.ANALYZE_PROJECTION
        self._previous_state = BuildState.IDLE
        self._running = True
        self._paused = False
        self._error_message = ""
        self._state_ticks = 0

        logger.info("Build started: %s (%d blocks)", projection.name, projection.total_blocks)
        self._op_logger.log(OperationType.BUILD, self._bot_id, details=f"Started: {projection.name}")

        # Start tick loop
        self._loop_task = asyncio.create_task(self._tick_loop())
        return True

    async def stop(self) -> None:
        """Stop the build."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
        self._state = BuildState.IDLE
        logger.info("Build stopped")

    async def pause(self) -> None:
        """Pause the build."""
        self._paused = True
        self._previous_state = self._state
        self._state = BuildState.PAUSED
        logger.info("Build paused at state %s", self._previous_state.name)

    async def resume(self) -> None:
        """Resume the build."""
        self._paused = False
        self._state = self._previous_state
        logger.info("Build resumed to state %s", self._state.name)

    async def _tick_loop(self) -> None:
        """Main tick loop — runs every 500ms."""
        while self._running:
            try:
                await asyncio.sleep(0.5)

                # Check for nearby players via MCC
                nearby_player_detected = False
                try:
                    result = await self._mcc.is_player_nearby(
                        radius=self._safety.policy.nearby_player_radius
                    )
                    nearby_player_detected = result.get("found", False)
                except MccMcpError:
                    pass  # Ignore player check errors

                # Safety check with player detection
                safety = await self._safety.check(nearby_player_detected=nearby_player_detected)
                if safety == CheckResult.EMERGENCY_STOP:
                    await self._transition(BuildState.ERROR, "Emergency stop")
                    return
                if safety == CheckResult.BLOCKED:
                    continue
                if self._paused:
                    continue
                if self._scanner.state.name == "SCANNING":
                    continue

                self._state_ticks += 1
                await self._dispatch_state()

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("Tick error in state %s: %s", self._state.name, e)
                self._op_logger.log(OperationType.ERROR, self._bot_id,
                                    details=f"Tick error: {e}", success=False)
                await self._transition(BuildState.ERROR, str(e))
                return

    async def _dispatch_state(self) -> None:
        """Dispatch to the handler for the current state."""
        handlers = {
            BuildState.ANALYZE_PROJECTION: self._do_analyze_projection,
            BuildState.ANALYZE_MATERIALS: self._do_analyze_materials,
            BuildState.CHECK_INVENTORY: self._do_check_inventory,
            BuildState.SELECT_WAREHOUSE: self._do_select_warehouse,
            BuildState.CHECK_WAREHOUSE_CACHE: self._do_check_warehouse_cache,
            BuildState.SCAN_WAREHOUSE: self._do_scan_warehouse,
            BuildState.NEED_RESTOCK: self._do_need_restock,
            BuildState.DECIDE_TRAVEL_MODE: self._do_decide_travel_mode,
            BuildState.PATH_TO_WAREHOUSE: self._do_path_to_warehouse,
            BuildState.TELEPORT_TO_WAREHOUSE: self._do_teleport_to_warehouse,
            BuildState.TAKE_MATERIALS: self._do_take_materials,
            BuildState.PATH_TO_BUILD_SITE: self._do_path_to_build_site,
            BuildState.TELEPORT_TO_BUILD_SITE: self._do_teleport_to_build_site,
            BuildState.BUILD_LAYER: self._do_build_layer,
            BuildState.VERIFY_LAYER: self._do_verify_layer,
            BuildState.NEXT_LAYER: self._do_next_layer,
            BuildState.DONE: self._do_done,
            BuildState.ERROR: self._do_error,
        }
        handler = handlers.get(self._state)
        if handler:
            await handler()
        elif self._state == BuildState.PAUSED:
            pass  # Do nothing

    async def _transition(self, new_state: BuildState, reason: str = "") -> None:
        """Transition to a new state."""
        old = self._state
        self._previous_state = old
        self._state = new_state
        self._state_ticks = 0
        logger.info("State: %s → %s%s", old.name, new_state.name,
                     f" ({reason})" if reason else "")

    # ── State Handlers ───────────────────────────────────────────────────

    async def _do_analyze_projection(self) -> None:
        """ANALYZE_PROJECTION: Load and validate the projection file."""
        if not self._projection:
            await self._transition(BuildState.ERROR, "No projection loaded")
            return

        success = await self._litematica.load_projection(
            self._projection.file_path,
            self._projection.origin_x,
            self._projection.origin_y,
            self._projection.origin_z,
        )
        if not success:
            await self._transition(BuildState.ERROR, "Failed to load projection")
            return

        info = await self._litematica.get_projection_info()
        if info:
            self._total_layers = max(1, info.size_y // self._layer_height)
            self._projection = info

        await self._transition(BuildState.ANALYZE_MATERIALS)

    async def _do_analyze_materials(self) -> None:
        """ANALYZE_MATERIALS: Get material requirements from projection."""
        self._requirements = await self._litematica.get_material_requirements()
        logger.info("Materials required: %d types", len(self._requirements))
        await self._transition(BuildState.CHECK_INVENTORY)

    async def _do_check_inventory(self) -> None:
        """CHECK_INVENTORY: Scan player inventory."""
        inv = await self._inventory_scanner.scan()
        inv_dict = inv  # Already {item_id: count}
        warehouse_materials = {}  # Will be populated after scan
        self._compare_results = MaterialCalculator.compare(
            self._requirements, warehouse_materials, inv_dict
        )
        shortfall = MaterialCalculator.get_shortfall_items(self._compare_results)
        if not shortfall:
            logger.info("All materials available in inventory")
            await self._transition(BuildState.BUILD_LAYER)
        else:
            logger.info("Material shortfall: %d types", len(shortfall))
            await self._transition(BuildState.SELECT_WAREHOUSE)

    async def _do_select_warehouse(self) -> None:
        """SELECT_WAREHOUSE: Select the best warehouse for restocking."""
        required = {r.item_id: r.shortfall for r in self._compare_results if r.shortfall > 0}
        wh_id = self._warehouse_mgr.select_best(required)
        if wh_id:
            self._selected_warehouse_id = wh_id
            await self._transition(BuildState.CHECK_WAREHOUSE_CACHE)
        else:
            await self._transition(BuildState.ERROR, "No suitable warehouse found")

    async def _do_check_warehouse_cache(self) -> None:
        """CHECK_WAREHOUSE_CACHE: Check if warehouse data is fresh enough."""
        snapshot = self._warehouse_mgr.get_snapshot(self._selected_warehouse_id)
        if snapshot:
            import time
            age = time.time() - snapshot.scanned_at
            if age < 300:  # 5 minutes
                logger.info("Warehouse cache fresh (%.0fs old)", age)
                await self._transition(BuildState.NEED_RESTOCK)
                return
        await self._transition(BuildState.SCAN_WAREHOUSE)

    async def _do_scan_warehouse(self) -> None:
        """SCAN_WAREHOUSE: Start scanning the warehouse containers."""
        wh = self._warehouse_mgr.get_warehouse(self._selected_warehouse_id)
        if not wh:
            await self._transition(BuildState.ERROR, "Warehouse not found")
            return

        # Get container positions from warehouse
        positions = [(z["x"], z["y"], z["z"]) for z in wh.get("storage_zones", [])]
        if not positions:
            await self._transition(BuildState.ERROR, "No containers in warehouse")
            return

        # Parse aisle_positions JSON to correct format
        raw_aisles = wh.get("aisle_positions", [])
        aisle_lines = []
        for aisle in raw_aisles:
            if isinstance(aisle, dict):
                start = aisle.get("start", {})
                end = aisle.get("end", {})
                aisle_lines.append((
                    (start.get("x", 0), start.get("y", 0), start.get("z", 0)),
                    (end.get("x", 0), end.get("y", 0), end.get("z", 0)),
                ))
            elif isinstance(aisle, (list, tuple)) and len(aisle) == 2:
                aisle_lines.append(tuple(aisle))

        success = await self._scanner.start_scan(positions, aisle_lines if aisle_lines else None)
        if success:
            # Wait for scan to complete (scanner runs in background)
            while self._scanner.state.name == "SCANNING":
                await asyncio.sleep(1)
            if self._scanner.state.name == "COMPLETED":
                materials = self._scanner.get_material_summary()
                self._warehouse_mgr.update_snapshot(self._selected_warehouse_id, materials)
                # Fill container positions from scanner results for TAKE_MATERIALS
                self._container_positions = [
                    (s.x, s.y, s.z) for s in self._scanner.results.values()
                ]
                logger.info("Scan complete: %d containers, %d material types",
                           len(self._container_positions), len(materials))
                await self._transition(BuildState.NEED_RESTOCK)
            else:
                await self._transition(BuildState.ERROR, "Scan failed")
        else:
            await self._transition(BuildState.ERROR, "Failed to start scan")

    async def _do_need_restock(self) -> None:
        """NEED_RESTOCK: Calculate what to restock."""
        snapshot = self._warehouse_mgr.get_snapshot(self._selected_warehouse_id)
        if not snapshot:
            await self._transition(BuildState.ERROR, "No warehouse snapshot")
            return

        inv = await self._inventory_scanner.scan()
        self._compare_results = MaterialCalculator.compare(
            self._requirements, snapshot.materials, inv
        )
        self._restock_list = MaterialCalculator.get_restock_list(self._compare_results)
        if not self._restock_list:
            logger.info("No restock needed after scan")
            await self._transition(BuildState.BUILD_LAYER)
            return

        self._restock_index = 0
        self._travel_purpose = "WAREHOUSE"
        await self._transition(BuildState.DECIDE_TRAVEL_MODE)

    async def _do_decide_travel_mode(self) -> None:
        """DECIDE_TRAVEL_MODE: Decide between pathfinding and teleport."""
        wh = self._warehouse_mgr.get_warehouse(self._selected_warehouse_id)
        if not wh:
            await self._transition(BuildState.ERROR, "Warehouse not found")
            return

        target = TravelTarget(x=wh["x"], y=wh["y"], z=wh["z"],
                               purpose=self._travel_purpose)

        # Get current position
        try:
            state = await self._mcc.get_player_state()
            loc = state.get("location", {})
            px, py, pz = loc.get("x", 0), loc.get("y", 0), loc.get("z", 0)
            import math
            distance = math.sqrt((px-target.x)**2 + (py-target.y)**2 + (pz-target.z)**2)
        except MccMcpError:
            distance = 0

        if self._travel.should_teleport(distance) and self._travel.can_teleport():
            if self._travel_purpose == "WAREHOUSE":
                await self._transition(BuildState.TELEPORT_TO_WAREHOUSE)
            else:
                await self._transition(BuildState.TELEPORT_TO_BUILD_SITE)
        else:
            if self._travel_purpose == "WAREHOUSE":
                await self._transition(BuildState.PATH_TO_WAREHOUSE)
            else:
                await self._transition(BuildState.PATH_TO_BUILD_SITE)

    async def _do_path_to_warehouse(self) -> None:
        """PATH_TO_WAREHOUSE: Pathfind to warehouse."""
        wh = self._warehouse_mgr.get_warehouse(self._selected_warehouse_id)
        if not wh:
            await self._transition(BuildState.ERROR, "Warehouse not found")
            return

        success = await self._baritone.path_to_near(wh["x"], wh["y"], wh["z"], radius=3)
        if success:
            await self._transition(BuildState.TAKE_MATERIALS)
        else:
            self._safety.record_failure()
            await self._transition(BuildState.DECIDE_TRAVEL_MODE)

    async def _do_teleport_to_warehouse(self) -> None:
        """TELEPORT_TO_WAREHOUSE: Teleport to warehouse."""
        wh = self._warehouse_mgr.get_warehouse(self._selected_warehouse_id)
        if not wh:
            await self._transition(BuildState.ERROR, "Warehouse not found")
            return

        cmd = self._teleport.get_command("self", wh["x"], wh["y"], wh["z"])
        try:
            await self._mcc.send_chat(cmd)
            self._travel.record_teleport()
            self._teleport.record_use()
            await asyncio.sleep(3)  # Wait for teleport
            await self._transition(BuildState.TAKE_MATERIALS)
        except MccMcpError as e:
            logger.warning("Teleport failed: %s", e)
            self._safety.record_failure()
            await self._transition(BuildState.DECIDE_TRAVEL_MODE)

    async def _do_take_materials(self) -> None:
        """TAKE_MATERIALS: Nested state machine for restocking from containers."""
        if self._restock_phase == RestockPhase.IDLE:
            self._restock_phase = RestockPhase.NAVIGATING
            self._container_index = 0

        if self._restock_phase == RestockPhase.NAVIGATING:
            # Navigate to container
            if self._container_index < len(self._container_positions):
                cx, cy, cz = self._container_positions[self._container_index]
                await self._baritone.path_to_near(cx, cy, cz, radius=2)
                self._restock_phase = RestockPhase.OPENING
            else:
                self._restock_phase = RestockPhase.DONE

        elif self._restock_phase == RestockPhase.OPENING:
            if self._container_index < len(self._container_positions):
                cx, cy, cz = self._container_positions[self._container_index]
                try:
                    result = await self._mcc.open_container_at(cx, cy, cz)
                    self._current_inv_id = result.get("inventoryId", 0)
                    self._restock_phase = RestockPhase.READING
                except MccMcpError as e:
                    logger.warning("Failed to open container at (%d,%d,%d): %s", cx, cy, cz, e)
                    self._container_index += 1
                    self._restock_phase = RestockPhase.NAVIGATING
            else:
                self._restock_phase = RestockPhase.DONE

        elif self._restock_phase == RestockPhase.READING:
            try:
                snapshot = await self._mcc.get_inventory_snapshot(self._current_inv_id)
                container_items = snapshot.get("items", [])
                # Check if any needed items are in this container
                found_any = False
                for slot in container_items:
                    item_type = slot.get("type", "")
                    for restock_item in self._restock_list:
                        item_id, item_name, needed = restock_item
                        if item_type == item_id or item_type.endswith(f":{item_id.split(':')[-1]}"):
                            found_any = True
                            break
                    if found_any:
                        break
                self._restock_phase = RestockPhase.EXTRACTING if found_any else RestockPhase.CLOSING
            except MccMcpError:
                self._restock_phase = RestockPhase.CLOSING

        elif self._restock_phase == RestockPhase.EXTRACTING:
            # Use withdraw_container_item API to extract needed items
            try:
                snapshot = await self._mcc.get_inventory_snapshot(self._current_inv_id)
                container_items = snapshot.get("items", [])
                extracted_any = False

                for restock_item in list(self._restock_list):
                    item_id, item_name, needed = restock_item
                    if needed <= 0:
                        continue

                    # Find matching item in container
                    for slot in container_items:
                        slot_type = slot.get("type", "")
                        slot_count = slot.get("count", 0)
                        if slot_count <= 0:
                            continue
                        # Match by exact ID or by short name
                        if slot_type == item_id or slot_type.endswith(f":{item_id.split(':')[-1]}"):
                            take = min(slot_count, needed, 64)
                            if take > 0:
                                try:
                                    await self._mcc.withdraw_container_item(
                                        slot_type, take, self._current_inv_id
                                    )
                                    extracted_any = True
                                    needed -= take
                                    logger.info("Withdrew %d x %s from container", take, slot_type)
                                except MccMcpError as e:
                                    logger.warning("Withdraw failed for %s: %s", slot_type, e)
                            break

                    # Update restock list
                    if needed > 0:
                        idx = self._restock_list.index(restock_item)
                        self._restock_list[idx] = (item_id, item_name, needed)
                    else:
                        self._restock_list.remove(restock_item)

                if extracted_any:
                    self._safety.reset_failures()
                else:
                    self._safety.record_failure()
            except MccMcpError as e:
                logger.warning("Extract phase error: %s", e)
                self._safety.record_failure()
            self._restock_phase = RestockPhase.CLOSING

        elif self._restock_phase == RestockPhase.CLOSING:
            try:
                await self._mcc.close_container(self._current_inv_id)
            except MccMcpError:
                pass
            self._container_index += 1
            self._restock_phase = RestockPhase.NAVIGATING

        elif self._restock_phase == RestockPhase.DONE:
            self._restock_phase = RestockPhase.IDLE
            # Check if we have all materials now
            inv = await self._inventory_scanner.scan()
            shortfall = [r for r in self._compare_results
                        if r.required > inv.get(r.item_id, 0)]
            if shortfall:
                logger.info("Still missing %d materials, will try again", len(shortfall))
            await self._transition(BuildState.BUILD_LAYER)

    async def _do_path_to_build_site(self) -> None:
        """PATH_TO_BUILD_SITE: Pathfind back to build site."""
        if not self._projection:
            await self._transition(BuildState.ERROR, "No projection")
            return
        success = await self._baritone.path_to_near(
            self._projection.origin_x, self._projection.origin_y,
            self._projection.origin_z, radius=5)
        if success:
            await self._transition(BuildState.BUILD_LAYER)
        else:
            self._safety.record_failure()
            await self._transition(BuildState.DECIDE_TRAVEL_MODE)

    async def _do_teleport_to_build_site(self) -> None:
        """TELEPORT_TO_BUILD_SITE: Teleport back to build site."""
        if not self._projection:
            await self._transition(BuildState.ERROR, "No projection")
            return
        cmd = self._teleport.get_command(
            "self", self._projection.origin_x,
            self._projection.origin_y, self._projection.origin_z)
        try:
            await self._mcc.send_chat(cmd)
            self._travel.record_teleport()
            self._teleport.record_use()
            await asyncio.sleep(3)
            await self._transition(BuildState.BUILD_LAYER)
        except MccMcpError:
            await self._transition(BuildState.DECIDE_TRAVEL_MODE)

    async def _do_build_layer(self) -> None:
        """BUILD_LAYER: Place all blocks in the current layer."""
        if not self._projection:
            await self._transition(BuildState.ERROR, "No projection")
            return

        layer_blocks = await self._litematica.get_layer_blocks(
            self._projection.file_path,
            self._current_layer,
            self._layer_height,
            self._projection.origin_x,
            self._projection.origin_y,
            self._projection.origin_z,
        )

        if not layer_blocks:
            logger.info("Layer %d: no blocks to place", self._current_layer)
            await self._transition(BuildState.VERIFY_LAYER)
            return

        self._printer.enable()
        placed = 0
        for (wx, wy, wz, block_state) in layer_blocks:
            if not self._running:
                return
            if self._paused:
                return

            # Select item in hotbar
            item_id = block_state.split("[")[0] if "[" in block_state else block_state
            try:
                await self._mcc.select_hotbar_item(item_id, prefer_lowest_slot=True)
            except MccMcpError:
                pass  # Item might not be in inventory

            # Place block
            try:
                await self._mcc.place_block(wx, wy, wz, face="UP",
                                             hand="MAIN_HAND", look_at_block=True)
                placed += 1
            except MccMcpError as e:
                logger.warning("Failed to place block at (%d,%d,%d): %s", wx, wy, wz, e)

            # Rate limit
            interval = self._printer.get_place_interval() * 0.05
            await asyncio.sleep(interval)

        self._printer.disable()
        logger.info("Layer %d: placed %d/%d blocks", self._current_layer, placed, len(layer_blocks))
        await self._transition(BuildState.VERIFY_LAYER)

    async def _do_verify_layer(self) -> None:
        """VERIFY_LAYER: Verify that blocks were placed correctly."""
        missing = await self._litematica.get_missing_block_count()
        if missing == 0:
            logger.info("Layer %d: verification passed", self._current_layer)
            await self._transition(BuildState.NEXT_LAYER)
        else:
            logger.warning("Layer %d: %d blocks missing", self._current_layer, missing)
            # Retry up to 3 times
            if self._state_ticks < 3:
                await self._transition(BuildState.BUILD_LAYER)
            else:
                logger.error("Layer %d: verification failed after 3 retries", self._current_layer)
                await self._transition(BuildState.NEXT_LAYER)  # Continue anyway

    async def _do_next_layer(self) -> None:
        """NEXT_LAYER: Move to the next layer or finish."""
        self._current_layer += 1
        if self._current_layer >= self._total_layers:
            await self._transition(BuildState.DONE)
            return

        logger.info("Moving to layer %d/%d", self._current_layer, self._total_layers)
        # Move up to next layer height
        if self._projection:
            next_y = self._projection.origin_y + self._current_layer * self._layer_height
            try:
                await self._mcc.move_to(
                    self._projection.origin_x, next_y,
                    self._projection.origin_z, max_offset=3, timeout_ms=10000)
            except MccMcpError:
                pass
        await self._transition(BuildState.BUILD_LAYER)

    async def _do_done(self) -> None:
        """DONE: Build completed."""
        self._running = False
        logger.info("Build completed: %s", self._projection.name if self._projection else "unknown")
        self._op_logger.log(OperationType.BUILD, self._bot_id,
                            details=f"Completed: {self._projection.name if self._projection else 'unknown'}")

    async def _do_error(self) -> None:
        """ERROR: Build failed."""
        self._running = False
        logger.error("Build failed: %s", self._error_message)
        self._op_logger.log(OperationType.ERROR, self._bot_id,
                            details=f"Failed: {self._error_message}", success=False)
