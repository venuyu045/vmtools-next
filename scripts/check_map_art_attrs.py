#!/usr/bin/env python3
"""地图画重构静态一致性检查（纯标准库，离线可跑）。

重构把 4432 + 1951 行的两套引擎拆成 ``core/map_art/`` 十几个模块，最容易出的两类
「拆分事故」编译器不会报、单测也未必覆盖，所以用 AST 静态扫描兜住：

**规则 A —— ``self._xxx`` 未赋值**
  对 ``core/map_art/**`` 里每个类，收集所有 ``self._xxx`` 使用点，沿「同包内可解析的
  父类 MRO」核对是否在某处被赋值过：
    - ``self._x = ...`` / ``self._x: T = ...`` / ``self._x: T``（仅声明）
    - ``setattr(self, "_x", ...)`` / ``self.__dict__["_x"] = ...``
    - 类体里的类属性 ``_x = ...``（``self._x`` 也能读到）
    - ``__init__`` 的参数 ``_x``（最弱证据，单独统计）
  典型事故：属性原来在 A 类赋值、拆分后搬到 B 类，但 A 的方法还在用 → 运行时
  ``AttributeError``。

**规则 B —— 模块级全局名未定义**
  模块内每个 ``Name`` 引用（Load）都必须能在「本模块定义 / 已 import / 内置 /
  局部变量 / 外层作用域」里解析。典型事故：重构时把常量搬到 ``types.py`` 却漏了
  ``from ... import TASK_COMPLETED`` → 运行到该分支才 ``NameError``（Lead 真踩过）。

用法::

    python3 scripts/check_map_art_attrs.py            # 有问题非零退出
    python3 scripts/check_map_art_attrs.py -v         # 附带统计与「弱证据」明细
    python3 scripts/check_map_art_attrs.py --root backend/src/vmtools_next/core/map_art
"""

from __future__ import annotations

import argparse
import ast
import builtins
import os
import sys

DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "backend", "src", "vmtools_next", "core", "map_art",
)

# 模块级「天然存在」的名字（解释器注入，不需要定义）
MODULE_DUNDERS = {
    "__name__", "__file__", "__doc__", "__package__", "__spec__", "__loader__",
    "__builtins__", "__debug__", "__annotations__", "__dict__", "__class__",
    "__all__", "__path__", "__module__", "__qualname__",
}

BUILTIN_NAMES = set(dir(builtins)) | MODULE_DUNDERS


# ──────────────────────────────────────────────────────────────
# 通用：作用域分析（规则 B）
# ──────────────────────────────────────────────────────────────

class Scope:
    """一层词法作用域。"""

    __slots__ = ("kind", "names", "globals", "nonlocals", "parent")

    def __init__(self, kind: str, parent: "Scope | None" = None):
        self.kind = kind                # module | function | class
        self.names: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()
        self.parent = parent

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Scope {self.kind} {sorted(self.names)[:6]}>"


