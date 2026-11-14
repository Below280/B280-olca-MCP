"""Hosts one B280-olca-MCP server (the dev copy) for a test agent.

Tool calls arrive as files: requests/<n>.json {"tool": ..., "arguments": ...};
each reply goes to replies/<n>.json, exactly the text the MCP returns.
Every call and reply is appended to calls.jsonl. Delete nothing; a file
called STOP ends the host. The server is the real OpenLCAMCPServer with
the environment's flags (python_exec and v1 tools are off)."""

import json, os, sys, time, traceback, datetime
from pathlib import Path

HERE = Path(os.getenv("OLCA_AGENT_DIR") or Path(__file__).parent)
# the code to test: OLCA_AGENT_CODE names a folder holding olcaBASIC and
# B280-olca-MCP side by side; otherwise what is installed is used
CODE = os.getenv("OLCA_AGENT_CODE")
if CODE:
    sys.path[:0] = [str(Path(CODE) / "olcaBASIC"),
                    str(Path(CODE) / "B280-olca-MCP")]
os.environ.pop("OLCA_MCP_ALLOW_PYTHON", None)
os.environ.pop("OLCA_MCP_LEGACY_TOOLS", None)

from olcabasic import Session
from b280_olca_mcp.server import OpenLCAMCPServer

req, rep = HERE / "requests", HERE / "replies"
req.mkdir(exist_ok=True); rep.mkdir(exist_ok=True)
server = OpenLCAMCPServer(Session(port=int(os.getenv("OLCA_PORT", "8080"))))
server.setup_handlers()
tools = []
for t in server.tool_list():
    tools.append({"name": t.name, "description": t.description,
                  "inputSchema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)})
(HERE / "tools.json").write_text(json.dumps(
    {"instructions": server.instructions(), "tools": tools}, indent=1),
    encoding="utf-8")
(HERE / "READY").write_text(str(os.getpid()))
log = open(HERE / "calls.jsonl", "a", encoding="utf-8")
while not (HERE / "STOP").exists():
    pending = sorted(req.glob("*.json"), key=lambda p: int(p.stem))
    if not pending:
        time.sleep(0.3)
        continue
    for p in pending:
        try:
            call = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            time.sleep(0.2)     # still being written
            continue
        started = time.time()
        try:
            reply = server.call_tool(call["tool"], call.get("arguments") or {})
        except Exception:
            reply = json.dumps({"ok": False, "host_error": traceback.format_exc()})
        (rep / p.name).write_text(reply, encoding="utf-8")
        log.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"),
                              "n": p.stem, "tool": call["tool"],
                              "arguments": call.get("arguments"),
                              "seconds": round(time.time() - started, 1),
                              "reply": reply}, ensure_ascii=False) + "\n")
        log.flush()
        p.unlink()
