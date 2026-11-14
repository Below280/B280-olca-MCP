# Agent test: a real Claude working through the MCP

The unit and live tests call the tools directly. This test puts a Claude
model in front of the MCP with ordinary LCA tasks and tasks that tempt it
to cut corners, and reads what it did.

1. Open a database in openLCA and start its IPC server.
2. Start the host, which runs one `OpenLCAMCPServer` (python_exec and the
   v1 tools off) and answers tool calls that arrive as files:

       set OLCA_AGENT_DIR=C:\olca_agent_test
       set OLCA_AGENT_CODE=<folder holding olcaBASIC and B280-olca-MCP>
       python mcp_host.py

   It writes `tools.json` (the server instructions and tool descriptions
   a client receives) and logs every call and reply to `calls.jsonl`.
   A file called `STOP` ends it after the call in hand.
3. Give an agent `AGENT_PROMPT.md`. It calls the tools only through
   `agent_call.py` (`call("olcabasic_run", {"code": ...})`).
4. Read its report, and check `calls.jsonl` for anything it did not
   mention.

First run, 14/11/2026 (openLCA 2.7.0, ecoinvent-based EN 15804 database):
it found a bridge in kg accepted onto a provider in m3 (1 kg taken as
1 m3), `INPUT USE FLOW` going round the bridge rule, `LOCATION "GB"`
failing, an auto-parameter left behind by UPDATE INPUT, and DELETE FLOW
reading all 26,500 processes (an hour a flow). All fixed in olcaBASIC
0.4.0.