class ScopeBuilder(ast.NodeVisitor):
    """第一遍：建作用域树，记录每个 Name 的 Store / Load 归属。"""

    def __init__(self) -> None:
        self.module_scope = Scope("module")
        self.stack: list[Scope] = [self.module_scope]
        self.loads: list[tuple[str, ast.AST, Scope]] = []

    @property
    def scope(self) -> Scope:
        return self.stack[-1]

    # ── 作用域边界 ──

    def _visit_function(self, node: ast.AST, params: list[ast.arg]) -> None:
        # 装饰器 / 默认值 / 注解都在「外层」求值
        for dec in getattr(node, "decorator_list", []):
            self.visit(dec)
        args = node.args
        for default in list(args.defaults) + [d for d in args.kw_defaults if d]:
            self.visit(default)
        for a in self._all_args(args):
            if a.annotation:
                self.visit(a.annotation)
        if getattr(node, "returns", None):
            self.visit(node.returns)

        scope = Scope("function", self.scope)
        for a in self._all_args(args):
            scope.names.add(a.arg)
        self.stack.append(scope)
        body = node.body if isinstance(node.body, list) else [node.body]
        for stmt in body:
            self.visit(stmt)
        self.stack.pop()

    @staticmethod
    def _all_args(args: ast.arguments) -> list[ast.arg]:
        out = list(getattr(args, "posonlyargs", [])) + list(args.args)
        if args.vararg:
            out.append(args.vararg)
        out += list(args.kwonlyargs)
        if args.kwarg:
            out.append(args.kwarg)
        return out

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.names.add(node.name)          # 函数名定义在外层
        self._visit_function(node, node.args)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.names.add(node.name)
        self._visit_function(node, node.args)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function(node, node.args)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.names.add(node.name)
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw.value)
        scope = Scope("class", self.scope)
        self.stack.append(scope)
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    def _visit_comprehension(self, node: ast.AST) -> None:
        scope = Scope("function", self.scope)
        self.stack.append(scope)
        for gen in node.generators:
            self.visit(gen.iter)
            self.visit(gen.target)
            for cond in gen.ifs:
                self.visit(cond)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.stack.pop()

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    # ── 名字记录 ──

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            target = self.scope
            if node.id in target.globals:
                target = self.module_scope
            self._record_store(target, node.id)
        else:
            self.loads.append((node.id, node, self.scope))

    def _record_store(self, scope: Scope, name: str) -> None:
        if scope.kind == "module":
            scope.names.add(name)
            return
        if name in scope.nonlocals:
            parent = scope.parent
            while parent is not None and parent.kind == "class":
                parent = parent.parent
            if parent is not None:
                self._record_store(parent, name)
            return
        scope.names.add(name)

    def visit_Global(self, node: ast.Global) -> None:
        self.scope.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.nonlocals.update(node.names)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.scope.names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            self.scope.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type:
            self.visit(node.type)
        if node.name:
            self.scope.names.add(node.name)
        for stmt in node.body:
            self.visit(stmt)

    def visit_MatchAs(self, node) -> None:
        if node.pattern:
            self.visit(node.pattern)
        if node.name:
            self.scope.names.add(node.name)

    def visit_MatchStar(self, node) -> None:
        if node.name:
            self.scope.names.add(node.name)

    def visit_MatchMapping(self, node) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest:
            self.scope.names.add(node.rest)


def _resolve_name(name: str, scope: Scope, module_scope: Scope) -> bool:
    """判断 ``name`` 在 ``scope`` 处能否解析（局部 → 外层函数 → 模块 → 内置）。"""
    current: Scope | None = scope
    first = True
    while current is not None:
        if current.kind == "class" and not first:
            current = current.parent          # 方法里看不到类属性
            continue
        if name in current.globals:
            return name in module_scope.names or name in BUILTIN_NAMES
        if name in current.names:
            return True
        current = current.parent
        first = False
    return name in BUILTIN_NAMES


def check_module_globals(tree: ast.Module, path: str) -> tuple[list[tuple[int, str]], list[str]]:
    """规则 B：返回 ([(行号, 未定义名)], 统计信息)。"""
    builder = ScopeBuilder()
    builder.visit(tree)
    errors: list[tuple[int, str]] = []
    for name, node, scope in builder.loads:
        if not _resolve_name(name, scope, builder.module_scope):
            errors.append((getattr(node, "lineno", 0), name))
    return errors, []


# ──────────────────────────────────────────────────────────────
# 规则 A：类属性赋值检查
# ──────────────────────────────────────────────────────────────

