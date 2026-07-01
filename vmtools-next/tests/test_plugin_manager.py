"""Tests for PluginManager."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from vmtools_next.plugins.manager import PluginManager
from vmtools_next.plugins.base import IPlugin, PluginContext


class MockPlugin(IPlugin):
    """Mock plugin for testing."""

    def __init__(self, name: str = "test_plugin", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.loaded = False
        self.started = False
        self.stopped = False
        self.reloaded = False
        self.events = []

    async def load(self, context: PluginContext) -> None:
        self.loaded = True

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def reload(self) -> None:
        self.reloaded = True

    async def on_event(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


@pytest.fixture
def mock_context():
    """Create a mock plugin context."""
    context = MagicMock(spec=PluginContext)
    context.task_engine = MagicMock()
    context.pool = MagicMock()
    return context


@pytest.fixture
def plugin_manager(mock_context):
    """Create a PluginManager with mock context."""
    return PluginManager(mock_context)


class TestPluginManager:
    """Test PluginManager operations."""

    def test_init(self, plugin_manager):
        """Test PluginManager initialization."""
        assert len(plugin_manager.plugins) == 0

    def test_is_enabled_unknown(self, plugin_manager):
        """Test is_enabled for unknown plugin."""
        assert plugin_manager.is_enabled("unknown") is False

    @pytest.mark.asyncio
    async def test_enable_plugin(self, plugin_manager):
        """Test enabling a plugin."""
        plugin = MockPlugin()
        plugin_manager._plugins["test"] = plugin
        plugin_manager._enabled["test"] = False

        result = await plugin_manager.enable("test")

        assert result is True
        assert plugin.started is True
        assert plugin_manager.is_enabled("test") is True

    @pytest.mark.asyncio
    async def test_enable_unknown_plugin(self, plugin_manager):
        """Test enabling an unknown plugin."""
        result = await plugin_manager.enable("unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_disable_plugin(self, plugin_manager):
        """Test disabling a plugin."""
        plugin = MockPlugin()
        plugin_manager._plugins["test"] = plugin
        plugin_manager._enabled["test"] = True

        result = await plugin_manager.disable("test")

        assert result is True
        assert plugin.stopped is True
        assert plugin_manager.is_enabled("test") is False

    @pytest.mark.asyncio
    async def test_disable_unknown_plugin(self, plugin_manager):
        """Test disabling an unknown plugin."""
        result = await plugin_manager.disable("unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_reload_plugin(self, plugin_manager):
        """Test reloading a plugin."""
        plugin = MockPlugin()
        plugin_manager._plugins["test"] = plugin

        result = await plugin_manager.reload("test")

        assert result is True
        assert plugin.reloaded is True

    @pytest.mark.asyncio
    async def test_reload_unknown_plugin(self, plugin_manager):
        """Test reloading an unknown plugin."""
        result = await plugin_manager.reload("unknown")
        assert result is False

    @pytest.mark.asyncio
    async def test_reload_all(self, plugin_manager):
        """Test reloading all plugins."""
        plugin1 = MockPlugin("plugin1")
        plugin2 = MockPlugin("plugin2")
        plugin_manager._plugins["plugin1"] = plugin1
        plugin_manager._plugins["plugin2"] = plugin2

        await plugin_manager.reload_all()

        assert plugin1.reloaded is True
        assert plugin2.reloaded is True

    @pytest.mark.asyncio
    async def test_reload_all_empty(self, plugin_manager):
        """Test reloading all plugins when none are loaded."""
        await plugin_manager.reload_all()  # Should not raise

    @pytest.mark.asyncio
    async def test_start_all(self, plugin_manager):
        """Test starting all enabled plugins."""
        plugin1 = MockPlugin("plugin1")
        plugin2 = MockPlugin("plugin2")
        plugin_manager._plugins["plugin1"] = plugin1
        plugin_manager._plugins["plugin2"] = plugin2
        plugin_manager._enabled["plugin1"] = True
        plugin_manager._enabled["plugin2"] = False

        await plugin_manager.start_all()

        assert plugin1.started is True
        assert plugin2.started is False

    @pytest.mark.asyncio
    async def test_stop_all(self, plugin_manager):
        """Test stopping all plugins."""
        plugin1 = MockPlugin("plugin1")
        plugin2 = MockPlugin("plugin2")
        plugin_manager._plugins["plugin1"] = plugin1
        plugin_manager._plugins["plugin2"] = plugin2

        await plugin_manager.stop_all()

        assert plugin1.stopped is True
        assert plugin2.stopped is True

    @pytest.mark.asyncio
    async def test_dispatch_event(self, plugin_manager):
        """Test dispatching an event to enabled plugins."""
        plugin1 = MockPlugin("plugin1")
        plugin2 = MockPlugin("plugin2")
        plugin_manager._plugins["plugin1"] = plugin1
        plugin_manager._plugins["plugin2"] = plugin2
        plugin_manager._enabled["plugin1"] = True
        plugin_manager._enabled["plugin2"] = False

        await plugin_manager.dispatch_event("test_event", {"key": "value"})

        assert len(plugin1.events) == 1
        assert plugin1.events[0] == ("test_event", {"key": "value"})
        assert len(plugin2.events) == 0
