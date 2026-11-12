# Moving from 1.x to 2.0

Version 2.0 turns the package inside out. The engine that talks to openLCA moved into [olcaBASIC](https://github.com/Below280/olcaBASIC) 0.4.0, and this server now runs olcaBASIC programs instead of offering one tool per operation.

This page is for two groups: people whose prompts, clients or scripts call the 36 tools of version 1, and people who import `LCAFunctions` from this package.

## If you only chat with an assistant

Nothing to change. Upgrade, restart the MCP client, and ask as before. The assistant now writes olcaBASIC and the server runs it. A few answers will differ, because rules that were advice are now enforced: see "Behaviour changes" in the [release notes](releases/release-notes-v2.0.0.md).

Three things you may notice:

- **Bridges.** A process of yours no longer uses a background dataset directly. The assistant writes a bridge for each one (`BRIDGE | Cement | kg`), and your processes use the bridge. Models built before 2.0 keep working as they are; new inputs go through bridges.
- **Rebuilding after a change.** After a process is edited, the product systems that hold it have to be built again and validated before anything is calculated. The assistant will do it, and it takes as long as building the system did the first time.
- **Refusals.** When the assistant reports that olcaBASIC refused something, there is no setting that turns the refusal off. The hint says what the model needs.

```
pip install --upgrade b280-olca-mcp
```

Python 3.11 or later is needed (`olca-ipc` needs it; 3.10 never worked in practice).

## If you call the version 1 tools

There are two routes.

**Keep them for now.** Set `OLCA_MCP_LEGACY_TOOLS=1` in the server's environment. All 36 tools come back with the same names, arguments and results, alongside the three new ones. They run on the same engine as before; nothing about their behaviour was changed.

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["-m", "b280_olca_mcp"],
      "env": { "OLCA_PORT": "8080", "OLCA_MCP_LEGACY_TOOLS": "1" }
    }
  }
}
```

Without the flag, a call to an old tool name is answered with an error that says how to switch it on.

**Move to `olcabasic_run`.** Each tool has an olcaBASIC command. Send the command as the `code` argument; several commands can go in one call, one per line.

| Version 1 tool | olcaBASIC |
|---|---|
| `database_info` | `PRINT DATABASE` |
| `set_database_family` | `DATABASE FAMILY "ecoinvent"` |
| `list_dq_systems` | `PRINT DQ SYSTEMS` |
| `list_systems` | `FIND SYSTEM "text"` |
| `list_methods` | `FIND METHOD "text"` |
| `search_processes` | `FIND PROCESS "text" [AT "GB"] [IN "folder"]` |
| `search_flows` | `FIND FLOW "text" [IN "folder"]` |
| `chemical_synonyms` | `FIND CHEMICAL "name"` |
| `process_details` | `SHOW PROCESS "name"` |
| `system_parameters` | `SHOW SYSTEM "name" PARAMS` |
| `global_parameters` | `SHOW GLOBAL PARAMS ["text"]` |
| `find_unit` | `FIND UNIT "kWh"` |
| `get_system_links` | `SHOW SYSTEM "name" LINKS ["text"]` |
| `data_quality` | `SHOW PROCESS "name" QUALITY` |
| `find_flow_usage` | `SHOW FLOW "name" USAGE [LIMIT n]` |
| `create_flow` | `MAKE FLOW "name", unit, PRODUCT` |
| `edit_flow` | `EDIT FLOW "name" ... END EDIT` |
| `create_bridge` | `BRIDGE "name", unit ... PROVIDER "uuid" ... END BRIDGE` |
| `create_process` | `MAKE PROCESS "name" ... END PROCESS` |
| `edit_process` | `EDIT PROCESS "name" ... END EDIT` |
| `create_global_parameter` | `LET name = value` at the top level (it becomes a global parameter when a process uses it), `UPDATE PARAMETER` to change one |
| `create_system` | `SYSTEM "process name"` |
| `delete_entity` | `CONFIRM DELETE ON`, then `DELETE PROCESS "name"`, `DELETE SYSTEM "name"` or `DELETE FLOW "name"` |
| `validate_system` | `VALIDATE "system"` |
| `audit_model` | `AUDIT FOLDER "folder"` |
| `extract_model` | `EXTRACT FOLDER "folder"` |
| `calculate` | `CALCULATE "system" USING "method"` |
| `contribution_analysis` | `CONTRIBUTION "system" USING "method" TOP 10` |
| `upstream_tree` | `TREE "system" USING "method" CATEGORY "name" LEVELS 3 TOP 5` |
| `monte_carlo` | `MONTECARLO "system" USING "method" RUNS 1000` |
| `inventory_flows` | `INVENTORY "system" USING "method" MAX 50` |
| `scenarios` | `SCENARIO "name" ... END SCENARIO`, then `RUN SCENARIOS ON "system" USING "method"` |
| `scenarios_csv` | `RUN SCENARIOS ON "system" USING "method" FROM CSV "file.csv"` |
| `sensitivity` | `SENSITIVITY ON "system" USING "method" BY 10% ... VARY name ... END SENSITIVITY` |
| `sensitivity_csv` | the same block with `FROM "file.csv"` in place of `VARY` |
| `help` | the `olcabasic_help` tool |

New in olcaBASIC, with no version 1 tool: the EPD commands (`olcabasic_help` topic `epd`), `PARAMETERISE PROCESS`, `MOVE`, `LINK`, `CHECK`, `SAVE PROGRAM`.

`olcabasic_help` with a command name (`MAKE PROCESS`, `SENSITIVITY`) gives the full syntax and an example of each.

The reply is JSON with five fields:

```json
{
  "ok": true,
  "text": "what a terminal would have shown",
  "data": [{"command": "CALCULATE", "line": 1, "call": "calculate", "result": {"impacts": []}}],
  "errors": [],
  "warnings": []
}
```

`data[n].result` is what the old tool of the same name returned, so code that read a tool's result reads the same structure from there. When `ok` is false, `errors` holds the line, the message and a hint that says what to type instead. The program stops at its first error.

Things a tool call could not do and a program can: several steps in one call, loops over inputs (`FOR EACH`), variables that persist between calls, and `dry_run` to check a program before it touches the database.

## If you import `LCAFunctions`

The class moved and was renamed. The old import still works and warns:

```python
from b280_olca_mcp.functions import LCAFunctions   # DeprecationWarning from 2.0
```

Change it to:

```python
from olca_ipc import Client
from olcabasic.engine import Engine

