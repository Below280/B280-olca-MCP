"""
Live tests of the MCP server: the tools driven through the MCP handlers
against a real openLCA, as an MCP client would call them.

    pytest -m live

One small model in the folder "00: olcaBASIC MCP live": a product that
takes electricity through a bridge. The electricity provider is taken
from the private live baseline (REBUILD_PLAN_2), so nothing about the
licensed database is written here. The system and the process are
deleted at the end; the bridge and the flow stay and are reused.
"""

import json
import os
import re
from pathlib import Path

import pytest

from conftest import Harness

pytestmark = pytest.mark.live

FOLDER = "00: olcaBASIC MCP live"
NAME = "olcaBASIC MCP live product"
BRIDGE_SHORT = "olcaBASIC MCP live electricity"
BRIDGE = f"BRIDGE | {BRIDGE_SHORT} | kWh"


def _baselines():
    env = os.getenv("OLCA_LIVE_BASELINE")
    paths = [Path(env)] if env else []
    for parent in Path(__file__).resolve().parents:
        paths += [parent / "REBUILD_PLAN" / "live_baseline.json"]
        paths += sorted((parent / "REBUILD_PLAN_2").glob("live_baseline_*.json")) \
            if (parent / "REBUILD_PLAN_2").is_dir() else []
    found = [json.loads(p.read_text(encoding="utf-8"))
             for p in paths if p.exists()]
    if not found:
        pytest.skip("no live baseline: set OLCA_LIVE_BASELINE")
    return found


@pytest.fixture(scope="module")
def harness():
    os.environ["OLCA_MCP_ALLOW_PYTHON"] = "1"
    os.environ.setdefault(
        "OLCA_MCP_PYTHON_LOG",
        str(Path(__file__).with_name("python_log_live.jsonl")))
    from olcabasic import Session
    from b280_olca_mcp.server import OpenLCAMCPServer
    session = Session(port=int(os.getenv("OLCA_PORT", "8080")))
    if not session.connected:
        pytest.skip("openLCA's IPC server is not answering")
    server = OpenLCAMCPServer(session)
    server.setup_handlers()
    yield Harness(server)
    session.close()


@pytest.fixture(scope="module")
def model(harness):
    # the baseline of the database that is open: its provider is there
    for data in _baselines():
        m = re.search(r'USE PROCESS "([^"]+)".*kWh LOCATION "([^"]+)"',
                      data["program_template"])
        if not m:
            continue
        provider, location = m.groups()
        hit = run(harness, f'FIND PROCESS "{provider}" LOCATION "{location}"')
        if hit["ok"] and hit["data"][-1]["result"].get("count"):
            break
    else:
        pytest.skip("no live baseline fits the database that is open")
    method = next(iter(data["calculate"]))
    cleanup = (f'CLOSE RESULT ALL\nCONFIRM DELETE ON\n'
               f'DELETE SYSTEM "{NAME}"\nDELETE PROCESS "{NAME}"')
    run(harness, cleanup)
    program = f'''DATABASE FAMILY "ecoinvent"
SET PROCESS FOLDER "{FOLDER}"
SET FLOW FOLDER "{FOLDER}"
BRIDGE "{BRIDGE_SHORT}", kWh
  PROVIDER "{provider}" LOCATION "{location}"
END BRIDGE
MAKE PROCESS "{NAME}"
  OUTPUT MAKE FLOW "{NAME}", 1, kg, PRODUCT
  INPUT USE PROCESS "{BRIDGE}", 2, kWh
END PROCESS
SYSTEM "{NAME}"
VALIDATE "{NAME}"
'''
    ok(harness, program)
    yield {"provider": provider, "location": location, "method": method}
    run(harness, cleanup)


def run(harness, code):
    return harness.call("olcabasic_run", {"code": code})


def ok(harness, code):
    r = run(harness, code)
    assert r["ok"], json.dumps(r, indent=1)[:3000]
    return r


