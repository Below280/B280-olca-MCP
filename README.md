# openLCA MCP Server

An MCP (Model Context Protocol) server that connects AI assistants to a running openLCA instance. Developed and tested with Claude Desktop; compatible with any MCP client that supports stdio transport. Built by [Below280](https://below280.com), the UK partner for openLCA.

The server exposes 31 tools covering the full LCA workflow: exploring databases, building and editing models, running calculations (scenarios, sensitivity, Monte Carlo, contribution analysis), auditing and validating models, and extracting data quality assessments. All calculation patterns are tested against production ecoinvent databases.

The server works with both ecoinvent-family databases (ecoinvent, EN15804GD, HiQLCD, BAFU) and FLCAC-family databases (LCA Commons, US LCI, USEEIO). It asks which family you are using, or auto-detects from the flow property names.

Available on [PyPI](https://pypi.org/project/b280-olca-mcp/) and the [MCP Registry](https://registry.modelcontextprotocol.io).

## Install

### Quick setup (PyPI)

```
pip install b280-olca-mcp
```

This installs the server and its dependencies (`mcp`, `olca-ipc`) in one step. The server runs from anywhere with `python -m b280_olca_mcp`.

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
- 'What can you do?' (the help tool)

The AI assistant handles the conversation, builds the tool calls, and presents results visually with charts, tables, and exportable data.

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

ChatGPT does not directly launch a local stdio server. A public Streamable HTTP endpoint remains the standard deployment route. For developer testing, OpenAI documents Secure MCP Tunnel, which can connect ChatGPT to a private stdio server without exposing it publicly.

### Other MCP clients

Any client that spawns a local Python process over stdin/stdout should work. With PyPI: `python -m b280_olca_mcp`. With GitHub clone: `python path/to/b280_olca_mcp/server.py`.

## Start it

1. Open your database in openLCA
2. Start the IPC server (Tools > Developer Tools > IPC Server > green play button, port 8080)
3. Restart your MCP client (or reconnect)
4. Ask something like 'what can you do?' or 'what's in my openLCA database?'

After creating or modifying anything, press the Refresh button in openLCA's toolbar to see changes in the GUI.

## Data security

The MCP server runs locally and communicates with openLCA on localhost. The AI client (Claude Desktop or equivalent) sends tool results to its provider's servers for processing. This means process names, exchange data, parameter values, and impact results from your database will be in the conversation.

**Do not connect a confidential client database through a personal or free-tier AI account.** Use a business or enterprise account with appropriate data retention controls, and check your provider's data processing terms before connecting any database containing sensitive information.

## Tools

### Explore (11 tools)

| Tool | Purpose |
|---|---|
| `database_info` | Counts of systems, processes, flows, methods, parameters. Auto-detects database family |
| `set_database_family` | Set ecoinvent or FLCAC naming conventions |
| `list_systems` | List/search product systems |
| `list_methods` | List/search impact assessment methods |
| `search_processes` | Find processes by name, location, or category |
| `search_flows` | Find flows by name and/or category folder |
| `process_details` | Full process info: exchanges, parameters, providers |
| `system_parameters` | List parameters for a product system |
| `global_parameters` | Look up database-level parameters |
| `find_unit` | Look up units and their flow properties |
| `chemical_synonyms` | PubChem synonym search to find database matches |

### Build (6 tools)

| Tool | Purpose |
|---|---|
| `create_flow` | Create product, waste, or elementary flows |
| `create_bridge` | Create a bridge flow + process in one call |
| `create_process` | Build a process with exchanges, parameters, and providers |
| `edit_process` | Edit an existing process: add/update/remove exchanges and parameters |
| `create_system` | Create a product system from a process |
| `delete_entity` | Delete a process, flow, or product system (requires user confirmation) |

### Audit (5 tools)

| Tool | Purpose |
|---|---|
| `extract_model` | Pull everything from a model folder for inspection |
| `audit_model` | Structural checks: missing qrefs, zero amounts, unit mismatches |
| `validate_system` | Mirrors openLCA's Validate button: linking, parameters, test calculation |
| `get_system_links` | Show which providers are linked for each exchange |
| `data_quality` | Extract pedigree matrices and uncertainty from a process |

### Calculate (8 tools)

| Tool | Purpose |
|---|---|
| `calculate` | Baseline impact assessment |
| `contribution_analysis` | Process-level contribution breakdown per impact category |
| `monte_carlo` | Uncertainty simulation with statistics |
| `inventory_flows` | Raw elementary flow results (LCI level) |
| `scenarios` | Scenario calculations from conversational parameter values |
| `scenarios_csv` | Scenario calculations from a CSV file |
| `sensitivity` | Parameter sensitivity analysis |
| `sensitivity_csv` | Sensitivity analysis from a CSV file |

### Meta (1 tool)

| Tool | Purpose |
|---|---|
| `help` | Show capabilities grouped by workflow, with optional topic filter |

## Tool annotations

Every tool carries MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so clients can decide whether to auto-approve or prompt for confirmation. Explore and Calculate tools are read-only. Build tools signal that they modify the database. `delete_entity` is marked destructive. CSV tools are marked as writing files to disk. `chemical_synonyms` is marked as reaching an external service (PubChem).

## Resources

The server exposes four MCP resources that AI clients can read on demand:

| Resource | URI | Purpose |
|---|---|---|
| Database info | `lca://database/info` | Live database overview |
| Assistant instructions | `lca://knowledge/instructions` | Operational rules, workflows, and conventions |
| IPC protocol reference | `lca://knowledge/ipc-protocol` | Complete JSON-RPC spec for all 60 IPC methods |
| openLCA resources | `lca://knowledge/openlca-resources` | Links to databases, docs, forums, and training |

The IPC protocol reference enables AI clients to help users connect to openLCA from any programming language by generating client code from the protocol specification.

## EPD model building

The server includes a guided workflow for building EN15804 EPD models from LCI data. The AI maps LCI items to lifecycle modules (A1-D), creates the folder structure, bridge processes, module processes, and product systems. Ask 'build an EPD from this LCI' to start.

## Standalone scripts

For repeated analyses, the server recommends standalone Python scripts that run without AI tokens. After a scenario or sensitivity calculation, it offers to generate the CSV file needed to run the equivalent script from the [openLCA-IPC-tools-python](https://github.com/Below280/openLCA-IPC-tools-python) repository.

## Related repositories

| Repository | Description |
|---|---|
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