engine = Engine(Client(8080))
engine.search_processes("cement", limit=5)
```

`Engine` is the same class: same public methods, same arguments, same return shapes. `olcabasic.engine.LCAFunctions` is kept as an alias. If your code only needs the engine, you can depend on `olcabasic` alone and drop `b280-olca-mcp` and `mcp`.

Two things to check:

- Methods whose names started with an underscore were private and some have moved or gained public names (`get_descriptors`, `find_process`, `find_system`, `find_method`, `clear_caches`). Code that reached into private methods needs a look.
- `b280_olca_mcp.ipc_reference` re-exports `olcabasic.engine.ipc_reference`.

For new code, `olcabasic.Session` is usually the better entry point. It runs programs, keeps state, serialises access to openLCA and returns structured results:

```python
from olcabasic import Session

s = Session(port=8080)
r = s.run('CALCULATE "Concrete block" USING "EF v3.1"')
if r.ok:
    impacts = r.data[-1]["result"]["impacts"]
```

## If you need Python inside the MCP

`OLCA_MCP_ALLOW_PYTHON=1` adds a `python_exec` tool with `session`, `engine` and `client` in scope. It is off by default because it lets the assistant run code on your machine with your rights. Every call has to say why olcaBASIC could not do the job, and is logged to `~/.olcabasic/python_log.jsonl`.
