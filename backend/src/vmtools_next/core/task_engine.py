"""Task Engine — unified scheduler for build and logistics tasks.

Ported from vmtools-backend task_engine.py. Manages:
  - BuildStateMachine instances (projection-based construction)
  - LogisticsRunner instances (freight transport)
  - Task lifecycle: create → start → pause/resume → complete/cancel
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from vmtools_next.core.build_state_machine import BuildStateMachine, BuildState
from vmtools_next.core.safety_manager import SafetyManager
from vmtools_next.core.travel_manager import TravelManager, TeleportManager
from vmtools_next.core.material_calculator import MaterialCalculator
from vmtools_next.core.warehouse_manager import WarehouseManager
from vmtools_next.core.warehouse_scanner import WarehouseScanner
from vmtools_next.core.inventory_scanner import InventoryScanner
from vmtools_next.core.operation_logger import OperationLogger
from vmtools_next.adapters.mcc.mcc_mcp_client import MccMcpClient
from vmtools_next.adapters.mcc.mcc_session_pool import MccSessionPool
from vmtools_next.adapters.mcc.mcc_baritone import MccBaritoneAdapter
from vmtools_next.adapters.mcc.mcc_printer import MccPrinterAdapter
from vmtools_next.adapters.mcc.mcc_litematica import MccLitematicaAdapter
from vmtools_next.adapters.mcc.mcc_minihud import MccMiniHudAdapter

logger = logging.getLogger("vmtools.task_engine")


class TaskEngine:
    """Unified task scheduler for build and logistics tasks."""

    def __init__(self, pool: MccSessionPool):
        self._pool = pool
        self._build_tasks: dict[str, BuildStateMachine] = {}  # task_id → state machine
        self._logistics_tasks: dict[str, "LogisticsRunner"] = {}  # task_id → runner
        self._bot_tasks: dict[str, str] = {}  # bot_id → task_id (one task per bot)
        self._warehouse_mgr = WarehouseManager()
        self._op_logger = OperationLogger()

    @property
    def warehouse_manager(self) -> WarehouseManager:
        return self._warehouse_mgr

    @property
    def operation_logger(self) -> OperationLogger:
        return self._op_logger

    def _create_build_sm(self, bot_id: str, mcc: MccMcpClient) -> BuildStateMachine:
        """Create a BuildStateMachine with all dependencies for a bot."""
        baritone = MccBaritoneAdapter(mcc)
        printer = MccPrinterAdapter(mcc)
        minihud = MccMiniHudAdapter(mcc)
        litematica = MccLitematicaAdapter(mcc)
        scanner = WarehouseScanner(mcc, minihud)
        safety = SafetyManager()
        travel = TravelManager()
        teleport = TeleportManager()
        material_calc = MaterialCalculator()
        inventory_scanner = InventoryScanner(mcc)

        return BuildStateMachine(
            bot_id=bot_id,
            mcc=mcc,
            litematica=litematica,
            baritone=baritone,
            printer=printer,
            minihud=minihud,
            scanner=scanner,
            warehouse_mgr=self._warehouse_mgr,
            safety=safety,
            travel=travel,
            teleport=teleport,
            material_calc=material_calc,
            inventory_scanner=inventory_scanner,
            op_logger=self._op_logger,
        )

    async def start_build_task(self, bot_id: str, projection_path: str,
                                origin_x: int = 0, origin_y: int = 0,
                                origin_z: int = 0) -> Optional[str]:
        """Start a build task for a bot.

        Returns task_id on success, None on failure.
        """
        # Check if bot already has a task
        if bot_id in self._bot_tasks:
            logger.warning("Bot %s already has task %s", bot_id, self._bot_tasks[bot_id])
            return None

        # Get MCP client
        client = self._pool.get_client(bot_id)
        if not client:
            logger.error("Bot %s not connected", bot_id)
            return None

        # Create state machine
        sm = self._create_build_sm(bot_id, client)
        task_id = str(uuid.uuid4())

        # Create projection info
        from vmtools_next.core.dataclasses import ProjectionInfo
        projection = ProjectionInfo(
            file_path=projection_path,
            origin_x=origin_x,
            origin_y=origin_y,
            origin_z=origin_z,
        )

        # Start the build
        success = await sm.start(projection)
        if success:
            self._build_tasks[task_id] = sm
            self._bot_tasks[bot_id] = task_id
            logger.info("Build task %s started for bot %s", task_id, bot_id)
            return task_id
        else:
            logger.error("Failed to start build task for bot %s", bot_id)
            return None

    async def start_logistics_task(self, bot_id: str, template_id: str) -> Optional[str]:
        """Start a logistics task for a bot.

        Looks up the template, waypoint, and drop point from the DB,
        creates a LogisticsRunner, and starts it.

        Returns task_id (run_id) on success, None on failure.
        """
        from vmtools_next.core.logistics_runner import LogisticsRunner

        # Check if bot already has a task
        if bot_id in self._bot_tasks:
            logger.warning("Bot %s already has task %s", bot_id, self._bot_tasks[bot_id])
            return None

        # Get MCP client
        client = self._pool.get_client(bot_id)
        if not client:
            logger.error("Bot %s not connected", bot_id)
            return None

        # Look up template, waypoint, drop point from DB
        from vmtools_next.data.db import get_session_factory
        from vmtools_next.data.models.logistics import (
            LogisticsTaskTemplateModel, LogisticsWaypointModel, LogisticsDropPointModel,
        )
        from vmtools_next.data.models.logistics import LogisticsTaskRunModel

        Session = get_session_factory()
        db = Session()
        try:
            template = db.query(LogisticsTaskTemplateModel).filter(
                LogisticsTaskTemplateModel.template_id == template_id
            ).first()
            if not template:
                logger.error("Template %s not found", template_id)
                return None

            waypoint = db.query(LogisticsWaypointModel).filter(
                LogisticsWaypointModel.waypoint_id == template.source_waypoint_id
            ).first()
            if not waypoint:
                logger.error("Waypoint %s not found", template.source_waypoint_id)
                return None

            drop_point = db.query(LogisticsDropPointModel).filter(
                LogisticsDropPointModel.drop_point_id == template.drop_point_id
            ).first()
            if not drop_point:
                logger.error("Drop point %s not found", template.drop_point_id)
                return None
        finally:
            db.close()

        # Create runner
        baritone = MccBaritoneAdapter(client)
        safety = SafetyManager()
        teleport = TeleportManager()
        runner = LogisticsRunner(
            mcc=client, baritone=baritone, safety=safety,
            teleport=teleport, op_logger=self._op_logger, bot_id=bot_id,
        )

        # Determine max_loops from template
        max_loops = 0 if template.loop_mode == "loop" else 1

        # Start the runner
        success = await runner.start(
            source_teleport_cmd=waypoint.teleport_command,
            source_container_x=waypoint.container_x,
            source_container_y=waypoint.container_y,
            source_container_z=waypoint.container_z,
            item_type=waypoint.item_id or waypoint.item_name,
            item_count=64,
            drop_teleport_cmd=drop_point.teleport_command,
            drop_x=drop_point.drop_x or 0,
            drop_y=drop_point.drop_y or 0,
            drop_z=drop_point.drop_z or 0,
            drop_method=drop_point.drop_method,
            wait_after_teleport=waypoint.wait_after_teleport,
            max_loops=max_loops,
        )

        if success:
            run_id = str(uuid.uuid4())
            self._logistics_tasks[run_id] = runner
            self._bot_tasks[bot_id] = run_id

            # Create run record in DB
            Session2 = get_session_factory()
            db2 = Session2()
            try:
                run = LogisticsTaskRunModel(
                    run_id=run_id,
                    template_id=template_id,
                    bot_id=bot_id,
                    status="running",
                    current_state="TELEPORT_TO_SOURCE",
                )
                db2.add(run)
                db2.commit()
            finally:
                db2.close()

            logger.info("Logistics task %s started for bot %s (template=%s)", run_id, bot_id, template_id)
            return run_id
        else:
            logger.error("Failed to start logistics task for bot %s", bot_id)
            return None

    async def stop_task(self, task_id: str) -> bool:
        """Stop a task (build or logistics)."""
        # Try build tasks first
        sm = self._build_tasks.get(task_id)
        if sm:
            await sm.stop()
            for bid, tid in list(self._bot_tasks.items()):
                if tid == task_id:
                    del self._bot_tasks[bid]
                    break
            del self._build_tasks[task_id]
            logger.info("Build task %s stopped", task_id)
            return True

        # Try logistics tasks
        runner = self._logistics_tasks.get(task_id)
        if runner:
            await runner.stop()
            for bid, tid in list(self._bot_tasks.items()):
                if tid == task_id:
                    del self._bot_tasks[bid]
                    break
            del self._logistics_tasks[task_id]
            logger.info("Logistics task %s stopped", task_id)
            return True

        return False

    async def pause_task(self, task_id: str) -> bool:
        """Pause a task (build or logistics)."""
        sm = self._build_tasks.get(task_id)
        if sm:
            await sm.pause()
            return True
        runner = self._logistics_tasks.get(task_id)
        if runner:
            await runner.pause()
            return True
        return False

    async def resume_task(self, task_id: str) -> bool:
        """Resume a task (build or logistics)."""
        sm = self._build_tasks.get(task_id)
        if sm:
            await sm.resume()
            return True
        runner = self._logistics_tasks.get(task_id)
        if runner:
            await runner.resume()
            return True
        return False

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get the status of a task (build or logistics)."""
        sm = self._build_tasks.get(task_id)
        if sm:
            return {
                "type": "build",
                "task_id": task_id,
                "state": sm.state.name,
                "current_layer": sm.current_layer,
                "total_layers": sm.total_layers,
                "is_running": sm.is_running,
            }
        runner = self._logistics_tasks.get(task_id)
        if runner:
            return {
                "type": "logistics",
                "task_id": task_id,
                "state": runner.state.name,
                "loop_count": runner.loop_count,
                "is_running": runner.is_running,
            }
        return None

    def get_all_tasks(self) -> list[dict]:
        """Get status of all tasks (build + logistics)."""
        tasks = []
        for tid, sm in self._build_tasks.items():
            tasks.append({
                "type": "build",
                "task_id": tid,
                "state": sm.state.name,
                "current_layer": sm.current_layer,
                "total_layers": sm.total_layers,
                "is_running": sm.is_running,
            })
        for tid, runner in self._logistics_tasks.items():
            tasks.append({
                "type": "logistics",
                "task_id": tid,
                "state": runner.state.name,
                "loop_count": runner.loop_count,
                "is_running": runner.is_running,
            })
        return tasks

    def get_bot_task(self, bot_id: str) -> Optional[str]:
        """Get the task_id for a bot."""
        return self._bot_tasks.get(bot_id)
