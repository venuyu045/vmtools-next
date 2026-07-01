"""Script Generator — generates MCC freight scripts (.txt format).

Migrated from vmtools-backend services/script_generator.py.
Generates step-by-step scripts for MCC's RunScript command.
"""
from __future__ import annotations

import logging
from typing import Optional

from vmtools_next.core.dataclasses import TravelTarget, TeleportCommandTemplate

logger = logging.getLogger("vmtools.script_generator")


class ScriptGenerator:
    """Generates MCC freight scripts."""

    @staticmethod
    def generate_pickup_script(
        waypoint_name: str,
        teleport_cmd: str,
        container_x: int, container_y: int, container_z: int,
        item_type: str, count: int,
        wait_after_teleport: int = 31,
        transfer_slots: Optional[list[tuple[int, int]]] = None,
    ) -> str:
        """Generate a pickup script for a single waypoint."""
        lines = [
            f"# Pickup: {waypoint_name}",
            f"# Item: {item_type} x{count}",
            "",
            "# Step 1: Teleport",
            teleport_cmd,
            f"wait {wait_after_teleport}",
            "",
            "# Step 2: Navigate to container",
            f"look {container_x} {container_y} {container_z}",
            f"goto {container_x} {container_y} {container_z}",
            "wait 5",
            "",
            "# Step 3: Open container",
            f"useblock {container_x} {container_y} {container_z}",
            "wait 3",
            "",
        ]

        if transfer_slots:
            lines.append("# Step 4: Transfer items")
            for src_slot, dst_slot in transfer_slots:
                lines.append(f"inventory shiftclick {src_slot}")
                lines.append("wait 1")
        else:
            lines.append("# Step 4: Withdraw items")
            lines.append(f"inventory withdraw {item_type} {count}")
            lines.append("wait 2")

        lines.extend([
            "",
            "# Step 5: Close container",
            "inventory close",
            "wait 1",
        ])

        return "\n".join(lines)

    @staticmethod
    def generate_drop_script(
        drop_point_name: str,
        teleport_cmd: str,
        drop_x: int, drop_y: int, drop_z: int,
        item_type: str, count: int,
        drop_method: str = "drop",
        wait_after_teleport: int = 5,
    ) -> str:
        """Generate a drop script for a single drop point."""
        lines = [
            f"# Drop: {drop_point_name}",
            f"# Item: {item_type} x{count}",
            "",
            "# Step 1: Teleport",
            teleport_cmd,
            f"wait {wait_after_teleport}",
            "",
            "# Step 2: Navigate to drop point",
            f"goto {drop_x} {drop_y} {drop_z}",
            "wait 3",
            "",
        ]

        if drop_method == "container":
            lines.extend([
                "# Step 3: Open container",
                f"useblock {drop_x} {drop_y} {drop_z}",
                "wait 3",
                f"inventory deposit {item_type} {count}",
                "wait 2",
                "inventory close",
            ])
        else:
            lines.extend([
                "# Step 3: Drop items",
                f"inventory drop {item_type} {count}",
                "wait 2",
            ])

        return "\n".join(lines)

    @staticmethod
    def generate_round_trip_script(
        waypoint_name: str,
        pickup_teleport: str, pickup_x: int, pickup_y: int, pickup_z: int,
        drop_teleport: str, drop_x: int, drop_y: int, drop_z: int,
        item_type: str, count: int,
        wait_after_teleport: int = 31,
    ) -> str:
        """Generate a complete round-trip script (pickup + drop)."""
        pickup = ScriptGenerator.generate_pickup_script(
            waypoint_name, pickup_teleport, pickup_x, pickup_y, pickup_z,
            item_type, count, wait_after_teleport,
        )
        drop = ScriptGenerator.generate_drop_script(
            "Drop Point", drop_teleport, drop_x, drop_y, drop_z,
            item_type, count,
        )
        return f"{pickup}\n\n{'='*40}\n\n{drop}"
