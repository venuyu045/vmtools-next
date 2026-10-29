"""时装接口的 HTTP 契约回归：query 参数名必须是文档里的 camelCase。

背景（2026-10-28 实测发现的两个真 bug）：

- 路由函数形参写的是 ``device_code``，FastAPI 默认按形参名取 query，于是 mod 按
  文档发 ``?deviceCode=…`` 时被当成「缺必填参数」→ 422，绑定轮询永远失败；
- 网页衣柜按 ``?identityId=…`` 切换身份，后端同样只认 ``identity_id``，
  多身份账号的切换被静默忽略（永远读写第一个身份）。

两处都用 ``Query(..., alias="...")`` 修好了。本用例不碰数据库 / 网络，只用真实
FastAPI 生成 OpenAPI 后断言对外参数名 —— 谁再改回形参名就会立刻红。

离线 stub 环境（没有真 fastapi）自动跳过；在装了依赖的机器 / CI 上会真正执行。
"""
from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import install, quiet_stub_noise  # noqa: E402

install()  # 幂等：把 backend/src 塞进 sys.path，并只补缺失的依赖
quiet_stub_noise()

try:  # 离线 stub 环境里 fastapi 是假的：FastAPI=object，没有 include_router
    from fastapi import FastAPI

    _HAS_REAL_FASTAPI = hasattr(FastAPI, "include_router") and hasattr(FastAPI, "openapi")
except Exception:  # pragma: no cover - 取决于环境
    _HAS_REAL_FASTAPI = False


@unittest.skipUnless(_HAS_REAL_FASTAPI, "需要真实 FastAPI（离线 stub 环境跳过）")
class FashionQueryParamContractTest(unittest.TestCase):
    """对外 query 参数名契约（文档 / mod / 前端都按 camelCase 调用）。"""

    @classmethod
    def setUpClass(cls) -> None:
        from vmtools_next.api.routers.fashion import router

        app = FastAPI()
        app.include_router(router)
        cls.spec = app.openapi()

    def _query_params(self, path: str, method: str) -> set[str]:
        operation = self.spec["paths"][path][method]
        return {
            param["name"]
            for param in operation.get("parameters", [])
            if param.get("in") == "query"
        }

    def test_device_status_accepts_device_code(self) -> None:
        params = self._query_params("/api/fashion/device/status", "get")
        self.assertIn("deviceCode", params)
        self.assertNotIn("device_code", params)

    def test_loadout_accepts_identity_id(self) -> None:
        for path, method in (
            ("/api/fashion/loadout", "put"),
            ("/api/fashion/loadout/me", "get"),
        ):
            with self.subTest(path=path, method=method):
                params = self._query_params(path, method)
                self.assertIn("identityId", params)
                self.assertNotIn("identity_id", params)

    def test_catalog_keeps_documented_param_names(self) -> None:
        # 文档写的是 category / pack_id（snake_case），不要顺手改成 camelCase
        params = self._query_params("/api/fashion/catalog", "get")
        self.assertIn("category", params)
        self.assertIn("pack_id", params)

    # ── 包级下发：mod 客户端按 /packs 拼 URL（net/PackCatalog.PACKS_PATH） ──

    def test_packs_manifest_route_is_registered_and_public(self) -> None:
        """缺了这个端点，mod 会判定「后端不支持」并关掉整条自动下发链路。"""
        self.assertIn("/api/fashion/packs", self.spec["paths"])
        operation = self.spec["paths"]["/api/fashion/packs"]["get"]
        # 公开：清单请求可能不带 token（匿名也要能拉）
        self.assertNotIn("security", operation)
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/PacksResponse")

    def test_pack_download_route_is_registered_and_public(self) -> None:
        path = "/api/fashion/packs/{pack_id}/{version}/download"
        self.assertIn(path, self.spec["paths"])
        operation = self.spec["paths"][path]["get"]
        self.assertNotIn("security", operation)
        names = {param["name"] for param in operation.get("parameters", [])}
        self.assertEqual(names, {"pack_id", "version"})

    def test_packs_response_schema_uses_camel_case(self) -> None:
        """清单字段名必须与 mod 的 JsonObject.get(...) 完全一致。"""
        schema = self.spec["components"]["schemas"]["PackItem"]
        self.assertEqual(
            set(schema["properties"]),
            {"id", "version", "sha256", "bytes", "url", "publishedAt", "signature", "signingKeyId"},
        )

    def test_resolve_item_schema_has_pack_fields(self) -> None:
        """mod 契约 §3：resolve / loadout 的每个 item 要带 packId / packVersion。"""
        for name in ("ResolvedItem", "LoadoutItemOut"):
            with self.subTest(schema=name):
                props = set(self.spec["components"]["schemas"][name]["properties"])
                self.assertIn("packId", props)
                self.assertIn("packVersion", props)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
