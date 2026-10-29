"""离线 stub 依赖环境 —— 让 ``vmtools_next.core.map_art`` 在无依赖机器上可 import / 可单测。

背景：本机后端依赖（fastapi / sqlalchemy / pydantic / socketio / loguru / nbtlib /
pydantic_settings / yaml）**未安装**，且 python3 无 pip。验证手段只能靠
``sys.modules`` 注入最小 stub（设计契约见 ``docs/dev/map-art-重构方案-2026-10-28.md`` §六）。

用法::

    from _stub_env import install
    install()                      # 幂等：多次调用只装一次
    import vmtools_next.core.map_art  # noqa: E402  —— 必须在 install() 之后

设计要点：
  - ``install()`` 幂等，重复调用无副作用（每个测试模块都会调一次）。
  - 只补**缺失**的模块/属性：真依赖装了的机器上不会被 stub 覆盖。
  - 同时把 ``backend/src`` 塞进 ``sys.path``，这样 ``vmtools_next`` 可被 import。
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
# backend/tests/_stub_env.py → backend/src
SRC = os.path.normpath(os.path.join(_HERE, os.pardir, "src"))

_INSTALLED = False


# ──────────────────────────────────────────────────────────
# 注入原语
# ──────────────────────────────────────────────────────────

_STUB_TOP_LEVEL = (
    "cachetools",
    "fastapi",
    "loguru",
    "nbtlib",
    "socketio",
    "sqlalchemy",
    "yaml",
    "pydantic",
    "pydantic_settings",
    "websockets",
    "psutil",
    "watchdog",
    "bcrypt",
)

_PREFLIGHT: dict[str, bool] = {}


def _preflight() -> None:
    """在**任何 stub 注入之前**探测每个顶层包能否真的 import。

    必须提前批量探测：一旦先 stub 了某个包，再 import 依赖它的真包就会失败，
    于是真包也会被误判成"缺失"而 stub 掉（``pydantic_settings`` 就踩过这个坑）。
    """
    if _PREFLIGHT:
        return
    for name in _STUB_TOP_LEVEL:
        try:
            importlib.import_module(name)
            _PREFLIGHT[name] = True
        except Exception:
            _PREFLIGHT[name] = False


def _is_real(name: str) -> bool:
    return _PREFLIGHT.get(name.split(".")[0], False)


def _mod(name: str, **attrs):
    """注册一个 stub 模块；已存在则复用（真依赖优先），只补缺失属性。

    **真依赖已安装时绝不创建 stub**：先用 ``_preflight()`` 探测，能 import 就用真模块。
    否则在装了依赖的机器上（CI / 开发机）stub 会遮蔽真包，出现
    ``cannot import name 'X' from 'pkg' (unknown location)`` 这种假故障。
    """
    _preflight()
    existing = sys.modules.get(name)
    if existing is not None:
        # 已经是真模块就原样返回：往真 pydantic 里塞 BaseSettings 之类的假符号会毁掉它
        if getattr(existing, "__file__", None):
            return existing
        for key, val in attrs.items():
            try:
                if not hasattr(existing, key):
                    setattr(existing, key, val)
            except Exception:
                pass
        return existing

    if _is_real(name):
        # 真依赖：直接返回，不注入任何假符号
        return importlib.import_module(name)

    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod
    return mod


# ── pydantic ──────────────────────────────────────────────

class _BaseModel:
    """够用就好的 BaseModel：关键字初始化 + model_dump/dict。"""

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)

    def model_dump(self, *args, **kwargs):
        return dict(self.__dict__)

    def dict(self, *args, **kwargs):
        return dict(self.__dict__)

    def model_copy(self, *args, **kwargs):
        return type(self)(**self.__dict__)


def _Field(default=None, **kwargs):
    return default


def _passthrough_decorator(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


# ── sqlalchemy ────────────────────────────────────────────

class _Col:
    """假 Column 描述符：支持 ``__set_name__`` 与常见比较/运算（供 ORM 模型 import）。"""

    def __init__(self, *args, **kwargs):
        self.default = kwargs.get("default")
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return obj.__dict__.get(
            self.name, self.default() if callable(self.default) else self.default)

    def __set__(self, obj, val):
        obj.__dict__[self.name] = val

    def is_(self, other):
        return self

    def isnot(self, other):
        return self

    def desc(self):
        return self

    def __eq__(self, other):
        return self

    def __ne__(self, other):
        return self

    def __lt__(self, other):
        return self

    def __le__(self, other):
        return self

    def __gt__(self, other):
        return self

    def __ge__(self, other):
        return self

    def in_(self, other):
        return self

    def __hash__(self):
        return id(self)

    def __add__(self, other):
        return self

    def __radd__(self, other):
        return self


def _column_factory(*args, **kwargs):
    return _Col(*args, **kwargs)


def _declarative_base():
    class Base:
        metadata = types.SimpleNamespace(
            create_all=lambda *a, **k: None, tables={})

        def __init__(self, **kwargs):
            for key, val in kwargs.items():
                setattr(self, key, val)

    return Base


class _Query:
    def filter(self, *a, **k):
        return self

    def filter_by(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def group_by(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def offset(self, *a):
        return self

    def first(self):
        return None

    def one_or_none(self):
        return None

    def all(self):
        return []

    def scalar(self):
        return 0

    def count(self):
        return 0

    def delete(self, *a, **k):
        return 0


class _Session:
    def query(self, *a, **k):
        return _Query()

    def execute(self, *a, **k):
        return None

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def add(self, obj):
        pass

    def add_all(self, objs):
        pass

    def flush(self):
        pass

    def get(self, *a, **k):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _noop(*args, **kwargs):
    return None


# ── socketio ──────────────────────────────────────────────

class _AsyncServer:
    def __init__(self, *args, **kwargs):
        pass

    async def emit(self, *args, **kwargs):
        return None

    def on(self, *args, **kwargs):
        return _passthrough_decorator()

    def event(self, *args, **kwargs):
        return _passthrough_decorator()

    async def enter_room(self, *args, **kwargs):
        pass

    async def leave_room(self, *args, **kwargs):
        pass

    async def save_session(self, *a, **k):
        pass


# ── loguru ────────────────────────────────────────────────

class _Logger:
    """所有方法调用都是 no-op，返回 None。"""

    def __getattr__(self, item):
        def _f(*args, **kwargs):
            return None
        return _f


# ── fastapi ───────────────────────────────────────────────

class _Router:
    """假 APIRouter：记录 prefix/tags/路由，供 import 冒烟断言「路由真的注册了」。"""

    def __init__(self, *args, **kwargs):
        self.prefix = kwargs.get("prefix", "")
        self.tags = list(kwargs.get("tags") or [])
        self.routes: list[dict] = []

    def _register(self, method: str, path: str = ""):
        def deco(fn):
            self.routes.append({"method": method, "path": path, "endpoint": fn})
            return fn
        return deco

    def get(self, path: str = "", *a, **k):
        return self._register("GET", path)

    def post(self, path: str = "", *a, **k):
        return self._register("POST", path)

    def put(self, path: str = "", *a, **k):
        return self._register("PUT", path)

    def delete(self, path: str = "", *a, **k):
        return self._register("DELETE", path)

    def patch(self, path: str = "", *a, **k):
        return self._register("PATCH", path)

    def include_router(self, *a, **k):
        return None


class _HTTPException(Exception):
    def __init__(self, status_code: int = 400, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _HTTPBearer:
    def __init__(self, *args, **kwargs):
        pass

    async def __call__(self, *args, **kwargs):
        return None


class _TTLCache(dict):
    """假 TTLCache：dict 语义 + maxsize/ttl 属性（测试里不会真的过期）。"""

    def __init__(self, maxsize: int = 128, ttl: int = 60, *args, **kwargs):
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl


class _ConnectionClosed(Exception):
    pass


class _FakeAsyncClient:
    """假 ``httpx.AsyncClient``：``async with`` 可用，请求一律返回空 dict（测试不联网）。"""

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")
        self.headers = kwargs.get("headers") or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return {}

    async def post(self, *args, **kwargs):
        return {}

    async def request(self, *args, **kwargs):
        return {}

    async def aclose(self):
        pass

    async def close(self):
        pass


def _install_stubs() -> None:
    # ── pydantic / pydantic_settings ──
    _mod(
        "pydantic",
        BaseModel=_BaseModel,
        Field=_Field,
        BaseSettings=_BaseModel,
        field_validator=_passthrough_decorator,
        model_validator=_passthrough_decorator,
        validator=_passthrough_decorator,
        root_validator=_passthrough_decorator,
        ConfigDict=lambda **k: dict(k),
        ValidationError=Exception,
        HttpUrl=str,
        AnyUrl=str,
    )
    _mod(
        "pydantic_settings",
        BaseSettings=_BaseModel,
        SettingsConfigDict=lambda **k: dict(k),
        # config.py 用 ``Annotated[list[str], NoDecode]`` 让 pydantic-settings
        # 不要按 JSON 解析逗号分隔的环境变量；离线 stub 里给个哨兵即可。
        NoDecode=object,
    )

    # ── sqlalchemy ──
    sa = _mod(
        "sqlalchemy",
        Column=_column_factory,
        String=_column_factory,
        Integer=_column_factory,
        Float=_column_factory,
        Boolean=_column_factory,
        DateTime=_column_factory,
        Text=_column_factory,
        ForeignKey=_column_factory,
        Index=_column_factory,
        BigInteger=_column_factory,
        JSON=_column_factory,
        Numeric=_column_factory,
        UniqueConstraint=_column_factory,
        create_engine=lambda *a, **k: types.SimpleNamespace(
            connect=lambda: None, dispose=lambda: None),
        text=lambda *a, **k: None,
        func=types.SimpleNamespace(
            count=lambda *a, **k: 0, max=lambda *a, **k: 0,
            min=lambda *a, **k: 0, sum=lambda *a, **k: 0,
            now=lambda *a, **k: None),
        update=lambda *a, **k: _noop(),
        bindparam=lambda *a, **k: _noop(),
        select=lambda *a, **k: _noop(),
        and_=lambda *a, **k: None,
        or_=lambda *a, **k: None,
        desc=lambda *a, **k: None,
        asc=lambda *a, **k: None,
        event=lambda *a, **k: None,
        inspect=lambda *a, **k: None,
        Table=lambda *a, **k: None,
        MetaData=lambda *a, **k: None,
        delete=lambda *a, **k: _noop(),
        insert=lambda *a, **k: _noop(),
    )
    orm = _mod(
        "sqlalchemy.orm",
        declarative_base=_declarative_base,
        sessionmaker=lambda *a, **k: (lambda *x, **y: _Session()),
        relationship=lambda *a, **k: None,
        Session=_Session,
        selectinload=lambda *a, **k: None,
        joinedload=lambda *a, **k: None,
        Mapped=object,
        mapped_column=_column_factory,
    )
    sa.orm = orm
    sa.Session = _Session
    sa.engine = types.SimpleNamespace(Engine=object)
    _mod("sqlalchemy.exc", SQLAlchemyError=Exception,
         IntegrityError=Exception, OperationalError=Exception)
    _mod("sqlalchemy.dialects", __path__=[])
    _mod("sqlalchemy.dialects.sqlite", insert=lambda *a, **k: _noop())
    _mod("sqlalchemy.pool", StaticPool=object)
    sa.types = _mod("sqlalchemy.types", TypeDecorator=object, JSON=object)
    _mod("sqlalchemy.sql", expression=types.SimpleNamespace(ColumnElement=object),
         select=_noop)

    # ── socketio ──
    _mod("socketio", AsyncServer=_AsyncServer, ASGIApp=object, Client=object)
    _mod("socketio.exceptions", ConnectionRefusedError=Exception)

    # ── loguru ──
    _mod("loguru", logger=_Logger())

    # ── yaml ──
    _mod("yaml", safe_load=lambda *a, **k: {}, safe_dump=lambda *a, **k: "",
         dump=lambda *a, **k: "", load=lambda *a, **k: {})

    # ── nbtlib ──
    _mod("nbtlib", File=object, Compound=dict, Int=object, Long=object,
         String=object, List=object, Byte=object, Short=object, Float=object,
         Double=object, Array=object, ByteArray=object, IntArray=object)

    # ── fastapi ──
    fastapi_mod = _mod(
        "fastapi",
        APIRouter=_Router,
        Depends=lambda x: x,
        HTTPException=_HTTPException,
        UploadFile=object,
        File=lambda *a, **k: None,
        Form=lambda *a, **k: None,
        FastAPI=object,
        Request=object,
        Response=object,
        Query=lambda *a, **k: None,
        Body=lambda *a, **k: None,
        Path=lambda *a, **k: None,
        Header=lambda *a, **k: None,
        status=types.SimpleNamespace(),
    )
    _mod("fastapi.responses", JSONResponse=object, FileResponse=object)
    _mod("fastapi.staticfiles", StaticFiles=object)
    _mod("fastapi.middleware.cors", CORSMiddleware=object)
    # fastapi 必须是「包」才能 ``from fastapi.security import ...``（api/deps.py 依赖）
    if not hasattr(fastapi_mod, "__path__"):
        fastapi_mod.__path__ = []
    security_mod = _mod(
        "fastapi.security",
        HTTPBearer=_HTTPBearer,
        HTTPAuthorizationCredentials=object,
        HTTPBasic=_HTTPBearer,
        OAuth2PasswordBearer=object,
        SecurityScopes=object,
    )
    fastapi_mod.security = security_mod

    # ── websockets（adapters/mineflayer/mineflayer_client.py）──
    _mod(
        "websockets",
        WebSocketClientProtocol=object,
        ConnectionClosed=_ConnectionClosed,
        connect=lambda *a, **k: None,
        exceptions=types.SimpleNamespace(ConnectionClosed=_ConnectionClosed,
                                         InvalidStatusCode=Exception),
    )

    # ── cachetools（adapters/litematica/litematica_parser.py）──
    _mod("cachetools", TTLCache=_TTLCache, LRUCache=_TTLCache, Cache=dict,
         cached=lambda *a, **k: _passthrough_decorator())

    # ── httpx ──
    # ``core/bluemap_monitor.py`` 顶层 import httpx（``runtime.py`` 里对它是惰性 import，
    # 但 API / main 侧会真拉到）。缺这个 stub 时相关模块 import 直接失败。
    _mod(
        "httpx",
        AsyncClient=_FakeAsyncClient,
        Client=_FakeAsyncClient,
        Timeout=lambda *a, **k: None,
        Limits=lambda *a, **k: None,
        Response=dict,
        Request=dict,
        HTTPError=Exception,
        RequestError=Exception,
        HTTPStatusError=Exception,
        TimeoutException=Exception,
        ConnectError=Exception,
        ReadTimeout=Exception,
        codes=types.SimpleNamespace(ok=200, not_found=404),
        get=lambda *a, **k: None,
        post=lambda *a, **k: None,
    )


def install() -> None:
    """注入 stub 依赖 + 把 ``backend/src`` 加进 ``sys.path``（幂等）。

    真依赖齐备的包不会被 stub（见 ``_mod`` 的 preflight），
    所以装了依赖的机器（CI / 生产）上跑同一套测试是安全的。
    """
    global _INSTALLED
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    if _INSTALLED:
        return
    _preflight()
    _install_stubs()
    _INSTALLED = True


def import_core_modules():
    """冒烟：三个历史入口都能 import（返回模块元组，失败直接抛）。"""
    install()
    from vmtools_next.core import map_art
    from vmtools_next.core import map_art_coordinator
    from vmtools_next.core import multi_bot_coordinator

    return map_art, map_art_coordinator, multi_bot_coordinator


@contextlib.contextmanager
def fast_teleport_settle():
    """测试加速：把 ``BotRuntime._send_teleport`` 里「等服务器落地」的 3.5s 压掉。

    这是**纯网络延迟**（FakeAgent 的 ``send_chat`` 立即生效），与要验证的坐标/编排
    逻辑无关；每个 bot 启动都要付这 3.5s，整编排用例里能省 20s+。

    只替换「等待」这一步，行为与原方法一致；并带**漂移守卫**：核心实现一变
    （方法体里不再有 ``asyncio.sleep(3.5)``）就报错，提醒更新本替身，避免悄悄测歪。
    """
    import inspect

    from vmtools_next.core.map_art.runtime import BotRuntime

    original = BotRuntime._send_teleport
    if "asyncio.sleep(3.5)" not in inspect.getsource(original):
        raise AssertionError(
            "BotRuntime._send_teleport 已改动（不再有 3.5s 落地等待），"
            "请同步更新 _stub_env.fast_teleport_settle()")

    async def _fast_send_teleport(self, cmd: str) -> bool:
        try:
            r = await self.mcp.send_chat(cmd)
            if isinstance(r, dict) and r.get("success") is False:
                self._activity("warn", f"传送失败：{r.get('error', '?')}")
                return False
            self._last_pos = None       # 传送后位置未知，强制重新寻路
            return True
        except Exception as e:
            self._activity("warn", f"传送异常：{e}")
            return False

    BotRuntime._send_teleport = _fast_send_teleport
    try:
        yield
    finally:
        BotRuntime._send_teleport = original


def quiet_stub_noise() -> None:
    """屏蔽 stub 环境**必然**产生的告警噪声（无 DB 桩 / 食物盒未配置）。

    这些日志不代表代码有问题：``store`` 层拿不到真 Session、``runtime`` 找不到食物
    潜影盒，都是离线环境的正常降级。设 ``VMT_TEST_VERBOSE=1`` 可保留完整日志。
    """
    if os.environ.get("VMT_TEST_VERBOSE"):
        return
    import logging

    for name in ("vmtools.map_art.store", "vmtools.map_art.runtime"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
