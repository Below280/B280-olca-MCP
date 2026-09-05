"""
Compare JSON-RPC method strings in the installed olca-ipc package
against our IPC protocol reference to detect drift.

Exits 0 if coverage is complete, 1 if new methods are found.
Writes a report to /tmp/ipc_drift_report.txt on failure.
"""

import importlib
import inspect
import re
import sys
from pathlib import Path

def extract_methods_from_olca_ipc():
    """Pull every JSON-RPC method string from the installed olca-ipc source."""
    import olca_ipc.ipc as ipc_module
    source = inspect.getsource(ipc_module)
    # Match strings like "data/get/descriptors" or "result/total-impacts"
    pattern = r'"((?:data|result)/[a-z][a-z0-9\-/]*)"'
    return sorted(set(re.findall(pattern, source)))

def extract_methods_from_reference():
    """Pull every JSON-RPC method string from our protocol reference."""
    ref_path = Path(__file__).parent.parent.parent / "b280_olca_mcp" / "ipc_reference.py"
    source = ref_path.read_text()
    pattern = r'((?:data|result)/[a-z][a-z0-9\-/]*)'
    return sorted(set(re.findall(pattern, source)))

def main():
    olca_methods = extract_methods_from_olca_ipc()
    ref_methods = extract_methods_from_reference()

    olca_set = set(olca_methods)
    ref_set = set(ref_methods)

    missing = olca_set - ref_set
    extra = ref_set - olca_set

    print(f"olca-ipc methods:  {len(olca_set)}")
    print(f"reference methods: {len(ref_set)}")

    if not missing and not extra:
        print("Coverage complete. No drift detected.")
        return 0

    lines = []
    lines.append("## IPC Protocol Drift Detected\n")
    lines.append(f"olca-ipc has **{len(olca_set)}** methods, "
                 f"the reference documents **{len(ref_set)}**.\n")

    if missing:
        lines.append(f"### New methods in olca-ipc ({len(missing)})\n")
        lines.append("These methods exist in the installed `olca-ipc` package "
                     "but are not documented in `ipc_reference.py`:\n")
        for m in sorted(missing):
            lines.append(f"- `{m}`")
        lines.append("")

    if extra:
        lines.append(f"### Methods in reference but not in olca-ipc ({len(extra)})\n")
        lines.append("These may have been removed or renamed:\n")
        for m in sorted(extra):
            lines.append(f"- `{m}`")
        lines.append("")

    lines.append("### Action needed\n")
    lines.append("Update `b280_olca_mcp/ipc_reference.py` to match the "
                 "current `olca-ipc` package, then close this issue.")

    report = "\n".join(lines)
    print(report)

    Path("/tmp/ipc_drift_report.txt").write_text(report)
    return 1

if __name__ == "__main__":
    sys.exit(main())
