# Tool Reference

Complete reference for all 29 tools in the openLCA MCP Server. Each entry shows the tool name, what it does, required and optional inputs, and an example prompt that would trigger it.

## Explore

### `database_info`

Get an overview of the connected openLCA database: counts of product systems, processes, flows, impact methods, and parameters. Also auto-detects the database family (ecoinvent or FLCAC).

**Inputs:** none

**Example:** 'What's in my openLCA database?'

---

### `set_database_family`

Set whether the connected database uses ecoinvent-family or FLCAC-family naming conventions. Call this after asking the user which database type they have.

**Inputs:**
- `family` (required): `"ecoinvent"` or `"flcac"`

**Example:** User says 'I'm using ecoinvent' → call with `{"family": "ecoinvent"}`

**ecoinvent family:** ecoinvent, EN15804GD, HiQLCD, BAFU
**FLCAC family:** LCA Commons, US LCI, USEEIO

---

### `list_systems`

List product systems in the database, with optional name filtering.

**Inputs:**
- `search_term` (optional): filter by name

**Example:** 'Show me all product systems with steel in the name'

---

### `list_methods`

List impact assessment methods available in the database, with optional name filtering.

**Inputs:**
- `search_term` (optional): filter by name

**Example:** 'What impact methods are available?'

---

### `search_processes`

Search for processes by name. Returns process IDs, names, and categories.

**Inputs:**
- `search_term` (required): process name to search for
- `limit` (optional): maximum results, default 20

**Example:** 'Find sodium hydroxide processes'

---

### `search_flows`

Search for flows by name and/or category folder.

**Inputs:**
- `search_term` (optional): flow name
- `category_filter` (optional): category/folder path
- `limit` (optional): maximum results, default 20

**Example:** 'Show me the flows in my 00: Kerdyn Green folder'

---

### `process_details`

Get full details of a specific process: exchanges (inputs/outputs with amounts, units, providers), parameters, location, and description.

**Inputs:**
- `process_id` (required): process UUID

**Example:** 'Show me the details of that sodium hydroxide process'

---

### `system_parameters`

List all parameters defined in a product system, with optional name filtering.

**Inputs:**
- `system` (required): product system name or ID
- `name_filter` (optional): filter parameters by name

**Example:** 'What parameters does my A1 system have?' or 'Show me parameters with electricity in the name'

---

### `global_parameters`

Look up global (database-level) parameters, not tied to a specific product system.

**Inputs:**
- `name_filter` (optional): filter by name

**Example:** 'What's my distance parameter set to?'

---

### `find_unit`

Look up a unit by name and return its ID and associated flow property.

**Inputs:**
- `unit_name` (required): unit name exactly as openLCA stores it (e.g. `kg`, `kWh`, `MJ`, `m3`, `t*km`, `Item(s)`)

**Example:** 'What flow property does kWh belong to?'

---

## Build

### `create_flow`

Create a new flow (product, waste, or elementary) in the database. The unit determines the flow property automatically based on the detected database family.

**Inputs:**
- `name` (required): flow name
- `unit` (required): unit name (e.g. `kg`, `kWh`, `m3`)
- `category` (optional): category/folder path
- `flow_type` (optional): `"product"`, `"waste"`, or `"elementary"` (default: product)

**Example:** 'Create a product flow called Steel Beam in kg'

---

### `create_bridge`

Create a bridge flow AND bridge process in one call. A bridge connects the foreground model to a background database process. Use `search_processes` first to find the provider ID.

**Inputs:**
- `name` (required): bridge name (e.g. `BRIDGE | UK grid electricity | kWh`)
- `unit` (required): unit name
- `category` (optional): folder path (convention: `00: Project/Bridges`)
- `provider_id` (optional): UUID of the background process to link to
- `waste` (optional): `true` for waste treatment bridges (default: false)

**Example:** 'Create a bridge for UK grid electricity at medium voltage'

---

### `create_process`

Create a process with exchanges and optional parameters. Exactly one exchange must have `is_qref: true`.

**Inputs:**
- `name` (required): process name
- `category` (required): category/folder path
- `exchanges` (required): list of exchange objects
- `parameters` (optional): list of parameter objects
- `description` (optional): process description

**Exchange object:**
- `flow_id` (required), `unit` (required), `is_input` (required)
- `amount` (optional), `formula` (optional), `is_qref` (optional), `provider_id` (optional)

**Example:** 'Make me a process with 1 kg sodium hydroxide, 3 kWh electricity, and 2 kg water as inputs'

---

### `edit_process`

Edit an existing process in place: add exchanges, add parameters, update parameter values, or change description/category.

**Inputs:**
- `process_id` (required): UUID of the process to edit
- `add_exchanges` (optional): new exchanges to add
- `add_parameters` (optional): new parameters to add
- `update_parameters` (optional): `{param_name: new_value}` for existing parameters
- `description` (optional): new description
- `category` (optional): new category

**Example:** 'Add a transport input to my process, 500 tkm by lorry'

---

### `delete_entity`

Delete a process, flow, or product system from the database. Always asks for explicit user confirmation before executing.

**Inputs:**
- `entity_type` (required): `"process"`, `"flow"`, or `"product_system"`
- `entity_id` (required): UUID of the entity to delete

