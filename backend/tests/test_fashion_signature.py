"""时装包 Ed25519 签名链路（审计 D1 / E2，P0）—— **真实签/验**，不 mock 算法。

为什么单开一个文件
------------------
旧测试只覆盖了「规范化字节串」和「monkeypatch 掉 signer 之后的输出」
（``test_fashion_loadout.py::TestPackSignature``），``_ed25519_signer`` 的真实
签/验、``cryptography`` 缺失时的降级、``signingKeyId`` 为空串的路径**从未被证明
能跑通**。叠加「部署脚本不装 ``cryptography``」（D1）就等于：签名链路在生产是死的，
客户端严格模式（``requireSignature=true``）永远开不了。

客户端口径（逐字节，不能改）
----------------------------
``MOD/src/client/java/com/venus/vmfashion/net/PackSignature.java`` 的
``canonicalString``（v1.0.1，:118-132）::

    UTF-8( packId.trim() + "\\n" + version.trim() + "\\n" + sha256.trim().toLowerCase() )

三段之间**单个** ``\\n``，结尾**没有**换行；sha256 必须是 64 位 hex（客户端会先校验）。
后端 :func:`vmtools_next.core.fashion_service.pack_canonical_string` 必须完全一致，
否则客户端会把所有服务端包判成 ``BAD_SIGNATURE``（宽松模式也拒绝安装）。
"""
from __future__ import annotations

import base64
import contextlib
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _stub_env import install, quiet_stub_noise  # noqa: E402

install()
quiet_stub_noise()

from vmtools_next.core import fashion_service as svc  # noqa: E402

try:  # cryptography 是可选 extra：没装时只跑「降级」分支，真实签/验用例 skip
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - 取决于环境
    HAVE_CRYPTOGRAPHY = False

# 固定种子：Ed25519 是确定性签名，同种子 + 同消息必然得到同一签名，
# 所以这里可以断言具体字节（跨机器/跨次运行稳定）。
FIXED_SEED = bytes(range(32))
KEY_ID = "vmtools-test-key"

PACK_ID = "example"
VERSION = "1.0.0"
SHA256 = "0123456789abcdef" * 4  # 64 位 hex


def make_signing_settings(
    *,
    key_b64: str = "",
    key_id: str = KEY_ID,
    **overrides,
) -> types.SimpleNamespace:
    """只带签名字段的 FashionSettings 替身（``pack_signature`` 只读这两个键）。"""
    base = dict(pack_signing_key_b64=key_b64, pack_signing_key_id=key_id)
    base.update(overrides)
    return types.SimpleNamespace(**base)


def seed_b64(seed: bytes = FIXED_SEED) -> str:
    return base64.b64encode(seed).decode("ascii")


@contextlib.contextmanager
def cryptography_missing():
    """模拟「生产环境没装 cryptography」：让 ``import cryptography`` 抛 ImportError。

    必须把**所有** ``cryptography.*`` 子模块从 ``sys.modules`` 里摘掉：``from
    cryptography.hazmat.primitives import serialization`` 只要子模块还在缓存里就会
    直接命中、绕过父模块。退出时完整还原（``cryptography`` 条目设为 None 触发
    ``ImportError: import of cryptography halted; None in sys.modules``）。
    """
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "cryptography" or name.startswith("cryptography.")
    }
    for name in saved:
        sys.modules.pop(name, None)
    sys.modules["cryptography"] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.modules.pop("cryptography", None)
        sys.modules.update(saved)


class _AssetRowsDB:
    """``_pack_snapshot`` 只需要 ``db.query(Model).all()``。"""

    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, _model):
        return self

    def all(self):
        return list(self.rows)


def make_asset_row(
    *,
    pack_id: str = PACK_ID,
    version: str = VERSION,
    sha256: str = SHA256,
    size: int = 1234,
    filename: str = "example.zip",
):
    return types.SimpleNamespace(
        pack_id=pack_id,
        version=version,
        sha256=sha256,
        bytes=size,
        filename=filename,
        storage_path=f"{pack_id}/{version}/x-{filename}",
        created_at=datetime(2026, 10, 30, 5, 0, tzinfo=timezone.utc),
    )


# ── 规范化字节串（与客户端逐字节一致） ──────────────────────────────────

