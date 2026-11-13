"""Shared fixtures for the B280-olca-MCP test suite."""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from fake_client import FakeClient, seed_ecoinvent_like  # noqa: E402


@pytest.fixture
def client() -> FakeClient:
    return seed_ecoinvent_like()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Each test chooses its own flags, and nothing writes to the real
    ~/.olcabasic."""
    for name in ("OLCA_MCP_ALLOW_PYTHON", "OLCA_MCP_LEGACY_TOOLS",
                 "OLCA_MCP_PYTHON_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLCA_MCP_PYTHON_LOG", str(tmp_path / "python_log.jsonl"))


def make_server(client):
    """A server on a Session that uses the fake client. Flags are read
    from the environment when the server is created."""
    from olcabasic import Session
    from b280_olca_mcp.server import OpenLCAMCPServer
    server = OpenLCAMCPServer(Session(client=client))
    server.setup_handlers()
    return server


class Harness:
    """Drives an OpenLCAMCPServer through its registered MCP handlers."""

    def __init__(self, server):
        self.server = server

    def _handler(self, method):
        entry = self.server.server.get_request_handler(method)
        return getattr(entry, "handler", entry)

    def request(self, method, params):
        handler = self._handler(method)
        return asyncio.run(handler(None, params))

    def list_tools(self):
        import mcp.types as types
        result = self.request("tools/list", types.PaginatedRequestParams())
        return {t.name: t for t in result.tools}

    def call_text(self, name, arguments=None) -> str:
        import mcp.types as types
        result = self.request("tools/call", types.CallToolRequestParams(
            name=name, arguments=arguments or {}))
        return "\n".join(c.text for c in result.content)

    def call(self, name, arguments=None):
        """Call a tool and parse the JSON part of its reply."""
        text = self.call_text(name, arguments)
        start = text.find("{")
        return json.loads(text[start:]) if start >= 0 else text

    def list_resources(self):
        import mcp.types as types
        result = self.request("resources/list", types.PaginatedRequestParams())
        return {str(r.uri): r for r in result.resources}

    def read_resource(self, uri) -> str:
        import mcp.types as types
        result = self.request("resources/read",
                              types.ReadResourceRequestParams(uri=uri))
        return result.contents[0].text


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: needs openLCA with its IPC server on localhost:8080 "
        "(run with: pytest -m live)")
    config.addinivalue_line(
        "markers", "slow: a live test that takes several minutes")


def pytest_collection_modifyitems(config, items):
    """Live tests run only when asked for with -m live."""
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live test: run with pytest -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
