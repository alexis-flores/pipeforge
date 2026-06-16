"""Co-simulation runner (CS-2, CS-3).

Verilator and cocotb are probed at call time; absence disables the feature
with an actionable message (C2) — never a crash, never a hidden no-op. All
tool invocations are subprocesses with captured logs.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pipeforge.core.audit.engine import Audit
from pipeforge.core.bisect.engine import BisectReport, Observations, bisect
from pipeforge.core.codegen.emitter import probe_port
from pipeforge.core.cosim.harness import write_harness
from pipeforge.core.cosim.stimulus import Vector, generate_stimulus
from pipeforge.core.fxp.evaluator import error_stats, evaluate_float
from pipeforge.core.fxp.fx import FxFormat, to_float


class CosimUnavailable(RuntimeError):
    """Raised when a required external tool is missing (C2)."""


@dataclass(frozen=True)
class OutputResult:
    name: str
    passed: bool
    compared: int
    first_failure: int  # vector index, -1 when passed
    expected: int  # raw, at first failure
    actual: int  # raw, at first failure
    max_abs_error: float  # float-vs-fixed stats (FX-4), on pass
    rms_error: float
    sqnr_db: float


@dataclass
class CosimResult:
    """Machine-readable co-simulation outcome (CS-3)."""

    passed: bool
    outputs: list[OutputResult] = field(default_factory=list)
    latency_expected: int = 0
    latency_observed: int = -1
    log: str = ""
    work_dir: str = ""
    capture_backend: str = ""  # 'probe' | 'trace' | '' (CS-7/CS-8)
    observations: Observations = field(default_factory=dict)  # node id -> streams
    bisect_report: BisectReport | None = None  # populated on failure (BI-4)
    harness_backend: str = "cocotb"  # 'cocotb' | 'verilator' (TL-1)

    def to_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "latency_expected": self.latency_expected,
            "latency_observed": self.latency_observed,
            "outputs": [
                {
                    "name": o.name,
                    "passed": o.passed,
                    "compared": o.compared,
                    "first_failure": o.first_failure,
                    "expected": o.expected,
                    "actual": o.actual,
                    "max_abs_error": o.max_abs_error,
                    "rms_error": o.rms_error,
                    "sqnr_db": o.sqnr_db,
                }
                for o in self.outputs
            ],
        }


HARNESS_BACKENDS = ("cocotb", "verilator")


def select_harness_backend(requested: str | None = None) -> str:
    """Resolve the harness backend; cocotb is the default until native parity
    is demonstrated (TL-1, mirroring the SL-1 reporting pattern)."""
    if requested in HARNESS_BACKENDS:
        return requested
    return "cocotb"


def check_tools() -> None:
    """Raise CosimUnavailable with an actionable message if tools are missing."""
    import importlib.util

    missing: list[str] = []
    if shutil.which("verilator") is None:
        missing.append("Verilator (install: pacman -S verilator / apt install verilator)")
    if importlib.util.find_spec("cocotb") is None:
        missing.append("cocotb (install: pip install cocotb)")
    if missing:
        raise CosimUnavailable(
            "Co-simulation needs external tools that are not available: "
            + "; ".join(missing)
            + ". Everything else in PipeForge keeps working without them."
        )


def compare_streams(
    audit: Audit,
    vectors: list[Vector],
    expected: dict[str, list[int]],
    actual: dict[str, list[int]],
    fmt: FxFormat,
) -> list[OutputResult]:
    """Bit-for-bit comparison plus FX-4 float-reference stats (CS-3)."""
    results: list[OutputResult] = []
    ref_streams: dict[str, list[float]] = {name: [] for name in expected}
    out_nodes = {n.signal: n.nid for n in audit.dag.outputs() if n.signal}
    for vec in vectors:
        ref = evaluate_float(audit.dag, dict(vec.items()), fmt)
        for name in ref_streams:
            ref_streams[name].append(ref[out_nodes[name]][0])
    for name, exp_stream in expected.items():
        act_stream = actual.get(name, [])
        n = min(len(exp_stream), len(act_stream))
        first_fail = -1
        for i in range(n):
            if exp_stream[i] != act_stream[i]:
                first_fail = i
                break
        passed = first_fail == -1 and n == len(exp_stream)
        if n < len(exp_stream) and first_fail == -1:
            first_fail = n  # truncated output stream
            passed = False
        measured = [to_float(x, fmt) for x in act_stream[:n]]
        stats = error_stats(ref_streams[name][:n], measured) if n else None
        results.append(
            OutputResult(
                name=name,
                passed=passed,
                compared=n,
                first_failure=first_fail,
                expected=exp_stream[first_fail] if 0 <= first_fail < len(exp_stream) else 0,
                actual=act_stream[first_fail] if 0 <= first_fail < len(act_stream) else 0,
                max_abs_error=stats.max_abs_error if stats else math.nan,
                rms_error=stats.rms_error if stats else math.nan,
                sqnr_db=stats.sqnr_db if stats else math.nan,
            )
        )
    return results


def run_cosim(
    audit: Audit,
    dut_sv: Path,
    dut_module: str,
    work_dir: Path,
    extra_sources: list[Path] | None = None,
    include_dirs: list[Path] | None = None,
    vector_count: int = 256,
    cadence: str = "continuous",
    vectors: list[Vector] | None = None,
    probes: list[str] | None = None,
    bisect_on_failure: bool = False,
    backend: str | None = None,
) -> CosimResult:
    """Build with Verilator via the cocotb runner and compare (CS-1c, CS-3, CS-6).

    `vectors` overrides synthetic stimulus with ground-truth inputs (WS-5).
    `probes` (DAG node ids) are captured from the DUT's probe ports into the
    result's Observations (CS-7); with `bisect_on_failure`, a failing run is
    localized automatically (BI-4). `backend` selects the harness: 'cocotb'
    (default) or the cocotb-free 'verilator' native path (TL-1).
    """
    fmt = FxFormat(audit.cm.width, audit.cm.scale)
    inputs = [n.label for n in audit.dag.inputs()]
    if vectors is None:
        vectors = generate_stimulus(inputs, fmt, count=vector_count)
    if select_harness_backend(backend) == "verilator":
        return _run_native(
            audit,
            dut_sv,
            dut_module,
            work_dir,
            extra_sources,
            include_dirs,
            vectors,
            bisect_on_failure=bisect_on_failure,
        )
    check_tools()
    probe_nids = probes or []
    probe_bases = [probe_port(nid) for nid in probe_nids]
    spec = write_harness(audit, dut_module, vectors, work_dir, cadence=cadence, probes=probe_bases)

    runner_script = work_dir / "run_cocotb.py"
    # absolute paths: the cocotb runner executes from inside the work dir,
    # so relative --source/--include arguments would not resolve there
    sources = [
        str(dut_sv.resolve()),
        *[str(s.resolve()) for s in (extra_sources or [])],
        "tb_wrapper.sv",
    ]
    includes = [str(i.resolve()) for i in (include_dirs or [])]
    # CS-8: when bisection is wanted but no probe ports exist (hand-written RTL),
    # dump a VCD and reconstruct per-node streams by the naming convention.
    trace = bisect_on_failure and not probe_nids
    build_args = ["-Wno-fatal", "--trace"] if trace else ["-Wno-fatal"]
    test_kwargs = ", waves=True" if trace else ""
    runner_script.write_text(
        f"""# generated by pipeforge cosim — executes inside the work dir