class TestCanonicalString(unittest.TestCase):
    def test_matches_client_rule_byte_for_byte(self):
        """等价于 Java：trim + 小写 + 单个 \\n 连接 + 无结尾换行。"""
        canonical = svc.pack_canonical_string(
            "  example  ", "  1.0.0 ", SHA256.upper()
        )
        self.assertEqual(
            canonical,
            f"{PACK_ID}\n{VERSION}\n{SHA256}".encode("utf-8"),
        )
        self.assertEqual(canonical.count(b"\n"), 2)
        self.assertFalse(canonical.endswith(b"\n"))

    def test_matches_mod_java_reference_implementation(self):
        """把 PackSignature.canonicalString 用 Python 抄一遍，逐字节比对。"""

        def java_reference(pack_id: str, version: str, sha256_hex: str) -> bytes:
            pid = (pack_id or "").strip()
            ver = (version or "").strip()
            sha = (sha256_hex or "").strip().lower()
            return (pid + "\n" + ver + "\n" + sha).encode("utf-8")

        for args in (
            (PACK_ID, VERSION, SHA256),
            (" wings ", " 1.2.0 ", "ABCDEF" * 10 + "ABCD"),
            ("a", "1", "f" * 64),
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    svc.pack_canonical_string(*args), java_reference(*args)
                )

    def test_utf8_encoding(self):
        canonical = svc.pack_canonical_string("pack1", "1.0.0", SHA256)
        self.assertEqual(canonical.decode("utf-8").split("\n")[0], "pack1")


# ── 真实 Ed25519 签 / 验 ────────────────────────────────────────────────

