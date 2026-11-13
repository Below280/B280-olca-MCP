# openLCA MCP Server

An MCP (Model Context Protocol) server that connects AI assistants to a running openLCA instance. Developed and tested with Claude Desktop; compatible with any MCP client that supports stdio transport. Built by [Below280](https://below280.com), the UK partner for openLCA.

From version 2.0 the server is a thin layer over [olcaBASIC](https://github.com/Below280/olcaBASIC), a BASIC-style language for openLCA. The assistant writes a short olcaBASIC program and the server runs it: exploring databases, building and editing models, calculations (scenarios, sensitivity, Monte Carlo, contribution analysis), model checks, and EPDs to EN 15804+A2. The rules that used to be advice to the assistant (name the impact method, never pick between same-named processes, validate before calculating) are now enforced by the language, so they hold whichever assistant is driving.

The server works with both ecoinvent-family databases (ecoinvent, EN15804GD, HiQLCD, BAFU) and FLCAC-family databases (LCA Commons, US LCI, USEEIO). It detects the family from the flow property names, and refuses to build until the family is known.

Upgrading from 1.x: see [docs/MIGRATION.md](docs/MIGRATION.md) and the [2.0.0 release notes](docs/releases/release-notes-v2.0.0.md).

Available on [PyPI](https://pypi.org/project/b280-olca-mcp/) and the [MCP Registry](https://registry.modelcontextprotocol.io).

## Install

### Quick setup (PyPI)

```
pip install b280-olca-mcp
```

This installs the server and its dependencies in one step: `mcp` and `olcabasic`, which brings `olca-ipc`. Python 3.11 or later. The server runs from anywhere with `python -m b280_olca_mcp`.

### Development setup (GitHub)

Clone the repository for the latest code, the React dashboard, or if you want to modify the server:

```
git clone https://github.com/Below280/B280-olca-MCP.git
cd B280-olca-MCP
pip install -r requirements.txt
```

The server entry point is `b280_olca_mcp/server.py`.

## What it does

Someone using this MCP can say things like:

- 'Make me a model with 34 kWh UK electricity, 5 kg sodium hydroxide, and 34 kWh steam'
- 'Build an EPD model from this LCI'
- 'Run two scenarios, one with transport at 100 km and one at 500 km'
- 'Which processes contribute most to climate change in my system?'
- 'Vary the electricity and PET resin parameters by 10%'
- 'Validate my product system and check if the linking is correct'
- 'Run 1000 Monte Carlo iterations and show me the uncertainty'
- 'Help me connect to openLCA from R / Go / Rust'
- 'Build an EPD for this product under the International EPD System rules'
- 'Which emissions drive the climate change result, and where do they come from?'
- 'Put uncertainty on the electricity and the steel, then run Monte Carlo'
- 'What can you do?'

The AI assistant handles the conversation, writes the olcaBASIC program, and presents results visually with charts, tables, and exportable data. The program is the record of the work: `SAVE PROGRAM "model.baslca"` writes out everything that ran, and `RUN "model.baslca"` repeats it without an assistant.

## Connect your MCP client

The server uses stdio transport. Any MCP client that can spawn a local Python process will work.

### Claude Desktop

In Claude Desktop, go to Settings > Developer > Edit Config. Add an `openLCA` entry to the `mcpServers` section.

If you installed via PyPI:

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["-m", "b280_olca_mcp"],
      "env": {
        "OLCA_PORT": "8080"
      }
    }
  }
}
```

If you cloned from GitHub:

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["C:/path/to/B280-olca-MCP/b280_olca_mcp/server.py"],
      "env": {
        "OLCA_PORT": "8080"
      }
    }
  }
}
```

On Windows, if Claude Desktop cannot find Python, use the full path to your Python executable.

Restart Claude Desktop after saving.

### Cursor

Go to Settings > Tools & MCP > Add MCP Server. Choose stdio transport, set the command to `python` and the argument to `-m b280_olca_mcp` (PyPI) or the path to `b280_olca_mcp/server.py` (GitHub clone). Cursor picks up config changes without restarting.

### VS Code

Add the server to `.vscode/mcp.json` in your workspace or user settings:

```json
{
  "servers": {
    "openLCA": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "b280_olca_mcp"],
      "env": {
        "OLCA_PORT": "8080"
      }
    }
  }
}
```

Note: VS Code uses `servers` as the root key, not `mcpServers`. If using GitHub Copilot, switch Copilot Chat to Agent mode.

### ChatGPT

