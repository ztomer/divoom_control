"""Find names a module USES but never defines — the class that parses and dies.

**Why this exists.** `scripts/hw_smoke.py` and `scripts/hw_walk_modes.py`
printed their results with `_GRAY`, `_DIM`, `_BOLD`, `_RED` and `_RESET`:
module-private colour constants in the house TUI (`tui/lib.py` exports them as
`_C_GRAY`, `_C_DIM`, ...). None of those names existed in the scripts, and
`tools/check_scripts.py` — the gate that exists so `scripts/` is not unverified
tooling — only checked that a script PARSES. A file with a NameError in it
parses perfectly. So the gate was green, the script was broken, and the
symptom was a run that reported "4 device(s)" and then died in the reporting:

    ✓ 4 device(s):
    ✗ scan failed: NameError: name '_GRAY' is not defined

The scan had WORKED. The four panels had answered. The report of that fact
raised, and because the raise was caught and reported as a warning, the script
exited 0. An instrument that cannot say NO is not an instrument.

**What this is.** A small scope-aware, AST-only pass. For every module it
collects the names the module BINDS (imports, assignments, def/class names,
parameters, comprehension targets, `global`/`nonlocal` declarations) and the
names it LOADS, then reports a load that resolves to no binding, no enclosing
scope, and no builtin.

It is a linter, written here because the house rule is that a gate may not
depend on a tool that is not already a dependency: `pyflakes` is not in
`requirements.txt`, and adding a linter to a repo to catch one class of
mistake is a heavier answer than writing the pass. `ast` is in the standard
library, so this runs anywhere the repo's own gates run.

**HONEST SCOPE.** It reads the module's own bindings; it does not import it,
so a name injected by a star-import (`from x import *`) cannot be seen and
would be reported. No script in this repo star-imports, and the gate's own
scope statement says so rather than pretending otherwise. It also does not
follow `exec`/`eval` strings, and it treats a comprehension's targets as
scoped to the comprehension (Python 3's rule) — so `[x for x in y]` followed
by a bare `x` IS reported, because that is a NameError at runtime.
"""
from __future__ import annotations

import ast
import builtins

# Names every module has, whether or not it assigned them.
_MODULE_DUNDERS = frozenset({
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__class__",
})

_BUILTINS = frozenset(dir(builtins)) | _MODULE_DUNDERS


class _Scope:
    """One binding scope: module, function, class, lambda or comprehension."""

    def __init__(self, kind: str, parent: "_Scope | None" = None):
        self.kind = kind
        self.parent = parent
        self.bindings: set[str] = set()
        # Where a walrus (`:=`) inside this scope binds. Python binds it in the
        # nearest enclosing FUNCTION scope, skipping comprehension scopes
        # (PEP 572), so a comprehension carries its parent's answer.
        self.walrus_scope = parent.walrus_scope if (
            kind == "comprehension" and parent is not None) else self

    def defines(self, name: str) -> bool:
        """Is `name` bound in this scope, or in a scope that encloses it?

        Python's own rule: a CLASS body is not an enclosing scope for the
        functions defined inside it, so a method cannot see the class's
        attributes as bare names. The lookup honours that, because a checker
        that does not would flag every method that reads a class constant.
        """
        scope: _Scope | None = self
        while scope is not None:
            if scope.kind == "class" and self.kind != "class":
                scope = scope.parent
                continue
            if name in scope.bindings:
                return True
            scope = scope.parent
        return False


