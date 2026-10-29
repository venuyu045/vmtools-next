"""import 冒烟 —— 离线 stub 环境下，重构涉及的入口模块都必须能 import。

覆盖（Lead / api-data 确认过的依赖缺口）：
  - ``core.map_art`` 新包 + 两个历史 shim（``map_art_coordinator`` / ``multi_bot_coordinator``）
  - ``api.routers.build_map_art``（依赖 fastapi.security / litematica_parser 的 cachetools）
  - ``api.socketio_handlers``
  - ``data.models``（SQLAlchemy ORM 模型全集）
  - ``config``（pydantic_settings）

这些 import 挂掉 = 服务起不来，比任何单测都优先。stub 缺符号时本文件会直接报
``ModuleNotFoundError`` / ``ImportError``，定位到具体模块。

跑法::

    python3 -m unittest discover -s backend/tests -p 'test_map_art_*.py' -v
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import install, quiet_stub_noise  # noqa: E402

install()
quiet_stub_noise()

IMPORT_SMOKE_MODULES = [
    # 引擎新包 + 两个兼容 shim
    "vmtools_next.core.map_art",
    "vmtools_next.core.map_art_coordinator",
    "vmtools_next.core.multi_bot_coordinator",
    # API / Socket / 数据层 / 配置
    "vmtools_next.api.routers.build_map_art",
    "vmtools_next.api.socketio_handlers",
    "vmtools_next.data.models",
    "vmtools_next.config",
]


class TestInstallIdempotent(unittest.TestCase):
    def test_install_twice_is_noop(self):
        before = set(sys.modules)
        install()
        install()
        self.assertTrue(before <= set(sys.modules))
        self.assertIn("pydantic", sys.modules)
        self.assertIn("sqlalchemy", sys.modules)
        self.assertIn("fastapi", sys.modules)

    def test_src_on_sys_path(self):
        from _stub_env import SRC

        self.assertIn(SRC, sys.path)
        self.assertTrue(os.path.isdir(os.path.join(SRC, "vmtools_next")))

    def test_stub_symbols_used_by_api(self):
        """api-data 报告过的三个依赖缺口：fastapi.security / websockets / cachetools。"""
        import cachetools
        import fastapi
        import websockets
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: F401

        self.assertTrue(hasattr(fastapi, "security"))
        self.assertTrue(hasattr(websockets, "connect"))
        self.assertTrue(hasattr(websockets, "ConnectionClosed"))
        self.assertTrue(hasattr(cachetools, "TTLCache"))


class TestImportSmoke(unittest.TestCase):
    def test_import_all_entry_modules(self):
        for name in IMPORT_SMOKE_MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertIsNotNone(mod)

    def test_shims_reexport_new_package(self):
        """两个 shim 必须是 re-export，不是第二份实现（防止重构回退）。"""
        from vmtools_next.core import map_art, map_art_coordinator, multi_bot_coordinator

        self.assertIs(map_art_coordinator.MapArtCoordinator, map_art.MapArtCoordinator)
        self.assertIs(map_art_coordinator.StripBuildLoop, map_art.StripBuildLoop)
        self.assertIs(multi_bot_coordinator.MultiBotCoordinator, map_art.MultiBotCoordinator)
        self.assertIs(multi_bot_coordinator.ColumnBuildLoop, map_art.ColumnBuildLoop)
        # 历史类名别名
        self.assertIs(map_art_coordinator.BotBuildLoop, map_art.StripBuildLoop)
        # shim 文件的函数也必须是新包里的同一个对象
        self.assertIs(map_art_coordinator.partition_rectangular,
                      map_art.partition_rectangular)
        self.assertIs(map_art_coordinator.build_2d_matrix, map_art.build_2d_matrix)

    def test_public_api_surface(self):
        """``__all__`` 里声明的名字都必须真的存在（防重构漏搬导出）。"""
        from vmtools_next.core import map_art

        missing = [n for n in map_art.__all__ if not hasattr(map_art, n)]
        self.assertEqual(missing, [], f"map_art.__all__ 里这些名字取不到：{missing}")

    def test_build_map_art_router_registered(self):
        """API 路由模块必须真的挂上 router（import 成功但空 router 也算异常）。"""
        from vmtools_next.api.routers import build_map_art

        self.assertTrue(hasattr(build_map_art, "router"))
        self.assertEqual(build_map_art.router.prefix, "/api/build/map-art")
        self.assertTrue(build_map_art.router.routes,
                        "build_map_art.router 一条路由都没注册")


if __name__ == "__main__":
    unittest.main(verbosity=2)
