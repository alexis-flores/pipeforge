"""SystemVerilog structural parsing (SL-1): pyslang when installed, else a
documented regex/structural fallback sufficient for nkMatlib-convention files.

`PIPE macro uses are always extracted textually (they are preprocessor
macros, invisible to a syntax tree without macros.svh), then the rest of the
file goes to the active backend. The active backend is reported.
"""

from __future__ import annotations

import re

from pipeforge.core.svlint.model import AssignStmt, Instance, PipeUse, Port, SvModule

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_PIPE_RE = re.compile(r"`PIPE\(\s*(\w+)\s*,\s*([^,]*?)\s*,\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_MODULE_RE = re.compile(r"\bmodule\s+(\w+)\s*(?:#\s*\(.*?\))?\s*\((.*?)\)\s*;", re.DOTALL)
_PORT_RE = re.compile(r"\b(input|output|fixedp)\b[^,()]*?(\w+)\s*(?:,|$)")
_INSTANCE_RE = re.compile(
    r"\b(\w+)\s*(?:#\s*\([^;]*?\))?\s+(\w+)\s*\(\s*((?:\.\w+\s*\([^()]*\)\s*,?\s*)+)\)\s*;",
    re.DOTALL,
)
_CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)")
_ASSIGN_RE = re.compile(r"\bassign\s+(\w+)\s*=\s*([^;]+);")

_SV_KEYWORDS = frozenset(
    {"module", "input", "output", "logic", "wire", "reg", "assign", "always", "if", "else"}
)


def strip_comments(text: str) -> str:
    """Remove comments, preserving line numbers."""

    def blank(m: re.Match[str]) -> str:
        return "".join("\n" if c == "\n" else " " for c in m.group(0))

    return _LINE_COMMENT.sub(lambda m: " " * len(m.group(0)), _BLOCK_COMMENT.sub(blank, text))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def extract_pipes(text: str) -> list[PipeUse]:
    pipes: list[PipeUse] = []
    for m in _PIPE_RE.finditer(text):
        pipes.append(
            PipeUse(
                pipe_module=m.group(1),
                signal=m.group(3),
                from_stage=int(m.group(4)),
                to_stage=int(m.group(5)),
                line=_line_of(text, m.start()),
            )
        )
    return pipes


def _blank_pipes(text: str) -> str:
    return _PIPE_RE.sub(lambda m: " " * len(m.group(0)), text)


# ---------------------------------------------------------------------------
# Regex/structural backend
# ---------------------------------------------------------------------------


def parse_structural(text: str) -> SvModule:
    clean = _blank_pipes(strip_comments(text))
    header = _MODULE_RE.search(clean)
    if header is None:
        return SvModule(name="")
    module = SvModule(name=header.group(1))
    for pm in _PORT_RE.finditer(header.group(2)):
        kind, name = pm.group(1), pm.group(2)
        if kind == "fixedp":
            module.has_fixedp = True
            module.ports.append(Port(name, "interface", _line_of(clean, header.start())))
        else:
            module.ports.append(Port(name, kind, _line_of(clean, header.start())))
    body = clean[header.end() :]
    body_offset = header.end()
    for im in _INSTANCE_RE.finditer(body):
        mod_name, inst_name = im.group(1), im.group(2)
        if mod_name in _SV_KEYWORDS:
            continue
        conns = {c.group(1): c.group(2).strip() for c in _CONN_RE.finditer(im.group(3))}
        module.instances.append(
            Instance(mod_name, inst_name, conns, _line_of(clean, body_offset + im.start()))
        )
    for am in _ASSIGN_RE.finditer(body):
        module.assigns.append(
            AssignStmt(am.group(1), am.group(2).strip(), _line_of(clean, body_offset + am.start()))
        )
    return module


# ---------------------------------------------------------------------------
# pyslang backend
# ---------------------------------------------------------------------------


def _parse_pyslang(text: str) -> SvModule | None:
    # Imported dynamically: pyslang is optional (C2) and its shipped stubs
    # do not parse under mypy, so the import stays invisible to type checking.
    import importlib

    try:
        pyslang = importlib.import_module("pyslang")
    except ImportError:
        return None
    try:
        # pyslang >= 7 nests SyntaxTree under .syntax; older versions are flat
        syntax_tree = getattr(pyslang, "SyntaxTree", None)
        if syntax_tree is None:
            syntax_tree = importlib.import_module("pyslang.syntax").SyntaxTree
        clean = _blank_pipes(strip_comments(text))
        tree = syntax_tree.fromText(clean)
        module: SvModule | None = None

        def visit(node: object) -> None:
            nonlocal module
            kind = getattr(node, "kind", None)
            kind_name = str(kind) if kind is not None else ""
            if kind_name.endswith("ModuleDeclaration") and module is None:
                module = _pyslang_module(node, clean)

        _walk_syntax(tree.root, visit)
        return module
    except Exception:
        return None


def _walk_syntax(node: object, fn: object) -> None:
    fn(node)  # type: ignore[operator]
    count = 0
    try:
        count = len(node)  # type: ignore[arg-type]
    except TypeError:
        return
    for i in range(count):
        child = node[i]  # type: ignore[index]
        if child is not None and hasattr(child, "kind"):
            _walk_syntax(child, fn)


def _pyslang_module(node: object, text: str) -> SvModule:
    header = node.header  # type: ignore[attr-defined]
    module = SvModule(name=str(header.name.valueText))
    ports_syntax = getattr(header, "ports", None)
    if ports_syntax is not None:
        port_text = str(ports_syntax)
        for pm in _PORT_RE.finditer(port_text):
            kind, name = pm.group(1), pm.group(2)
            if kind == "fixedp":
                module.has_fixedp = True
                module.ports.append(Port(name, "interface", 1))
            else:
                module.ports.append(Port(name, kind, 1))

    def visit(child: object) -> None:
        kind_name = str(getattr(child, "kind", ""))
        if kind_name.endswith("HierarchyInstantiation"):
            mod_name = str(child.type.valueText)  # type: ignore[attr-defined]
            inst_text = str(child)
            line = 1
            try:
                pos = text.index(inst_text.strip()[:40])
                line = text.count("\n", 0, pos) + 1
            except ValueError:
                pass
            for inst in child.instances:  # type: ignore[attr-defined]
                inst_name = str(inst.decl.name.valueText)
                conns = {c.group(1): c.group(2).strip() for c in _CONN_RE.finditer(str(inst))}
                module.instances.append(Instance(mod_name, inst_name, conns, line))
        elif kind_name.endswith("ContinuousAssign"):
            for am in _ASSIGN_RE.finditer(str(child)):
                line = 1
                try:
                    pos = text.index(str(child).strip()[:30])
                    line = text.count("\n", 0, pos) + 1
                except ValueError:
                    pass
                module.assigns.append(AssignStmt(am.group(1), am.group(2).strip(), line))

    _walk_syntax(node, visit)
    return module


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_sv(text: str, prefer_pyslang: bool = True) -> tuple[SvModule, str]:
    """Parse to the structural model; returns (module, backend_name) (SL-1)."""
    pipes = extract_pipes(strip_comments(text))
    module: SvModule | None = None
    backend = "structural"
    if prefer_pyslang:
        module = _parse_pyslang(text)
        if module is not None:
            backend = "pyslang"
    if module is None:
        module = parse_structural(text)
        backend = "structural"
    module.pipes = pipes
    return module, backend
