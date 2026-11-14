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
    assert r["ok"] and r["output"].strip() == (
        "CheckedSession Engine True olca_schema")


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
    assert set(lines[0]) == {"time", "why_not_basic", "code", "ok", "seconds",
                             "writes"}


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


# ── free, but checked ────────────────────────────────────────

from shortcut_cases import B_STEEL, CALC, SYSTEM, widget   # noqa: E402
from fake_client import STEEL                                # noqa: E402

WIDGET_SYSTEM = widget() + SYSTEM


def _built(harness):
    r = harness.call("olcabasic_run", {"code": WIDGET_SYSTEM})
    assert r["ok"], r


def test_every_result_says_it_is_not_an_olcabasic_result(harness):
    r = run(harness, "1 + 1")
    assert r["checked_by_olcabasic"] is False
    assert "not an olcaBASIC result" in r["about_the_output"]
    assert r["writes"] == [] and r["systems_out_of_date"] == []


def test_a_write_in_a_model_folder_is_made_and_recorded(harness, client):
    r = run(harness, "client.put(o.Actor(id='a1', name='Lab', "
                     "category='00: Test'))")
    assert r["ok"], r
    assert client.by_name(o.Actor, "Lab")
    assert r["writes"] == [{"action": "save", "type": "Actor", "id": "a1",
                            "name": "Lab", "folder": "00: Test"}]


def test_background_data_is_not_edited(harness, client):
    steel = client.by_name(o.Process, STEEL)[0]
    before = steel.to_dict()
    r = run(harness, f"p = client.get(o.Process, '{steel.id}')\n"
                     "p.description = 'changed'\nclient.put(p)")
    assert not r["ok"] and "WriteRefused" in r["error"]
    assert "not in a model folder" in r["error"]
    assert client.by_name(o.Process, STEEL)[0].to_dict() == before
    assert r["writes"] == []


def test_a_new_entity_outside_a_model_folder_is_refused(harness, client):
    r = run(harness, "client.put(o.Actor(name='Loose'))")
    assert not r["ok"] and "writes only in model folders" in r["error"]
    assert client.by_name(o.Actor, "Loose") == []


def test_background_data_is_not_deleted(harness, client):
    steel = client.by_name(o.Process, STEEL)[0]
    r = run(harness, f"client.delete(o.Ref(id='{steel.id}', "
                     "ref_type=o.RefType.Process))")
    assert not r["ok"] and "WriteRefused" in r["error"]
    assert client.by_name(o.Process, STEEL)


def test_raw_json_rpc_writes_are_checked_too(harness, client):
    steel = client.by_name(o.Process, STEEL)[0]
    r = run(harness, f"client.rpc_call('data/delete', {{'@type': 'Process', "
                     f"'@id': '{steel.id}'}})")
    assert not r["ok"] and "WriteRefused" in r["error"]
    r = run(harness, "client.rpc_call('runtime/shutdown', {})")
    assert not r["ok"] and "not open to the Python route" in r["error"]


def test_engine_writes_go_through_the_check(harness, client):
    r = run(harness, "engine.client.put(o.Actor(name='Via engine'))")
    assert not r["ok"] and "writes only in model folders" in r["error"]
    # the engine has its own client back afterwards
    assert type(harness.server.session.engine.client).__name__ != \
        "CheckedClient"


def test_session_run_inside_python_is_not_recorded_again(harness, client):
    r = run(harness, "r = session.run('MAKE ACTOR \"Inside\"\\nEND ACTOR')\n"
                     "print(r.ok)")
    assert r["ok"] and r["output"].strip() == "True", r
    assert r["writes"] == []


def test_a_process_changed_from_python_makes_its_system_out_of_date(
        harness, client):
    _built(harness)
    assert harness.call("olcabasic_run", {"code": CALC})["ok"]
    widget = client.by_name(o.Process, "Widget")[0]
    r = run(harness, f"p = client.get(o.Process, '{widget.id}')\n"
                     "p.exchanges[1].amount = 9\nclient.put(p)")
    assert r["ok"], r
    assert r["systems_out_of_date"] == ["Widget"]
    assert any("out of date" in n for n in r.get("notes", []))
    r = harness.call("olcabasic_run", {"code": CALC})
    assert not r["ok"]
    assert "out of date" in r["errors"][0]["message"]


def test_python_cannot_link_past_a_bridge(harness, client):
    """The case the bridge rule exists for: a direct link to the
    background, made from Python, is refused at CALCULATE."""
    _built(harness)
    code = f'''
system = next(d for d in client.get_descriptors(o.ProductSystem)
              if d.name == "Widget")
s = client.get(o.ProductSystem, system.id)
bridge = next(d for d in client.get_descriptors(o.Process)
              if d.name == "{B_STEEL}")
steel = next(d for d in client.get_descriptors(o.Process)
             if d.name == "{STEEL}")
for link in s.process_links:
    if link.provider and link.provider.id == bridge.id:
        link.provider = o.Ref(id=steel.id, name=steel.name,
                              ref_type=o.RefType.Process)
s.category = None   # openLCA files an IPC-built system in no folder
client.put(s)
'''
    r = run(harness, code)
    assert r["ok"], r
    assert "Widget" in r["systems_out_of_date"]
    r = harness.call("olcabasic_run", {"code": CALC})
    assert not r["ok"]
    assert "no bridge" in r["errors"][0]["message"]


# ── a loop that never ends, and printing from other threads ──

def test_a_loop_that_never_ends_is_stopped_and_frees_the_session(
        harness, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_PYTHON_TIMEOUT", "1")
    r = run(harness, "while True:\n    try:\n        pass\n    except "
                     "Exception:\n        pass")
    assert not r["ok"] and r["timed_out"]
    assert "Stopped after 1 seconds" in r["error"]
    assert harness.call("olcabasic_run", {"code": "PRINT 41 + 1"})["ok"]


def test_only_the_codes_own_printing_is_captured(harness):
    import io
    import sys
    import threading
    seen = io.StringIO()
    old = sys.stdout
    sys.stdout = seen
    try:
        r = run(harness, "import threading, time\n"
                         "print('mine')\n"
                         "t = threading.Thread(target=lambda: print('other'))\n"
                         "t.start(); t.join()\n'done'")
    finally:
        sys.stdout = old
    assert r["ok"] and "mine" in r["output"]
    assert "other" not in r["output"] and "other" in seen.getvalue()
