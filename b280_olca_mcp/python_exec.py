"""
python_exec: the opt-in Python route.

Off unless OLCA_MCP_ALLOW_PYTHON=1. Code runs in a namespace holding
the live Session, its engine, its olca_ipc client and olca_schema (as
"o"), under the Session lock, so it never opens a second connection or
runs alongside an olcaBASIC program.

The client is a CheckedClient (checked_client.py): reads and
calculations are free; writes are limited to model folders ('00: ...'),
recorded, and every product system they touch is marked out of date
until it is built again and passes VALIDATE.

Every call must say which olcaBASIC command was missing or not enough
(why_not_basic). Calls are appended to ~/.olcabasic/python_log.jsonl;
the reasons that repeat in that log are the commands to add to the
language next.
"""

import ast
import sys
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


class _ThisThread:
    """sys.stdout (or stderr) while code runs: what this thread prints
    goes to the captured output; every other thread of the server keeps
    printing where it did."""

    def __init__(self, original, captured, thread):
        self._original = original
        self._captured = captured
        self._thread = thread

    def _target(self):
        return (self._captured if threading.current_thread() is self._thread
                else self._original)

    def write(self, text):
        return self._target().write(text)

    def flush(self):
        return self._target().flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


class _Stopped(BaseException):
    """Raised inside the code when its time is up."""


def _deadline_tracer(deadline: float):
    """A trace function that stops pure-Python code at the deadline, so a
    loop that never ends cannot hold the session for ever. (A call that
    waits inside C, such as a long sleep, is only stopped when it
    returns.)"""
    def tracer(frame, event, arg):
        if time.monotonic() > deadline:
            raise _Stopped("time limit reached")
        return tracer
    return tracer


def _execute(code: str, namespace: Dict, out: io.StringIO,
             deadline: float = 0.0) -> None:
    """Run the code. If its last statement is an expression, print its
    value, as an interactive Python prompt would."""
    tree = ast.parse(code, "<python_exec>", "exec")
    last = tree.body[-1] if tree.body else None
    me = threading.current_thread()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _ThisThread(old_out, out, me)
    sys.stderr = _ThisThread(old_err, out, me)
    if deadline:
        sys.settrace(_deadline_tracer(deadline))
    try:
        if isinstance(last, ast.Expr):
            body = ast.Module(body=tree.body[:-1], type_ignores=[])
            exec(compile(body, "<python_exec>", "exec"), namespace)
            value = eval(compile(ast.Expression(last.value),
                                 "<python_exec>", "eval"), namespace)
            if value is not None:
                print(repr(value))
        else:
            exec(compile(tree, "<python_exec>", "exec"), namespace)
    finally:
        sys.settrace(None)
        sys.stdout, sys.stderr = old_out, old_err


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
    from .checked_client import CheckedClient, CheckedSession, settle
    checked = CheckedClient(session.client)
    namespace = {
        "__name__": "__python_exec__",
        "session": CheckedSession(session, checked),
        "engine": session.engine,
        "client": checked,
        "o": o,
    }
    out = io.StringIO()
    outcome: Dict = {}
    limit = timeout_seconds()
    started = time.time()

    def worker():
        with session.lock:
            engine = session.engine
            raw = engine.client
            engine.client = checked    # engine methods write through it too
            try:
                _execute(code, namespace, out,
                         deadline=time.monotonic() + limit)
                outcome["ok"] = True
            except BaseException:
                outcome["ok"] = False
                outcome["error"] = traceback.format_exc()
            finally:
                engine.client = raw
                try:
                    outcome["settled"] = settle(session, checked.writes)
                except Exception as ex:   # never lose the result over this
                    outcome["settled"] = {"systems": [], "notes": [
                        f"Could not mark the changed systems: {ex}"]}

    thread = threading.Thread(target=worker, name="python_exec", daemon=True)
    thread.start()
    thread.join(limit + 0.5)    # the tracer stops Python code at the limit
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
            error = outcome.get("error", "unknown error")
            if "_Stopped: time limit reached" in error:
                error = (f"Stopped after {limit:g} seconds, the time limit. "
                         f"Set OLCA_MCP_PYTHON_TIMEOUT for a longer one.")
                result["timed_out"] = True
            result["error"] = error

    result["writes"] = list(checked.writes)
    settled = outcome.get("settled") or {"systems": [], "notes": []}
    result["systems_out_of_date"] = settled["systems"]
    if settled["notes"]:
        result["notes"] = settled["notes"]
    result["checked_by_olcabasic"] = False
    result["about_the_output"] = (
        "Anything this code calculated itself is not an olcaBASIC result "
        "and has not been through its checks. Say so if you report it. "
        "Results to rely on come from olcabasic_run (CALCULATE and the "
        "rest), which refuses a system changed here until it is built "
        "again and passes VALIDATE.")

    _log({
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "writes": len(checked.writes),
        "why_not_basic": reason,
        "code": code,
        "ok": result["ok"],
        "seconds": seconds,
    })
    return result