@unittest.skipUnless(HAVE_CRYPTOGRAPHY, "需要 cryptography（pip install '.[signing]'）")
class TestRealEd25519Signature(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.from_private_bytes(FIXED_SEED)
        self.public_key = self.private_key.public_key()

    def _verify(self, signature_b64: str, pack_id=PACK_ID, version=VERSION, sha256=SHA256):
        signature = base64.b64decode(signature_b64)
        self.assertEqual(len(signature), 64, "Ed25519 签名必须是 64 字节")
        self.public_key.verify(
            signature, svc.pack_canonical_string(pack_id, version, sha256)
        )

    def test_signature_verifies_over_canonical_bytes(self):
        signature, key_id = svc.pack_signature(
            PACK_ID,
            VERSION,
            SHA256,
            settings=make_signing_settings(key_b64=seed_b64()),
        )
        self.assertEqual(key_id, KEY_ID)
        self._verify(signature)

    def test_signature_is_deterministic_and_matches_manual_sign(self):
        settings = make_signing_settings(key_b64=seed_b64())
        first, _ = svc.pack_signature(PACK_ID, VERSION, SHA256, settings=settings)
        second, _ = svc.pack_signature(PACK_ID, VERSION, SHA256, settings=settings)
        self.assertEqual(first, second)
        expected = self.private_key.sign(
            svc.pack_canonical_string(PACK_ID, VERSION, SHA256)
        )
        self.assertEqual(base64.b64decode(first), expected)

    def test_signature_covers_sha_version_and_id(self):
        settings = make_signing_settings(key_b64=seed_b64())
        base, _ = svc.pack_signature(PACK_ID, VERSION, SHA256, settings=settings)
        other_sha, _ = svc.pack_signature(PACK_ID, VERSION, "f" * 64, settings=settings)
        other_ver, _ = svc.pack_signature(PACK_ID, "2.0.0", SHA256, settings=settings)
        other_id, _ = svc.pack_signature("other", VERSION, SHA256, settings=settings)
        self.assertEqual(len({base, other_sha, other_ver, other_id}), 4)
        # 换了内容但用旧签名 → 必须验签失败
        with self.assertRaises(Exception):
            self._verify(base, sha256="f" * 64)

    def test_pkcs8_der_private_key_supported(self):
        """运维也可能贴 PKCS#8 DER（base64），不能只支持裸 32 字节种子。"""
        der = self.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        signature, key_id = svc.pack_signature(
            PACK_ID,
            VERSION,
            SHA256,
            settings=make_signing_settings(key_b64=base64.b64encode(der).decode()),
        )
        self.assertEqual(key_id, KEY_ID)
        self._verify(signature)

    def test_signing_key_id_can_be_empty(self):
        """配了私钥但没配 keyId：仍然签名，``signingKeyId`` 是空串（不是缺字段）。"""
        signature, key_id = svc.pack_signature(
            PACK_ID,
            VERSION,
            SHA256,
            settings=make_signing_settings(key_b64=seed_b64(), key_id=""),
        )
        self.assertTrue(signature)
        self.assertEqual(key_id, "")
        self._verify(signature)


# ── 未配置 / 降级路径（任何环境都能跑） ────────────────────────────────

class TestSignatureDegrade(unittest.TestCase):
    def test_no_key_configured_returns_empty(self):
        for settings in (None, make_signing_settings(key_b64="")):
            with self.subTest(settings=settings):
                self.assertEqual(
                    svc.pack_signature(PACK_ID, VERSION, SHA256, settings=settings),
                    ("", ""),
                )

    def test_broken_key_degrades_with_warning(self):
        """私钥写错（不是 base64 / 长度不对）→ 记 warn、返回空签名，绝不抛。"""
        with mock.patch.object(svc.logger, "warning") as warn:
            result = svc.pack_signature(
                PACK_ID,
                VERSION,
                SHA256,
                settings=make_signing_settings(key_b64="not-base64!!"),
            )
        self.assertEqual(result, ("", ""))
        self.assertTrue(warn.called)

    def test_missing_cryptography_degrades_with_warning(self):
        """生产没装 cryptography（D1 的现场）→ warn + 不签名，**不能 500**。"""
        with cryptography_missing():
            with mock.patch.object(svc.logger, "warning") as warn:
                result = svc.pack_signature(
                    PACK_ID,
                    VERSION,
                    SHA256,
                    settings=make_signing_settings(key_b64=seed_b64()),
                )
        self.assertEqual(result, ("", ""))
        self.assertTrue(warn.called)

    def test_signer_override_still_supported(self):
        """路由/测试可以注入 signer（旧测试依赖这个入口，别删）。"""
        seen = []

        def fake_signer(payload: bytes) -> bytes:
            seen.append(payload)
            return b"\x01" * 64

        signature, key_id = svc.pack_signature(
            PACK_ID,
            VERSION,
            SHA256,
            settings=make_signing_settings(key_b64=seed_b64()),
            signer=fake_signer,
        )
        self.assertEqual(len(base64.b64decode(signature)), 64)
        self.assertEqual(key_id, KEY_ID)
        self.assertEqual(seen, [svc.pack_canonical_string(PACK_ID, VERSION, SHA256)])


# ── 清单（/packs 的数据源）里的签名字段 ────────────────────────────────

class TestPackManifestSignature(unittest.TestCase):
    def setUp(self):
        svc.invalidate_caches()
        self.addCleanup(svc.invalidate_caches)

    def test_manifest_has_no_signature_without_key(self):
        db = _AssetRowsDB([make_asset_row()])
        packs = svc.list_packs(
            db, settings=make_signing_settings(key_b64="", catalog_cache_ttl_seconds=0)
        )
        self.assertEqual(len(packs), 1)
        self.assertNotIn("signature", packs[0])
        self.assertNotIn("signingKeyId", packs[0])

    @unittest.skipUnless(HAVE_CRYPTOGRAPHY, "需要 cryptography")
    def test_manifest_emits_signature_and_key_id(self):
        db = _AssetRowsDB([make_asset_row()])
        packs = svc.list_packs(
            db,
            settings=make_signing_settings(
                key_b64=seed_b64(), catalog_cache_ttl_seconds=0
            ),
        )
        pack = packs[0]
        self.assertIn("signature", pack)
        self.assertEqual(pack["signingKeyId"], KEY_ID)
        public_key = Ed25519PrivateKey.from_private_bytes(FIXED_SEED).public_key()
        public_key.verify(
            base64.b64decode(pack["signature"]),
            svc.pack_canonical_string(pack["id"], pack["version"], pack["sha256"]),
        )

    def test_manifest_without_cryptography_still_200(self):
        """cryptography 缺失时清单照常生成（只是不带签名），不能整条挂掉。"""
        db = _AssetRowsDB([make_asset_row()])
        with cryptography_missing():
            packs = svc.list_packs(
                db,
                settings=make_signing_settings(
                    key_b64=seed_b64(), catalog_cache_ttl_seconds=0
                ),
            )
        self.assertEqual(len(packs), 1)
        self.assertNotIn("signature", packs[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
