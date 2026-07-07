"""JUnit XML export of a co-simulation result (CI-1).

One <testcase> per compared output, so CI dashboards and PR checks show
exactly which output diverged and at which vector.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from pipeforge.core.cosim.runner import CosimResult


def junit_xml(result: CosimResult, suite_name: str) -> str:
    """Render the result as a JUnit XML document string."""
    failures = sum(1 for o in result.outputs if not o.passed)
    cases: list[str] = []
    for o in result.outputs:
        name = quoteattr(o.name)
        if o.passed:
            cases.append(
                f"    <testcase classname={quoteattr(suite_name)} name={name}>"
                f"<system-out>{o.compared} vectors bit-exact — "
                f"SQNR {o.sqnr_db:.1f} dB</system-out></testcase>"
            )
        else:
            msg = (
                f"first failing vector #{o.first_failure} "
                f"(expected 0x{o.expected:x}, got 0x{o.actual:x})"
            )
            detail = msg
            if result.bisect_report is not None and result.bisect_report.diverged:
                detail += f"\n{result.bisect_report.message}"
            cases.append(
                f"    <testcase classname={quoteattr(suite_name)} name={name}>\n"
                f"      <failure message={quoteattr(msg)}>{escape(detail)}</failure>\n"
                f"    </testcase>"
            )
    if not result.outputs:  # build/sim never produced streams
        cases.append(
            f'    <testcase classname={quoteattr(suite_name)} name="build">\n'
            f'      <error message="build or simulation failed">'
            f"{escape(result.log[-2000:])}</error>\n"
            f"    </testcase>"
        )
        failures = 1
    body = "\n".join(cases)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name={quoteattr(suite_name)} tests="{max(len(result.outputs), 1)}" '
        f'failures="{failures}" errors="0">\n'
        f"{body}\n"
        "</testsuite>\n"
    )