ChatGPT cannot directly launch a local stdio server. OpenAI provides the [Secure MCP Tunnel](https://github.com/openai/tunnel-client), which bridges ChatGPT to a local MCP server without exposing anything publicly. The architecture is:

```text
ChatGPT → Secure MCP Tunnel → B280 MCP (stdio) → openLCA IPC localhost:8080
```

The tunnel launches the B280 server (`python -m b280_olca_mcp`) on your machine. No changes to the B280 server are needed; it remains stdio throughout. No additional `search` or `fetch` tools are required for ChatGPT custom MCP servers.

B280's existing [tool annotations](#tool-annotations) (read-only, destructive, idempotent) are used by ChatGPT when deciding whether to auto-approve or prompt for confirmation.

For the full setup guide, including installation, configuration, troubleshooting and security considerations, see **[docs/chatgpt.md](docs/chatgpt.md)**.

ChatGPT support is currently experimental. A remote Streamable HTTP transport option may be added in future for users who prefer not to run the local tunnel.

### Other MCP clients

Any client that spawns a local Python process over stdin/stdout should work. With PyPI: `python -m b280_olca_mcp`. With GitHub clone: `python path/to/b280_olca_mcp/server.py`.

> **Beta software.** This server is under active development. Test it on a copy of your database before connecting a production database. Report issues on [GitHub](https://github.com/Below280/B280-olca-MCP/issues) or at mcp-feedback@below280.com.

## Start it

1. Open your database in openLCA
2. Start the IPC server (Tools > Developer Tools > IPC Server > green play button, port 8080)
3. Restart your MCP client (or reconnect)
4. Ask something like 'what can you do?' or 'what's in my openLCA database?'

After creating or modifying anything, press the Refresh button in openLCA's toolbar to see changes in the GUI.

**Give openLCA enough memory.** The openLCA installer sets its maximum memory to about 3.5 GB, which is not enough for a product system on ecoinvent or another large background database: openLCA runs out of memory, drops the connection and may restart itself. Set it to 10 GB or more in openLCA (File > Preferences > Configuration) and restart openLCA. If openLCA drops the connection, the tool's error says so and says what to check.

## Data security

The MCP server runs locally and communicates with openLCA on localhost. The AI client (Claude Desktop or equivalent) sends tool results to its provider's servers for processing. This means process names, exchange data, parameter values, and impact results from your database will be in the conversation.

**Do not connect a confidential client database through a personal or free-tier AI account.** Use a business or enterprise account with appropriate data retention controls, and check your provider's data processing terms before connecting any database containing sensitive information.

## Tools

Three tools, always present:

| Tool | Purpose |
|---|---|
| `olcabasic_run` | Run an olcaBASIC program. Arguments: `code`, and `dry_run` to check a program without touching openLCA. Returns `ok`, `text` (what a terminal would show), `data` (the result of every command as a structure, each `RESULT` query included, in the shape `olcabasic.Session` gives Python), `errors` (line, message, hint) and `warnings` |
| `olcabasic_help` | The command reference, from the same registry as olcaBASIC's `HELP`: no argument for the overview, a topic (`build`, `calculate`, `epd` ...) or a command (`MAKE PROCESS`) |
| `olcabasic_reset` | Clear the session: variables, scenarios, folders, the active EPD. The database is not touched |

One session lasts as long as the server, so variables, the current folder, scenarios and the latest results carry over between calls. Calls run one at a time: two programs can never write to openLCA at once, and product systems are never created in parallel.

The server starts whether or not openLCA is running. The first call that needs openLCA connects, and says what to do if it cannot.

### What it will not do

The language refuses anything that would build or calculate a wrong model, and an assistant cannot talk it out of a refusal. Each of these comes back as an error with the line and what to type instead:

- a background process used without a bridge;
- a name that could mean several processes or flows, and a method name that is not the full name;
- a `MAKE PROCESS` block run again after it was changed;
- a calculation on a product system that is out of date (one of its processes was edited, linked, moved or parameterised, or its links no longer match its processes) or that failed `VALIDATE`. `olcabasic_reset` and a new session do not get round either: the links are compared with the database every time, and a system not checked in the session is checked before it is calculated;
- an output that would create a flow by accident, a new emission that the method has no factor for, Monte Carlo with nothing uncertain, allocation without factors;
- in an EPD: a module using another module's process, and any broken rule of the programme.

Three kinds of command ask a person a question, and only run in the olcaBASIC terminal: `PARAMETERISE ... ALL`, changing an impact method olcaBASIC did not make, and `SHUTDOWN SERVER`. Through the MCP they are refused with a hint that says so.

`tests/test_shortcuts.py` plays an assistant cutting corners: 27 programs, each trying one way round a rule, each refused with the database unchanged.

### Two flags

Both are off by default and are set as environment variables in the MCP client's configuration.

| Variable | Effect |
|---|---|
| `OLCA_MCP_ALLOW_PYTHON=1` | Adds `python_exec`: run Python with `session`, `engine` and `client` in scope, for the cases olcaBASIC cannot express. Reading and calculating are free, and the code can call R, Fortran or anything else installed. **Writes are checked**: only in model folders (top folder starting `00: `), never on background data; each is listed in the reply; and every product system they touch is marked out of date, so `CALCULATE` and the rest refuse it until it is built again and passes `VALIDATE`, where the bridge rule is checked from the database. Numbers the code works out itself are labelled as not olcaBASIC results. Python can still open its own connection to openLCA and write past the wrapper; the gates read the database, so the bridge rule and the structure check still hold at `CALCULATE`. It runs in the server process, under the same lock, with your user's rights. Each call needs a `why_not_basic` reason and is logged to `~/.olcabasic/python_log.jsonl` (`OLCA_MCP_PYTHON_LOG` moves the log; `OLCA_MCP_PYTHON_TIMEOUT` sets the time limit in seconds). Leave it off unless you want an assistant to be able to run code on your machine |
| `OLCA_MCP_LEGACY_TOOLS=1` | Adds the 36 typed tools of version 1 (`search_processes`, `create_process`, `calculate` and so on), for clients and prompts written against them. They call the engine directly, so **they skip every rule the language enforces**; each tool's description starts by saying so. They are listed in [docs/tools.md](docs/tools.md) |

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["-m", "b280_olca_mcp"],
      "env": {
        "OLCA_PORT": "8080",
        "OLCA_MCP_LEGACY_TOOLS": "1"
      }
    }
  }
}
```

### What changed underneath

Up to 1.16 the engine that talks to openLCA lived in this package and olcaBASIC depended on it. From 2.0 it is the other way round: the engine is `olcabasic.engine.Engine`, and this package depends on `olcabasic`. `from b280_olca_mcp.functions import LCAFunctions` still works and gives a deprecation warning.

## Tool annotations

Every tool carries MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so clients can decide whether to auto-approve or prompt for confirmation. `olcabasic_help` is read-only. `olcabasic_run` can change and delete things in the database and is marked so; deletions inside a program still need `CONFIRM DELETE ON`. The legacy tools keep the annotations they had.

## Resources

The server exposes four MCP resources that AI clients can read on demand:

| Resource | URI | Purpose |
|---|---|---|
| Database info | `lca://database/info` | Live database overview |
| Assistant instructions | `lca://knowledge/instructions` | How to work with the user: when to ask, how to present results, how to check a model (144 lines; the rules are in the language) |
| IPC protocol reference | `lca://knowledge/ipc-protocol` | JSON-RPC reference for the 60 IPC methods of the olca-ipc client |
| openLCA resources | `lca://knowledge/openlca-resources` | Links to databases, docs, forums, and training |

