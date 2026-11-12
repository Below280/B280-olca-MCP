"""
openLCA MCP Server

A thin layer over olcaBASIC. The main tool, olcabasic_run, sends
olcaBASIC code to one persistent Session; olcabasic_help serves the
command reference; olcabasic_reset clears the session's state.

Two environment variables add tools:
  OLCA_MCP_ALLOW_PYTHON=1   registers python_exec
  OLCA_MCP_LEGACY_TOOLS=1   registers the 36 typed tools of v1

Requires openLCA running with its IPC server (port 8080 by default,
OLCA_PORT to change it).
"""

import asyncio
import json
import logging
import os

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent, ToolAnnotations
import mcp.types as types

from olcabasic import Session, registry
from olcabasic.engine.ipc_reference import IPC_PROTOCOL_REFERENCE

from . import __version__
from . import python_exec
from .instructions import ASSISTANT_INSTRUCTIONS
from .legacy_tools import LEGACY_TOOL_REFERENCE, LegacyTools, tool_definitions
from .openlca_resources import OPENLCA_RESOURCES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("openLCA-MCP")

# Results larger than this are returned without the structured data
# (the text output still carries the tables).
MAX_REPLY_CHARS = 60_000
# Tables in a reply that is too long are cut to this many rows first.
MAX_ROWS = 50

RUN_DESCRIPTION = """\
Run olcaBASIC code against openLCA, in a session that keeps its state between calls.
1. One statement per line; names in "double quotes"; blocks end with END <word>.
2. Explore with FIND, SHOW and CAT; build with BRIDGE, MAKE PROCESS and SYSTEM; analyse with CALCULATE "system" USING "method", then RESULT ... on the result it leaves open, CONTRIBUTION, SENSITIVITY.
3. The language refuses anything that would build or calculate a wrong model: a background process used without a bridge, an ambiguous or partial name, a changed block run again, a product system that is out of date or failed VALIDATE, a programme rule broken in an EPD. There is no override. Each error gives the line and a hint that says what to type: do that.
4. A program stops at its first error. dry_run=true checks a program without touching openLCA. Use a FOR loop in one program for batch work.
5. The reply is JSON: ok, text, data (the structured result of each command, RESULT queries included), errors, warnings. DELETE needs CONFIRM DELETE ON. Commands that ask a person (PARAMETERISE ... ALL, changing a method olcaBASIC did not make, SHUTDOWN SERVER) only run in the olcaBASIC terminal.
Call olcabasic_help first for the command list; olcabasic_help with a topic or a command name gives syntax and examples."""

HELP_DESCRIPTION = (
    "The olcaBASIC command reference, straight from the language's command "
    "registry. Without a topic: the rules of the language, the commands "
    "most programs use and the name of every command (short; read it "
    "before the first olcabasic_run). With a topic ("
    + ", ".join(t.lower() for t in registry.TOPICS)
    + ") or a command name (for example 'MAKE PROCESS' or 'RESULT "
    "CONTRIBUTION'): syntax, an example and notes."
)

RESET_DESCRIPTION = (
    "Clear the olcaBASIC session's state: variables, SUBs, folders, "
    "scenarios, last results and CONFIRM DELETE. The openLCA database is "
    "not touched and the connection stays open."
)

PYTHON_DESCRIPTION = (
    "Run Python against the live session, for jobs olcaBASIC has no "
    "command for. It skips every rule olcaBASIC enforces (bridges, exact "
    "names, validation, stale systems, EPD and programme rules): what it "
    "writes to the database is checked by nothing, so tell the user what "
    "you did with it. The namespace holds: session (the olcaBASIC Session; "
    "session.run('...') works), engine (its Engine), client (its "
    "olca_ipc.Client, for raw IPC) and o (olca_schema). It shares the "
    "session's connection and lock. why_not_basic is required: name the "
    "olcaBASIC command that was missing or not enough. Every call is "
    "logged to ~/.olcabasic/python_log.jsonl. Output is cut at 20,000 "
    "characters; the time limit is 300 seconds unless "
    "OLCA_MCP_PYTHON_TIMEOUT says otherwise."
)


def _flag(name: str) -> bool:
    return os.getenv(name) == "1"


