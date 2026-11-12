"""
python_exec: the opt-in Python route.

Off unless OLCA_MCP_ALLOW_PYTHON=1. Code runs in a namespace holding
the live Session, its engine, its olca_ipc client and olca_schema (as
"o"), under the Session lock, so it never opens a second connection or
runs alongside an olcaBASIC program.

Every call must say which olcaBASIC command was missing or not enough
(why_not_basic). Calls are appended to ~/.olcabasic/python_log.jsonl;
the reasons that repeat in that log are the commands to add to the
language next.
"""

import ast
import contextlib
import datetime
import io
import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Dict

MAX_OUTPUT = 20_000
DEFAULT_TIMEOUT = 300


def enabled() -> bool:
    return os.getenv("OLCA_MCP_ALLOW_PYTHON") == "1"


def timeout_seconds() -> float:
    try:
        value = float(os.getenv("OLCA_MCP_PYTHON_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return float(DEFAULT_TIMEOUT)
    return value if value > 0 else float(DEFAULT_TIMEOUT)


def log_path() -> Path:
    override = os.getenv("OLCA_MCP_PYTHON_LOG")
    if override:
        return Path(override)
    return Path.home() / ".olcabasic" / "python_log.jsonl"


def _log(entry: Dict) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass   # a full disk must not break the call


def _truncate(text: str) -> tuple:
    if len(text) <= MAX_OUTPUT:
        return text, False
    cut = len(text) - MAX_OUTPUT
    return (text[:MAX_OUTPUT]
            + f"\n... [output truncated: {cut} more characters]"), True


def _execute(code: str, namespace: Dict, out: io.StringIO) -> None:
    """Run the code. If its last statement is an expression, print its
    value, as an interactive Python prompt would."""
    tree = ast.parse(code, "<python_exec>", "exec")
    last = tree.body[-1] if tree.body else None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        if isinstance(last, ast.Expr):
            body = ast.Module(body=tree.body[:-1], type_ignores=[])
            exec(compile(body, "<python_exec>", "exec"), namespace)
            value = eval(compile(ast.Expression(last.value),
                                 "<python_exec>", "eval"), namespace)
            if value is not None:
                print(repr(value))
        else:
            exec(compile(tree, "<python_exec>", "exec"), namespace)


def run(session, code: str, why_not_basic: str) -> Dict:
    """Run Python code against the Session. Returns a dictionary:
    ok, output, error (a traceback, if it failed), truncated, seconds."""
    reason = (why_not_basic or "").strip()
    if not reason:
        return {
            "ok": False,
            "error": "why_not_basic is required: name the olcaBASIC command "
                     "that was missing or not enough for this job. If there "
                     "is a command for it, use olcabasic_run instead "
                     "(olcabasic_help lists the commands).",
        }
    if not (code or "").strip():
        return {"ok": False, "error": "No code was given."}

    import olca_schema as o
    namespace = {
        "__name__": "__python_exec__",
        "session": session,
        "engine": session.engine,
        "client": session.client,
        "o": o,
    }
    out = io.StringIO()
    outcome: Dict = {}
    limit = timeout_seconds()
    started = time.time()

    def worker():
        with session.lock:
            try:
                _execute(code, namespace, out)
                outcome["ok"] = True
            except BaseException:
                outcome["ok"] = False
                outcome["error"] = traceback.format_exc()

    thread = threading.Thread(target=worker, name="python_exec", daemon=True)
    thread.start()
    thread.join(limit)
    seconds = round(time.time() - started, 3)

    if thread.is_alive():
        output, truncated = _truncate(out.getvalue())
        result = {
            "ok": False,
            "output": output,
            "truncated": truncated,
            "seconds": seconds,
            "timed_out": True,
            "error": f"Timed out after {limit:g} seconds. The code is still "
                     f"running and holds the session until it finishes, so "
                     f"olcabasic_run will wait for it. Set "
                     f"OLCA_MCP_PYTHON_TIMEOUT for a longer limit.",
        }
    else:
        output, truncated = _truncate(out.getvalue())
        result = {"ok": bool(outcome.get("ok")), "output": output,
                  "truncated": truncated, "seconds": seconds}
        if not result["ok"]:
            result["error"] = outcome.get("error", "unknown error")

    _log({
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "why_not_basic": reason,
        "code": code,
        "ok": result["ok"],
        "seconds": seconds,
    })
    return result
