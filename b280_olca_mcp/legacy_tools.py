"""
The 36 tools of B280-olca-MCP v1.

From v2.0.0 the server's main route is olcabasic_run. These typed tools
are thin wrappers over engine methods and are kept for one major
version so that existing set-ups are not broken by an upgrade. They are
registered only when the environment variable OLCA_MCP_LEGACY_TOOLS=1
is set. Their names, schemas, behaviour and results are the same as in
v1.16.0.
"""

import json
import logging
import os

from mcp.types import Tool, ToolAnnotations

logger = logging.getLogger("openLCA-MCP")

# ── tool annotation presets ──────────────────────────────
READONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)

DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)

CALCULATE = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

FILE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

EXTERNAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

# Shared property definition for the allocation parameter on calculation tools.
ALLOCATION_PROPERTY = {
    "type": "string",
    "description": (
        "Allocation method for multi-output processes. "
        "Options: 'as_defined' (use factors set in each process, "
        "the openLCA GUI default), 'physical', 'economic', 'causal', "
        "'none'. Default: 'as_defined'."
    ),
    "enum": ["as_defined", "physical", "economic", "causal", "none"],
    "default": "as_defined",
}


def validate_file_path(path: str, must_exist: bool = False) -> str:
    """Resolve and validate a file path. Blocks path traversal."""
    resolved = os.path.realpath(os.path.expanduser(path))
    # Block obvious traversal attempts
    if ".." in path:
        raise ValueError(f"Path traversal not allowed: {path}")
    if must_exist and not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")
    return resolved


# The tool list from the v1 instructions, appended to the instructions
# resource when the legacy tools are switched on.
LEGACY_TOOL_REFERENCE = """
LEGACY TOOLS (OLCA_MCP_LEGACY_TOOLS=1)
--------------------------------------
The typed tools of v1 are also registered. They call the engine
directly and skip every rule olcaBASIC enforces: no bridge rule, no
exact-name rule, no validation gate, no stale-system check, no EPD or
programme rules. A model built with them can be wrong without an
error. Prefer olcabasic_run; use these only where an existing workflow
depends on them, and say so to the user.

QUICK TOOL REFERENCE
--------------------
EXPLORE the database:
  database_info         → what's in the database (counts)
  list_systems          → find product systems by name
  list_methods          → find impact methods by name
  search_processes      → find processes by name
  search_flows          → find flows by name or category folder
  process_details       → full info on one process (exchanges, params)
  system_parameters     → parameters for a product system
  global_parameters     → database-level parameters
  find_unit             → look up units and flow properties

BUILD a model:
  create_global_parameter → database-level parameter (value or formula)
  edit_flow             → add or update flow properties, set the reference
  create_flow           → make a product/waste/elementary flow
  create_bridge         → make a bridge flow + process (foreground-to-background link)
  create_process        → build a process with exchanges and parameters
  create_system         → create a product system from a process

AUDIT a model:
  validate_system       → run this FIRST (mirrors openLCA Validate button)
  extract_model         → pull everything from a model folder
  audit_model           → structural checks on a folder
  data_quality          → pedigree matrices and uncertainty for a process

CALCULATE:
  calculate             → baseline impact assessment
  contribution_analysis → which processes drive each impact category
  monte_carlo           → uncertainty simulation with statistics
  inventory_flows       → raw elementary flows (LCI level)
  scenarios             → run scenarios from parameter values
  scenarios_csv         → run scenarios from a CSV file on disk
  sensitivity           → parameter sensitivity analysis
  sensitivity_csv       → sensitivity from a CSV file on disk
"""


# Said at the start of every v1 tool's description.
LEGACY_WARNING = (
    "[v1 tool: it skips every rule olcaBASIC enforces (bridges, exact "
    "names, validation, stale systems, EPD and programme rules). Prefer "
    "olcabasic_run.] ")


def tool_definitions() -> list:
    """The v1 tool definitions. Each description starts by saying that
    the tool skips the rules of the language."""
    tools = _tool_definitions()
    for tool in tools:
        tool.description = LEGACY_WARNING + (tool.description or "")
    return tools


