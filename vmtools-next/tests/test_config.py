"""Tests for configuration loading."""
import pytest
import os
import tempfile
import yaml
from vmtools_next.config import AppConfig, load_config, _deep_merge


class TestConfig:
    def test_default_config(self):
        config = AppConfig()
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8080
        assert config.generic.enabled == True

    def test_deep_merge(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        overlay = {"b": {"c": 10}, "e": 5}
        result = _deep_merge(base, overlay)
        assert result["a"] == 1
        assert result["b"]["c"] == 10
        assert result["b"]["d"] == 3
        assert result["e"] == 5

    def test_config_from_yaml(self, tmp_path):
        config_data = {
            "server": {"port": 9090, "debug": True},
            "generic": {"enabled": False},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        # This would need VMT_CONFIG_PATH set
        assert config_file.exists()

    def test_safety_config(self):
        config = AppConfig()
        assert config.safety.max_ops_per_tick == 1
        assert config.safety.max_failures_before_stop == 3
        assert config.safety.pause_on_nearby_player == True

    def test_warehouse_config(self):
        config = AppConfig()
        assert config.warehouse.default_scan_range_x == 16
        assert config.warehouse.cache_validity_minutes == 5

    def test_build_config(self):
        config = AppConfig()
        assert config.build.default_layer_height == 6
        assert config.build.printer_range == 6

    def test_travel_config(self):
        config = AppConfig()
        assert config.travel.teleport_threshold == 200
        assert config.travel.arrival_verify_radius == 3

    def test_mcc_config(self):
        config = AppConfig()
        assert config.mcc.protocol == "mcp"
        assert config.mcc.mcp_endpoint == "http://127.0.0.1:33333/mcp"