**Example:** 'Delete the old superseded process'

---

### `create_system`

Create a product system from a process. Auto-links the supply chain. Optionally set target amount, unit, and flow property.

**Inputs:**
- `process` (required): process name or ID
- `linking` (optional): `"prefer_defaults"` or `"only_defaults"`
- `target_amount` (optional): target amount
- `target_unit` (optional): unit name (e.g. `m3`, `kg`)
- `target_flow_property` (optional): flow property name (e.g. `Volume`, `Mass`)
- `category` (optional): category to assign

**Example:** 'Create a product system from my A1 process, 0.85 m3 volume'

---

### `get_system_links`

Show which providers are linked to which exchanges in a product system. Use search_term to filter by flow or provider name. Essential for checking what `create_system` chose for ambiguous flows like electricity.

**Inputs:**
- `system` (required): product system name or ID
- `search_term` (optional): filter links by flow or provider name (recommended for large systems)
- `limit` (optional): max links to return (default: 50)

**Example:** 'Which electricity provider got linked in my system?' → `{"system": "My System", "search_term": "electricity"}`

---

## Audit

### `extract_model`

Extract all processes from a model folder and its subfolders. Returns every process with exchanges, parameters, providers, and descriptions, plus all custom flows in the folder.

**Inputs:**
- `category` (required): category/folder path (e.g. `00: My Project`)

**Example:** 'Show me everything in the 00: East Bros folder'

---

### `audit_model`

Run structural checks on a model folder. Only called when the user explicitly asks.

**Checks:** missing quantitative references, zero-amount exchanges without formulas, missing providers, parameter/unit naming mismatches.

**Does not flag:** amount differences between connected processes (openLCA scales automatically), same-property unit differences (auto-converted).

**Inputs:**
- `category` (required): category/folder path

**Example:** 'Audit my model for problems'

---

### `validate_system`

Validate a product system. Checks target process, linking, parameters, and runs a test calculation. Only called when the user explicitly asks.

**Inputs:**
- `system` (required): product system name or ID

**Example:** 'Check my product system is valid'

---

### `data_quality`

Extract pedigree matrix and data quality entries for a process and all its exchanges. Parses scores into Reliability, Completeness, Temporal correlation, Geographical correlation, and Further technological correlation (1-5, lower is better).

**Inputs:**
- `process_id` (required): process UUID

**Example:** 'What's the data quality on this process?'

---

## Calculate

### `calculate`

Run a baseline impact assessment calculation. Always asks the user which impact method to use first.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID

**Example:** 'Run an LCA on my product system'

---

### `contribution_analysis`

Process-level contribution breakdown showing which processes in the supply chain drive each impact category. Filter to specific categories or analyse all.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `threshold_pct` (optional): minimum contribution % to include (default: 0.1)
- `max_contributors` (optional): max contributors per category (default: 30)
- `categories` (optional): filter to specific category names

**Example:** 'Which processes contribute most to climate change in my system?'

---

### `monte_carlo`

Run Monte Carlo uncertainty simulation. Returns mean, standard deviation, CV, min, max, median, and 5th/95th percentiles per category.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `iterations` (optional): number of iterations (default: 1000)

**Example:** 'Run 1000 Monte Carlo iterations on my system'

---

### `inventory_flows`

Get elementary flow inventory results at LCI level. Returns raw biosphere flows (kg CO2, MJ energy, etc.) rather than characterised impact scores.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `max_flows` (optional): maximum flows to return (default: 50)

**Example:** 'Show me the raw emissions from my system'

---

### `scenarios`

Run scenario-based LCA calculations from conversational parameter values.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `scenarios` (required): `{scenario_name: {param_name: value, ...}, ...}`

**Example:** 'Compare two scenarios: one with transport at 100 km and one at 500 km'

**Tool call:**
```json
{
  "system": "My System",
  "method": "EF v3.1",
  "scenarios": {
    "Short haul": {"transport_km": 100},
    "Long haul": {"transport_km": 500}
  }
}
```

---

### `scenarios_csv`

Run scenarios from a CSV file on disk. Same CSV format as B280_olca_scenarios.py.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `csv_path` (required): path to the scenarios CSV file
- `output_path` (optional): path for results CSV

**Example:** 'Run the scenarios in C:/data/scenarios.csv against my system'

---

### `sensitivity`

Run parameter sensitivity analysis. Each parameter varied independently by +/- the specified percentage.

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `parameters` (required): list of parameter names to vary
- `variation_pct` (optional): variation percentage (default: 20)

**Example:** 'Vary the electricity and transport parameters by 10%'

**Tool call:**
```json
{
  "system": "My System",
  "method": "EF v3.1",
  "parameters": ["electricity_kwh", "transport_km"],
  "variation_pct": 10
}
```

---

### `sensitivity_csv`

Run sensitivity analysis from a CSV file listing parameter names (one per line).

**Inputs:**
- `system` (required): product system name or ID
- `method` (required): impact assessment method name or ID
- `csv_path` (required): path to the sensitivity CSV file
- `variation_pct` (optional): variation percentage (default: 20)
- `output_path` (optional): path for results CSV

**Example:** 'Run sensitivity on the parameters listed in my_params.csv'