from cocotb_tools.runner import get_runner

runner = get_runner("verilator")
runner.build(
    verilog_sources={sources!r},
    includes={includes!r},
    hdl_toplevel="tb_wrapper",
    build_args={build_args!r},
)
runner.test(hdl_toplevel="tb_wrapper", test_module="tb_cosim"{test_kwargs})
""",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PIPEFORGE_COSIM_DIR"] = str(work_dir)
    proc = subprocess.run(
        [sys.executable, str(runner_script)],
        cwd=work_dir,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    log = proc.stdout + proc.stderr
    result = CosimResult(
        passed=False,
        latency_expected=spec.latency,
        log=log,
        work_dir=str(work_dir),
    )
    actual_path = work_dir / "actual.json"
    if proc.returncode != 0 or not actual_path.is_file():
        return result
    actual_doc = json.loads(actual_path.read_text(encoding="utf-8"))
    expected_doc = json.loads((work_dir / "expected.json").read_text(encoding="utf-8"))
    actual_outputs = actual_doc["outputs"]
    result.outputs = compare_streams(audit, vectors, expected_doc["outputs"], actual_outputs, fmt)
    result.passed = all(o.passed for o in result.outputs)
    first_valid = actual_doc.get("first_valid_cycle")
    if isinstance(first_valid, int):
        result.latency_observed = first_valid - 1  # cycle counter starts after feed

    # CS-7: reconstruct per-node Observations from the captured probe ports
    if probe_nids:
        result.capture_backend = "probe"
        result.observations = {
            nid: [[raw] for raw in actual_outputs.get(probe_port(nid), [])] for nid in probe_nids
        }
    # CS-8: no probes -> reconstruct streams from the VCD trace by convention
    elif not result.passed and bisect_on_failure:
        result.observations = _capture_from_trace(audit, work_dir, spec.latency)
        if result.observations:
            result.capture_backend = "trace"
    # BI-4: on failure, localize the first divergent stage automatically
    if not result.passed and bisect_on_failure and result.observations:
        stimulus = [{k: v for k, v in vec.items()} for vec in vectors]
        result.bisect_report = bisect(audit.dag, stimulus, result.observations, fmt)
    return result


def _run_native(
    audit: Audit,
    dut_sv: Path,
    dut_module: str,
    work_dir: Path,
    extra_sources: list[Path] | None,
    include_dirs: list[Path] | None,
    vectors: list[Vector],
    bisect_on_failure: bool = False,
) -> CosimResult:
    """Verilator-native harness: a pure-SV self-driving testbench, no cocotb (TL-1).

    With `bisect_on_failure`, the testbench dumps a VCD and a failing run is
    localized by reconstructing per-node streams from the trace (CS-8) — the
    native path is the reliable way to get a waveform out.
    """
    from pipeforge.core.cosim.harness import write_native_collateral

    if shutil.which("verilator") is None:
        raise CosimUnavailable(
            "The Verilator-native backend needs Verilator "
            "(install: pacman -S verilator / apt install verilator)."
        )
    fmt = FxFormat(audit.cm.width, audit.cm.scale)
    spec = write_native_collateral(audit, dut_module, vectors, work_dir, dump=bisect_on_failure)
    sources = [
        str(dut_sv.resolve()),
        *[str(s.resolve()) for s in (extra_sources or [])],
        "tb_native.sv",
    ]
    includes = [f"-I{i.resolve()}" for i in (include_dirs or [])]
    trace_args = ["--trace"] if bisect_on_failure else []
    build = subprocess.run(
        [
            "verilator",
            "--binary",
            "--build",
            "-Wno-fatal",
            *trace_args,
            "--top-module",
            "tb_native",
            "-o",
            "sim",
            *includes,
            *sources,
        ],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=600,
    )
    result = CosimResult(
        passed=False,
        latency_expected=spec.latency,
        log=build.stdout + build.stderr,
        work_dir=str(work_dir),
        harness_backend="verilator",
    )
    sim = work_dir / "obj_dir" / "sim"
    if build.returncode != 0 or not sim.is_file():
        return result
    run = subprocess.run([str(sim)], cwd=work_dir, capture_output=True, text=True, timeout=600)
    result.log += run.stdout + run.stderr
    actual_path = work_dir / "actual.txt"
    if not actual_path.is_file():
        return result
    actual: dict[str, list[int]] = {n: [] for n in spec.outputs}
    for line in actual_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == len(spec.outputs):
            for name, value in zip(spec.outputs, parts, strict=True):
                actual[name].append(int(value))
    expected = json.loads((work_dir / "expected.json").read_text(encoding="utf-8"))["outputs"]
    result.outputs = compare_streams(audit, vectors, expected, actual, fmt)
    result.passed = all(o.passed for o in result.outputs)
    # CS-8: on failure, reconstruct per-node streams from the dumped VCD and bisect
    if not result.passed and bisect_on_failure:
        result.observations = _capture_from_trace(audit, work_dir, spec.latency)
        if result.observations:
            result.capture_backend = "trace"
            stimulus = [dict(vec.items()) for vec in vectors]
            result.bisect_report = bisect(audit.dag, stimulus, result.observations, fmt)
    return result


def _capture_from_trace(audit: Audit, work_dir: Path, total: int) -> Observations:
    """CS-8: reconstruct stage-aligned per-node streams from the Verilator VCD.

    Works when the RTL's signal stage suffixes equal the cost-model ready times
    (always true for generated RTL; true for convention-following hand-written
    RTL). Returns an empty dict — gracefully, never raising — when no matching
    signals are found, in which case bisection simply does not run.
    """
    from pipeforge.core.cosim.trace import observations_from_vcd

    vcds = sorted(work_dir.rglob("*.vcd"))
    if not vcds:
        return {}
    try:
        return observations_from_vcd(vcds[0].read_text(encoding="utf-8"), audit.dag, total)
    except (OSError, ValueError):
        return {}
