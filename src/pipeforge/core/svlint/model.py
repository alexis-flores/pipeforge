"""Structural model of an nkMatlib-convention SystemVerilog file (SL-1).

Both parser backends (pyslang and the regex fallback) normalize to these
types; every check runs on this model only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeforge.core.costmodel.model import CostModel


@dataclass(frozen=True)
class Port:
    name: str
    direction: str  # 'input' | 'output' | 'interface'
    line: int


@dataclass(frozen=True)
class Instance:
    module: str
    name: str
    conns: dict[str, str]  # port -> connected expression (trimmed)
    line: int


@dataclass(frozen=True)
class PipeUse:
    """One `PIPE(<pipe module>, <type>, <signal>, <from>, <to>) macro use."""

    pipe_module: str
    signal: str
    from_stage: int
    to_stage: int
    line: int


@dataclass(frozen=True)
class AssignStmt:
    lhs: str
    rhs: str
    line: int


@dataclass
class SvModule:
    name: str
    ports: list[Port] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    pipes: list[PipeUse] = field(default_factory=list)
    assigns: list[AssignStmt] = field(default_factory=list)
    has_fixedp: bool = False


_SUFFIX_RE = re.compile(r"^(\w+?)_(\d+|N)$")


def split_suffix(signal: str) -> tuple[str, str] | None:
    """'prod_1' -> ('prod', '1'); 'valid_N' -> ('valid', 'N'); else None."""
    m = _SUFFIX_RE.match(signal)
    if not m:
        return None
    return m.group(1), m.group(2)


def is_valid_signal(signal: str) -> bool:
    base = split_suffix(signal)
    name = base[0] if base else signal
    return name == "valid" or name.endswith("valid")


#: Delay-matching pipe families. *_valid modules reset their flip-flops;
#: *_pipe (and `pipe`) do not, so synthesis can infer SRLs.
RESET_PIPES = frozenset(
    {
        "valid",
        "validone",
        "mul_valid",
        "div_valid",
        "sqrt_valid",
        "matmul_valid",
        "sumsqr_valid",
        "rootsqr_valid",
        "crossp_valid",
        "vecnorm_valid",
    }
)
UNRESET_PIPES = frozenset(
    {
        "pipe",
        "pipeone",
        "piperam",
        "mul_pipe",
        "div_pipe",
        "sqrt_pipe",
        "matmul_pipe",
        "sumsqr_pipe",
        "rootsqr_pipe",
        "crossp_pipe",
        "vecnorm_pipe",
    }
)
PIPE_MODULES = RESET_PIPES | UNRESET_PIPES


def pipe_latency(module: str, cm: CostModel) -> int | None:
    """Matching-delay cycles provided by a pipe/valid module."""
    base = module.removesuffix("_valid").removesuffix("_pipe")
    if module in ("pipe", "valid", "pipeone", "validone", "piperam"):
        return 1
    table = {
        "mul": cm.mul_lat,
        "div": cm.div_lat,
        "sqrt": cm.sqrt_lat,
        "matmul": cm.matmul_lat,
        "sumsqr": cm.sumsqr_lat,
        "rootsqr": cm.rootsqr_lat,
        "crossp": cm.crossp_lat,
        "vecnorm": cm.rootsqr_lat,
    }
    return table.get(base)


def operator_latency(module: str, cm: CostModel) -> int | None:
    """Latency of an nkMatlib operator module, incl. scalar variants."""
    try:
        return cm.latency_of(module)
    except KeyError:
        pass
    scalar = {
        "add": cm.add_lat,
        "add3": cm.add_lat,
        "add3b1": cm.add_lat,
        "add3b2": cm.add_lat,
        "add4": cm.add_lat,
        "sub": cm.add_lat,
        "sub4": cm.add_lat,
        "matadd4": cm.add_lat,
        "abs": 1,
        "neg": 1,
        "condneg": 1,
        "elem_condneg": 1,
        "smax": 1,
        "smin": 1,
        "slimit": 1,
        "vecmax": 1,
        "vecmin": 1,
        "vecmaxmag": 1,
        "smul": cm.mul_lat,
        "umul": cm.mul_lat,
        "ssqr": cm.mul_lat,
        "usqr": cm.mul_lat,
        "elem_smul_by_col": cm.mul_lat,
        "sdiv": cm.div_lat,
        "udiv": cm.div_lat,
        "sinv": cm.div_lat,
        "uinv": cm.div_lat,
        "usqrt": cm.sqrt_lat,
        "snorm": 0,
        "unorm": 0,
        "norm": 0,
        "dup_rows": 0,
        "dup_cols": 0,
    }
    return scalar.get(module)


#: Instance ports that carry operand data (vs. g/h interface and outputs).
DATA_PORTS = ("a", "b", "c", "i")
OUTPUT_PORTS = ("f", "o")
