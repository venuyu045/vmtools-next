"""Logistics Runner — executes freight transport tasks.

Drives the complete logistics cycle:
  1. Teleport to warehouse waypoint
  2. Navigate to container
  3. Open container and withdraw items
  4. Teleport to drop point
  5. Deposit items (container or drop)
  6. Loop or complete

Integrates with TaskEngine and Socket.IO for real-time status updates.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Optional, Callable, Awaitable

from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient, MccMcpError
from vmtools_next.adapters.mcc.mcc_baritone import MccBaritoneAdapter
from vmtools_next.core.safety_manager import SafetyManager
from vmtools_next.core.travel_manager import TeleportManager
from vmtools_next.core.operation_logger import OperationLogger, OperationType
from vmtools_next.core.dataclasses import CheckResult

logger = logging.getLogger("vmtools.logistics_runner")


class LogisticsState(Enum):
    """Logistics runner states."""
    IDLE = auto()
    TELEPORT_TO_SOURCE = auto()
    NAVIGATE_TO_CONTAINER = auto()
    OPEN_CONTAINER = auto()
    READ_CONTAINER = auto()
    WITHDRAW_ITEMS = auto()
    CLOSE_CONTAINER = auto()
    TELEPORT_TO_DROP = auto()
    NAVIGATE_TO_DROP = auto()
    DEPOSIT_ITEMS = auto()
    WAITING = auto()
    COMPLETED = auto()
    FAILED = auto()
    PAUSED = auto()


# Progress callback: (state, progress_pct, message)
ProgressCallback = Callable[[LogisticsState, float, str], Awaitable[None]]


class LogisticsRunner:
    """Executes logistics freight transport tasks."""

    def __init__(
        self,
        mcc: MccMcpClient,
        baritone: MccBaritoneAdapter,
        safety: SafetyManager,
        teleport: TeleportManager,
        op_logger: OperationLogger,
        bot_id: str = "",
    ):
        self._mcc = mcc
        self._baritone = baritone
        self._safety = safety
        self._teleport = teleport
        self._op_logger = op_logger
        self._bot_id = bot_id

        self._state = LogisticsState.IDLE
        self._running = False
        self._paused = False
        self._loop_count = 0
        self._max_loops = 1  # 0 = infinite
        self._progress_callback: Optional[ProgressCallback] = None

        # Task configuration
        self._source_teleport_cmd = ""
        self._source_container_x = 0
        self._source_container_y = 0
        self._source_container_z = 0
        self._item_type = ""
        self._item_count = 64
        self._drop_teleport_cmd = ""
        self._drop_x = 0
        self._drop_y = 0
        self._drop_z = 0
        self._drop_method = "drop"  # "drop" or "container"
        self._wait_after_teleport = 5

        # Runtime state
        self._current_inv_id = 0
        self._error_message = ""

    @property
    def state(self) -> LogisticsState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def loop_count(self) -> int:
        return self._loop_count

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    async def start(
        self,
        source_teleport_cmd: str,
        source_container_x: int, source_container_y: int, source_container_z: int,
        item_type: str, item_count: int = 64,
        drop_teleport_cmd: str = "",
        drop_x: int = 0, drop_y: int = 0, drop_z: int = 0,
        drop_method: str = "drop",
        wait_after_teleport: int = 5,
        max_loops: int = 1,
    ) -> bool:
        """Start a logistics task.

        Args:
            source_teleport_cmd: Teleport command to reach source
            source_container_x/y/z: Source container position
            item_type: Item ID to transport
            item_count: Number of items per trip
            drop_teleport_cmd: Teleport command to reach drop point
            drop_x/y/z: Drop point position
            drop_method: "drop" (throw) or "container" (deposit)
            wait_after_teleport: Seconds to wait after teleporting
            max_loops: Number of round trips (0 = infinite)
        """
        if self._running:
            logger.warning("Logistics runner already running")
            return False

        # Check safety
        safety = await self._safety.check()
        if safety == CheckResult.EMERGENCY_STOP:
            logger.error("Cannot start: emergency stop active")
            return False

        # Store configuration
        self._source_teleport_cmd = source_teleport_cmd
        self._source_container_x = source_container_x
        self._source_container_y = source_container_y
        self._source_container_z = source_container_z
        self._item_type = item_type
        self._item_count = item_count
        self._drop_teleport_cmd = drop_teleport_cmd
        self._drop_x = drop_x
        self._drop_y = drop_y
        self._drop_z = drop_z
        self._drop_method = drop_method
        self._wait_after_teleport = wait_after_teleport
        self._max_loops = max_loops

        self._running = True
        self._paused = False
        self._loop_count = 0
        self._state = LogisticsState.TELEPORT_TO_SOURCE
        self._error_message = ""

        logger.info("Logistics started: %s x%d, loops=%d",
                   item_type, item_count, max_loops)
        self._op_logger.log(OperationType.RESTOCK, self._bot_id,
                           details=f"Started: {item_type} x{item_count}")

        # Start execution loop
        asyncio.create_task(self._execution_loop())
        return True

    async def stop(self) -> None:
        """Stop the logistics task."""
        self._running = False
        self._state = LogisticsState.IDLE
        logger.info("Logistics stopped")

    async def pause(self) -> None:
        """Pause the logistics task."""
        self._paused = True
        logger.info("Logistics paused")

    async def resume(self) -> None:
        """Resume the logistics task."""
        self._paused = False
        logger.info("Logistics resumed")

    async def _update_progress(self, state: LogisticsState, progress: float, message: str) -> None:
        """Update progress and notify callback."""
        self._state = state
        if self._progress_callback:
            try:
                await self._progress_callback(state, progress, message)
            except Exception as e:
                logger.warning("Progress callback error: %s", e)

    async def _execution_loop(self) -> None:
        """Main execution loop."""
        try:
            while self._running:
                # Safety check
                safety = await self._safety.check()
                if safety == CheckResult.EMERGENCY_STOP:
                    self._error_message = "Emergency stop"
                    self._state = LogisticsState.FAILED
                    self._running = False
                    return
                if safety == CheckResult.BLOCKED or self._paused:
                    await asyncio.sleep(0.5)
                    continue

                # Execute current state
                await self._dispatch_state()

                # Check completion
                if self._state == LogisticsState.COMPLETED:
                    self._running = False
                    logger.info("Logistics completed after %d loops", self._loop_count)
                    self._op_logger.log(OperationType.RESTOCK, self._bot_id,
                                       details=f"Completed: {self._loop_count} loops")
                    return
                elif self._state == LogisticsState.FAILED:
                    self._running = False
                    logger.error("Logistics failed: %s", self._error_message)
                    self._op_logger.log(OperationType.ERROR, self._bot_id,
                                       details=f"Failed: {self._error_message}", success=False)
                    return

                await asyncio.sleep(0.1)  # Small delay between states

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Execution loop error: %s", e)
            self._error_message = str(e)
            self._state = LogisticsState.FAILED
            self._running = False

    async def _dispatch_state(self) -> None:
        """Dispatch to the handler for the current state."""
        handlers = {
            LogisticsState.TELEPORT_TO_SOURCE: self._do_teleport_to_source,
            LogisticsState.NAVIGATE_TO_CONTAINER: self._do_navigate_to_container,
            LogisticsState.OPEN_CONTAINER: self._do_open_container,
            LogisticsState.READ_CONTAINER: self._do_read_container,
            LogisticsState.WITHDRAW_ITEMS: self._do_withdraw_items,
            LogisticsState.CLOSE_CONTAINER: self._do_close_container,
            LogisticsState.TELEPORT_TO_DROP: self._do_teleport_to_drop,
            LogisticsState.NAVIGATE_TO_DROP: self._do_navigate_to_drop,
            LogisticsState.DEPOSIT_ITEMS: self._do_deposit_items,
            LogisticsState.WAITING: self._do_waiting,
        }
        handler = handlers.get(self._state)
        if handler:
            await handler()

    # ── State Handlers ───────────────────────────────────────────────────

    async def _do_teleport_to_source(self) -> None:
        """Teleport to source warehouse."""
        await self._update_progress(LogisticsState.TELEPORT_TO_SOURCE, 0.1,
                                   "Teleporting to source...")
        try:
            await self._mcc.send_chat(self._source_teleport_cmd)
            await asyncio.sleep(self._wait_after_teleport)
            self._state = LogisticsState.NAVIGATE_TO_CONTAINER
        except MccMcpError as e:
            logger.warning("Teleport to source failed: %s", e)
            self._safety.record_failure()
            self._error_message = f"Teleport failed: {e}"
            self._state = LogisticsState.FAILED

    async def _do_navigate_to_container(self) -> None:
        """Navigate to the source container."""
        await self._update_progress(LogisticsState.NAVIGATE_TO_CONTAINER, 0.2,
                                   "Navigating to container...")
        success = await self._baritone.path_to_near(
            self._source_container_x, self._source_container_y,
            self._source_container_z, radius=2
        )
        if success:
            self._state = LogisticsState.OPEN_CONTAINER
        else:
            self._safety.record_failure()
            self._error_message = "Failed to navigate to container"
            self._state = LogisticsState.FAILED

    async def _do_open_container(self) -> None:
        """Open the source container."""
        await self._update_progress(LogisticsState.OPEN_CONTAINER, 0.3,
                                   "Opening container...")
        try:
            result = await self._mcc.open_container_at(
                self._source_container_x, self._source_container_y,
                self._source_container_z
            )
            self._current_inv_id = result.get("inventoryId", 0)
            self._state = LogisticsState.READ_CONTAINER
        except MccMcpError as e:
            logger.warning("Failed to open container: %s", e)
            self._safety.record_failure()
            self._error_message = f"Open container failed: {e}"
            self._state = LogisticsState.FAILED

    async def _do_read_container(self) -> None:
        """Read container contents."""
        await self._update_progress(LogisticsState.READ_CONTAINER, 0.4,
                                   "Reading container...")
        try:
            snapshot = await self._mcc.get_inventory_snapshot(self._current_inv_id)
            items = snapshot.get("items", [])
            # Check if target item is available
            found = False
            for slot in items:
                slot_type = slot.get("type", "")
                if slot_type == self._item_type or slot_type.endswith(f":{self._item_type.split(':')[-1]}"):
                    if slot.get("count", 0) > 0:
                        found = True
                        break
            if found:
                self._state = LogisticsState.WITHDRAW_ITEMS
            else:
                logger.info("Item %s not found in container, closing", self._item_type)
                self._state = LogisticsState.CLOSE_CONTAINER
        except MccMcpError:
            self._state = LogisticsState.CLOSE_CONTAINER

    async def _do_withdraw_items(self) -> None:
        """Withdraw items from container."""
        await self._update_progress(LogisticsState.WITHDRAW_ITEMS, 0.5,
                                   f"Withdrawing {self._item_type}...")
        try:
            snapshot = await self._mcc.get_inventory_snapshot(self._current_inv_id)
            items = snapshot.get("items", [])

            for slot in items:
                slot_type = slot.get("type", "")
                slot_count = slot.get("count", 0)
                if slot_count <= 0:
                    continue
                if slot_type == self._item_type or slot_type.endswith(f":{self._item_type.split(':')[-1]}"):
                    take = min(slot_count, self._item_count, 64)
                    if take > 0:
                        await self._mcc.withdraw_container_item(
                            slot_type, take, self._current_inv_id
                        )
                        logger.info("Withdrew %d x %s", take, slot_type)
                        self._safety.reset_failures()
                    break
        except MccMcpError as e:
            logger.warning("Withdraw failed: %s", e)
            self._safety.record_failure()
        self._state = LogisticsState.CLOSE_CONTAINER

    async def _do_close_container(self) -> None:
        """Close the container."""
        try:
            await self._mcc.close_container(self._current_inv_id)
        except MccMcpError:
            pass
        self._state = LogisticsState.TELEPORT_TO_DROP

    async def _do_teleport_to_drop(self) -> None:
        """Teleport to drop point."""
        if not self._drop_teleport_cmd:
            # No drop teleport, navigate directly
            self._state = LogisticsState.NAVIGATE_TO_DROP
            return

        await self._update_progress(LogisticsState.TELEPORT_TO_DROP, 0.6,
                                   "Teleporting to drop point...")
        try:
            await self._mcc.send_chat(self._drop_teleport_cmd)
            await asyncio.sleep(self._wait_after_teleport)
            self._state = LogisticsState.NAVIGATE_TO_DROP
        except MccMcpError as e:
            logger.warning("Teleport to drop failed: %s", e)
            self._safety.record_failure()
            self._error_message = f"Teleport to drop failed: {e}"
            self._state = LogisticsState.FAILED

    async def _do_navigate_to_drop(self) -> None:
        """Navigate to the drop point."""
        await self._update_progress(LogisticsState.NAVIGATE_TO_DROP, 0.7,
                                   "Navigating to drop point...")
        success = await self._baritone.path_to_near(
            self._drop_x, self._drop_y, self._drop_z, radius=2
        )
        if success:
            self._state = LogisticsState.DEPOSIT_ITEMS
        else:
            self._safety.record_failure()
            self._error_message = "Failed to navigate to drop point"
            self._state = LogisticsState.FAILED

    async def _do_deposit_items(self) -> None:
        """Deposit items at drop point."""
        await self._update_progress(LogisticsState.DEPOSIT_ITEMS, 0.8,
                                   "Depositing items...")
        try:
            if self._drop_method == "container":
                # Open container and deposit
                result = await self._mcc.open_container_at(
                    self._drop_x, self._drop_y, self._drop_z
                )
                inv_id = result.get("inventoryId", 0)
                await self._mcc.deposit_container_item(
                    self._item_type, self._item_count, inv_id
                )
                await self._mcc.close_container(inv_id)
            else:
                # Drop items on ground
                await self._mcc.drop_inventory_item(self._item_type, self._item_count)
            logger.info("Deposited %d x %s", self._item_count, self._item_type)
            self._safety.reset_failures()
        except MccMcpError as e:
            logger.warning("Deposit failed: %s", e)
            self._safety.record_failure()

        self._loop_count += 1
        if self._max_loops > 0 and self._loop_count >= self._max_loops:
            self._state = LogisticsState.COMPLETED
        else:
            self._state = LogisticsState.WAITING

    async def _do_waiting(self) -> None:
        """Wait between loops."""
        await self._update_progress(LogisticsState.WAITING, 0.9,
                                   f"Loop {self._loop_count}/{self._max_loops} complete, waiting...")
        await asyncio.sleep(2)  # Brief pause between loops
        self._state = LogisticsState.TELEPORT_TO_SOURCE