The IPC protocol reference enables AI clients to help users connect to openLCA from any programming language by generating client code from the protocol specification.

## EPD model building

EPDs to EN 15804+A2 are olcaBASIC commands: an `EPD` block (declared unit, method, modules, programme), a `MODULE` block per information module, then `EPD SYSTEMS`, `EPD CHECK`, `EPD CALCULATE`, `EPD DATA QUALITY`, `EPD REPORT` and `EPD SAVE` (which writes the EPD into openLCA as its own EPD entity). `RATING` lines record how well each dataset represents geography, technology and time; `EPD SENSITIVITY` varies groups of parameters; `EPD EXPORT MODEL` writes the model out for a verifier. The module rules of the standard and, with `PROGRAMME "IES"`, the rules of the International EPD System are errors, not advice. What the assistant still does with you is decide which item of your inventory belongs in which module. Ask 'build an EPD from this LCI' to start. `olcabasic_help` with the topic `epd` shows the commands.

## Standalone scripts

The reproducible artefact is the olcaBASIC program itself: `SAVE PROGRAM "model.baslca"` after a session, then `olcabasic run model.baslca` (or `RUN "model.baslca"` in a session) runs it again with no AI tokens. The Python scripts in [openLCA-IPC-tools-python](https://github.com/Below280/openLCA-IPC-tools-python) remain for scenario and sensitivity runs from CSV files.

## Related repositories

| Repository | Description |
|---|---|
| [olcaBASIC](https://github.com/Below280/olcaBASIC) | The language this server runs, and the engine underneath it |
| [openLCA-IPC-tools-python](https://github.com/Below280/openLCA-IPC-tools-python) | Standalone Python scripts for scenarios, sensitivity, parameters, prospective LCA |
| [openLCA-IPC-tools-r](https://github.com/Below280/openLCA-IPC-tools-r) | R client for openLCA IPC (first R package for openLCA) |
| [openLCA-IPC-tools-fortran](https://github.com/Below280/openLCA-IPC-tools-fortran) | Fortran IPC client and batch calculator |

## About

Built by [Below280 Limited](https://below280.com), a UK LCA, EPD and CBAM consultancy and official UK partner for [openLCA](https://www.openlca.org). The calculation patterns in this server are derived from production scripts used in EPD and LCA consulting work, tested against ecoinvent 3.10/3.11/3.12, EN15804GD, and US Federal LCA Commons (FLCAC) databases.

For issues: [GitHub Issues](https://github.com/Below280/B280-olca-MCP/issues) or mcp-feedback@below280.com

## Documentation

- [Connecting AI to openLCA](https://below280.com/knowledge-base/openlca-scripting/lca-integration-ai/connecting-ai-to-openlca-the-mcp-server/) (full setup guide)
- [openLCA scripting knowledge base](https://below280.com/knowledge-base/openlca-scripting/)
- [openLCA Manual](https://greendelta.github.io/openLCA2-manual/introduction/index.html)

## Licence

MPL-2.0

mcp-name: io.github.Below280/b280-olca-mcp