class OpenLCAMCPServer:

    def __init__(self, session: Session = None):
        self.server = Server("openLCA-MCP")
        self.session = session
        self.allow_python = python_exec.enabled()
        self.legacy_enabled = _flag("OLCA_MCP_LEGACY_TOOLS")
        self.legacy = LegacyTools(lambda: self.lca)

    # ── the session ──────────────────────────────────────────

    @property
    def lca(self):
        """The engine (the name the v1 server used)."""
        return self.session.engine if self.session is not None else None

    @property
    def client(self):
        return self.session.client if self.session is not None else None

    async def initialise(self) -> bool:
        """Create the one Session of this server process. The server
        starts even if openLCA is not answering yet: the Session tries
        again on each run."""
        port = int(os.getenv("OLCA_PORT", "8080"))
        logger.info(f"Connecting to openLCA on port {port}")
        self.session = Session(port=port)
        if self.session.connected:
            info = self.session.engine.get_database_info()
            logger.info(f"Connected: {info.get('processes', '?')} processes")
        else:
            logger.warning(
                "openLCA is not answering on port %s. The server is running; "
                "start the IPC server in openLCA and try again.", port)
        return True

    # ── tools ────────────────────────────────────────────────

    def tool_list(self) -> list:
        tools = [
            Tool(
                name="olcabasic_run",
                description=RUN_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "olcaBASIC program text, one "
                                           "statement per line",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "default": False,
                            "description": "Parse and check the program "
                                           "without touching openLCA",
                        },
                    },
                    "required": ["code"],
                },
                annotations=ToolAnnotations(
                    readOnlyHint=False, destructiveHint=True,
                    idempotentHint=False, openWorldHint=False),
            ),
            Tool(
                name="olcabasic_help",
                description=HELP_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "A topic or a command name "
                                           "(optional)",
                        },
                    },
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False,
                    idempotentHint=True, openWorldHint=False),
            ),
            Tool(
                name="olcabasic_reset",
                description=RESET_DESCRIPTION,
                inputSchema={"type": "object", "properties": {}},
                annotations=ToolAnnotations(
                    readOnlyHint=False, destructiveHint=False,
                    idempotentHint=True, openWorldHint=False),
            ),
        ]
        if self.allow_python:
            tools.append(Tool(
                name="python_exec",
                description=PYTHON_DESCRIPTION,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string",
                                 "description": "Python source"},
                        "why_not_basic": {
                            "type": "string",
                            "description": "The olcaBASIC command that was "
                                           "missing or not enough",
                        },
                    },
                    "required": ["code", "why_not_basic"],
                },
                annotations=ToolAnnotations(
                    readOnlyHint=False, destructiveHint=True,
                    idempotentHint=False, openWorldHint=True),
            ))
        if self.legacy_enabled:
            tools.extend(tool_definitions())
        return tools

    def instructions(self) -> str:
        text = ASSISTANT_INSTRUCTIONS
        if self.legacy_enabled:
            text += LEGACY_TOOL_REFERENCE
        return text

    # ── tool calls ───────────────────────────────────────────

    def call_tool(self, name: str, arguments: dict) -> str:
        """Run a tool and return the text of its reply."""
        arguments = arguments or {}
        if name == "olcabasic_help":
            return self._help(arguments.get("topic") or "")
        if self.session is None:
            return ("The server is still starting and has no session yet. "
                    "Try again in a moment.")
        if name == "olcabasic_run":
            return self._run(arguments.get("code", ""),
                             bool(arguments.get("dry_run", False)))
        if name == "olcabasic_reset":
            self.session.reset()
            return ("Session state cleared: variables, SUBs, folders, "
                    "scenarios, last results, the active EPD and CONFIRM "
                    "DELETE. The database was not touched.")
        if name == "python_exec" and self.allow_python:
            result = python_exec.run(self.session, arguments.get("code", ""),
                                     arguments.get("why_not_basic", ""))
            return json.dumps(result, indent=1, default=str)
        if self.legacy_enabled and name in self.legacy.names():
            with self.session.lock:
                return self.legacy.call(name, arguments)
        return json.dumps({
            "error": f"Unknown tool: {name}",
            "hint": self._unknown_tool_hint(name),
        })

    def _unknown_tool_hint(self, name: str) -> str:
        if name == "python_exec":
            return ("python_exec is switched off. The user can switch it on "
                    "by setting OLCA_MCP_ALLOW_PYTHON=1 for the server.")
        if name in self.legacy.names():
            return (f"'{name}' is a v1 tool. Use olcabasic_run (see "
                    f"olcabasic_help), or set OLCA_MCP_LEGACY_TOOLS=1 for "
                    f"the server to get the v1 tools back.")
        return "The tools are olcabasic_run, olcabasic_help and olcabasic_reset."

    def _run(self, code: str, dry_run: bool) -> str:
        if not (code or "").strip():
            return json.dumps({
                "ok": False, "text": "", "data": [], "warnings": [],
                "errors": [{"line": 0, "message": "No code was given.",
                            "hint": "Pass olcaBASIC code in 'code'. "
                                    "olcabasic_help lists the commands."}],
            }, indent=1)
        result = self.session.run(code, dry_run=dry_run).to_dict()
        text = json.dumps(result, indent=1, default=str)
        if len(text) > MAX_REPLY_CHARS:
            # First shorten the long tables (RESULT queries can return
            # thousands of rows); the shape stays the one the Session
            # gives, with rows_omitted saying how many were cut.
            cut = 0
            for entry in result["data"]:
                inner = entry.get("result")
                rows = inner.get("rows") if isinstance(inner, dict) else None
                if isinstance(rows, list) and len(rows) > MAX_ROWS:
                    inner["rows_omitted"] = len(rows) - MAX_ROWS
                    inner["rows"] = rows[:MAX_ROWS]
                    cut += 1
            if cut:
                result["rows_omitted"] = (
                    f"{cut} table(s) were cut to their first {MAX_ROWS} "
                    f"rows to keep the reply short. Add TOP n or a filter "
                    f"(CATEGORY, FLOW, OF PROCESS) to the query, or SAVE "
                    f"\"file.csv\" for the whole table.")
                text = json.dumps(result, indent=1, default=str)
        if len(text) > MAX_REPLY_CHARS:
            kept = len(result["data"])
            result["data"] = []
            result["data_omitted"] = (
                f"{kept} structured result(s) were left out because the "
                f"reply would be too long. The text has the tables. Ask for "
                f"less at a time (TOP n, CATEGORIES, MAX n, one command per "
                f"call) to get the data.")
            text = json.dumps(result, indent=1, default=str)
            if len(text) > MAX_REPLY_CHARS:
                result["text"] = (result["text"][:MAX_REPLY_CHARS // 2]
                                  + "\n... [text truncated]")
                text = json.dumps(result, indent=1, default=str)
        return text

    @staticmethod
    def _help(topic: str) -> str:
        topic = (topic or "").strip()
        if not topic:
            return registry.render_overview()
        return registry.render(topic)

    # ── MCP handlers ─────────────────────────────────────────

    def setup_handlers(self):

        async def handle_list_resources(ctx, params):
            return types.ListResourcesResult(resources=[
                Resource(
                    uri="lca://database/info",
                    name="Database Information",
                    description="Overview of the connected openLCA database",
                    mimeType="application/json",
                ),
                Resource(
                    uri="lca://knowledge/instructions",
                    name="LCA Assistant Instructions",
                    description=(
                        "IMPORTANT: Read this first. How to work with the "
                        "user: when to ask, how to present results, how to "
                        "check a model. Short; the rules of the language "
                        "itself are in olcabasic_help."
                    ),
                    mimeType="text/plain",
                ),
                Resource(
                    uri="lca://knowledge/ipc-protocol",
                    name="openLCA IPC Protocol Reference",
                    description=(
                        "Complete JSON-RPC protocol specification for openLCA IPC. "
                        "All 60 methods with parameter formats, response structures, "
                        "curl examples, and known gotchas. Use this to help users "
                        "connect to openLCA from any programming language."
                    ),
                    mimeType="text/plain",
                ),
                Resource(
                    uri="lca://knowledge/openlca-resources",
                    name="openLCA Resources",
                    description=(
                        "Links to databases, documentation, forums, tutorials, "
                        "and training courses. Use when someone asks where to "
                        "learn openLCA, find data, or get help."
                    ),
                    mimeType="text/plain",
                ),
            ])

        self.server.add_request_handler(
            "resources/list", types.PaginatedRequestParams, handle_list_resources
        )

        async def handle_read_resource(ctx, params):
            uri = str(params.uri)

            if uri == "lca://database/info":
                if self.lca:
                    text = json.dumps(self.lca.get_database_info(), indent=2)
                else:
                    text = json.dumps({"status": "not connected"}, indent=2)
            elif uri == "lca://knowledge/instructions":
                text = self.instructions()
            elif uri == "lca://knowledge/ipc-protocol":
                text = IPC_PROTOCOL_REFERENCE
            elif uri == "lca://knowledge/openlca-resources":
                text = OPENLCA_RESOURCES
            else:
                text = f"Unknown resource: {uri}"

            return types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        uri=params.uri, mimeType="text/plain", text=text
                    )
                ]
            )

        self.server.add_request_handler(
            "resources/read", types.ReadResourceRequestParams, handle_read_resource
        )

        async def handle_list_tools(ctx, params):
            return types.ListToolsResult(tools=self.tool_list())

        self.server.add_request_handler(
            "tools/list", types.PaginatedRequestParams, handle_list_tools
        )

        async def handle_call_tool(ctx, params):
            name = params.name
            arguments = params.arguments or {}
            try:
                # openLCA calls can take minutes: keep the event loop free.
                # The Session lock keeps the calls themselves in order.
                text = await asyncio.to_thread(self.call_tool, name, arguments)
            except Exception as e:
                logger.error(f"Tool {name} failed: {e}", exc_info=True)
                text = json.dumps({"error": str(e), "tool": name})
            return types.CallToolResult(
                content=[TextContent(type="text", text=text)])

        self.server.add_request_handler(
            "tools/call", types.CallToolRequestParams, handle_call_tool
        )

    # ── server lifecycle ─────────────────────────────────────

    def initialization_options(self) -> InitializationOptions:
        return InitializationOptions(
            server_name="openLCA-MCP",
            server_version=__version__,
            capabilities=self.server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )

    async def run(self):
        await self.initialise()
        self.setup_handlers()
        logger.info("openLCA MCP server %s ready (%d tools)", __version__,
                    len(self.tool_list()))

        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.initialization_options(),
            )


def main():
    server = OpenLCAMCPServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
