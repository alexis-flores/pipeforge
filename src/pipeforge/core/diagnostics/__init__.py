"""Cross-domain diagnostics built on the correspondence map (DX).

Once operation groups exist (MP-3), unified failure triage (DX-1) and a
MATLAB↔RTL traceability export (DX-2) fall out of data the earlier phases
already produce.
"""

from __future__ import annotations

from pipeforge.core.diagnostics.traceability import export_traceability
from pipeforge.core.diagnostics.triage import TriageSummary, triage

__all__ = ["TriageSummary", "export_traceability", "triage"]
