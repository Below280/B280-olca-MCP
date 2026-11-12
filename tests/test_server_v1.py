"""The v1 tools, behind OLCA_MCP_LEGACY_TOOLS=1.

Changed on purpose in 2.0.0 (command map section 7): the 36 typed
tools are no longer registered by default. With the flag set they must
behave as they did in v1.16.0.
"""

import pytest

from conftest import Harness, make_server

V1_TOOLS = {
    "database_info", "list_dq_systems", "set_database_family", "list_systems",
    "list_methods", "system_parameters", "global_parameters",
    "create_global_parameter", "edit_flow", "find_unit", "create_flow",
    "create_bridge", "create_process", "edit_process", "delete_entity",
    "extract_model", "audit_model", "validate_system", "create_system",
    "get_system_links", "calculate", "contribution_analysis", "upstream_tree",
    "find_flow_usage", "monte_carlo", "inventory_flows", "data_quality",
    "scenarios", "scenarios_csv", "sensitivity", "sensitivity_csv",
    "search_processes", "search_flows", "chemical_synonyms", "process_details",
    "help",
}


@pytest.fixture
def harness(client, monkeypatch):
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", "1")
    return Harness(make_server(client))


def test_server_lists_the_36_v1_tools(harness):
    tools = harness.list_tools()
    assert V1_TOOLS <= set(tools)
    assert len(V1_TOOLS) == 36


def test_every_tool_has_a_description_and_schema(harness):
    for name, tool in harness.list_tools().items():
        assert tool.description, name
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")
        assert schema["type"] == "object", name


def test_database_info_dispatches_to_the_engine(harness):
    info = harness.call("database_info")
    assert info["status"] == "connected" and info["processes"] == 10
    assert info["database_family"] == "ecoinvent"


def test_search_processes_dispatches_with_arguments(harness):
    r = harness.call("search_processes", {"search_term": "test steel"})
    assert r["total_matches"] == 1
    assert set(r["processes"][0]) == {"id", "name", "category"}


def test_create_flow_writes_through_the_engine(harness, client):
    import olca_schema as o
    r = harness.call("create_flow", {"name": "MCP flow", "unit": "kg",
                                     "category": "00: Test"})
    assert r["flow_property"] == "Mass"
    assert len(client.by_name(o.Flow, "MCP flow")) == 1


def test_calculation_tools_keep_the_presentation_hint(harness, client):
    import olca_schema as o
    from fake_client import STEEL
    steel = client.by_name(o.Process, STEEL)[0]
    harness.call("create_system", {"process": steel.id})
    text = harness.call_text("calculate", {"system": STEEL, "method": "EF v3.1"})
    assert text.startswith("Formatting note:")
    assert "calculate: 6 categories/items calculated" in text


def test_legacy_engine_lookup_still_accepts_part_of_a_method_name(harness, client):
    """The strict method names belong to olcaBASIC; the v1 tools keep
    their v1 behaviour."""
    import olca_schema as o
    from fake_client import STEEL
    steel = client.by_name(o.Process, STEEL)[0]
    harness.call("create_system", {"process": steel.id})
    r = harness.call("calculate", {"system": STEEL, "method": "IPCC 2013"})
    assert r["method"] == "IPCC 2013"


def test_unknown_tool_reports_an_error(harness):
    text = harness.call_text("no_such_tool")
    assert "no_such_tool" in text


def test_help_counts_the_tools_it_has(harness):
    """v1 said "total_tools": 31 whatever the number was."""
    assert harness.call("help")["total_tools"] == 36


def test_not_connected_message(monkeypatch):
    from olcabasic import Session
    from b280_olca_mcp.server import OpenLCAMCPServer
    monkeypatch.setenv("OLCA_MCP_LEGACY_TOOLS", "1")
    server = OpenLCAMCPServer(Session(offline=True))
    server.setup_handlers()
    assert "openLCA is not connected" in Harness(server).call_text("database_info")


def test_resources(harness):
    resources = harness.list_resources()
    assert {"lca://knowledge/instructions", "lca://knowledge/ipc-protocol",
            "lca://knowledge/openlca-resources"} <= set(resources)
    assert "JSON-RPC" in harness.read_resource("lca://knowledge/ipc-protocol")


def test_instructions_gain_the_v1_tool_reference(harness):
    text = harness.read_resource("lca://knowledge/instructions")
    assert "LEGACY TOOLS" in text and "create_bridge" in text