class ClassInfo:
    """一个类的「self 属性使用 / 赋值」摘要。"""

    def __init__(self, module: str, node: ast.ClassDef, path: str):
        self.module = module
        self.name = node.name
        self.node = node
        self.path = path
        self.lineno = node.lineno
        self.bases: list[str] = []          # 源码里写的基类名（Name/Attribute 的末段）
        self.bases_full: list[str] = []     # 原始写法（用于诊断）
        self.uses: list[tuple[str, int]] = []
        self.assigned: set[str] = set()
        self.class_attrs: set[str] = set()
        self.init_params: set[str] = set()
        self._collect(node)

    # ── 收集 ──

    def _collect(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            if isinstance(base, ast.Name):
                self.bases.append(base.id)
                self.bases_full.append(base.id)
            elif isinstance(base, ast.Attribute):
                self.bases.append(base.attr)
                self.bases_full.append(_attr_chain(base))
        for stmt in node.body:
            self._walk_stmt(stmt, in_class_body=True)

    def _walk_stmt(self, stmt: ast.AST, in_class_body: bool = False) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if in_class_body:
                # 方法 / property 也是 self.<name> 的合法来源
                self.class_attrs.add(stmt.name)
            if stmt.name == "__init__":
                for a in ScopeBuilder._all_args(stmt.args):
                    if a.arg != "self":
                        self.init_params.add(a.arg)
            for child in ast.walk(stmt):
                self._note_expr(child, in_class_body=False)
            return
        if isinstance(stmt, ast.ClassDef):
            # 嵌套类：self 属于内层，不并入外层
            return
        if in_class_body:
            # 类体里的直接赋值 → 类属性（self._x 可读）
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        self.class_attrs.add(target.id)
                    elif isinstance(target, ast.Tuple):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                self.class_attrs.add(elt.id)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                self.class_attrs.add(stmt.target.id)
        for child in ast.walk(stmt):
            self._note_expr(child, in_class_body=in_class_body)

    def _note_expr(self, node: ast.AST, in_class_body: bool = False) -> None:
        if isinstance(node, ast.Attribute) and _is_self(node.value):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                return          # self.__dict__ / self.__class__ 等解释器内建属性
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.assigned.add(attr)
            else:
                self.uses.append((attr, getattr(node, "lineno", 0)))
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "setattr" and len(node.args) >= 2 \
                and _is_self(node.args[0]) and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            self.assigned.add(node.args[1].value)
            return
        # self.__dict__["_x"] = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = _dict_subscript_attr(target)
                if name:
                    self.assigned.add(name)

    def self_attrs(self) -> set[str]:
        """本类「可用」的全部属性名（自身赋值 + 类属性 + init 参数）。"""
        return set(self.assigned) | set(self.class_attrs) | set(self.init_params)


def _is_self(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _attr_chain(node: ast.AST) -> str:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _dict_subscript_attr(node: ast.AST) -> str | None:
    """``self.__dict__["_x"] = ...`` → ``_x``。"""
    if not isinstance(node, ast.Subscript):
        return None
    if not (isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__"
            and _is_self(node.value.value)):
        return None
    sl = node.slice
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


# ──────────────────────────────────────────────────────────────
# 包级索引：模块 → import 映射 → 类注册表（供 MRO 解析）
# ──────────────────────────────────────────────────────────────

class PackageIndex:
    def __init__(self, root: str, package: str):
        self.root = root
        self.package = package
        self.classes: dict[tuple[str, str], ClassInfo] = {}
        self.by_name: dict[str, list[ClassInfo]] = {}
        self.imports: dict[str, dict[str, tuple[str, str | None]]] = {}
        self.trees: dict[str, ast.Module] = {}
        self.paths: dict[str, str] = {}

    # ── 扫描 ──

    def scan(self) -> None:
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root)
                modname = self._module_name(rel)
                with open(full, "r", encoding="utf-8") as fh:
                    src = fh.read()
                tree = ast.parse(src, filename=full)
                self.trees[modname] = tree
                self.paths[modname] = full
                self.imports[modname] = self._collect_imports(tree, modname)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        info = ClassInfo(modname, node, full)
                        self.classes[(modname, node.name)] = info
                        self.by_name.setdefault(node.name, []).append(info)

    def _module_name(self, rel: str) -> str:
        parts = os.path.splitext(rel)[0].split(os.sep)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join([self.package] + [p for p in parts if p and p != "."])

    def _collect_imports(self, tree: ast.Module,
                         modname: str) -> dict[str, tuple[str, str | None]]:
        """{本地名: (目标模块, 目标属性)}；``import x.y`` 记为 (x.y, None)。"""
        out: dict[str, tuple[str, str | None]] = {}
        pkg = modname.rsplit(".", 1)[0] if "." in modname else ""
        is_pkg_init = modname.endswith(self.package) or modname == self.package
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out[alias.asname or alias.name.split(".")[0]] = (alias.name, None)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = modname if is_pkg_init else pkg
                    parts = anchor.split(".")
                    if node.level > 1:
                        parts = parts[: len(parts) - (node.level - 1)]
                    base = ".".join(parts + ([base] if base else []))
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    out[alias.asname or alias.name] = (base, alias.name)
        return out

    # ── MRO 解析 ──

    def resolve_base(self, info: ClassInfo, base_name: str,
                     _depth: int = 0) -> ClassInfo | None:
        if _depth > 12:
            return None
        target = self.imports.get(info.module, {}).get(base_name)
        if target is not None:
            mod, attr = target
            found = self._lookup(mod, attr, _depth)
            if found is not None:
                return found
        # 兜底：同包内同名类（唯一时）
        candidates = self.by_name.get(base_name) or []
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _lookup(self, mod: str, attr: str | None, depth: int) -> ClassInfo | None:
        if attr is None:
            return None
        hit = self.classes.get((mod, attr))
        if hit is not None:
            return hit
        # 通过包 __init__ 的 re-export 跳一层
        reexport = self.imports.get(mod, {}).get(attr)
        if reexport is not None:
            sub_mod, sub_attr = reexport
            return self._lookup(sub_mod, sub_attr, depth + 1)
        return None

    def mro_attrs(self, info: ClassInfo, _seen: set[str] | None = None):
        """沿可解析的父类收集属性。

        返回 ``(strong, init_params, unresolved)``：
          - ``strong``       真实赋值过的属性（self.x= / 类属性 / 方法名）
          - ``init_params``  仅作为 ``__init__`` 参数同名存在的名字（弱证据）
          - ``unresolved``   无法在包内解析的基类名
        """
        seen = _seen if _seen is not None else set()
        key = f"{info.module}.{info.name}"
        if key in seen:
            return set(), set(), []
        seen.add(key)
        strong = set(info.assigned) | set(info.class_attrs)
        init_params = set(info.init_params)
        unresolved: list[str] = []
        for base_name in info.bases:
            parent = self.resolve_base(info, base_name)
            if parent is None:
                unresolved.append(base_name)
                continue
            p_strong, p_init, p_unresolved = self.mro_attrs(parent, seen)
            strong |= p_strong
            init_params |= p_init
            unresolved.extend(p_unresolved)
        return strong, init_params, unresolved


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────

def run_checks(root: str, package: str = "vmtools_next.core.map_art"):
    """对目录跑两条规则，返回 (规则A错误, 规则A无法确认, 规则B错误, 索引)。"""
    index = PackageIndex(root, package)
    index.scan()

    rule_a_errors: list[str] = []
    rule_a_warns: list[str] = []
    weak_attrs: list[str] = []
    rule_b_errors: list[str] = []

    # ── 规则 A：self 属性必须有赋值来源 ──
    for (mod, cls_name), info in sorted(index.classes.items()):
        strong, init_params, unresolved = index.mro_attrs(info)
        for attr, lineno in info.uses:
            if attr in strong:
                continue
            where = f"{_rel(info.path)}:{lineno}"
            msg = (f"[规则A] {where} 类 {cls_name} 使用 self.{attr}，"
                   f"但本类及可解析父类均未赋值")
            if attr in init_params:
                # 弱证据：只在 __init__ 参数里同名出现过，没有任何 self.<attr> = ...
                weak_attrs.append(
                    f"{where} 类 {cls_name} 的 self.{attr} 仅由 __init__ 参数同名支撑"
                    f"（建议显式 self.{attr} = ...）")
                continue
            if unresolved:
                rule_a_warns.append(
                    msg + f"（父类无法解析：{', '.join(sorted(set(unresolved)))}，无法确认）")
            else:
                rule_a_errors.append(msg)

    # ── 规则 B：模块级全局名必须可解析 ──
    for mod, tree in sorted(index.trees.items()):
        errors, _stats = check_module_globals(tree, index.paths[mod])
        for lineno, name in errors:
            rule_b_errors.append(
                f"[规则B] {_rel(index.paths[mod])}:{lineno} 模块 {mod} 引用未定义名 {name!r}")

    return rule_a_errors, rule_a_warns, rule_b_errors, weak_attrs, index


# ──────────────────────────────────────────────────────────────
# 自检：证明两条规则真的能抓到它们要抓的 bug
# ──────────────────────────────────────────────────────────────

SELF_TEST_FILES = {
    "__init__.py": "",
    "types.py": "TASK_COMPLETED = 'completed'\n",
    "broken.py": (
        "from pkg.types import TASK_COMPLETED\n"
        "\n"
        "class Base:\n"
        "    def __init__(self):\n"
        "        self._ok = 1\n"
        "        self.count: int = 0\n"
        "\n"
        "    def helper(self):\n"
        "        return 1\n"
        "\n"
        "class Child(Base):\n"
        "    def good(self):\n"
        "        return self._ok + self.count + self.helper()\n"
        "\n"
        "    def bad_attr(self):\n"
        "        return self._missing\n"
        "\n"
        "    def bad_name(self):\n"
        "        return TASK_COMPLETED + UNDEFINED_CONSTANT\n"
        "\n"
        "    def ok_name(self):\n"
        "        local = 1\n"
        "        return TASK_COMPLETED + str(local) + str(len([]))\n"
    ),
}


def self_test() -> int:
    """在临时目录里跑一份「故意写错」的代码，验证两条规则都能命中。"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pkg")
        os.makedirs(root, exist_ok=True)
        for name, src in SELF_TEST_FILES.items():
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(src)
        a_errors, a_warns, b_errors, _weak, _idx = run_checks(root, package="pkg")

    ok = True
    # 规则A 必须抓到 _missing，且不能误报继承来的 _ok / count / helper
    if not any("self._missing" in e for e in a_errors):
        print("❌ 自检失败：规则A 没抓到 self._missing")
        ok = False
    if any(("self._ok" in e) or ("self.count" in e) or ("self.helper" in e) for e in a_errors):
        print("❌ 自检失败：规则A 误报了父类/类属性")
        ok = False
    # 规则B 必须抓到 UNDEFINED_CONSTANT，且不能误报 TASK_COMPLETED / local / str / len
    if not any("UNDEFINED_CONSTANT" in e for e in b_errors):
        print("❌ 自检失败：规则B 没抓到 UNDEFINED_CONSTANT")
        ok = False
    if any(("TASK_COMPLETED" in e) or ("local" in e) for e in b_errors):
        print("❌ 自检失败：规则B 误报了已 import 的名字 / 局部变量")
        ok = False
    if ok:
        print("✅ 自检通过：规则A/规则B 均能命中目标缺陷且无误报")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="地图画重构静态一致性检查")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="map_art 包目录")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印统计与弱证据")
    parser.add_argument("--self-test", action="store_true",
                        help="先跑检查器自检（验证两条规则真的能抓到 bug）")
    args = parser.parse_args(argv)

    if args.self_test:
        rc = self_test()
        if rc:
            return rc

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"[FATAL] 目录不存在：{root}", file=sys.stderr)
        return 2

    rule_a_errors, rule_a_warns, rule_b_errors, weak_attrs, index = run_checks(root)
    if not index.classes:
        print(f"[FATAL] 在 {root} 下没找到任何类", file=sys.stderr)
        return 2

    print(f"扫描目录：{_rel(root)}")
    print(f"模块 {len(index.trees)} 个 / 类 {len(index.classes)} 个\n")

    for line in rule_a_errors + rule_a_warns + rule_b_errors:
        print(line)

    if args.verbose:
        print("\n── 统计 ──")
        for (mod, cls_name), info in sorted(index.classes.items()):
            strong, init_params, unresolved = index.mro_attrs(info)
            print(f"  {mod}.{cls_name}: self 属性使用 {len(info.uses)} 处 / "
                  f"已赋值 {len(strong)} 个 / 弱证据 {len(init_params)} 个 / "
                  f"未解析父类 {unresolved or '无'}")
        if weak_attrs:
            print("\n── 弱证据（仅 __init__ 参数支撑，非错误）──")
            for line in weak_attrs:
                print("  " + line)

    total = len(rule_a_errors) + len(rule_b_errors)
    print(f"\n规则A 错误 {len(rule_a_errors)} / 无法确认 {len(rule_a_warns)}"
          f" | 规则B 错误 {len(rule_b_errors)}")
    if total:
        print("❌ 静态检查未通过")
        return 1
    print("✅ 静态检查通过")
    return 0


def _rel(path: str) -> str:
    """尽量显示相对路径（repo 根或 backend 起算）。"""
    try:
        cwd = os.getcwd()
        rel = os.path.relpath(path, cwd)
        if not rel.startswith(".."):
            return rel
    except Exception:
        pass
    return path


if __name__ == "__main__":
    sys.exit(main())