def _tool_definitions() -> list:
    return [
        Tool(
            name="database_info",
            description=(
                "Get an overview of the connected openLCA database: "
                "counts of product systems, processes, flows, impact "
                "methods, and parameters. Also auto-detects the "
                "database family (ecoinvent or FLCAC)."
            ),
            inputSchema={"type": "object", "properties": {}},
            annotations=READONLY,
        ),
        Tool(
            name="list_dq_systems",
            description=(
                "List all Data Quality (DQ) systems available in the "
                "database. These can be assigned as flow schema "
                "(exchange_dq_system) or process schema (dq_system) "
                "when creating processes. Call this before building "
                "an EPD model to ask the user which schemas to use."
            ),
            inputSchema={"type": "object", "properties": {}},
            annotations=READONLY,
        ),
        Tool(
            name="set_database_family",
            description=(
                "Set the database family from user input. Call this "
                "AFTER asking the user whether their database is "
                "ecoinvent-family (ecoinvent, EN15804GD, HiQLCD, BAFU) "
                "or FLCAC-family (LCA Commons, US LCI, USEEIO). "
                "If the user doesn't know, call database_info instead "
                "which auto-detects."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "family": {
                        "type": "string",
                        "description": "Database family: 'ecoinvent' or 'flcac'",
                        "enum": ["ecoinvent", "flcac"],
                    },
                },
                "required": ["family"],
            },
            annotations=WRITE,
        ),
        Tool(
            name="list_systems",
            description=(
                "List product systems in the database. These are the "
                "calculable models. Accepts an optional search term "
                "to filter by name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Filter systems by name (optional)",
                    },
                },
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="list_methods",
            description=(
                "List impact assessment methods available in the "
                "database. Accepts an optional search term."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Filter methods by name (optional)",
                    },
                },
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="system_parameters",
            description=(
                "List all parameters defined in a product system. "
                "Shows parameter names and current values. Use "
                "name_filter to search for specific parameters."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "name_filter": {
                        "type": "string",
                        "description": "Filter parameters by name substring (optional)",
                    },
                },
                "required": ["system"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="global_parameters",
            description=(
                "Look up global (database-level) parameters. "
                "These are parameters defined at database scope, "
                "not tied to a specific product system. Use "
                "name_filter to search by name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name_filter": {
                        "type": "string",
                        "description": "Filter parameters by name substring (optional)",
                    },
                },
            },
        
            annotations=READONLY,
        ),
        # ── model building tools ─────────────────
        Tool(
            name="create_global_parameter",
            description=(
                "Create or update a GLOBAL (database-level) "
                "parameter. Give a value for an input parameter, "
                "or a formula for a dependent parameter that "
                "openLCA calculates from others (e.g. "
                "'cement_mass * water_ratio'). Process exchange "
                "formulas anywhere in the database can refer to "
                "it by name. Use global parameters for anything "
                "shared by several processes, so one scenario or "
                "sensitivity change applies to the whole model. "
                "If the name already exists it is updated in "
                "place and the previous value is returned; check "
                "'changed' before overwriting a parameter another "
                "model may use."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Parameter name (letters, digits, underscores; must not start with a digit)",
                    },
                    "value": {
                        "type": "number",
                        "description": "Value for an input parameter. Give this OR formula.",
                    },
                    "formula": {
                        "type": "string",
                        "description": "Formula for a dependent parameter, using other parameter names. Give this OR value.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description",
                    },
                },
                "required": ["name"],
            },
            annotations=WRITE,
        ),
        Tool(
            name="edit_flow",
            description=(
                "Add or update a flow's properties, or change its "
                "reference property. A property is given as a "
                "relation, e.g. amount 2400, unit 'kg', per_unit "
                "'m3' means 1 m3 = 2400 kg; either unit may belong "
                "to the named property and the other must belong to "
                "a property already on the flow. Changing the "
                "reference rescales every factor so exchanges keep "
                "their meaning. Properties are never removed here: "
                "removal is left to openLCA's flow editor, which can "
                "check where they are used. Changing a background "
                "flow affects every model that uses it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow UUID"},
                    "operations": {
                        "type": "array",
                        "description": "Applied in order",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string",
                                       "enum": ["add", "update", "reference"]},
                                "property": {"type": "string",
                                             "description": "Flow property name or ID, e.g. 'Mass'"},
                                "amount": {"type": "number"},
                                "unit": {"type": "string"},
                                "per_unit": {"type": "string"},
                            },
                            "required": ["op", "property"],
                        },
                    },
                },
                "required": ["flow_id", "operations"],
            },
            annotations=WRITE,
        ),
        Tool(
            name="find_unit",
            description=(
                "Look up a unit by name (e.g. 'kg', 'kWh', 'm3') "
                "and return its ID and associated flow property. "
                "Needed before creating flows."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "unit_name": {
                        "type": "string",
                        "description": "Unit name exactly as openLCA stores it, e.g. 'kg', 'kWh', 'MJ', 'm3', 't*km', 'Item(s)'",
                    },
                },
                "required": ["unit_name"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="create_flow",
            description=(
                "Create a NEW flow (product, waste, or elementary). "
                "Insert-only: calling with the same name creates a "
                "duplicate, not an update. The unit determines the "
                "flow property automatically based on database family. "
                "Convention: model flows go in a '00: ' folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Flow name",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit name e.g. 'kg', 'kWh', 'm3'",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category/folder path (optional)",
                    },
                    "flow_type": {
                        "type": "string",
                        "enum": ["product", "waste", "elementary"],
                        "description": "Type of flow (default: product)",
                        "default": "product",
                    },
                },
                "required": ["name", "unit"],
            },
        
            annotations=WRITE,
        ),
        Tool(
            name="create_bridge",
            description=(
                "Create a bridge flow AND bridge process in one call. "
                "A bridge connects the foreground model to a background "
                "database process (e.g. ecoinvent). Use search_processes "
                "first to find the background provider ID. For waste "
                "treatment bridges, set waste=true. "
                "Convention: place bridges in a subfolder of the model's "
                "'00: ' folder, e.g. '00: My Project/Bridges'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Bridge name e.g. 'BRIDGE | UK grid electricity | kWh'",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit name e.g. 'kWh', 'kg', 'MJ'",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category/folder path (optional)",
                    },
                    "provider_id": {
                        "type": "string",
                        "description": "UUID of the background process to link to (optional, can be set later in openLCA)",
                    },
                    "provider_flow_id": {
                        "type": "string",
                        "description": "UUID of the specific flow to use from the provider (optional, auto-detected from provider's qref if omitted)",
                    },
                    "waste": {
                        "type": "boolean",
                        "description": "True for waste treatment bridges (default: false)",
                        "default": False,
                    },
                },
                "required": ["name", "unit"],
            },
        
            annotations=WRITE,
        ),
        Tool(
            name="create_process",
            description=(
                "Create a NEW process. Insert-only: calling with the "
                "same name creates a duplicate. Use edit_process to "
                "modify an existing process. Exchanges define inputs "
                "and outputs. Exactly one must have is_qref=true. "
                "Flow IDs are validated against the connected database. "
                "Convention: place in a '00: ' model folder. "
                "NOTE: openLCA scales processes automatically. "
                "Every exchange is fully parametrised: a bare 'amount' "
                "is automatically turned into a process-scoped "
                "parameter named NN_processname__flowname_unit and the "
                "exchange references it, matching Below280's own "
                "modelling convention. Pass 'formula' instead only "
                "when the exchange should reference an existing, "
                "shared, or global parameter."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Process name",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category/folder path",
                    },
                    "exchanges": {
                        "type": "array",
                        "description": "List of exchanges (inputs/outputs)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "flow_id": {
                                    "type": "string",
                                    "description": "UUID of the flow",
                                },
                                "amount": {
                                    "type": "number",
                                    "description": (
                                        "Numeric amount (ignored if formula is set). "
                                        "Automatically becomes a named process "
                                        "parameter (NN_processname__flowname_unit) "
                                        "unless formula is set."
                                    ),
                                    "default": 0,
                                },
                                "formula": {
                                    "type": "string",
                                    "description": (
                                        "Formula referencing an existing, shared, or "
                                        "global parameter (optional, overrides amount). "
                                        "Leave unset for a bare amount, which is "
                                        "auto-parametrised instead."
                                    ),
                                },
                                "unit": {
                                    "type": "string",
                                    "description": "Unit name e.g. 'kg', 'kWh'",
                                },
                                "is_input": {
                                    "type": "boolean",
                                    "description": "True for inputs, false for outputs",
                                },
                                "is_qref": {
                                    "type": "boolean",
                                    "description": "True for the quantitative reference (main product)",
                                    "default": False,
                                },
                                "provider_id": {
                                    "type": "string",
                                    "description": "UUID of provider process (optional)",
                                },
                                "dq_entry": {
                                    "type": "string",
                                    "description": "Pedigree scores, e.g. '(1;2;1;1;3)'. Needs flow_schema; one score (1-5) per indicator.",
                                },
                                "comment": {
                                    "type": "string",
                                    "description": "Comment on this exchange (optional)",
                                },
                            },
                            "required": ["flow_id", "unit", "is_input"],
                        },
                    },
                    "parameters": {
                        "type": "array",
                        "description": (
                            "Process-scoped parameters (optional). "
                            "Give value for an input parameter or "
                            "formula for a dependent one. For "
                            "anything shared between processes, "
                            "use create_global_parameter instead."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "number"},
                                "formula": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "description": {
                        "type": "string",
                        "description": "Process description (optional)",
                    },
                    "flow_schema": {
                        "type": "string",
                        "description": (
                            "Name or UUID of a DQ system to set as "
                            "the flow schema (exchange_dq_system). "
                            "Use list_dq_systems to find available "
                            "options. Optional."
                        ),
                    },
                    "process_schema": {
                        "type": "string",
                        "description": (
                            "Name or UUID of a DQ system to set as "
                            "the process schema (dq_system). "
                            "Use list_dq_systems to find available "
                            "options. Optional."
                        ),
                    },
                },
                "required": ["name", "category", "exchanges"],
            },

            annotations=WRITE,
        ),
        Tool(
            name="edit_process",
            description=(
                "Edit an existing process in place. Can add, update, "
                "or remove exchanges, add/update parameters, and change "
                "the description or category. No need to rebuild."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "UUID of the process to edit",
                    },
                    "add_exchanges": {
                        "type": "array",
                        "description": "New exchanges to add (same format as create_process)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "flow_id": {"type": "string"},
                                "amount": {"type": "number", "default": 0},
                                "formula": {"type": "string"},
                                "unit": {"type": "string"},
                                "is_input": {"type": "boolean"},
                                "is_qref": {"type": "boolean", "default": False},
                                "provider_id": {"type": "string"},
                                "dq_entry": {"type": "string"},
                                "comment": {"type": "string"},
                            },
                            "required": ["flow_id", "unit", "is_input"],
                        },
                    },
                    "update_exchanges": {
                        "type": "array",
                        "description": "Update existing exchanges (matched by flow_id). Can change amount, formula, or unit.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "flow_id": {"type": "string", "description": "Flow ID to match"},
                                "amount": {"type": "number"},
                                "formula": {"type": "string"},
                                "unit": {"type": "string"},
                            },
                            "required": ["flow_id"],
                        },
                    },
                    "remove_exchanges": {
                        "type": "array",
                        "description": "Flow IDs of exchanges to remove from the process",
                        "items": {"type": "string"},
                    },
                    "add_parameters": {
                        "type": "array",
                        "description": "New parameters to add",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "number"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "update_parameters": {
                        "type": "object",
                        "description": "Update existing parameter values: {param_name: new_value}",
                        "additionalProperties": {"type": "number"},
                    },
                    "description": {
                        "type": "string",
                        "description": "New process description (replaces existing)",
                    },
                    "category": {
                        "type": "string",
                        "description": "New category (replaces existing)",
                    },
                },
                "required": ["process_id"],
            },
        
            annotations=WRITE,
        ),
        Tool(
            name="delete_entity",
            description=(
                "Delete a process, flow, or product system from the "
                "database. This is IRREVERSIBLE. "
                "BEFORE calling this tool you MUST: "
                "1. Tell the user the exact name and ID of what will be deleted. "
                "2. Ask the user to explicitly confirm by typing 'yes' or 'delete it'. "
                "3. Only call this tool AFTER receiving that confirmation. "
                "NEVER call this tool without the user's explicit approval in the conversation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["process", "flow", "product_system"],
                        "description": "Type of entity to delete",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "UUID of the entity to delete",
                    },
                },
                "required": ["entity_type", "entity_id"],
            },
        
            annotations=DESTRUCTIVE,
        ),
        # ── model extraction and audit ───────────
        Tool(
            name="extract_model",
            description=(
                "Extract all processes from a model folder and its "
                "subfolders. Returns every process with its exchanges, "
                "parameters, providers, and descriptions. Use this to "
                "inspect a model, check it against an LCI, or understand "
                "its structure. Convention: model folders start with "
                "'00: ' (e.g. '00: My Project'). "
                "IMPORTANT: openLCA scales processes automatically. "
                "A process outputting 1 kg feeding one needing 5 kg "
                "is NOT a mismatch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category/folder path to extract (e.g. '00: My Project')",
                    },
                },
                "required": ["category"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="audit_model",
            description=(
                "Run STRUCTURAL checks on all processes in a model "
                "folder. Takes a category path, not a system ID. "
                "Checks: missing qrefs, missing units, zero amounts, "
                "missing providers, duplicate exchanges, unit mismatches, "
                "and process description warnings. "
                "These are structural checks only. They verify that "
                "links resolve and fields are populated. They do NOT "
                "assess whether exchange quantities are physically "
                "plausible or correct. A clean result means the model "
                "is structurally sound, not that the numbers are right. "
                "ONLY call when user explicitly asks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category/folder path to audit (e.g. '00: My Project')",
                    },
                },
                "required": ["category"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="validate_system",
            description=(
                "Validate a product system's STRUCTURE. Checks that "
                "the target process exists, has a qref, links are "
                "present, and parameters have values. Does NOT check "
                "whether exchange quantities are correct or plausible. "
                "Set test_calculate=true for a test calculation (slower). "
                "ONLY call when user explicitly asks."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "test_calculate": {
                        "type": "boolean",
                        "description": "Run a test calculation too (default: false, slower)",
                        "default": False,
                    },
                },
                "required": ["system"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="create_system",
            description=(
                "Create a product system from a process. This auto-links "
                "the supply chain so the system is ready for calculation. "
                "Returns already_existed if a system for this process "
                "already exists. Optionally set the target amount, unit, "
                "and flow property. Convention: the source process should "
                "be in a folder starting with '00: '. IMPORTANT: never "
                "call this tool in parallel; create systems one at a time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "process": {
                        "type": "string",
                        "description": "Process name or ID to build the system from",
                    },
                    "linking": {
                        "type": "string",
                        "description": (
                            "Provider linking strategy: 'prefer_defaults' "
                            "(recommended) or 'only_defaults'"
                        ),
                        "enum": ["prefer_defaults", "only_defaults"],
                        "default": "prefer_defaults",
                    },
                    "target_amount": {
                        "type": "number",
                        "description": "Target amount for the system (optional)",
                    },
                    "target_unit": {
                        "type": "string",
                        "description": "Target unit e.g. 'kg', 'm3', 'MJ' (optional)",
                    },
                    "target_flow_property": {
                        "type": "string",
                        "description": "Flow property e.g. 'Mass', 'Volume' (optional)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category to assign the system to (optional)",
                    },
                },
                "required": ["process"],
            },
        
            annotations=WRITE,
        ),
        Tool(
            name="get_system_links",
            description=(
                "Show which providers are linked to which exchanges "
                "in a product system. Use search_term to filter by "
                "flow or provider name (e.g. 'electricity'). Always "
                "filter on large systems, otherwise results will be "
                "generic background links."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "search_term": {
                        "type": "string",
                        "description": "Filter links by flow or provider name (recommended for large systems)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max links to return (default: 50)",
                        "default": 50,
                    },
                },
                "required": ["system"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="calculate",
            description=(
                "Run a baseline impact assessment calculation. "
                "BEFORE calling this: you MUST first call list_methods, "
                "show the user the available methods, and ask which one "
                "to use. Do not assume a method. "
                "AFTER receiving results: present them visually (chart, "
                "table, or artifact) rather than narrating numbers "
                "as prose paragraphs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method"],
            },
        
            annotations=CALCULATE,
        ),
        Tool(
            name="contribution_analysis",
            description=(
                "Process-level contribution breakdown showing which "
                "processes drive each impact category. "
                "BEFORE calling: confirm the impact method with the user. "
                "AFTER receiving results: present visually (chart or "
                "table) rather than narrating as prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "threshold_pct": {
                        "type": "number",
                        "description": "Minimum contribution %% to include (default: 0.1)",
                        "default": 0.1,
                    },
                    "max_contributors": {
                        "type": "integer",
                        "description": "Max contributors per category (default: 30)",
                        "default": 30,
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter to specific impact categories by name substring (optional, default: all)",
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method"],
            },

            annotations=CALCULATE,
        ),
        Tool(
            name="upstream_tree",
            description=(
                "Multi-level contribution tree for ONE impact category, "
                "following the supply chain downwards. Each branch has "
                "its upstream result, its share of the total, and the "
                "pedigree (data quality) scores on the exchange linking "
                "it to its parent, with indicator names. Use it to find "
                "where an impact comes from and whether the data along "
                "that path is weak (scores of 4 or 5). "
                "BEFORE calling: confirm the method and category."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {"type": "string",
                               "description": "Product system name or ID"},
                    "method": {"type": "string",
                               "description": "Impact method name or ID"},
                    "category": {"type": "string",
                                 "description": "Impact category name (exact, or a unique part of it)"},
                    "levels": {"type": "integer", "default": 3,
                               "description": "How many levels down to go (default 3)"},
                    "top": {"type": "integer", "default": 5,
                            "description": "Children kept per branch; the rest are grouped as 'other' (default 5)"},
                    "with_quality": {"type": "boolean", "default": True,
                                     "description": "Include pedigree scores on each branch"},
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method", "category"],
            },
            annotations=CALCULATE,
        ),
        Tool(
            name="find_flow_usage",
            description=(
                "Find which processes (and, for elementary flows, which "
                "impact categories) use a flow. openLCA's IPC has no "
                "'where used' query, so this reads every process and "
                "can take a while on large databases. delete_entity "
                "runs this check itself before deleting a flow."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow UUID"},
                    "max_hits": {"type": "integer", "default": 10,
                                 "description": "Stop after this many uses"},
                },
                "required": ["flow_id"],
            },
            annotations=READONLY,
        ),
        Tool(
            name="monte_carlo",
            description=(
                "Run Monte Carlo uncertainty simulation. "
                "BEFORE calling: confirm the impact method with the user. "
                "AFTER receiving results: present visually (chart or "
                "table) rather than narrating as prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "iterations": {
                        "type": "integer",
                        "description": "Number of MC iterations (default: 1000)",
                        "default": 1000,
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method"],
            },

            annotations=CALCULATE,
        ),
        Tool(
            name="inventory_flows",
            description=(
                "Get elementary flow inventory results (LCI level). "
                "Returns raw biosphere flows (kg CO2, MJ, etc.) "
                "rather than characterised impacts. "
                "BEFORE calling: confirm the impact method with the user. "
                "AFTER receiving results: present as a table rather "
                "than narrating as prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "max_flows": {
                        "type": "integer",
                        "description": "Maximum flows to return (default: 50)",
                        "default": 50,
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method"],
            },

            annotations=CALCULATE,
        ),
        Tool(
            name="data_quality",
            description=(
                "Extract pedigree matrix and data quality entries "
                "for a process and all its exchanges. Returns DQ "
                "scores parsed into Reliability, Completeness, "
                "Temporal correlation, Geographical correlation, "
                "and Further technological correlation (1-5, lower "
                "is better). Also returns uncertainty distributions "
                "where set."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "Process UUID",
                    },
                },
                "required": ["process_id"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="scenarios",
            description=(
                "Run scenario-based LCA calculations. "
                "BEFORE calling: confirm the impact method with the user. "
                "AFTER receiving results: present visually (chart and "
                "table) rather than narrating numbers as prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "scenarios": {
                        "type": "object",
                        "description": (
                            "Scenarios as {name: {param: value, ...}}. "
                            "Example: {\"Baseline\": {\"distance_km\": 100}, "
                            "\"Long haul\": {\"distance_km\": 500}}"
                        ),
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method", "scenarios"],
            },

            annotations=CALCULATE,
        ),
        Tool(
            name="scenarios_csv",
            description=(
                "Run scenarios from a CSV file on disk. The CSV "
                "should have 'Parameter' as the first column and "
                "one column per scenario. Calculates all scenarios "
                "and writes results to a new CSV file. Same format "
                "as B280_olca_scenarios.py."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "csv_path": {
                        "type": "string",
                        "description": "Path to the scenarios CSV file",
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Where to save the results CSV. Ask the user "
                            "which folder they want it in. If not specified, "
                            "saves next to the input CSV file."
                        ),
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method", "csv_path"],
            },

            annotations=FILE_WRITE,
        ),
        Tool(
            name="sensitivity",
            description=(
                "Run parameter sensitivity analysis. Each parameter "
                "is varied independently by +/- the specified percentage. "
                "BEFORE calling: confirm the impact method with the user. "
                "AFTER receiving results: present visually (tornado "
                "diagram or table) rather than narrating as prose."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Parameter names to vary",
                    },
                    "variation_pct": {
                        "type": "number",
                        "description": "Variation percentage (default: 20)",
                        "default": 20,
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method", "parameters"],
            },

            annotations=CALCULATE,
        ),
        Tool(
            name="sensitivity_csv",
            description=(
                "Run sensitivity analysis from a CSV file on disk. "
                "The CSV lists one parameter name per line (lines "
                "starting with '#' are comments). Calculates +/- "
                "variation for each parameter and writes results "
                "to a CSV. Same format as B280_olca_sensitivity.py."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "system": {
                        "type": "string",
                        "description": "Product system name or ID",
                    },
                    "method": {
                        "type": "string",
                        "description": "Impact assessment method name or ID",
                    },
                    "csv_path": {
                        "type": "string",
                        "description": "Path to the sensitivity CSV file",
                    },
                    "variation_pct": {
                        "type": "number",
                        "description": "Variation percentage (default: 20)",
                        "default": 20,
                    },
                    "output_path": {
                        "type": "string",
                        "description": (
                            "Where to save the results CSV. Ask the user "
                            "which folder they want it in. If not specified, "
                            "saves next to the input CSV file."
                        ),
                    },
                    "allocation": ALLOCATION_PROPERTY,
                },
                "required": ["system", "method", "csv_path"],
            },

            annotations=FILE_WRITE,
        ),
        Tool(
            name="search_processes",
            description=(
                "Search for processes by name, category, and/or "
                "location. Use location_filter to find processes "
                "for a specific geography (e.g. 'GB', 'RER')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Process name to search for",
                    },
                    "category_filter": {
                        "type": "string",
                        "description": "Filter by category/folder path (optional)",
                    },
                    "location_filter": {
                        "type": "string",
                        "description": "Filter by location code e.g. 'GB', 'RER', 'US' (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["search_term"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="search_flows",
            description=(
                "Search for flows in the database by name and/or "
                "category folder. Use category_filter to find flows "
                "in a specific model folder (e.g. '00: My Project'). "
                "Convention: model flows go in a '00: ' folder matching "
                "the process folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Flow name to search for (optional if category_filter is set)",
                    },
                    "category_filter": {
                        "type": "string",
                        "description": "Filter by category/folder path (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20,
                    },
                },
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="chemical_synonyms",
            description=(
                "Look up chemical synonyms via PubChem (US NIH). "
                "Takes a common name, trade name, or IUPAC name and "
                "returns known synonyms, CAS number, and matching "
                "processes in the connected openLCA database. "
                "ONLY call this when: (a) the user explicitly asks "
                "for a deeper or synonym-based search, OR (b) a "
                "normal search_processes returned few results and "
                "the user approved trying synonyms. NEVER call this "
                "without the user's agreement."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "chemical_name": {
                        "type": "string",
                        "description": "Chemical name to look up (e.g. 'caustic soda', 'MEK', 'PET')",
                    },
                    "search_database": {
                        "type": "boolean",
                        "description": "Also search the openLCA database for matches (default: true)",
                        "default": True,
                    },
                },
                "required": ["chemical_name"],
            },
        
            annotations=EXTERNAL,
        ),
        Tool(
            name="process_details",
            description=(
                "Get full details of a specific process: exchanges "
                "(inputs/outputs with amounts, units, providers), "
                "parameters, location, and description."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "Process UUID",
                    },
                },
                "required": ["process_id"],
            },
        
            annotations=READONLY,
        ),
        Tool(
            name="help",
            description=(
                "Show what this MCP server can do, grouped by workflow. "
                "Call this when the user asks 'what can you do', 'help', "
                "'what tools do you have', or seems unsure where to start."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "Optional: filter to a specific area. "
                            "One of: explore, build, audit, calculate, "
                            "scripting, epd, connect"
                        ),
                        "enum": [
                            "explore", "build", "audit", "calculate",
                            "scripting", "epd", "connect"
                        ],
                    },
                },
            },
            annotations=READONLY,
        ),
    ]