def _target_names(node: ast.AST) -> list[str]:
    """The names an assignment target binds."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in node.elts:
            out += _target_names(elt)
        return out
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        # `obj.attr = 1` and `obj[0] = 1` bind `obj`, not a new name.
        return _target_names(node.value)
    return []


def _pattern_names(node: ast.AST) -> list[str]:
    """The names a `match` pattern captures."""
    out: list[str] = []
    if isinstance(node, ast.MatchAs):
        if node.name:
            out.append(node.name)
        out += _pattern_names(node.pattern)
    elif isinstance(node, ast.MatchStar):
        if node.name:
            out.append(node.name)
    elif isinstance(node, ast.MatchMapping):
        if node.rest:
            out.append(node.rest)
        for child in node.patterns:
            out += _pattern_names(child)
    elif isinstance(node, ast.MatchClass):
        for child in node.patterns:
            out += _pattern_names(child)
        for child in node.kwd_patterns:
            out += _pattern_names(child)
    elif isinstance(node, ast.MatchOr):
        for child in node.patterns:
            out += _pattern_names(child)
    elif isinstance(node, ast.MatchValue):
        pass
    return out


def _arg_names(args: ast.arguments) -> list[str]:
    out = [a.arg for a in
           list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
    if args.vararg:
        out.append(args.vararg.arg)
    if args.kwarg:
        out.append(args.kwarg.arg)
    return out


def _walrus_targets(node: ast.AST) -> list[str]:
    """The names bound by walrus operators inside one expression."""
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.NamedExpr):
            out += _target_names(child.target)
    return out


def _annotations(args: ast.arguments) -> list[ast.AST]:
    out = [a.annotation for a in
           list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
           if a.annotation is not None]
    return out


class _Finder:
    """Walks one module and collects its undefined loads."""

    def __init__(self) -> None:
        self.module = _Scope("module")
        self.problems: list[tuple[str, int]] = []
        self._seen: set[tuple[str, int]] = set()
        # `from __future__ import annotations` makes every annotation a STRING
        # that is never evaluated, so an undefined name in an annotation cannot
        # raise NameError at runtime. Flagging it would be a false positive
        # about a class of bug this pass exists to find.
        self._lazy_annotations = False

    # ── entry point ────────────────────────────────────────────────────────
    def run(self, tree: ast.Module) -> list[tuple[str, int]]:
        self._lazy_annotations = any(
            isinstance(stmt, ast.ImportFrom)
            and stmt.module == "__future__"
            and any(a.name == "annotations" for a in stmt.names)
            for stmt in tree.body
        )
        self._collect(tree.body, self.module)
        for stmt in tree.body:
            self._stmt(stmt, self.module)
        return self.problems

    # ── bindings ───────────────────────────────────────────────────────────
    def _collect(self, body: list[ast.stmt], scope: _Scope) -> None:
        """Every name this scope binds.

        Done as a pre-pass over the whole body, because Python binds a local
        name for the WHOLE function, not from the assignment onwards.
        """
        for stmt in body:
            if isinstance(stmt, ast.Global):
                for name in stmt.names:
                    scope.bindings.discard(name)
                    self.module.bindings.add(name)
            elif isinstance(stmt, ast.Nonlocal):
                for name in stmt.names:
                    scope.bindings.discard(name)
        for stmt in body:
            for name in self._bound_names(stmt):
                scope.bindings.add(name)

    def _bound_names(self, node: ast.AST) -> list[str]:
        """The names one statement binds in the scope that contains it."""
        out: list[str] = []
        kind = type(node)
        if kind is ast.Assign:
            for target in node.targets:
                out += _target_names(target)
        elif kind in (ast.AnnAssign, ast.AugAssign):
            out += _target_names(node.target)
        elif kind is ast.NamedExpr:
            out += _target_names(node.target)
        elif kind in (ast.For, ast.AsyncFor):
            out += _target_names(node.target)
        elif kind in (ast.Import, ast.ImportFrom):
            for alias in node.names:
                out.append(alias.asname or alias.name.split(".")[0])
        elif kind in (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef):
            out.append(node.name)
        elif kind is ast.TypeAlias:  # Python 3.12
            if isinstance(node.name, ast.Name):
                out.append(node.name.id)
        elif kind is ast.Try:
            for handler in node.handlers:
                if handler.name:
                    out.append(handler.name)
        elif kind is ast.Match:
            for case in node.cases:
                out += _pattern_names(case.pattern)
        # Nested blocks bind in the SAME scope, so recurse into their bodies.
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                out += self._bound_names(child)
            elif isinstance(child, ast.excepthandler):
                # An `except` block is a block, not a scope: a name bound in
                # it is bound in the function around it.
                for stmt in child.body:
                    out += self._bound_names(stmt)
            elif isinstance(child, ast.withitem):
                if child.optional_vars is not None:
                    out += _target_names(child.optional_vars)
            elif isinstance(child, ast.match_case):
                out += _pattern_names(child.pattern)
        return out

    # ── loads ──────────────────────────────────────────────────────────────
    def _check(self, name: str, lineno: int, scope: _Scope) -> None:
        if name in _BUILTINS or scope.defines(name):
            return
        key = (name, lineno)
        if key in self._seen:
            return
        self._seen.add(key)
        self.problems.append((name, lineno))

    def _expr(self, node: ast.AST | None, scope: _Scope,
              in_annotation: bool = False) -> None:
        if node is None:
            return
        kind = type(node)
        if kind is ast.Lambda:
            inner = _Scope("function", scope)
            for name in _arg_names(node.args):
                inner.bindings.add(name)
            for default in node.args.defaults:
                self._expr(default, scope)
            for default in node.args.kw_defaults:
                self._expr(default, scope)
            for ann in _annotations(node.args):
                self._expr(ann, scope, self._lazy_annotations)
            self._expr(node.body, inner)
            return
        if kind in (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp):
            self._comprehension(node, scope)
            return
        if kind is ast.Name:
            if isinstance(node.ctx, ast.Load) and not in_annotation:
                self._check(node.id, node.lineno, scope)
            return
        for child in ast.iter_child_nodes(node):
            self._expr(child, scope, in_annotation)

    def _comprehension(self, node: ast.AST, scope: _Scope) -> None:
        """A comprehension is its own scope; its first iterable is not."""
        inner = _Scope("comprehension", scope)
        # A walrus inside a comprehension binds in the nearest enclosing
        # function scope (PEP 572), NOT in the comprehension. Binding it in
        # both places is what Python does: the comprehension can read it, and
        # so can the code around the comprehension.
        for target in _walrus_targets(node):
            inner.bindings.add(target)
            scope.walrus_scope.bindings.add(target)
        for index, gen in enumerate(node.generators):
            self._expr(gen.iter, scope if index == 0 else inner)
            for name in _target_names(gen.target):
                inner.bindings.add(name)
            for cond in gen.ifs:
                self._expr(cond, inner)
        if isinstance(node, ast.DictComp):
            self._expr(node.key, inner)
            self._expr(node.value, inner)
        else:
            self._expr(node.elt, inner)

    # ── statements ─────────────────────────────────────────────────────────
    def _stmt(self, node: ast.stmt, scope: _Scope) -> None:
        kind = type(node)
        if kind in (ast.FunctionDef, ast.AsyncFunctionDef):
            for deco in node.decorator_list:
                self._expr(deco, scope)
            for default in node.args.defaults:
                self._expr(default, scope)
            for default in node.args.kw_defaults:
                self._expr(default, scope)
            for ann in _annotations(node.args):
                self._expr(ann, scope, self._lazy_annotations)
            if node.returns is not None:
                self._expr(node.returns, scope, self._lazy_annotations)
            inner = _Scope("function", scope)
            for name in _arg_names(node.args):
                inner.bindings.add(name)
            self._collect(node.body, inner)
            for stmt in node.body:
                self._stmt(stmt, inner)
            return
        if kind is ast.ClassDef:
            for deco in node.decorator_list:
                self._expr(deco, scope)
            for base in node.bases:
                self._expr(base, scope)
            for kw in node.keywords:
                self._expr(kw.value, scope)
            inner = _Scope("class", scope)
            self._collect(node.body, inner)
            for stmt in node.body:
                self._stmt(stmt, inner)
            return
        if kind is ast.Global:
            return
        if kind is ast.Nonlocal:
            return
        if kind is ast.AnnAssign:
            # `x: T = v` — the annotation is a type expression, not a value.
            if node.value is not None:
                self._expr(node.value, scope)
            if node.annotation is not None:
                self._expr(node.annotation, scope, self._lazy_annotations)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                self._stmt(child, scope)
            elif isinstance(child, ast.expr):
                self._expr(child, scope)
            elif isinstance(child, ast.withitem):
                self._expr(child.context_expr, scope)
                if child.optional_vars is not None:
                    self._expr(child.optional_vars, scope)
            elif isinstance(child, ast.excepthandler):
                self._expr(child.type, scope)
                for stmt in child.body:
                    self._stmt(stmt, scope)
            elif isinstance(child, ast.match_case):
                self._expr(child.guard, scope)
            elif isinstance(child, (ast.alias, ast.keyword)):
                self._expr(getattr(child, "value", None), scope)
            else:
                self._expr(child, scope)


def undefined_names(source: str) -> list[tuple[str, int]]:
    """Names `source` uses but never defines.

    Returns (name, lineno) pairs, sorted by line. Raises SyntaxError for
    unparsable source — the caller that wants a syntax check has one.
    """
    tree = ast.parse(source)
    return sorted(_Finder().run(tree), key=lambda item: (item[1], item[0]))


def undefined_names_in_file(path) -> list[tuple[str, int]]:
    from pathlib import Path

    p = Path(path)
    return undefined_names(p.read_text(encoding="utf-8", errors="replace"))
