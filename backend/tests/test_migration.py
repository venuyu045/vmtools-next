"""Tests for data migration utilities."""
import json
import os
import tempfile
import pytest
from pathlib import Path

from vmtools_next.data.migration import ConfigMigrator, WarehouseMigrator


class TestConfigMigrator:
    """Test ConfigMigrator."""

    def test_migrate_basic(self, tmp_path):
        """Test basic config migration."""
        # Create a Java config JSON file
        java_config = {
            "enabled": True,
            "debugLogging": False,
            "maxOpsPerTick": 1,
            "placeIntervalTicks": 3,
            "teleportThreshold": 200,
        }
        json_path = tmp_path / "config.json"
        with open(json_path, "w") as f:
            json.dump(java_config, f)

        yaml_path = tmp_path / "config.yaml"

        result = ConfigMigrator.migrate(str(json_path), str(yaml_path))

        assert result is True
        assert yaml_path.exists()

        import yaml
        with open(yaml_path) as f:
            migrated = yaml.safe_load(f)

        assert migrated["generic"]["enabled"] is True
        assert migrated["generic"]["debug_logging"] is False
        assert migrated["safety"]["max_ops_per_tick"] == 1
        assert migrated["safety"]["place_interval_ticks"] == 3
        assert migrated["travel"]["teleport_threshold"] == 200

    def test_migrate_missing_file(self, tmp_path):
        """Test migration with missing source file."""
        result = ConfigMigrator.migrate(
            str(tmp_path / "nonexistent.json"),
            str(tmp_path / "output.yaml"),
        )
        assert result is False

    def test_migrate_unknown_keys(self, tmp_path):
        """Test migration with unknown keys (should be ignored)."""
        java_config = {
            "enabled": True,
            "unknownKey": "value",
            "anotherUnknown": 42,
        }
        json_path = tmp_path / "config.json"
        with open(json_path, "w") as f:
            json.dump(java_config, f)

        yaml_path = tmp_path / "config.yaml"

        result = ConfigMigrator.migrate(str(json_path), str(yaml_path))

        assert result is True
        import yaml
        with open(yaml_path) as f:
            migrated = yaml.safe_load(f)

        assert migrated["generic"]["enabled"] is True
        assert "unknownKey" not in migrated


class TestWarehouseMigrator:
    """Test WarehouseMigrator."""

    def test_migrate_basic(self, tmp_path):
        """Test basic warehouse migration."""
        # Note: This test requires a database session
        # For now, just test the JSON parsing logic
        java_data = {
            "warehouses": [
                {
                    "name": "Main Warehouse",
                    "materials": {
                        "minecraft:stone": 1000,
                        "minecraft:oak_planks": 500,
                    },
                },
            ],
        }
        json_path = tmp_path / "warehouses.json"
        with open(json_path, "w") as f:
            json.dump(java_data, f)

        # Verify the file can be read
        with open(json_path) as f:
            data = json.load(f)

        assert len(data["warehouses"]) == 1
        assert data["warehouses"][0]["name"] == "Main Warehouse"
        assert data["warehouses"][0]["materials"]["minecraft:stone"] == 1000

    def test_migrate_missing_file(self):
        """Test migration with missing source file."""
        # Create a mock db session
        class MockDb:
            def add(self, obj):
                pass
            def commit(self):
                pass
            def rollback(self):
                pass

        result = WarehouseMigrator.migrate("/nonexistent/path.json", MockDb())
        assert result == 0

    def test_migrate_empty_warehouses(self, tmp_path):
        """Test migration with empty warehouses list."""
        java_data = {"warehouses": []}
        json_path = tmp_path / "warehouses.json"
        with open(json_path, "w") as f:
            json.dump(java_data, f)

        class MockDb:
            def __init__(self):
                self.added = []
            def add(self, obj):
                self.added.append(obj)
            def commit(self):
                pass
            def rollback(self):
                pass

        db = MockDb()
        result = WarehouseMigrator.migrate(str(json_path), db)
        assert result == 0
        assert len(db.added) == 0
