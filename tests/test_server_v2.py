"""MCP 2.0: three tools over one olcaBASIC Session."""

import json

import pytest
import olca_schema as o

from conftest import Harness, make_server
from fake_client import ELECTRICITY, STEEL

WIDGET = f'''
CONFIRM DELETE ON
SET PROCESS FOLDER "00: Test"
SET FLOW FOLDER "00: Test"
BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "GB"
END BRIDGE
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
LET elec = 2.5
MAKE PROCESS "Widget"
  OUTPUT MAKE FLOW "Widget", 1, kg, PRODUCT
  INPUT USE PROCESS "BRIDGE | electricity | kWh", elec, kWh
  INPUT USE PROCESS "BRIDGE | steel | kg", 0.8, kg
END PROCESS
SYSTEM "Widget"
'''


@pytest.fixture
def harness(client):
    return Harness(make_server(client))


# ── tool listing, with and without each flag ─────────────────

def names(client):
    return set(Harness(make_server(client)).list_tools())


def test_default_tools(client):
    assert names(client) == {"olcabasic_run", "olcabasic_help", "olcabasic_reset"}


def test_python_flag_adds_python_exec(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", "1")
    assert names(client) == {"olcabasic_run", "olcabasic_help",
                             "olcabasic_reset", "python_exec"}


def test_legacy_flag_adds_the_36_v1_tools(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", "1")
    tools = names(client)
    assert len(tools) == 39 and "python_exec" not in tools
    assert {"olcabasic_run", "create_process", "calculate", "help"} <= tools


def test_both_flags(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", "1")
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", "1")
    assert len(names(client)) == 40


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_flags_need_exactly_1(client, monkeypatch, value):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", value)
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", value)
    assert len(names(client)) == 3


def test_tool_schemas(harness):
    tools = harness.list_tools()
    run = getattr(tools["olcabasic_run"], "input_schema", None) or \
        getattr(tools["olcabasic_run"], "inputSchema")
    assert run["required"] == ["code"]
    assert run["properties"]["dry_run"]["default"] is False
    help_schema = getattr(tools["olcabasic_help"], "input_schema", None) or \
        getattr(tools["olcabasic_help"], "inputSchema")
    assert "required" not in help_schema


def test_run_description_is_a_five_line_summary_pointing_to_help(harness):
    text = harness.list_tools()["olcabasic_run"].description
    lines = text.splitlines()
    assert [l[:2] for l in lines[1:6]] == ["1.", "2.", "3.", "4.", "5."]
    assert "olcabasic_help" in lines[-1] and len(lines) == 7
    assert "—" not in text


# ── olcabasic_run ────────────────────────────────────────────

def test_run_round_trip(harness, client):
    r = harness.call("olcabasic_run", {
        "code": WIDGET + 'CALCULATE "Widget" USING "EF v3.1"'})
    assert r["ok"] and r["errors"] == []
    assert set(r) == {"ok", "text", "data", "errors", "warnings"}
    assert "Process created: Widget" in r["text"]
    assert len(client.by_name(o.Process, "Widget")) == 1
    calc = r["data"][-1]
    assert calc["command"] == "CALCULATE"
    fossil = next(i for i in calc["result"]["impacts"]
                  if i["category"] == "Climate change: fossil")
    assert fossil["amount"] == pytest.approx(2.5 * 0.25 + 0.8 * 2.0)


def test_state_persists_across_calls(harness):
    assert harness.call("olcabasic_run", {"code": "LET mass = 12"})["ok"]
    r = harness.call("olcabasic_run", {"code": "PRINT mass * 2"})
    assert r["text"] == "  24"


def test_one_session_per_server(client):
    a, b = make_server(client), make_server(client)
    Harness(a).call("olcabasic_run", {"code": "LET only_in_a = 1"})
    assert not Harness(b).call("olcabasic_run", {"code": "PRINT only_in_a"})["ok"]
    assert a.session is not b.session


def test_errors_come_back_with_line_and_hint(harness):
    r = harness.call("olcabasic_run", {"code": WIDGET.replace(' LOCATION "GB"', "")})
    assert not r["ok"]
    error = r["errors"][0]
    assert error["line"] == 5 and "matches 3 processes" in error["message"]
    assert "LOCATION" in error["hint"]


def test_method_must_be_named_in_full(harness):
    harness.call("olcabasic_run", {"code": WIDGET})
    r = harness.call("olcabasic_run", {"code": 'CALCULATE "Widget" USING "EF 3.1"'})
    assert '"EF v3.1"' in r["errors"][0]["hint"]


def test_dry_run(harness, client):
    before = len(client.calls)
    r = harness.call("olcabasic_run", {"code": WIDGET, "dry_run": True})
    assert r["ok"] and len(client.calls) == before
    assert r["data"][0]["command"] == "DRY RUN"
    assert client.by_name(o.Process, "Widget") == []


def test_empty_code(harness):
    r = harness.call("olcabasic_run", {"code": "  "})
    assert not r["ok"] and "olcabasic_help" in r["errors"][0]["hint"]


def test_delete_needs_confirm_in_the_program(harness):
    harness.call("olcabasic_run", {"code": WIDGET + "CONFIRM DELETE OFF"})
    r = harness.call("olcabasic_run", {"code": 'DELETE SYSTEM "Widget"'})
    assert not r["ok"]
    assert r["errors"][0]["hint"] == "Put CONFIRM DELETE ON before the DELETE line."


def test_long_replies_drop_the_structured_data(harness, monkeypatch):
    import b280_olca_mcp.server as server
    harness.call("olcabasic_run", {"code": WIDGET})
    monkeypatch.setattr(server, "MAX_REPLY_CHARS", 1500)
    r = harness.call("olcabasic_run", {
        "code": 'CONTRIBUTION "Widget" USING "EF v3.1"'})
    assert r["ok"] and r["data"] == [] and "left out" in r["data_omitted"]
    assert "Contribution analysis" in r["text"]


def test_not_connected(monkeypatch):
    from olcabasic import Session
    from b280_olca_mcp.server import OpenLCAMCPServer
    server = OpenLCAMCPServer(Session(offline=True))
    server.setup_handlers()
    h = Harness(server)
    assert h.call("olcabasic_run", {"code": "PRINT 1 + 1"})["text"] == "  2"
    r = h.call("olcabasic_run", {"code": 'FIND PROCESS "x"'})
    assert r["errors"][0]["message"] == "Not connected to openLCA."
    assert "IPC server" in r["errors"][0]["hint"]


def test_tool_calls_do_not_block_the_event_loop(harness):
    """The handler runs the call in a worker thread."""
    import asyncio
    import mcp.types as types
    handler = harness._handler("tools/call")

    async def scenario():
        ticks = []

        async def ticker():
            for _ in range(3):
                await asyncio.sleep(0)
                ticks.append(1)

        call = handler(None, types.CallToolRequestParams(
            name="olcabasic_run", arguments={"code": "PRINT 1"}))
        result, _ = await asyncio.gather(call, ticker())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert json.loads(result.content[0].text)["ok"] and len(ticks) == 3


# ── olcabasic_help ───────────────────────────────────────────

def test_help_overview_is_short_and_complete(harness):
    text = harness.call_text("olcabasic_help")
    assert len(text) / 3 < 2000
    for needle in ("MAKE PROCESS", 'CALCULATE "system" USING "method"',
                   "CAT", "LS", "CONFIRM DELETE ON"):
        assert needle in text


def test_help_topic_and_command(harness):
    assert "SENSITIVITY ON" in harness.call_text("olcabasic_help",
                                                 {"topic": "scenarios"})
    text = harness.call_text("olcabasic_help", {"topic": "MAKE PROCESS"})
    assert "Example:" in text and "INPUT USE PROCESS" in text
    assert "No help for" in harness.call_text("olcabasic_help", {"topic": "zzz"})


def test_help_is_the_registry(harness):
    from olcabasic import registry
    assert harness.call_text("olcabasic_help") == registry.render_overview()
    assert harness.call_text("olcabasic_help", {"topic": "LS"}) == registry.render("LS")


def test_help_works_without_a_connection():
    from olcabasic import Session
    from b280_olca_mcp.server import OpenLCAMCPServer
    server = OpenLCAMCPServer(Session(offline=True))
    server.setup_handlers()
    assert "NAVIGATION" in Harness(server).call_text("olcabasic_help")


# ── olcabasic_reset ──────────────────────────────────────────

def test_reset_clears_state_not_the_database(harness, client):
    harness.call("olcabasic_run", {"code": WIDGET})
    text = harness.call_text("olcabasic_reset")
    assert "Session state cleared" in text and "not touched" in text
    assert not harness.call("olcabasic_run", {"code": "PRINT elec"})["ok"]
    assert len(client.by_name(o.Process, "Widget")) == 1


# ── tools that are switched off ──────────────────────────────

def test_v1_tool_without_the_flag_says_how_to_get_it(harness):
    r = harness.call("create_flow", {"name": "x", "unit": "kg"})
    assert "Unknown tool" in r["error"]
    assert "OLCA_MCP_LEGACY_TOOLS=1" in r["hint"] and "olcabasic_run" in r["hint"]


def test_python_exec_without_the_flag(harness):
    r = harness.call("python_exec", {"code": "1", "why_not_basic": "x"})
    assert "OLCA_MCP_ALLOW_PYTHON=1" in r["hint"]


# ── resources, instructions, version ─────────────────────────

def test_resources_are_kept(harness):
    resources = harness.list_resources()
    assert set(resources) == {
        "lca://database/info", "lca://knowledge/instructions",
        "lca://knowledge/ipc-protocol", "lca://knowledge/openlca-resources"}
    assert "JSON-RPC" in harness.read_resource("lca://knowledge/ipc-protocol")
    assert "http" in harness.read_resource("lca://knowledge/openlca-resources")
    info = json.loads(harness.read_resource("lca://database/info"))
    assert info["status"] == "connected"


def test_instructions_are_under_150_lines(harness):
    text = harness.read_resource("lca://knowledge/instructions")
    assert len(text.strip().splitlines()) < 150
    assert "—" not in text and "–" not in text


def test_instructions_keep_the_conversation_rules(harness):
    text = harness.read_resource("lca://knowledge/instructions")
    for needle in ("CONVERSATION FIRST", "Never use em dashes",
                   "#2e0a4a, #12ebf2, #ff5c05", "openLCA scales processes",
                   "three tiers", "PubChem", "SAVE PROGRAM",
                   "mcp-feedback@below280.com", "A1 raw material supply",
                   "back up the", "olcabasic_run"):
        assert needle in text, needle


def test_instructions_drop_what_the_language_enforces(harness):
    text = harness.read_resource("lca://knowledge/instructions")
    for gone in ("QUICK TOOL REFERENCE", "create_system", "set_database_family",
                 "list_methods", "validate_system", "Never call create_system "
                 "in parallel", "Step 2: Folder structure"):
        assert gone not in text, gone


def test_server_version_comes_from_the_package(harness):
    import b280_olca_mcp
    options = harness.server.initialization_options()
    assert options.server_version == b280_olca_mcp.__version__ != "1.0.0"


def test_server_starts_without_openlca(monkeypatch):
    import asyncio
    from b280_olca_mcp.server import OpenLCAMCPServer
    monkeypatch.setenv("OLCA_PORT", "1")
    server = OpenLCAMCPServer()
    assert asyncio.run(server.initialise()) is True
    assert server.session is not None and not server.session.connected
    assert server.lca is None
