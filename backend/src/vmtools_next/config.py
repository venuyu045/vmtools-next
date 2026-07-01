"""Configuration loader for VMTools Next.

Loads YAML config with pydantic-settings, supports environment variable
override (VMT_* prefix) and multi-environment files (dev/prod overlay).
"""
from __future__ import annotations

import os
import pathlib
from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Section models ──────────────────────────────────────────────────────

class GenericConfig(BaseModel):
    enabled: bool = True
    debug_logging: bool = False
    hud_refresh_interval: int = 20


class SafetyConfig(BaseModel):
    max_ops_per_tick: int = 1
    place_interval_ticks: int = 3
    container_interact_interval: int = 10
    teleport_cooldown_seconds: int = 5
    max_pathing_distance: int = 500
    max_failures_before_stop: int = 3
    pause_on_nearby_player: bool = True
    nearby_player_radius: int = 10
    auto_pause_on_disconnect: bool = True


class WarehouseConfig(BaseModel):
    default_scan_range_x: int = 16
    default_scan_range_y: int = 8
    default_scan_range_z: int = 16
    cache_validity_minutes: int = 5
    max_scan_containers: int = 0
    scan_shulker_contents: bool = True
    shulker_recursion_depth: int = 3
    servux_direct_scan: bool = True
    navigate_on_read_fail: bool = False
    servux_read_timeout_ms: int = 800
    servux_prefetch_window: int = 8
    scan_progress_interval: int = 25


class BuildConfig(BaseModel):
    default_layer_height: int = 6
    printer_range: int = 6
    printer_blocks_per_tick: int = 1
    layer_verify_retry_count: int = 3
    auto_continue_next_layer: bool = True


class TravelConfig(BaseModel):
    teleport_threshold: int = 200
    arrival_verify_radius: int = 3
    arrival_timeout_seconds: int = 10
    max_teleports_per_minute: int = 6
    fallback_to_baritone: bool = True


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    debug: bool = False
    database_url: str = "sqlite:///vmtools-next.db"
    secret_key: str = "change-in-production"
    jwt_algorithm: str = "HS256"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    api_token: str = "vmtools-next-token-2026"


class MccConfig(BaseModel):
    protocol: str = "mcp"  # mcp | ws
    mcp_endpoint: str = "http://127.0.0.1:33333/mcp"
    mcp_auth_token_env: str = "MCC_MCP_AUTH_TOKEN"
    ws_timeout: float = 10.0
    reconnect_base_delay: float = 1.0
    reconnect_max_delay: float = 60.0
    command_timeout: float = 30.0
    working_dir: str = "/opt/mcc"

    # Remote process management
    instance_root: str = "/opt/vmtools/mcc-instances"
    binary_path: str = "/opt/vmtools/mcc-runtime/MinecraftClient.exe"
    launch_command: list[str] = Field(default_factory=list)
    instance_start_port: int = 33333
    instance_end_port: int = 33352
    max_instances: int = 20
    terminal_buffer_lines: int = 2000
    log_retention_days: int = 14


class MonitorConfig(BaseModel):
    enabled: bool = True
    collect_interval_seconds: int = 10
    alert_check_interval_seconds: int = 30
    webhook_url: str = ""
    email_smtp_host: str = ""


class PluginBuiltinConfig(BaseModel):
    auto_restock: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})
    discord_notify: dict[str, Any] = Field(default_factory=lambda: {"enabled": False, "webhook": ""})


class PluginsConfig(BaseModel):
    enabled: bool = True
    builtin: PluginBuiltinConfig = Field(default_factory=PluginBuiltinConfig)


class AppConfig(BaseSettings):
    """Top-level application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VMT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    generic: GenericConfig = Field(default_factory=GenericConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    warehouse: WarehouseConfig = Field(default_factory=WarehouseConfig)
    build: BuildConfig = Field(default_factory=BuildConfig)
    travel: TravelConfig = Field(default_factory=TravelConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    mcc: MccConfig = Field(default_factory=MccConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)


# ── Loader ──────────────────────────────────────────────────────────────

def _find_config_dir() -> pathlib.Path:
    """Locate the config directory.

    Priority:
    1. VMT_CONFIG_PATH env var (file or dir)
    2. ../config/ relative to this module (src/vmtools_next/config.py → vmtools-next/config/)
    3. ./config/ cwd fallback
    """
    env_path = os.getenv("VMT_CONFIG_PATH")
    if env_path:
        p = pathlib.Path(env_path)
        if p.is_file():
            return p.parent
        return p
    # src/vmtools_next/config.py → ../../config/
    here = pathlib.Path(__file__).resolve().parent
    candidate = here.parent.parent / "config"
    if candidate.is_dir():
        return candidate
    return pathlib.Path("config")


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base (overlay wins)."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _load_yaml(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def _parse_env_value(value: str) -> Any:
    try:
        parsed = yaml.safe_load(value)
        return value if parsed is None else parsed
    except yaml.YAMLError:
        return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply VMT_* env vars after YAML merge so env wins over files."""
    result = dict(config)
    prefix = "VMT_"
    for raw_key, raw_value in os.environ.items():
        if not raw_key.startswith(prefix) or raw_key in {"VMT_ENV", "VMT_CONFIG_PATH"}:
            continue
        path = raw_key.removeprefix(prefix).lower().split("__")
        if not path or len(path) < 2:
            continue
        cursor = result
        for part in path[:-1]:
            node = cursor.get(part)
            if not isinstance(node, dict):
                node = {}
                cursor[part] = node
            cursor = node
        cursor[path[-1]] = _parse_env_value(raw_value)
    return result


def load_config() -> AppConfig:
    """Load merged configuration from YAML files + environment variables.

    Loading order (later overrides earlier):
    1. config/config.yaml (base)
    2. config/config.{env}.yaml (overlay, env from VMT_ENV or 'dev')
    3. Environment variables (VMT_* prefix, via pydantic-settings)
    """
    config_dir = _find_config_dir()
    base = _load_yaml(config_dir / "config.yaml")

    env = os.getenv("VMT_ENV", "dev")
    overlay = _load_yaml(config_dir / f"config.{env}.yaml")
    merged = _deep_merge(base, overlay)
    merged = _apply_env_overrides(merged)

    return AppConfig(**merged)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Cached singleton config accessor."""
    return load_config()


def save_mcc_config(instance_root: str | None = None, binary_path: str | None = None,
                    launch_command: list[str] | None = None, instance_start_port: int | None = None,
                    instance_end_port: int | None = None, max_instances: int | None = None,
                    log_retention_days: int | None = None) -> AppConfig:
    """Update MCC section in config.yaml and reload."""
    import yaml

    config_dir = _find_config_dir()
    config_path = config_dir / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    mcc = data.setdefault("mcc", {})
    updates = {
        "instance_root": instance_root,
        "binary_path": binary_path,
        "launch_command": launch_command,
        "instance_start_port": instance_start_port,
        "instance_end_port": instance_end_port,
        "max_instances": max_instances,
        "log_retention_days": log_retention_days,
    }
    for key, value in updates.items():
        if value is not None:
            mcc[key] = value

    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    get_config.cache_clear()
    return get_config()


def reload_config() -> AppConfig:
    """Force reload config (clears cache). Call after hot-reload."""
    get_config.cache_clear()
    return get_config()
