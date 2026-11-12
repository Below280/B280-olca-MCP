"""The v1.16 server: it lists its tools and a call reaches the engine."""

import pytest

from conftest import Harness


@pytest.fixture
def harness(client):
    from b280_olca_mcp.functions import LCAFunctions
    from b280_olca_mcp.server import OpenLCAMCPServer
    server = OpenLCAMCPServer()
    server.client = client
    server.lca = LCAFunctions(client)
    server.setup_handlers()
    return Harness(server)


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


def test_server_lists_the_36_v1_tools(harness):
    tools = harness.list_tools()
    assert set(tools) == V1_TOOLS and len(tools) == 36


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


def test_create_flow_writes_through_the_engine(harness, client):
    import olca_schema as o
    r = harness.call("create_flow", {"name": "MCP flow", "unit": "kg",
                                     "category": "00: Test"})
    assert r["flow_property"] == "Mass"
    assert len(client.by_name(o.Flow, "MCP flow")) == 1


def test_unknown_tool_reports_an_error(harness):
    text = harness.call_text("no_such_tool")
    assert "no_such_tool" in text


def test_not_connected_message(client):
    from b280_olca_mcp.server import OpenLCAMCPServer
    server = OpenLCAMCPServer()
    server.setup_handlers()
    assert "openLCA is not connected" in Harness(server).call_text("database_info")


def test_resources(harness):
    resources = harness.list_resources()
    assert {"lca://knowledge/instructions", "lca://knowledge/ipc-protocol",
            "lca://knowledge/openlca-resources"} <= set(resources)
    assert "JSON-RPC" in harness.read_resource("lca://knowledge/ipc-protocol")
