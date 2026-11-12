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
