# openLCA MCP Server

An MCP (Model Context Protocol) server that connects AI assistants to a running openLCA instance. Developed and tested with Claude Desktop; compatible with any MCP client that supports stdio transport. Built by [Below280](https://below280.com), the UK partner for openLCA.

The server exposes 29 tools covering the full LCA workflow: exploring databases, building and editing models, running calculations (scenarios, sensitivity, Monte Carlo, contribution analysis), auditing and validating models, and extracting data quality assessments. All calculation patterns are tested against production ecoinvent databases.

The server works with both ecoinvent-family databases (ecoinvent, EN15804GD, HiQLCD, BAFU) and FLCAC-family databases (LCA Commons, US LCI, USEEIO). It asks which family you are using, or auto-detects from the flow property names.

## What it does

Someone using this MCP can say things like:

- 'Make me a model with 34 kWh UK electricity, 5 kg sodium hydroxide, and 34 kWh steam'
- 'Run two scenarios, one with transport at 100 km and one at 500 km'
- 'Which processes contribute most to climate change in my system?'
- 'Vary the electricity and PET resin parameters by 10%'
- 'Validate my product system and check if the linking is correct'
- 'Run 1000 Monte Carlo iterations and show me the uncertainty'

The AI assistant handles the conversation, builds the tool calls, and presents results in a branded dashboard with bar charts, radar profiles, tornado diagrams, and exportable tables.

## Data security

The MCP server runs locally and communicates with openLCA on localhost. The AI client (Claude Desktop or equivalent) sends tool results to its provider's servers for processing. This means process names, exchange data, parameter values, and impact results from your database will be in the conversation.

**Do not connect a confidential client database through a personal or free-tier AI account.** These accounts may use conversation data for model training. Use a business or enterprise account with appropriate data retention controls, and check your provider's current data processing terms before connecting any database containing sensitive information.

The MCP server has no data filtering or redaction. Everything in your database is accessible to the connected AI client.

## Requirements

- openLCA 2.x with IPC server running (Tools > Developer Tools > IPC Server, port 8080)
- Python 3.10+
- The `mcp` and `olca-ipc` packages
- An MCP-compatible desktop application

```bash
pip install mcp olca-ipc
```

## Setup

### 1. Copy the files

Place these in a directory (e.g. `C:/software/lca-assistant/` or `~/lca-assistant/`):

```
lca-assistant/
  lca_functions.py
  mcp_lca_server.py
```

### 2. Connect your MCP client

The server uses stdio transport. Any MCP client that can spawn a local Python process will work. The command is always `python path/to/mcp_lca_server.py`.

#### Claude Desktop

Go to Settings > Developer > Edit Config. Add an `openLCA` entry to the `mcpServers` section:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["C:/software/lca-assistant/mcp_lca_server.py"],
      "env": {
        "OLCA_PORT": "8080"
      }
    }
  }
}
```

On Windows, if the client can't find Python, use the full path (e.g. `C:\\Users\\yourname\\AppData\\Local\\Python\\bin\\python.exe`).

Restart Claude Desktop after saving.

#### Cursor

Go to Settings > Tools & MCP > Add MCP Server. Choose stdio transport, set the command to `python` and the argument to the path to `mcp_lca_server.py`. Cursor picks up config changes without restarting.

#### VS Code

Add the server to `.vscode/mcp.json` or user settings, using the same command and args pattern as the Claude Desktop config above.

#### ChatGPT

This server uses local stdio transport. ChatGPT currently requires remote MCP servers (Streamable HTTP/SSE). A local stdio server does not connect directly to ChatGPT under OpenAI's current architecture. If OpenAI adds local stdio support, the server should work without modification.

#### Other MCP clients

Any client that spawns a local Python process over stdin/stdout should work. The server command is always: `python path/to/mcp_lca_server.py`.

### 3. Start the IPC server in openLCA

1. Open your database in openLCA
2. Go to **Tools > Developer Tools > IPC Server**
3. Leave the port as **8080**
4. Click the green play button
5. Status shows **Running** when ready

### 4. Restart your MCP client

Most clients read config on startup. After saving, restart the application (or reconnect, depending on the client). The openLCA tools will appear in the tool list.

## After creating or modifying anything

openLCA does not auto-refresh when changes are made via IPC. After using the model-building tools (create_flow, create_bridge, create_process), press the **Refresh** button in openLCA's toolbar (the circular arrow icon) to see the changes in the navigation panel.

## Tools

### Explore (10 tools)

| Tool | Purpose |
|------|---------|
| `database_info` | Counts of systems, processes, flows, methods, parameters. Auto-detects database family |
| `set_database_family` | Set ecoinvent or FLCAC naming conventions (from user input) |
| `list_systems` | List/search product systems |
| `list_methods` | List/search impact assessment methods |
| `search_processes` | Find processes by name |
| `search_flows` | Find flows by name and/or category folder |
| `process_details` | Full process info: exchanges, parameters, providers |
| `system_parameters` | List parameters for a product system |
| `global_parameters` | Look up database-level parameters |
| `find_unit` | Look up units and their flow properties |

### Build (7 tools)

| Tool | Purpose |
|------|---------|
| `create_flow` | Create product, waste, or elementary flows |
| `create_bridge` | Create a bridge flow + process in one call (connects foreground to background) |
| `create_process` | Build a process with exchanges, parameters, and providers |
| `create_system` | Create a product system from a process, with optional target amount/unit |
| `get_system_links` | Show which providers were linked for each exchange (filterable by name) |
| `edit_process` | Edit an existing process: add/update/remove exchanges, add/update parameters |
| `delete_entity` | Delete a process, flow, or product system (requires explicit user confirmation) |

### Audit (4 tools)

| Tool | Purpose |
|------|---------|
| `extract_model` | Pull everything from a model folder: processes, flows, exchanges, parameters |
| `audit_model` | Structural checks: missing qrefs, zero amounts, unit mismatches |
| `validate_system` | Mirrors openLCA's Validate button: linking, parameters, test calculation |
| `data_quality` | Extract pedigree matrices and uncertainty from a process |

### Calculate (8 tools)

| Tool | Purpose |
|------|---------|
| `calculate` | Baseline impact assessment |
| `contribution_analysis` | Process-level contribution breakdown per impact category |
| `monte_carlo` | Uncertainty simulation with statistics (mean, SD, CV, percentiles) |
| `inventory_flows` | Raw elementary flow results (LCI level) |
| `scenarios` | Scenario calculations from conversational parameter values |
| `scenarios_csv` | Scenario calculations from a CSV file |
| `sensitivity` | Parameter sensitivity analysis (conversational) |
| `sensitivity_csv` | Sensitivity analysis from a CSV file |

## Model building conventions

Models built through this MCP follow the Below280 bridge architecture:

- All processes and flows go in a folder starting with `00: ` (e.g. `00: My Project`)
- Background database connections go through **bridge processes**: single-exchange processes that connect the foreground to ecoinvent or other background databases
- Bridges go in a subfolder (e.g. `00: My Project/Bridges`)
- Module processes go in subfolders by stage (e.g. `00: My Project/Modules/A1`)
- Parameters are independent with default values, suitable for scenario CSV injection

This architecture allows database swapping by updating bridges only, and keeps the foreground model independent of the background database choice.

## Visualisation

The repository includes a React dashboard artifact (`B280_LCA_Dashboard.jsx`) for presenting results visually. It provides:

- Scenario comparison bar charts with radar profiles
- Sensitivity tornado diagrams
- Contribution breakdown charts
- Results tables with CSV export
- Four colour themes: Greyscale (default), Dark, B280, openLCA
- English and Portuguese language support

The assistant uses this template when presenting calculation results in clients that support artifacts.

## Scaling behaviour

openLCA scales processes automatically to meet demand. A process outputting 1 kg of steel feeding one that needs 5 kg is correct: openLCA runs the first process five times. The audit and validation tools understand this and will not flag amount differences between connected processes as errors.

openLCA also handles same-property unit conversions automatically (MJ to kWh, kg to t). These are not flagged either.

## Reference documentation

- [Connecting AI to openLCA](https://below280.com/knowledge-base/openlca-scripting/) (full setup guide and examples)
- [Below280 Knowledge Base](https://below280.com/knowledge-base/) (especially [openLCA Scripting](https://below280.com/knowledge-base/openlca-scripting/))
- [openLCA Manual](https://greendelta.github.io/openLCA2-manual/introduction/index.html)
- [openLCA IPC Documentation](https://greendelta.github.io/openLCA-ApiDoc/)

## About

Built by [Below280 Limited](https://below280.com), a UK LCA consultancy and UK partner for [openLCA](https://www.openlca.org). The calculation patterns in this server are derived from production scripts used in EPD and LCA consulting work, tested against ecoinvent 3.10/3.11, EN15804GD, and US Federal LCA Commons (FLCAC) databases.

The server uses GreenDelta's official `olca-ipc` and `olca-schema` Python packages for all openLCA communication.

Developed and tested with Claude Desktop. The server uses the MCP standard and should therefore be usable by other MCP-compatible clients, although these have not been tested by Below280.

## Licence

MIT
