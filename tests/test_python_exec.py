"""python_exec: opt-in, logged, limited, and inside the Session lock."""

import json
import threading
import time

import pytest
import olca_schema as o

from conftest import Harness, make_server
from b280_olca_mcp import python_exec


@pytest.fixture
def harness(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", "1")
    return Harness(make_server(client))


def run(harness, code, why="no command lists flow properties"):
    return harness.call("python_exec", {"code": code, "why_not_basic": why})


def log_lines():
    path = python_exec.log_path()
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_not_registered_by_default(client):
    assert "python_exec" not in Harness(make_server(client)).list_tools()


def test_schema_requires_both_arguments(harness):
    tool = harness.list_tools()["python_exec"]
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")
    assert schema["required"] == ["code", "why_not_basic"]


@pytest.mark.parametrize("why", ["", "   ", None])
def test_refused_without_why_not_basic(harness, client, why):
    args = {"code": "client.put(o.Actor(name='should not exist'))"}
    if why is not None:
        args["why_not_basic"] = why
    r = harness.call("python_exec", args)
    assert not r["ok"] and "why_not_basic is required" in r["error"]
    assert "olcabasic_run" in r["error"]
    assert client.by_name(o.Actor, "should not exist") == []
    assert log_lines() == []


def test_namespace(harness, client):
    r = run(harness, "print(type(session).__name__, type(engine).__name__, "
                     "client is session.client, o.__name__)")
    assert r["ok"] and r["output"].strip() == "Session Engine True olca_schema"


def test_last_expression_is_shown(harness):
    r = run(harness, "x = 2\nx * 21")
    assert r["ok"] and r["output"].strip() == "42"


def test_session_run_works_from_python(harness):
    harness.call("olcabasic_run", {"code": "LET shared = 7"})
    r = run(harness, "r = session.run('PRINT shared * 2')\nprint(r.text.strip())")
    assert r["ok"] and r["output"].strip() == "14"


def test_raw_client_access(harness, client):
    r = run(harness, "len(client.get_descriptors(o.FlowProperty))")
    assert r["output"].strip() == str(len(client.store["FlowProperty"]))


def test_exception_comes_back_as_a_traceback(harness):
    r = run(harness, "print('before')\n1 / 0")
    assert not r["ok"] and "ZeroDivisionError" in r["error"]
    assert "Traceback" in r["error"] and r["output"].strip() == "before"


def test_syntax_error(harness):
    r = run(harness, "def broken(:")
    assert not r["ok"] and "SyntaxError" in r["error"]


def test_output_is_truncated_at_20000_characters(harness):
    r = run(harness, "print('x' * 50000)")
    assert r["ok"] and r["truncated"]
    assert r["output"].startswith("x" * 20000)
    assert "output truncated: 30001 more characters" in r["output"]
    assert len(r["output"]) < 20100


def test_every_call_is_logged(harness):
    run(harness, "print('one')", why="FIND has no flow property search")
    run(harness, "1 / 0", why="needed a raw IPC call")
    lines = log_lines()
    assert len(lines) == 2
    assert lines[0]["why_not_basic"] == "FIND has no flow property search"
    assert lines[0]["code"] == "print('one')" and lines[0]["ok"] is True
    assert lines[1]["ok"] is False
    assert set(lines[0]) == {"time", "why_not_basic", "code", "ok", "seconds"}


def test_default_log_is_in_the_home_folder(monkeypatch):
    monkeypatch.delenv("OLCA_MCP_PYTHON_LOG")
    path = python_exec.log_path()
    assert path.name == "python_log.jsonl" and path.parent.name == ".olcabasic"


def test_timeout(harness, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_PYTHON_TIMEOUT", "0.2")
    started = time.time()
    r = run(harness, "import time\nprint('started')\ntime.sleep(1.5)")
    assert time.time() - started < 1.2
    assert not r["ok"] and r["timed_out"]
    assert "Timed out after 0.2 seconds" in r["error"]
    assert r["output"].strip() == "started"
    time.sleep(1.6)          # let the worker finish and release the lock
    assert harness.server.session.lock.acquire(timeout=2)
    harness.server.session.lock.release()


def test_timeout_default_and_bad_values(monkeypatch):
    assert python_exec.timeout_seconds() == 300
    monkeypatch.setenv("OLCA_MCP_PYTHON_TIMEOUT", "45")
    assert python_exec.timeout_seconds() == 45
    monkeypatch.setenv("OLCA_MCP_PYTHON_TIMEOUT", "nonsense")
    assert python_exec.timeout_seconds() == 300


def test_shares_the_session_lock(harness):
    """While python_exec runs, olcabasic_run has to wait: the BASIC
    program sees the variable the Python code set at its very end."""
    session = harness.server.session
    code = "import time\ntime.sleep(0.3)\nsession.run('LET marker = 1')"
    t = threading.Thread(target=run, args=(harness, code))
    t.start()
    time.sleep(0.1)
    assert not session.lock.acquire(blocking=False)      # held by python_exec
    r = harness.call("olcabasic_run", {"code": "PRINT marker"})
    t.join()
    assert r["ok"] and r["text"].strip() == "1"


def test_stdout_is_captured_not_printed(harness, capsys):
    run(harness, "import sys\nprint('to stdout')\nprint('to stderr', file=sys.stderr)")
    captured = capsys.readouterr()
    assert "to stdout" not in captured.out and "to stderr" not in captured.err