def py(harness, code, why="live test of the Python route"):
    return harness.call("python_exec", {"code": code, "why_not_basic": why})


def calc(model):
    return f'CALCULATE "{NAME}" USING "{model["method"]}"'


# ── the tools are there and answer ───────────────────────────

def test_the_tools(harness):
    assert set(harness.list_tools()) >= {
        "olcabasic_run", "olcabasic_help", "olcabasic_reset", "python_exec"}


def test_help(harness):
    text = harness.call_text("olcabasic_help", {"topic": "CALCULATE"})
    assert "CALCULATE" in text and "USING" in text


def test_find_in_the_background(harness, model):
    r = ok(harness, f'FIND PROCESS "{model["provider"]}"')
    assert model["provider"] in json.dumps(r)


# ── the model, and the rules through the MCP ─────────────────

def test_calculate(harness, model):
    r = ok(harness, calc(model) + "\nCLOSE RESULT ALL")
    assert "impacts" in json.dumps(r)


def test_a_background_input_without_a_bridge_is_refused(harness, model):
    r = run(harness, f'''SET PROCESS FOLDER "{FOLDER}"
MAKE PROCESS "olcaBASIC MCP live shortcut"
  OUTPUT MAKE FLOW "{NAME}", 1, kg, PRODUCT
  INPUT USE PROCESS "{model["provider"]}", 2, kWh LOCATION "{model["location"]}"
END PROCESS''')
    assert not r["ok"]
    assert "bridge" in (r["errors"][0]["message"] + r["errors"][0]["hint"]).lower()
    found = run(harness, 'FIND PROCESS "olcaBASIC MCP live shortcut"')
    assert found["data"][-1]["result"]["count"] == 0


def test_reset_does_not_get_round_the_rules(harness, model):
    harness.call("olcabasic_reset", {})
    r = ok(harness, calc(model) + "\nCLOSE RESULT ALL")
    assert "VALIDATE ran first" in r["text"]


# ── the Python route: free to read, checked when it writes ───

def test_python_reads_freely(harness, model):
    r = py(harness, "len(client.get_descriptors(o.ImpactMethod))")
    assert r["ok"] and int(r["output"].strip()) > 0
    assert r["checked_by_olcabasic"] is False and r["writes"] == []


def test_python_cannot_edit_background_data(harness, model):
    r = py(harness, f'''p = next(d for d in client.get_descriptors(o.Process)
         if d.name == "{model["provider"]}")
full = client.get(o.Process, p.id)
full.description = (full.description or "") + " edited"
client.put(full)''')
    assert not r["ok"] and "WriteRefused" in r["error"], r
    assert r["writes"] == []


@pytest.mark.slow
def test_python_linking_past_the_bridge_is_refused_at_calculate(harness,
                                                                model):
    r = py(harness, f'''sd = next(d for d in client.get_descriptors(o.ProductSystem)
          if d.name == "{NAME}")
s = client.get(o.ProductSystem, sd.id)
bridge = next(d for d in client.get_descriptors(o.Process)
              if d.name == "{BRIDGE}")
target = None
for link in s.process_links:
    if link.process.id == bridge.id:
        target = link.provider
        break
n = 0
for link in s.process_links:
    if link.provider and link.provider.id == bridge.id:
        link.provider = target
        n += 1
client.put(s)
n''')
    assert r["ok"], r
    assert NAME in r["systems_out_of_date"]
    refused = run(harness, calc(model))
    assert not refused["ok"]
    assert "no bridge" in refused["errors"][0]["message"], refused
    # built again from the processes, it is bridged and calculates
    ok(harness, f'CLOSE RESULT ALL\nCONFIRM DELETE ON\nDELETE SYSTEM "{NAME}"\n'
                f'SYSTEM "{NAME}"\nVALIDATE "{NAME}"\n' + calc(model)
                + "\nCLOSE RESULT ALL")
