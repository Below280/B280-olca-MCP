"""MCP 2.0 after the second rebuild: RESULT data, help from the
registry, shorter instructions, terminal-only commands, and tools that
say they skip the rules."""

import json

import pytest

from conftest import Harness, make_server
from test_server_v2 import WIDGET

EF = "EF v3.1"
CALC = f'CALCULATE "Widget" USING "{EF}"\n'
# the Widget with an emission of its own, so the inventory is not empty
WIDGET = WIDGET.replace(
    "END PROCESS",
    '  OUTPUT "Carbon dioxide, fossil", 0.5, kg TO AIR\nEND PROCESS')


@pytest.fixture
def harness(client):
    return Harness(make_server(client))


def run(harness, code, **kw):
    return harness.call("olcabasic_run", dict(code=code, **kw))


# ── structured RESULT data ───────────────────────────────────

QUERIES = [
    "RESULT IMPACTS",
    'RESULT IMPACTS CATEGORY "Climate change"',
    "RESULT CATEGORIES",
    "RESULT PROCESSES",
    "RESULT DEMAND",
    "RESULT FLOWS TOP 5",
    'RESULT FLOWS OF PROCESS "Widget" DIRECT',
    'RESULT CONTRIBUTION BY PROCESS CATEGORY "Climate change"',
    'RESULT CONTRIBUTION BY FLOW CATEGORY "Climate change"',
    'RESULT FLOW "Carbon dioxide, fossil" BY PROCESS',
    'RESULT FACTORS CATEGORY "Climate change"',
    'RESULT INTENSITY OF PROCESS "Widget" CATEGORY "Climate change"',
    "RESULT SCALING",
    "RESULT REQUIREMENTS",
    'RESULT TREE CATEGORY "Climate change" LEVELS 2',
    'RESULT SANKEY CATEGORY "Climate change"',
]


@pytest.mark.parametrize("query", QUERIES)
def test_every_result_query_comes_back_as_data(harness, client, query):
    """The same dictionary the Session gives Python, as JSON."""
    assert run(harness, WIDGET + CALC)["ok"]
    r = run(harness, query)
    assert r["ok"], r["errors"]
    entry = r["data"][-1]
    assert entry["command"] == "RESULT QUERY"
    got = entry["result"]
    assert {"query", "title", "system", "method", "columns", "rows"} <= set(got)
    assert got["system"] == "Widget" and got["method"] == EF
    # ask the Session directly: the same data, through JSON
    direct = harness.server.session.run(query)
    assert direct.ok
    want = json.loads(json.dumps(direct.data[-1]["result"], default=str))
    assert got == want
    for row in got["rows"]:
        assert set(got["columns"]) <= set(row) or got["query"] in (
            "tree", "sankey"), (got["columns"], row)


def test_a_result_stays_open_between_calls_and_is_closed_on_reset(harness,
                                                                  client):
    assert run(harness, WIDGET + CALC)["ok"]
    assert client.undisposed() == 1
    assert run(harness, "RESULT IMPACTS TOP 1")["ok"]
    harness.call_text("olcabasic_reset")
    assert client.undisposed() == 0
    r = run(harness, "RESULT IMPACTS")
    assert not r["ok"] and r["errors"][0]["message"] == "No result is open."


def test_costs_normalised_and_groups_say_what_is_missing(harness):
    assert run(harness, WIDGET + CALC)["ok"]
    for query, hint in (("RESULT COSTS", "WITH COSTS"),
                        ("RESULT NORMALISED", "NW SET"),
                        ("RESULT IMPACTS BY GROUP", "ANALYSIS GROUP")):
        r = run(harness, query)
        assert not r["ok"]
        assert hint in r["errors"][0]["hint"], r["errors"]


def test_a_long_table_is_cut_before_the_data_is_dropped(harness, monkeypatch):
    import b280_olca_mcp.server as server
    assert run(harness, WIDGET + CALC)["ok"]
    monkeypatch.setattr(server, "MAX_REPLY_CHARS", 1900)
    monkeypatch.setattr(server, "MAX_ROWS", 2)
    r = run(harness, "RESULT IMPACTS")
    assert r["ok"]
    got = r["data"][-1]["result"]
    assert len(got["rows"]) == 2 and got["rows_omitted"] >= 1
    assert "TOP n" in r["rows_omitted"]
    assert "data_omitted" not in r


# ── help comes from the registry ─────────────────────────────

def test_help_covers_every_command_of_the_registry(harness):
    from olcabasic import registry
    for command in registry.COMMANDS:
        text = harness.call_text("olcabasic_help", {"topic": command.name})
        assert "No help for" not in text, command.name
        assert command.name in text and "Example:" in text, command.name


def test_help_overview_names_the_new_rules_and_stays_short(harness):
    text = harness.call_text("olcabasic_help")
    assert len(text) / 3 < 2000            # tokens, with room to spare
    for needle in ("goes through a bridge", "differs from the stored process",
                   "out of date", "IGNORE FACTORS", "RESULT"):
        assert needle in text, needle


def test_help_tool_lists_the_topics_of_the_registry(harness):
    from olcabasic import registry
    described = harness.list_tools()["olcabasic_help"].description
    for topic in registry.TOPICS:
        assert topic.lower() in described, topic
        assert "No help for" not in harness.call_text(
            "olcabasic_help", {"topic": topic.lower()})


# ── instructions ─────────────────────────────────────────────

