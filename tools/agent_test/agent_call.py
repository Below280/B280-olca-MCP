"""What the test agent runs (through dev_python) to call one MCP tool:

    exec(open(r"<this file>").read())
    print(call("olcabasic_run", {"code": "FIND PROCESS \\"cement\\""}))

It writes a request file and waits for the host's reply."""

import json, time
from pathlib import Path

import os
_HERE = Path(os.getenv("OLCA_AGENT_DIR") or r"C:\olca_agent_test")


def call(tool, arguments=None, wait=1700):
    req, rep = _HERE / "requests", _HERE / "replies"
    numbers = [int(p.stem) for p in list(req.glob("*.json")) + list(rep.glob("*.json"))]
    log = _HERE / "calls.jsonl"
    if log.exists():
        numbers += [int(json.loads(l)["n"]) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    n = max(numbers, default=0) + 1
    tmp = req / f"{n}.tmp"
    tmp.write_text(json.dumps({"tool": tool, "arguments": arguments or {}}), encoding="utf-8")
    tmp.rename(req / f"{n}.json")
    end = time.time() + wait
    while time.time() < end:
        out = rep / f"{n}.json"
        if out.exists():
            time.sleep(0.2)
            return out.read_text(encoding="utf-8")
        time.sleep(0.5)
    return json.dumps({"ok": False, "agent_call": f"no reply after {wait} s; the call is still running in the host"})
