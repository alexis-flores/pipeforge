"""SARIF 2.1.0 export of lint findings (CI-2).

GitHub (and most code-scanning UIs) render SARIF as inline PR annotations,
so nkMatlib convention violations appear on the exact RTL line in review.
"""

from __future__ import annotations

import json

from pipeforge.core.svlint.checks import LintResult


def sarif_document(result: LintResult, file_path: str, tool_version: str) -> str:
    """Render one file's lint findings as a SARIF JSON string."""
    rules_seen: dict[str, dict[str, object]] = {}
    results: list[dict[str, object]] = []
    for f in result.findings:
        rules_seen.setdefault(
            f.check,
            {
                "id": f.check,
                "shortDescription": {"text": f"nkMatlib convention: {f.check}"},
                "help": {"text": f.fix},
            },
        )
        entry: dict[str, object] = {
            "ruleId": f.check,
            "level": "warning",
            "message": {"text": f"{f.message} — fix: {f.fix}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path},
                        "region": {"startLine": max(f.line, 1)},
                    }
                }
            ],
        }
        results.append(entry)
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "pipeforge-lint",
                        "version": tool_version,
                        "informationUri": "https://github.com/nklabs/matlib",
                        "rules": list(rules_seen.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(doc, indent=2) + "\n"