# Tools whose results should be presented as artifacts
ARTIFACT_TOOLS = {
    "calculate", "contribution_analysis", "monte_carlo",
    "inventory_flows", "scenarios", "sensitivity",
}

PRESENTATION_HINT = (
    "Formatting note: these results are best presented as a "
    "chart or table rather than narrated as prose. A short "
    "summary sentence followed by a visual is ideal.\n\n"
    "IMPORTANT: Each impact category has its own unit and "
    "scale. Categories are NOT comparable by magnitude — "
    "e.g. 2 billion kBq (ionizing radiation) does not mean "
    "a larger environmental problem than 6 kg CO2eq (global "
    "warming). Never normalise categories onto a single axis "
    "or rank them by raw value. Present each category with "
    "its own value and unit. If a comparative view is needed, "
    "use the normalised or endpoint-level method instead."
)


class LegacyTools:
    """Runs the v1 tools against an engine."""

    def __init__(self, get_engine):
        self._get_engine = get_engine

    @property
    def lca(self):
        return self._get_engine()

    def names(self) -> set:
        return {t.name for t in tool_definitions()}

    def call(self, name: str, arguments: dict) -> str:
        """Run a tool and return the text of its reply, as v1 did."""
        if not self.lca:
            return "openLCA is not connected. Check the IPC server is running."
        try:
            result = self._dispatch(name, arguments)
            return self.format_result(name, result)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return json.dumps({"error": str(e), "tool": name})

    @staticmethod
    def format_result(name: str, result: dict) -> str:
        if name in ARTIFACT_TOOLS:
            # Compact format: instruction first, then minimal JSON
            count = 0
            if "impacts" in result:
                count = len(result["impacts"])
            elif "categories" in result:
                count = len(result["categories"])
            elif "statistics" in result:
                count = len(result["statistics"])
            elif "results" in result:
                count = len(result["results"])
            elif "flows" in result:
                count = len(result["flows"])

            summary = (
                f"{name}: {count} categories/items calculated for "
                f"{result.get('system', result.get('method', '?'))}."
            )
            return (
                f"{PRESENTATION_HINT}\n\n"
                f"{summary}\n\n"
                f"{json.dumps(result, separators=(',', ':'))}"
            )
        # Exploration/build tools: readable JSON
        return json.dumps(result, indent=2)

    def _dispatch(self, name: str, args: dict) -> dict:
        """Route tool calls to LCA functions."""

        if name == "database_info":
            return self.lca.get_database_info()

        elif name == "list_dq_systems":
            return self.lca.list_dq_systems()

        elif name == "set_database_family":
            return self.lca.set_database_family(args["family"])

        elif name == "list_systems":
            return self.lca.list_product_systems(
                args.get("search_term", ""))

        elif name == "list_methods":
            return self.lca.list_impact_methods(
                args.get("search_term", ""))

        elif name == "system_parameters":
            return self.lca.get_system_parameters(
                args["system"],
                args.get("name_filter", ""))

        elif name == "global_parameters":
            return self.lca.get_global_parameters(
                args.get("name_filter", ""))

        # ── model building ───────────────────────────

        elif name == "find_unit":
            return self.lca.find_unit(args["unit_name"])

        elif name == "edit_flow":
            return self.lca.edit_flow(args["flow_id"], args["operations"])

        elif name == "create_global_parameter":
            return self.lca.create_global_parameter(
                args["name"],
                args.get("value"),
                args.get("formula"),
                args.get("description", ""))

        elif name == "create_flow":
            return self.lca.create_flow(
                args["name"],
                args["unit"],
                args.get("category", ""),
                args.get("flow_type", "product"))

        elif name == "create_bridge":
            return self.lca.create_bridge(
                args["name"],
                args["unit"],
                args.get("category", ""),
                args.get("provider_id"),
                args.get("provider_flow_id"),
                args.get("waste", False))

        elif name == "create_process":
            return self.lca.create_process(
                args["name"],
                args["category"],
                args["exchanges"],
                args.get("parameters"),
                args.get("description", ""),
                args.get("location"),
                args.get("flow_schema"),
                args.get("process_schema"))

        elif name == "edit_process":
            return self.lca.edit_process(
                args["process_id"],
                args.get("add_exchanges"),
                args.get("update_exchanges"),
                args.get("remove_exchanges"),
                args.get("add_parameters"),
                args.get("update_parameters"),
                args.get("description"),
                args.get("category"),
                args.get("location"))

        elif name == "delete_entity":
            return self.lca.delete_entity(
                args["entity_type"],
                args["entity_id"])

        # ── model extraction and audit ───────────────

        elif name == "extract_model":
            return self.lca.extract_model(args["category"])

        elif name == "audit_model":
            return self.lca.audit_model(args["category"])

        elif name == "validate_system":
            return self.lca.validate_system(
                args["system"],
                args.get("test_calculate", False))

        elif name == "create_system":
            return self.lca.create_product_system(
                args["process"],
                args.get("linking", "prefer_defaults"),
                args.get("target_amount"),
                args.get("target_unit"),
                args.get("target_flow_property"),
                args.get("category"))

        elif name == "get_system_links":
            return self.lca.get_system_links(
                args["system"],
                args.get("search_term", ""),
                args.get("limit", 50))

        elif name == "calculate":
            return self.lca.calculate_impacts(
                args["system"], args["method"],
                allocation=args.get("allocation"))

        elif name == "upstream_tree":
            return self.lca.upstream_tree(
                args["system"], args["method"], args["category"],
                args.get("levels", 3), args.get("top", 5),
                allocation=args.get("allocation"),
                with_quality=args.get("with_quality", True))

        elif name == "find_flow_usage":
            return self.lca.find_flow_usage(
                args["flow_id"], args.get("max_hits", 10))

        elif name == "contribution_analysis":
            return self.lca.contribution_analysis(
                args["system"],
                args["method"],
                args.get("threshold_pct", 0.1),
                args.get("max_contributors", 30),
                args.get("categories"),
                allocation=args.get("allocation"))

        elif name == "monte_carlo":
            return self.lca.monte_carlo(
                args["system"],
                args["method"],
                args.get("iterations", 1000),
                allocation=args.get("allocation"))

        elif name == "inventory_flows":
            return self.lca.inventory_flows(
                args["system"],
                args["method"],
                max_flows=args.get("max_flows", 50),
                allocation=args.get("allocation"))

        elif name == "data_quality":
            return self.lca.get_data_quality(args["process_id"])

        elif name == "scenarios":
            return self.lca.run_scenarios(
                args["system"], args["method"], args["scenarios"],
                allocation=args.get("allocation"))

        elif name == "scenarios_csv":
            csv_path = validate_file_path(args["csv_path"], must_exist=True)
            output_path = validate_file_path(args["output_path"]) if args.get("output_path") else ""
            return self.lca.run_scenarios_csv(
                args["system"],
                args["method"],
                csv_path,
                output_path,
                allocation=args.get("allocation"))

        elif name == "sensitivity":
            return self.lca.run_sensitivity(
                args["system"],
                args["method"],
                args["parameters"],
                args.get("variation_pct", 20.0),
                allocation=args.get("allocation"))

        elif name == "sensitivity_csv":
            csv_path = validate_file_path(args["csv_path"], must_exist=True)
            output_path = validate_file_path(args["output_path"]) if args.get("output_path") else ""
            return self.lca.run_sensitivity_csv(
                args["system"],
                args["method"],
                csv_path,
                args.get("variation_pct", 20.0),
                output_path,
                allocation=args.get("allocation"))

        elif name == "search_processes":
            return self.lca.search_processes(
                args["search_term"],
                args.get("category_filter", ""),
                args.get("location_filter", ""),
                args.get("limit", 20))

        elif name == "search_flows":
            return self.lca.search_flows(
                args.get("search_term", ""),
                args.get("category_filter", ""),
                args.get("limit", 20))

        elif name == "chemical_synonyms":
            return self.lca.chemical_synonyms(
                args["chemical_name"],
                args.get("search_database", True),
                args.get("max_synonyms", 20))

        elif name == "process_details":
            return self.lca.get_process_details(args["process_id"])

        elif name == "help":
            return self._get_help(args.get("topic"))

        else:
            return {"error": f"Unknown tool: {name}"}

    def _get_help(self, topic: str = None) -> dict:
        """Return capability summary grouped by workflow."""
        sections = {
            "explore": {
                "title": "Explore your database",
                "description": "Search and inspect what is in the connected openLCA database.",
                "tools": [
                    "database_info: overview and entity counts",
                    "list_systems: find product systems",
                    "list_methods: find impact assessment methods",
                    "search_processes: find processes by name, location, or category",
                    "search_flows: find flows by name or folder",
                    "process_details: full info on one process",
                    "system_parameters: parameters in a product system",
                    "global_parameters: database-level parameters",
                    "find_unit: look up units and flow properties",
                    "chemical_synonyms: PubChem synonym search to find database matches",
                ],
            },
            "build": {
                "title": "Build a model",
                "description": "Create processes, flows, bridges, and product systems. Changes are saved to the database.",
                "tools": [
                    "create_global_parameter: make or update a database-level parameter (value or formula)",
                    "edit_flow: add or update a flow's properties, or change its reference property",
                    "create_flow: make a product, waste, or elementary flow",
                    "create_bridge: make a bridge flow and process linking to a background database",
                    "create_process: build a process with exchanges and parameters",
                    "edit_process: modify an existing process",
                    "create_system: create a product system from a process",
                    "delete_entity: remove a process, flow, or system (irreversible, requires confirmation)",
                ],
            },
            "audit": {
                "title": "Check and review a model",
                "description": "Validate structure, extract model data, and assess data quality.",
                "tools": [
                    "validate_system: structural validation of a product system",
                    "audit_model: check all processes in a model folder",
                    "extract_model: pull everything from a folder for inspection",
                    "get_system_links: see which providers are linked in a system",
                    "data_quality: pedigree matrices and uncertainty for a process",
                ],
            },
            "calculate": {
                "title": "Run calculations",
                "description": "Impact assessment, scenarios, sensitivity, Monte Carlo, and contribution analysis.",
                "tools": [
                    "calculate: baseline impact assessment",
                    "contribution_analysis: which processes drive each impact category",
                    "scenarios: compare parameter variations",
                    "sensitivity: vary parameters individually (+/- percentage)",
                    "monte_carlo: uncertainty simulation",
                    "inventory_flows: raw elementary flows (LCI level)",
                    "scenarios_csv: run scenarios from a CSV file",
                    "sensitivity_csv: run sensitivity from a CSV file",
                ],
            },
            "scripting": {
                "title": "Standalone scripts and automation",
                "description": (
                    "For repeated analyses, standalone Python scripts run "
                    "without AI tokens. I can generate CSVs and scripts, or "
                    "point you to tested tools on GitHub."
                ),
                "resources": [
                    "Scenarios script: github.com/Below280/openLCA-IPC-tools-python/tree/main/openLCA-scenarios",
                    "Sensitivity script: github.com/Below280/openLCA-IPC-tools-python/tree/main/openLCA-sensitivity",
                    "Prospective electricity: github.com/Below280/openLCA-IPC-tools-python/tree/main/prospective-electricity",
                    "R client: github.com/Below280/openLCA-IPC-tools-r",
                    "Fortran client: github.com/Below280/openLCA-IPC-tools-fortran",
                ],
            },
            "epd": {
                "title": "Build an EPD model",
                "description": (
                    "I can build an EN15804 EPD model from an LCI document. "
                    "The workflow maps items to lifecycle modules (A1-D), "
                    "creates the folder structure, bridge processes, module "
                    "processes, and product systems. Ask me to 'build an EPD' "
                    "to start."
                ),
            },
            "connect": {
                "title": "Connect from other languages",
                "description": (
                    "I have the full IPC protocol specification and can "
                    "generate client code for any language. Tested clients "
                    "exist for Python, R, and Fortran. For other languages "
                    "(Go, Rust, JavaScript, Julia, etc.) I can generate "
                    "experimental code from the protocol spec."
                ),
            },
        }

        if topic and topic in sections:
            return {
                "topic": topic,
                **sections[topic],
                "note": (
                    "This server carries detailed operational instructions "
                    "which use significant context. For lighter interactions, "
                    "simple explore and calculate queries are the most "
                    "token-efficient."
                ),
            }

        return {
            "capabilities": {k: v["title"] for k, v in sections.items()},
            "total_tools": len(tool_definitions()),
            "detail": "Call help with a topic for more detail: explore, build, audit, calculate, scripting, epd, or connect.",
            "note": (
                "This server carries detailed operational instructions "
                "which use significant context. For lighter interactions, "
                "simple explore and calculate queries are the most "
                "token-efficient."
            ),
        }
