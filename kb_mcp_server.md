# Connecting AI to openLCA: the MCP Server

openLCA has an IPC server built in. The [scripting articles](https://below280.com/knowledge-base/openlca-scripting/) on this site cover using it from Python scripts. This article covers something different: connecting openLCA directly to an AI assistant through the Model Context Protocol (MCP), so that it can search your database, build models, run calculations, and present results, all from a conversation.

The server is open source and available on GitHub.

**[View the openLCA MCP Server on GitHub →](https://github.com/below280/openLCA-MCP-server)**

Below280 is the UK partner for openLCA. We built this server using patterns from our production LCA and EPD consulting work, tested against ecoinvent 3.10/3.11 and EN15804GD databases. The calculation patterns are the same ones used in the [scenario](https://below280.com/knowledge-base/openlca-scripting/) and [sensitivity](https://below280.com/knowledge-base/openlca-scripting/) scripts elsewhere in this knowledge base.

## What is the openLCA MCP server?

The Below280 openLCA MCP server is an open-source bridge between AI applications that support Model Context Protocol and openLCA's IPC server. It allows an AI assistant to search LCA databases, build and audit models, run calculations, and retrieve results through natural-language conversation.

MCP is Anthropic's open standard for connecting AI applications to external tools. The server uses the MCP standard and should therefore be usable by other MCP-compatible clients, although we have developed and tested it with Claude Desktop. The examples and setup instructions in this article focus on Claude Desktop because that is what we use and can vouch for.

## How can AI be used in Life Cycle Assessment?

AI can assist LCA practitioners across the full workflow: finding appropriate processes and flows in databases, constructing foreground models from defined inputs, reviewing models for structural errors, comparing scenarios, running sensitivity and uncertainty analysis, identifying contribution hotspots, extracting inventory results, and automating repetitive modelling tasks.

These are not theoretical applications. This server implements them by allowing AI assistants to interact directly with openLCA through its IPC server. The tools, examples, and source code are all public.

AI does not determine whether an LCA is methodologically valid. Functional units, system boundaries, allocation methods, dataset selection, and interpretation still require appropriate LCA expertise. The [validation note](#a-note-on-validation) later in this article covers this distinction in detail.

## What it does

The server exposes 29 tools across four areas.

### Exploring the database

The assistant can search for processes, flows, product systems, and impact methods by name. It can pull full process details (exchanges, parameters, providers, descriptions) and look up global or system-level parameters. When someone asks 'find me sodium hydroxide processes for a UK project', the assistant searches the database, reads the descriptions, and recommends the right dataset based on geography, technology, and data vintage.

### Building models

This is where it gets interesting. Someone can describe their system in plain language: 'make me a model with 1 kg sodium hydroxide, 3 kWh electricity, and 2 kg water' and the assistant builds it in openLCA. It creates the product flow, searches for background processes, creates bridge processes to connect them, builds the foreground process with all exchanges wired up, and creates a product system ready for calculation.

The server uses the bridge architecture throughout. Every background database connection goes through a named bridge process, which means the foreground model stays independent of the background database. Swapping ecoinvent for another database means updating bridges only.

Models are organised in folders starting with '00: ' (e.g. '00: My Project') to keep them separate from background data.

Existing processes can be edited in place: adding exchanges, adding parameters, updating parameter values, or changing descriptions. There is no need to rebuild a process from scratch to make a change. Orphaned or superseded entities can be deleted directly, though the assistant will always ask for explicit confirmation before removing anything from the database.

### Auditing and reviewing models

The assistant can extract everything from a model folder: processes, flows, exchanges, parameters, and providers. It can run structural checks (missing quantitative references, zero amounts, unit mismatches, missing providers) and validate product systems the same way the openLCA Validate button does, including running a test calculation to catch linking errors.

The server understands openLCA's scaling behaviour. A process outputting 1 kg feeding one that needs 5 kg is correct: openLCA runs it five times. The audit tools will never flag this as an error. Same-property unit conversions (MJ to kWh, kg to t) are handled automatically by openLCA and are also left alone.

Data quality is covered too. The assistant can extract pedigree matrices from processes and exchanges, parsing the scores into their five indicators (Reliability, Completeness, Temporal correlation, Geographical correlation, Further technological correlation).

### Running calculations

The server supports six types of calculation:

**Baseline impact assessment** runs a product system against a chosen impact method and returns all category results.

**Scenario analysis** accepts parameter values for multiple scenarios (either from conversation or from a CSV file) and calculates each one. The CSV format matches the [B280 scenario script](https://below280.com/knowledge-base/openlca-scripting/).

**Sensitivity analysis** varies each named parameter independently by a specified percentage above and below baseline, showing which parameters have the most influence on each impact category. Again, CSV input is supported using the same format as the [B280 sensitivity script](https://below280.com/knowledge-base/openlca-scripting/).

**Contribution analysis** uses `get_tech_flows()` and `get_total_impacts_of()` to show which processes in the supply chain drive each impact category. This is the same pattern used in our [EPD data quality work](https://below280.com/knowledge-base/) and gives foreground-level contributions rather than atomised background processes.

**Monte Carlo simulation** runs uncertainty analysis across N iterations and returns statistics per category: mean, standard deviation, coefficient of variation, min, max, median, and 5th/95th percentiles.

**Inventory flow results** returns raw elementary flows (kg CO2, MJ energy, etc.) at the LCI level rather than characterised impact scores.

Before running any calculation, the assistant asks which impact method to use. The common options are 'EN15804+A2 (EF 3.1)' for EPD work (38 categories) and 'EF v3.1' for general European LCA. The server knows the exact method names and the common pitfalls around them.

### Database compatibility

The server works with both major database families used in openLCA:

**ecoinvent family** covers ecoinvent itself, the EN15804GD addon, HiQLCD, and BAFU databases. These use flow property names like 'Time', 'Mass transport', and 'Volume'.

**FLCAC family** covers LCA Commons databases including US LCI and USEEIO. These use different names for the same concepts: 'Duration' instead of 'Time', 'Goods transport (mass*distance)' instead of 'Mass transport'.

When building a model, the assistant asks which family your database belongs to. If you don't know, the server auto-detects by checking which flow property names exist. This determines how flows are created so that units and flow properties match the connected database correctly.

A diagnostic script (`pull_units.py`) is included in the repository for testing compatibility with other databases.

## Things you can ask it

These are real prompts. Once the MCP is connected, type any of these into your MCP client and the assistant will call the right tools, ask clarifying questions where needed, and present results.

### Exploring a database

'What's in my openLCA database?' gives you the counts: how many processes, flows, product systems, impact methods, and parameters are in the connected database. Useful as a first check that the connection is working.

'Find me sodium hydroxide processes for a UK project' searches by name, reads the process descriptions, and recommends the right dataset based on geography and technology. The assistant will explain why it picked membrane cell over mercury cell, and flag if the location data covers GB production.

'Show me all the flows in my 00: Kerdyn Green folder' searches flows by category, returning the custom product and bridge flows that belong to a specific model.

'What parameters does my A1 system have?' lists every parameter in a product system with its current value. 'Show me any parameters with electricity in the name' filters the list.

### Building a model from scratch

'Make me a model with 1 kg sodium hydroxide, 3 kWh electricity, 1 kg HDPE granulate, and 2 kg water' is enough for the assistant to build the entire thing. It will ask what to call the product and the folder, search for the right background processes, create bridge flows and processes for each input, build the foreground process with all exchanges linked, and create a product system ready for calculation.

'Add a transport input to my process, 500 tkm by lorry' works on an existing model. The assistant finds the transport process in the database, creates a bridge, and adds the exchange.

'Create a bridge for UK grid electricity at medium voltage' builds just the bridge flow and process, ready to wire into a foreground process later.

### Running calculations

'Run an LCA on my product system' triggers the method selection first. The assistant lists what's available and asks which one to use before calculating.

'Compare two scenarios: one with 100 km transport and one with 500 km' builds the parameter overrides and runs both calculations, presenting the comparison as a chart.

'Which processes contribute most to climate change in my system?' runs contribution analysis and shows the breakdown: which background processes drive the GWP result, with percentages.

'Vary the electricity and transport parameters by 10%' runs sensitivity analysis, producing a tornado diagram showing which parameter has the most influence on each impact category.

'Run 1000 Monte Carlo iterations' produces uncertainty statistics: mean, standard deviation, coefficient of variation, and percentiles for every impact category.

### Reviewing a model

'Check my product system is valid' runs the same checks as the openLCA Validate button: target process, linking, parameters, and a test calculation.

'Show me everything in the 00: East Bros folder' extracts every process, flow, exchange, and parameter from that model folder, giving the assistant the full picture to reason about.

'Audit my model for problems' runs structural checks: missing quantitative references, placeholder exchanges, missing providers, and parameter/unit mismatches.

'What's the data quality on this process?' pulls the pedigree matrix scores and uncertainty distributions for a process and all its exchanges.

### Checking against an LCI

'Here's my LCI spreadsheet, check it against what's in the model' works when you paste or describe your inventory data. The assistant extracts the model, compares the exchange amounts and units against your LCI, and flags discrepancies. It understands that openLCA scales processes, so a process outputting 1 kg feeding one that needs 5 kg is correct.

'Does the model match the data in this report?' is the same idea with a written source. The assistant reads the document, pulls the model data, and compares them systematically.

## Data security: read this before connecting

The MCP server runs locally on your machine. It reads from and writes to your openLCA database through the IPC server on localhost. So far, nothing leaves your computer.

The AI client is the part that leaves your computer. When Claude Desktop (or any other MCP client) calls a tool, the results travel to the AI provider's servers for processing. That means process names, exchange amounts, parameter values, flow descriptions, and impact results from your openLCA database are sent to the AI provider as part of the conversation.

If your database contains confidential client data, proprietary formulations, trade secrets, or unpublished LCI, that data will be in the conversation.

**Personal and consumer AI accounts** may allow conversation data to be used to improve models, depending on the provider, product, and account settings. Do not connect a confidential database until you have checked the current data-use terms and settings for your specific AI provider and account.

**Business and enterprise accounts** (Claude for Teams, Claude for Enterprise, and equivalents from other providers) generally offer data retention controls and the ability to opt out of training. 'Generally' is doing work in that sentence because policies change and vary between providers; verify the current terms for your specific account.

**The safe default:** if you would not paste the contents of a process into an email to the AI provider, do not connect that database to this MCP server through that account.

This is a tool decision, not a technology limitation. The MCP server has no data filtering or redaction capability. Everything in your database is accessible to whatever AI client you connect. Choose your account type and your database accordingly.

## Setting it up

### Requirements

openLCA 2.x with the IPC server started (Tools > Developer Tools > IPC Server, port 8080). Python 3.10 or later. An MCP-compatible desktop application.

### Install the packages

```bash
pip install mcp olca-ipc
```

### Get the server files

Download `lca_functions.py` and `mcp_lca_server.py` from the [GitHub repository](https://github.com/below280/openLCA-MCP-server) and place them in the same folder.

### Claude Desktop

In Claude Desktop, go to Settings > Developer > Edit Config. This opens `claude_desktop_config.json`. Add an `openLCA` entry to the `mcpServers` section:

```json
{
  "mcpServers": {
    "openLCA": {
      "command": "python",
      "args": ["C:/path/to/your/folder/mcp_lca_server.py"],
      "env": {
        "OLCA_PORT": "8080"
      }
    }
  }
}
```

Update the path to match where you placed the files. If you have other MCP servers already configured, add the `openLCA` block alongside them with a comma separating the entries.

On Windows, if Claude Desktop can't find Python, use the full path to your Python executable (e.g. `C:\\Users\\yourname\\AppData\\Local\\Python\\bin\\python.exe`).

Restart Claude Desktop after saving. It reads the config on startup.

### ChatGPT

This server uses local stdio transport. ChatGPT currently requires remote MCP servers (Streamable HTTP or SSE with a public HTTPS endpoint). A local stdio server like this one does not connect directly to ChatGPT under OpenAI's current documented architecture.

If OpenAI adds local stdio support in future, the server should work without modification. For now, ChatGPT users would need to expose the server through a tunnel or remote hosting solution, which is beyond the scope of this guide.

### Cursor

Cursor reads MCP config from its settings UI. Go to Settings > Tools & MCP > Add MCP Server. Choose stdio transport, set the command to `python` and the argument to the path to `mcp_lca_server.py`. Cursor picks up config changes without restarting.

### VS Code

VS Code supports MCP servers through its settings. Add the server configuration to your `.vscode/mcp.json` or user settings, using the same command and args pattern as the Claude Desktop config above.

### Other MCP clients

The server uses stdio transport: any MCP client that can spawn a local Python process and communicate over stdin/stdout should be able to use it. The configuration details vary by client but the server command is always the same: `python path/to/mcp_lca_server.py`.

### Start it

1. Open your database in openLCA
2. Start the IPC server (Tools > Developer Tools > IPC Server > green play button)
3. Restart your MCP client (or reconnect, depending on the client)
4. Ask something like 'what's in my openLCA database?'

If the tools are working, the AI will call `database_info` and report the counts of processes, flows, methods, and systems in your database.

### After creating or modifying anything

openLCA does not auto-refresh when changes come in through IPC. After using the model-building tools, press the Refresh button in openLCA's toolbar (the circular arrow icon) to see the new processes, flows, and product systems in the navigation panel.

## The full tool list

### Explore

`database_info`, `set_database_family`, `list_systems`, `list_methods`, `search_processes`, `search_flows`, `process_details`, `system_parameters`, `global_parameters`, `find_unit`

### Build

`create_flow`, `create_bridge`, `create_process`, `edit_process`, `delete_entity`, `create_system`, `get_system_links`

### Audit

`extract_model`, `audit_model`, `validate_system`, `data_quality`

### Calculate

`calculate`, `contribution_analysis`, `monte_carlo`, `inventory_flows`, `scenarios`, `scenarios_csv`, `sensitivity`, `sensitivity_csv`

## Visualisation

MCP clients that support artifacts (such as Claude Desktop) can render interactive React components inside the conversation. When calculation results come back from the MCP, asking the assistant to 'show that as a chart' or 'visualise those results' will produce a dashboard with the relevant chart type for the data.

Scenario comparisons produce bar charts with a category selector and a radar profile for normalised comparison across categories. Sensitivity results produce a tornado diagram with parameters ranked by influence. Contribution analysis produces horizontal bar charts showing which processes drive each impact category. All results include a table view with a CSV export button.

The dashboard has four colour themes (Greyscale, Dark, B280, and openLCA) and English/Portuguese language support. The Greyscale theme is the default, designed for embedding in reports. The others are there for anyone who prefers a different look.

A template (`B280_LCA_Dashboard.jsx`) is included in the repository. The assistant uses this as a reference when building artifacts, though it adapts the layout to fit the specific data being presented.

## Early release: help us break it

This server is a work in progress. The core tools are tested and the calculation patterns come from production EPD work, but MCP integration is still a young technology and there will be rough edges. Some things the assistant does well (searching, calculating, presenting results), others it occasionally gets wrong (choosing the right tool sequence, formatting output consistently).

We are releasing it now so people can try it, use it, and tell us what breaks. Every failure report makes the next version better.

If something goes wrong, or if the assistant does something unexpected, or if you find a workflow that ought to work but doesn't, please email **info@below280.com** with what you tried and what happened. Screenshots of the conversation are particularly useful.

The [GitHub repository](https://github.com/below280/openLCA-MCP-server) is also open for issues and pull requests.

## A note on validation

The MCP server gives an AI assistant tools to interact with openLCA. It does not make AI-generated modelling decisions inherently correct. Background dataset selection, system boundaries, allocation choices, functional units, and other methodological decisions still need review by a competent LCA practitioner.

The audit and validation tools check model structure: missing quantitative references, broken linking, unit mismatches, placeholder exchanges. They catch mechanical errors. They do not assess whether the model is a reasonable representation of the system being studied. That judgement remains yours.

## Getting help

The [Below280 knowledge base](https://below280.com/knowledge-base/) covers openLCA scripting patterns in detail. The [openLCA manual](https://greendelta.github.io/openLCA2-manual/introduction/index.html) covers the desktop application. The [openLCA IPC documentation](https://greendelta.github.io/openLCA-ApiDoc/) covers the protocol itself.

If you'd like help setting up the MCP server for your organisation, building custom LCA models, or automating EPD workflows, [get in touch](https://below280.com/contact).