def test_instructions_leave_the_enforced_rules_to_the_language(harness):
    text = harness.read_resource("lca://knowledge/instructions")
    assert len(text.strip().splitlines()) < 150
    assert "There is no override and no way round" in text
    # how to write a bridge, rebuild a system and so on is in the hints
    # and in olcabasic_help, not here
    for gone in ("PROVIDER \"", "END BRIDGE", "DELETE SYSTEM", "END EDIT",
                 "product systems are built one at a time"):
        assert gone not in text, gone


# ── commands that need a person ──────────────────────────────

TERMINAL = "olcaBASIC terminal"


def fixed_amount_process(client):
    """A database process with fixed amounts: one product, one input
    and one emission (what PARAMETERISE ... ALL would rewrite)."""
    import olca_schema as o
    from fake_client import ELECTRICITY
    flows = {f.name: f for f in client.store["Flow"].values()}
    out = client.add_flow("test grid mix", "Energy", category="D:Test supply")
    provider = next(p for p in client.store["Process"].values()
                    if p.name == ELECTRICITY)

    def ref(flow):
        return o.Ref(id=flow.id, name=flow.name, ref_type=o.RefType.Flow)

    kwh, kg = client._unit_ref("kWh"), client._unit_ref("kg")
    proc = o.Process(
        id="mix-0001", name="test grid mix, one source",
        category="D:Test supply", last_internal_id=3,
        process_type=o.ProcessType.UNIT_PROCESS,
        exchanges=[
            o.Exchange(internal_id=1, amount=1.0, is_input=False,
                       flow=ref(out), unit=kwh,
                       is_quantitative_reference=True),
            o.Exchange(internal_id=2, amount=1.0, is_input=True, unit=kwh,
                       flow=ref(flows["test electricity, medium voltage"]),
                       default_provider=o.Ref(
                           id=provider.id, name=provider.name,
                           ref_type=o.RefType.Process)),
            o.Exchange(internal_id=3, amount=0.001, is_input=False,
                       flow=ref(flows["Carbon dioxide, fossil"]), unit=kg),
        ])
    client.put(proc)
    return proc


def test_parameterise_all_is_refused_through_the_mcp(harness, client):
    proc = fixed_amount_process(client)
    before = client.store["Process"][proc.id].to_dict()
    r = run(harness, f'PARAMETERISE PROCESS "{proc.name}" ALL CONFIRM')
    assert not r["ok"]
    error = r["errors"][0]
    assert error["line"] == 1 and TERMINAL in error["hint"]
    assert client.store["Process"][proc.id].to_dict() == before


@pytest.mark.parametrize("code", [
    f'EDIT METHOD "{EF}"\n  DESCRIPTION "changed"\nEND METHOD',
    f'EDIT METHOD "{EF}" CONFIRM\n  DESCRIPTION "changed"\nEND METHOD',
    f'CONFIRM DELETE ON\nDELETE METHOD "{EF}"',
    f'CONFIRM DELETE ON\nDELETE METHOD "{EF}" CONFIRM',
])
def test_a_method_olcabasic_did_not_make_cannot_be_changed_through_the_mcp(
        harness, client, code):
    import olca_schema as o
    before = {m.id: m.to_dict() for m in client.store["ImpactMethod"].values()}
    r = run(harness, code)
    assert not r["ok"]
    assert TERMINAL in r["errors"][0]["hint"], r["errors"]
    assert "cannot be done through a Session or the MCP" in r["errors"][0]["hint"]
    assert {m.id: m.to_dict()
            for m in client.store["ImpactMethod"].values()} == before


def test_shutdown_server_is_refused_through_the_mcp(harness, client):
    r = run(harness, "SHUTDOWN SERVER CONFIRM")
    assert not r["ok"] and TERMINAL in r["errors"][0]["hint"]
    assert client.shut_down is False


def test_the_run_description_says_which_commands_need_the_terminal(harness):
    text = harness.list_tools()["olcabasic_run"].description
    assert "only run in the olcaBASIC terminal" in text
    assert "There is no override" in text


# ── tools that skip the rules say so ─────────────────────────

def test_python_exec_says_how_its_writes_are_checked(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", "1")
    tools = Harness(make_server(client)).list_tools()
    text = tools["python_exec"].description
    assert "Writes are checked" in text and "model folders" in text
    assert "not olcaBASIC results" in text


def test_every_v1_tool_says_it_skips_every_rule(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", "1")
    h = Harness(make_server(client))
    tools = h.list_tools()
    legacy = [t for name, t in tools.items()
              if not name.startswith("olcabasic_")]
    assert len(legacy) == 36
    for tool in legacy:
        assert tool.description.startswith("[v1 tool: it skips every rule"), \
            tool.name
    text = h.read_resource("lca://knowledge/instructions")
    assert "skip every rule olcaBASIC enforces" in text


def test_both_stay_off_by_default(harness):
    assert set(harness.list_tools()) == {
        "olcabasic_run", "olcabasic_help", "olcabasic_reset"}
    text = harness.read_resource("lca://knowledge/instructions")
    assert "The v1 tools skip the rules" in text
    assert "not olcaBASIC results" in text


@pytest.mark.parametrize("args, words", [
    ({"code": 123}, "'code' is text, not int"),
    ({"code": ["PRINT 1"]}, "'code' is text, not list"),
])
def test_arguments_of_the_wrong_kind(client, args, words):
    h = Harness(make_server(client))
    assert words in h.call_text("olcabasic_run", args)


def test_the_unknown_tool_hint_names_python_exec_when_it_is_on(
        client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_ALLOW_PYTHON", "1")
    h = Harness(make_server(client))
    assert "and python_exec" in h.call_text("nope", {})
