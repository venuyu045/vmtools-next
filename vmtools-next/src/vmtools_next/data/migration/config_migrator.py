"""Config Migrator — converts Java vmtools.json to config.yaml.

Reads malilib-format JSON config and maps to YAML format.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Optional

import yaml

logger = logging.getLogger("vmtools.migration.config")

# Java config key → YAML path mapping (supports both flat and nested Java keys)
# Flat keys: "enabled" → "generic.enabled" (used by simple Java configs)
# Nested keys: "generic.enabled" → "generic.enabled" (used by structured Java configs)
FLAT_KEY_MAPPING = {
    "enabled": "generic.enabled",
    "debugLogging": "generic.debug_logging",
    "hudRefreshInterval": "generic.hud_refresh_interval",
    "maxOpsPerTick": "safety.max_ops_per_tick",
    "placeIntervalTicks": "safety.place_interval_ticks",
    "containerInteractInterval": "safety.container_interact_interval",
    "teleportCooldownSeconds": "safety.teleport_cooldown_seconds",
    "maxPathingDistance": "safety.max_pathing_distance",
    "maxFailuresBeforeStop": "safety.max_failures_before_stop",
    "pauseOnNearbyPlayer": "safety.pause_on_nearby_player",
    "nearbyPlayerRadius": "safety.nearby_player_radius",
    "defaultLayerHeight": "build.default_layer_height",
    "printerRange": "build.printer_range",
    "printerBlocksPerTick": "build.printer_blocks_per_tick",
    "teleportThreshold": "travel.teleport_threshold",
    "arrivalVerifyRadius": "travel.arrival_verify_radius",
}

# Nested keys: "section.key" → "section.yaml_key"
NESTED_KEY_MAPPING = {
    "generic.enabled": "generic.enabled",
    "generic.debugLogging": "generic.debug_logging",
    "generic.hudRefreshInterval": "generic.hud_refresh_interval",
    "safety.maxOpsPerTick": "safety.max_ops_per_tick",
    "safety.placeIntervalTicks": "safety.place_interval_ticks",
    "safety.containerInteractInterval": "safety.container_interact_interval",
    "safety.teleportCooldownSeconds": "safety.teleport_cooldown_seconds",
    "safety.maxPathingDistance": "safety.max_pathing_distance",
    "safety.maxFailuresBeforeStop": "safety.max_failures_before_stop",
    "safety.pauseOnNearbyPlayer": "safety.pause_on_nearby_player",
    "safety.nearbyPlayerRadius": "safety.nearby_player_radius",
    "warehouse.defaultScanRangeX": "warehouse.default_scan_range_x",
    "warehouse.defaultScanRangeY": "warehouse.default_scan_range_y",
    "warehouse.defaultScanRangeZ": "warehouse.default_scan_range_z",
    "warehouse.cacheValidityMinutes": "warehouse.cache_validity_minutes",
    "warehouse.scanShulkerContents": "warehouse.scan_shulker_contents",
    "build.defaultLayerHeight": "build.default_layer_height",
    "build.printerRange": "build.printer_range",
    "build.printerBlocksPerTick": "build.printer_blocks_per_tick",
    "build.layerVerifyRetryCount": "build.layer_verify_retry_count",
    "travel.teleportThreshold": "travel.teleport_threshold",
    "travel.arrivalVerifyRadius": "travel.arrival_verify_radius",
    "travel.arrivalTimeoutSeconds": "travel.arrival_timeout_seconds",
    "travel.maxTeleportsPerMinute": "travel.max_teleports_per_minute",
}


class ConfigMigrator:
    """Migrates Java vmtools.json to config.yaml."""

    @staticmethod
    def migrate(json_path: str, yaml_path: str) -> bool:
        """Convert Java JSON config to YAML format.

        Supports two Java config formats:
        - Flat keys: {"enabled": true, "debugLogging": false, ...}
        - Nested keys: {"generic": {"enabled": true}, "safety": {"maxOpsPerTick": 1}}
        """
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                java_config = json.load(f)

            yaml_config: dict = {}

            # Detect format: if any top-level key contains a dot-key in NESTED_KEY_MAPPING,
            # it's nested; otherwise flat.
            is_nested = any(
                isinstance(java_config.get(section), dict)
                for section in ("generic", "safety", "build", "travel", "warehouse")
            )

            if is_nested:
                # Nested format: {"generic": {"enabled": true, ...}, ...}
                for java_key, yaml_path_str in NESTED_KEY_MAPPING.items():
                    value = ConfigMigrator._get_nested(java_config, java_key)
                    if value is not None:
                        ConfigMigrator._set_nested(yaml_config, yaml_path_str, value)
            else:
                # Flat format: {"enabled": true, "debugLogging": false, ...}
                for flat_key, yaml_path_str in FLAT_KEY_MAPPING.items():
                    value = java_config.get(flat_key)
                    if value is not None:
                        ConfigMigrator._set_nested(yaml_config, yaml_path_str, value)

            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(yaml_config, f, default_flow_style=False, allow_unicode=True)

            logger.info("Config migrated: %s → %s (%d keys)", json_path, yaml_path, len(yaml_config))
            return True
        except Exception as e:
            logger.error("Config migration failed: %s", e)
            return False

    @staticmethod
    def _get_nested(data: dict, key: str) -> Optional[str]:
        """Get a value from nested dict using dot notation."""
        parts = key.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    @staticmethod
    def _set_nested(data: dict, path: str, value) -> None:
        """Set a value in nested dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
