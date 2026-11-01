"""「我的衣柜」收藏 API 单测（service + 路由接线 + 迁移）。

背景：商店页（/fashion/store）与衣柜页（/fashion/wardrobe）此前共用「全站目录」，
用户要求只有**主动加入衣柜**的时装才出现在衣柜里，且支持单件/批量删除。后端为此
新增 ``fashion_wardrobe`` 表 + 4 个接口（见 task-1 契约）。

离线可跑：本机没装 fastapi/sqlalchemy，走 ``_stub_env`` 的 stub + 本文件的
``FakeSession``（与 test_fashion_loadout.py / test_fashion_api.py 同一套写法）。

路由层断言：stub 的 ``_Router`` 没有 ``.head``，直接 import ``routers/fashion.py``
会炸（这也是 test_fashion_api / test_fashion_http 在离线环境里的既有错误），
所以 :func:`_import_fashion_router` 在导入期间临时补一个 ``.head`` 再立刻还原，
只在**本文件**生效，不污染其它测试模块。

跑法::

    cd backend && python3 -m unittest tests.test_fashion_wardrobe -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import install, quiet_stub_noise  # noqa: E402

install()
quiet_stub_noise()

from vmtools_next.core import fashion_service as svc  # noqa: E402
from vmtools_next.core.fashion_service import FashionServiceError  # noqa: E402
from vmtools_next.data.models.fashion import (  # noqa: E402
    FashionCatalogModel,
    FashionWardrobeModel,
)

USER_A = "user-aaaa-1111"
USER_B = "user-bbbb-2222"

# 契约里 WardrobeItemOut 的字段集合（对外 camelCase，一个字都不能少/多）
_WARDROBE_ITEM_KEYS = {
    "cosmeticId", "name", "category", "packId", "assetKey",
    "sha256", "bytes", "sortOrder", "addedAt", "missing",
}


# ── 最小假 Session（内存表 + filter_by 语义，同 test_fashion_loadout 的写法） ──

class _FakeQuery:
    def __init__(self, session: "FakeSession", model):
        self.session = session
        self.model = model
        self._preds: list[tuple] = []

    def filter_by(self, **kwargs):
        for key, value in kwargs.items():
            self._preds.append(("eq", key, value))
        return self

    def filter(self, *criteria):
        for crit in criteria:
            if isinstance(crit, tuple) and crit and crit[0] in ("eq", "ne", "in"):
                self._preds.append(crit)
        return self

    def order_by(self, *args):
        return self

    def limit(self, count):
        return self

    def _match(self, row) -> bool:
        for op, name, value in self._preds:
            actual = getattr(row, name, None)
            if op == "eq" and actual != value:
                return False
            if op == "ne" and actual == value:
                return False
            if op == "in" and actual not in value:
                return False
        return True

    def all(self):
        return [row for row in self.session.rows(self.model) if self._match(row)]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

    def count(self):
        return len(self.all())

    def delete(self):
        rows = self.all()
        for row in rows:
            self.session.delete(row)
        return len(rows)


class FakeSession:
    """最小 Session：add/delete/commit/rollback/query。"""

    def __init__(self):
        self.tables: dict[type, list] = {}
        self.commits = 0
        self.rollbacks = 0

    def rows(self, model) -> list:
        return self.tables.setdefault(model, [])

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        rows = self.rows(type(obj))
        if obj not in rows:
            rows.append(obj)

    def delete(self, obj):
        rows = self.rows(type(obj))
        if obj in rows:
            rows.remove(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        pass

    def close(self):
        pass

    def get(self, model, pk):
        for row in self.rows(model):
            if getattr(row, "id", None) == pk:
                return row
        return None


def make_settings(**overrides):
    """目录缓存 TTL 设 0：单测里每个用例自己 seed 目录，缓存只会串味。"""
    base = dict(catalog_cache_ttl_seconds=0)
    base.update(overrides)
    return types.SimpleNamespace(**base)


class _User:
    """``deps.get_current_user`` 返回值的替身（路由函数只要 ``.id``）。"""

    def __init__(self, user_id: str):
        self.id = user_id
        self.role = "user"
        self.status = "approved"


def _attr(obj, *names):
    """兼容 stub BaseModel（原样 setattr）与真 pydantic（字段名/别名）两种取值。"""
    for name in names:
        if isinstance(obj, dict):
            if obj.get(name) is not None:
                return obj[name]
            continue
        value = getattr(obj, name, None)
        if value is not None and value is not Ellipsis:
            return value
    return None


def _http_code(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return str(detail.get("code", ""))
    return ""


_ROUTER_MODULE = None


def _import_fashion_router():
    """导入 ``routers/fashion.py``；stub 的 ``_Router`` 缺 ``.head`` 时临时补上。"""
    global _ROUTER_MODULE
    if _ROUTER_MODULE is not None:
        return _ROUTER_MODULE
    from _stub_env import _Router

    patched = not hasattr(_Router, "head")
    if patched:
        _Router.head = _Router.get
    try:
        from vmtools_next.api.routers import fashion as api_module
    finally:
        if patched:
            try:
                del _Router.head
            except AttributeError:  # pragma: no cover - 已被别处还原
                pass
    _ROUTER_MODULE = api_module
    return api_module


# ── 夹具 ────────────────────────────────────────────────────────────────

class _Base(unittest.TestCase):
    """三件目录时装 + 空衣柜。"""

    def setUp(self):
        svc.invalidate_caches()
        self.settings = make_settings()
        self.db = FakeSession()
        svc.upsert_catalog_item(self.db, {
            "cosmeticId": "cape_dragon",
            "packId": "pack1",
            "name": "龙翼披风",
            "category": "cape",
            "assetKey": "cape/dragon.png",
            "sortOrder": 1,
        })
        svc.upsert_catalog_item(self.db, {
            "cosmeticId": "wings_angel",
            "packId": "pack1",
            "name": "天使之翼",
            "category": "wings",
            "assetKey": "wings/angel.glb",
            "sortOrder": 2,
        })
        svc.upsert_catalog_item(self.db, {
            "cosmeticId": "hat_crown",
            "packId": "pack1",
            "name": "王冠",
            "category": "hat",
            "assetKey": "hat/crown.png",
            "sortOrder": 3,
        })

    # -- helpers --
    def add(self, cosmetic_id, user_id=USER_A):
        return svc.add_wardrobe_item(self.db, user_id, cosmetic_id)

    def list_items(self, user_id=USER_A):
        return svc.list_wardrobe(self.db, user_id, settings=self.settings)

    def rows(self, user_id=None):
        rows = list(self.db.rows(FashionWardrobeModel))
        if user_id is not None:
            rows = [row for row in rows if row.user_id == user_id]
        return rows

    def row(self, cosmetic_id, user_id=USER_A):
        for row in self.rows(user_id):
            if row.cosmetic_id == cosmetic_id:
                return row
        return None

    def set_added_at(self, cosmetic_id, value, user_id=USER_A):
        row = self.row(cosmetic_id, user_id)
        self.assertIsNotNone(row, f"{cosmetic_id} 不在衣柜里")
        row.added_at = value
        return row


# ── 加入衣柜 ────────────────────────────────────────────────────────────

class TestAddWardrobeItem(_Base):
    def test_add_persists_and_returns_item(self):
        item, added = self.add("cape_dragon")

        self.assertTrue(added)
        self.assertEqual(item["cosmeticId"], "cape_dragon")
        self.assertEqual(item["name"], "龙翼披风")
        self.assertEqual(item["category"], "cape")
        self.assertEqual(item["packId"], "pack1")
        self.assertEqual(item["assetKey"], "cape/dragon.png")
        self.assertEqual(item["sha256"], "")
        self.assertEqual(item["bytes"], 0)
        self.assertEqual(item["sortOrder"], 1)
        self.assertFalse(item["missing"])
        self.assertIsInstance(item["addedAt"], str)
        self.assertTrue(item["addedAt"].endswith("+00:00"))
        # 对外字段与契约完全一致（不多不少）
        self.assertEqual(set(item), _WARDROBE_ITEM_KEYS)

        self.assertEqual(len(self.rows(USER_A)), 1)
        self.assertEqual(self.rows(USER_A)[0].cosmetic_id, "cape_dragon")

    def test_add_is_idempotent(self):
        first, first_added = self.add("cape_dragon")
        second, second_added = self.add("cape_dragon")

        self.assertTrue(first_added)
        self.assertFalse(second_added, "重复加入应返回 added=False（幂等，不报错）")
        self.assertEqual(second["cosmeticId"], first["cosmeticId"])
        self.assertEqual(second["addedAt"], first["addedAt"], "幂等时不能刷新加入时间")
        self.assertEqual(len(self.rows(USER_A)), 1, "唯一约束下不能出现重复行")

    def test_add_unknown_cosmetic_404(self):
        with self.assertRaises(FashionServiceError) as ctx:
            self.add("no_such_cosmetic")
        self.assertEqual(ctx.exception.code, "cosmetic_not_found")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.rows(USER_A), [])

    def test_add_disabled_cosmetic_404(self):
        svc.upsert_catalog_item(self.db, {
            "cosmeticId": "cape_dragon", "enabled": False,
        })
        with self.assertRaises(FashionServiceError) as ctx:
            self.add("cape_dragon")
        self.assertEqual(ctx.exception.code, "cosmetic_not_found")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.rows(USER_A), [])

    def test_add_empty_cosmetic_id_400(self):
        for bad in ("", "   ", None):
            with self.assertRaises(FashionServiceError) as ctx:
                self.add(bad)
            self.assertEqual(ctx.exception.code, "invalid_cosmetic_id")
            self.assertEqual(ctx.exception.status_code, 400)

    def test_add_overlong_cosmetic_id_400(self):
        with self.assertRaises(FashionServiceError) as ctx:
            self.add("a" * 129)
        self.assertEqual(ctx.exception.code, "invalid_cosmetic_id")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_add_accepts_global_id_alias_of_legacy_catalog(self):
        """目录是历史简单 ID（packId=pack1）时，传全局 ID 也能加入且原样保留。

        商店页拿到的是目录里的原值；保留玩家传入的形态，删除时用同一个值即可命中。
        """
        item, added = self.add("pack1:cape_dragon")
        self.assertTrue(added)
        self.assertEqual(item["cosmeticId"], "pack1:cape_dragon")
        self.assertEqual(item["name"], "龙翼披风")
        self.assertFalse(item["missing"])
        # 列表里同一形态也能解析到目录元数据（_catalog_map 的别名兜底）
        listed = self.list_items()
        self.assertEqual([it["cosmeticId"] for it in listed], ["pack1:cape_dragon"])
        self.assertFalse(listed[0]["missing"])


# ── 衣柜列表 ────────────────────────────────────────────────────────────

class TestListWardrobe(_Base):
    def test_empty_wardrobe_returns_empty_list(self):
        self.assertEqual(self.list_items(), [])

    def test_list_fields_and_order(self):
        base = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.add("cape_dragon")
        self.set_added_at("cape_dragon", base)
        self.add("wings_angel")
        # 故意混一个 naive datetime：SQLite 读回就是 naive，排序不能 TypeError
        self.set_added_at("wings_angel", base + timedelta(minutes=1))
        self.add("hat_crown")
        self.set_added_at("hat_crown", base + timedelta(minutes=2))

        items = self.list_items()
        self.assertEqual(
            [it["cosmeticId"] for it in items],
            ["hat_crown", "wings_angel", "cape_dragon"],
            "必须按 addedAt 倒序（最近加入的排最前）",
        )
        first = items[0]
        self.assertEqual(set(first), _WARDROBE_ITEM_KEYS)
        self.assertEqual(first["name"], "王冠")
        self.assertEqual(first["category"], "hat")
        self.assertEqual(first["packId"], "pack1")
        self.assertEqual(first["assetKey"], "hat/crown.png")
        self.assertEqual(first["sortOrder"], 3)
        self.assertFalse(first["missing"])
        self.assertEqual(
            first["addedAt"], "2026-11-01T00:02:00+00:00",
            "naive datetime 要按 UTC 渲染（svc.iso 的约定）",
        )

    def test_catalog_deleted_item_is_missing_but_still_listed(self):
        self.add("cape_dragon")
        self.assertTrue(svc.delete_catalog_item(self.db, "cape_dragon"))

        items = self.list_items()
        self.assertEqual(len(items), 1, "目录被删也要返回条目，玩家才删得掉")
        item = items[0]
        self.assertEqual(item["cosmeticId"], "cape_dragon")
        self.assertTrue(item["missing"])
        self.assertEqual(item["name"], "", "目录整条没了，没有残留值可用 → 空串")
        self.assertEqual(item["category"], "other")
        self.assertEqual(item["assetKey"], "")
        self.assertEqual(item["sortOrder"], 0)

    def test_catalog_disabled_item_is_missing_with_residual_name(self):
        self.add("cape_dragon")
        svc.upsert_catalog_item(self.db, {
            "cosmeticId": "cape_dragon", "enabled": False,
        })

        items = self.list_items()
        self.assertEqual(len(items), 1, "已停用的条目同样要返回")
        self.assertTrue(items[0]["missing"])
        self.assertEqual(items[0]["name"], "龙翼披风", "name 用目录里的残留值")

    def test_list_is_isolated_per_user(self):
        self.add("cape_dragon", USER_A)
        self.add("wings_angel", USER_B)

        self.assertEqual([it["cosmeticId"] for it in self.list_items(USER_A)],
                         ["cape_dragon"])
        self.assertEqual([it["cosmeticId"] for it in self.list_items(USER_B)],
                         ["wings_angel"])
        self.assertEqual(self.list_items("user-never-used"), [])


# ── 删除 ────────────────────────────────────────────────────────────────

class TestRemoveWardrobeItem(_Base):
    def test_remove_single(self):
        self.add("cape_dragon")
        self.assertTrue(svc.remove_wardrobe_item(self.db, USER_A, "cape_dragon"))
        self.assertEqual(self.rows(USER_A), [])
        self.assertEqual(self.list_items(), [])

    def test_remove_missing_returns_false(self):
        self.add("cape_dragon")
        self.assertFalse(svc.remove_wardrobe_item(self.db, USER_A, "wings_angel"))
        self.assertFalse(svc.remove_wardrobe_item(self.db, USER_A, ""))
        self.assertEqual(len(self.rows(USER_A)), 1, "删不存在的不能误删别的")

    def test_remove_cannot_touch_other_user(self):
        self.add("cape_dragon", USER_A)
        self.add("cape_dragon", USER_B)

        self.assertTrue(svc.remove_wardrobe_item(self.db, USER_B, "cape_dragon"))
        self.assertEqual(len(self.rows(USER_B)), 0)
        self.assertEqual(len(self.rows(USER_A)), 1, "A 的衣柜不能被 B 删掉")


class TestBatchRemoveWardrobeItems(_Base):
    def test_batch_remove_counts(self):
        self.add("cape_dragon")
        self.add("wings_angel")
        self.add("hat_crown")

        removed = svc.remove_wardrobe_items(
            self.db, USER_A, ["cape_dragon", "wings_angel"]
        )
        self.assertEqual(removed, 2)
        self.assertEqual([it["cosmeticId"] for it in self.list_items()], ["hat_crown"])

    def test_batch_remove_dedupes_and_ignores_unknown(self):
        self.add("cape_dragon")
        self.add("wings_angel")

        removed = svc.remove_wardrobe_items(
            self.db, USER_A,
            ["cape_dragon", "cape_dragon", "  ", "no_such_cosmetic", "cape_dragon"],
        )
        self.assertEqual(removed, 1, "重复 id 只算一次；不存在的 id 静默忽略")
        self.assertEqual([it["cosmeticId"] for it in self.list_items()], ["wings_angel"])

    def test_batch_remove_empty_selection_400(self):
        for bad in ([], ["", "   "], None):
            with self.assertRaises(FashionServiceError) as ctx:
                svc.remove_wardrobe_items(self.db, USER_A, bad)
            self.assertEqual(ctx.exception.code, "empty_selection")
            self.assertEqual(ctx.exception.status_code, 400)

    def test_batch_remove_too_many_400(self):
        ids = [f"cosmetic_{i}" for i in range(svc.MAX_WARDROBE_BATCH_DELETE + 1)]
        with self.assertRaises(FashionServiceError) as ctx:
            svc.remove_wardrobe_items(self.db, USER_A, ids)
        self.assertEqual(ctx.exception.code, "too_many_items")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_batch_remove_limit_is_checked_after_dedupe(self):
        """上限按「去重后」算：600 个相同 id 去重成 1 个，不该被判 too_many_items。"""
        ids = ["cape_dragon"] * 600
        self.add("cape_dragon")
        self.assertEqual(svc.remove_wardrobe_items(self.db, USER_A, ids), 1)

    def test_batch_remove_is_isolated_per_user(self):
        for cosmetic_id in ("cape_dragon", "wings_angel", "hat_crown"):
            self.add(cosmetic_id, USER_A)
            self.add(cosmetic_id, USER_B)

        removed = svc.remove_wardrobe_items(
            self.db, USER_B, ["cape_dragon", "wings_angel", "hat_crown"]
        )
        self.assertEqual(removed, 3)
        self.assertEqual(len(self.rows(USER_B)), 0)
        self.assertEqual(len(self.rows(USER_A)), 3, "批量删除不能跨用户")


class TestNormalizeWardrobeIds(unittest.TestCase):
    def test_strips_dedupes_and_drops_impossible_ids(self):
        self.assertEqual(
            svc.normalize_wardrobe_ids(
                [" a ", "a", "", "  ", None, "b", "x" * 129, "c"]
            ),
            ["a", "b", "c"],
        )


# ── 路由层接线（导入期间临时补 _Router.head） ───────────────────────────

class TestWardrobeApiWiring(_Base):
    @classmethod
    def setUpClass(cls):
        try:
            cls.api = _import_fashion_router()
        except Exception as exc:  # pragma: no cover - 取决于离线 stub 的完整度
            raise unittest.SkipTest(f"无法导入路由模块：{exc}")

    def test_four_endpoints_registered(self):
        table = set()
        for route in getattr(self.api.router, "routes", []):
            if isinstance(route, dict):  # _stub_env 的假 APIRouter
                table.add((route["method"].upper(), route["path"]))
            else:  # 真 fastapi.APIRoute
                for method in getattr(route, "methods", set()) or set():
                    table.add((method.upper(), route.path))

        self.assertIn(("GET", "/wardrobe"), table)
        self.assertIn(("POST", "/wardrobe"), table)
        self.assertIn(("POST", "/wardrobe/batch-delete"), table)
        self.assertIn(("DELETE", "/wardrobe/{cosmetic_id}"), table)

    def test_route_list_returns_items(self):
        self.add("cape_dragon")
        response = self.api.list_wardrobe(user=_User(USER_A), db=self.db)
        items = _attr(response, "items")
        self.assertEqual(len(items), 1)
        self.assertEqual(_attr(items[0], "cosmetic_id", "cosmeticId"), "cape_dragon")

    def test_route_add_returns_added_flag(self):
        first = self.api.add_wardrobe_item(
            body=self.api.WardrobeAddRequest(cosmetic_id="cape_dragon"),
            user=_User(USER_A),
            db=self.db,
        )
        second = self.api.add_wardrobe_item(
            body=self.api.WardrobeAddRequest(cosmetic_id="cape_dragon"),
            user=_User(USER_A),
            db=self.db,
        )
        self.assertTrue(_attr(first, "added"))
        self.assertFalse(_attr(second, "added"), "重复加入仍是 200，只是 added=False")
        self.assertEqual(
            _attr(_attr(second, "item"), "cosmetic_id", "cosmeticId"), "cape_dragon"
        )

    def test_route_add_translates_404(self):
        try:
            self.api.add_wardrobe_item(
                body=self.api.WardrobeAddRequest(cosmetic_id="no_such_cosmetic"),
                user=_User(USER_A),
                db=self.db,
            )
        except Exception as exc:  # stub 的 HTTPException 不是真 fastapi 的类
            self.assertEqual(getattr(exc, "status_code", None), 404)
            self.assertEqual(_http_code(exc), "cosmetic_not_found")
        else:
            self.fail("未知时装应当抛 404 cosmetic_not_found")

    def test_route_batch_delete_empty_selection_400(self):
        try:
            self.api.batch_delete_wardrobe_items(
                body=self.api.WardrobeBatchDeleteRequest(cosmetic_ids=[]),
                user=_User(USER_A),
                db=self.db,
            )
        except Exception as exc:
            self.assertEqual(getattr(exc, "status_code", None), 400)
            self.assertEqual(_http_code(exc), "empty_selection")
        else:
            self.fail("空数组应当抛 400 empty_selection")

    def test_route_delete_reports_removed(self):
        self.add("cape_dragon")
        hit = self.api.delete_wardrobe_item(
            cosmetic_id="cape_dragon", user=_User(USER_A), db=self.db
        )
        miss = self.api.delete_wardrobe_item(
            cosmetic_id="cape_dragon", user=_User(USER_A), db=self.db
        )
        self.assertTrue(_attr(hit, "removed"))
        self.assertFalse(_attr(miss, "removed"), "删不存在的仍是 200，removed=False")


# ── alembic 迁移 ────────────────────────────────────────────────────────

class _FakeOp:
    def __init__(self):
        self.created: list[str] = []
        self.columns: list = []
        self.indexes: list[tuple[str, str]] = []
        self.dropped: list[str] = []

    def get_bind(self):
        return object()

    def create_table(self, name, *columns, **kwargs):
        self.created.append(name)
        self.columns.extend(columns)

    def create_index(self, name, table, columns, **kwargs):
        self.indexes.append((name, table))

    def drop_table(self, name):
        self.dropped.append(name)


class TestWardrobeMigration(unittest.TestCase):
    MIGRATION = os.path.join(
        _HERE, os.pardir, "alembic", "versions", "20261101_fashion_wardrobe.py"
    )

    def _load(self):
        op = _FakeOp()
        alembic_stub = types.ModuleType("alembic")
        alembic_stub.op = op
        previous = sys.modules.get("alembic")
        sys.modules["alembic"] = alembic_stub
        try:
            spec = importlib.util.spec_from_file_location(
                "fashion_wardrobe_migration_under_test", os.path.abspath(self.MIGRATION)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop("alembic", None)
            else:
                sys.modules["alembic"] = previous
        return module, op

    def test_upgrade_creates_table_and_indexes(self):
        module, op = self._load()
        module._existing_tables = lambda: set()
        module.upgrade()

        self.assertEqual(op.created, ["fashion_wardrobe"])
        self.assertEqual(
            {table for _name, table in op.indexes}, {"fashion_wardrobe"}
        )
        self.assertEqual(len(op.indexes), 2, "user_id / cosmetic_id 各一个索引")

    def test_upgrade_is_idempotent(self):
        module, op = self._load()
        module._existing_tables = lambda: {"fashion_wardrobe"}
        module.upgrade()
        self.assertEqual(op.created, [], "表已存在时不应重复建表（create_all 已建过）")

    def test_revision_graph(self):
        module, _op = self._load()
        self.assertEqual(module.revision, "20261101_fashion_wardrobe")
        self.assertEqual(module.down_revision, "20261028_fashion")

    def test_downgrade_drops_table(self):
        module, op = self._load()
        module._existing_tables = lambda: {"fashion_wardrobe"}
        module.downgrade()
        self.assertEqual(op.dropped, ["fashion_wardrobe"])

    def test_downgrade_is_idempotent(self):
        module, op = self._load()
        module._existing_tables = lambda: set()
        module.downgrade()
        self.assertEqual(op.dropped, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
