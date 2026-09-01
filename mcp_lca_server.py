"""
openLCA MCP Server

Exposes openLCA IPC functionality as MCP tools for Claude Desktop.
Calculations always target product systems and all results are
from the connected database - nothing fabricated.

Requires openLCA running with IPC server on port 8080.
"""

import asyncio
import json
import logging
import os
import sys

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent
import mcp.types as types

from olca_ipc import Client
import olca_schema as o

from lca_functions import LCAFunctions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("openLCA-MCP")

# ── Knowledge base for Claude ────────────────────────────────
ASSISTANT_INSTRUCTIONS = """
openLCA MCP Assistant - Instructions
=====================================

Read this first. Follow these instructions on every interaction.

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

BEHAVIOUR RULES
---------------
1. NEVER USE EM DASHES ( — ) ANYWHERE IN ANY OUTPUT. Not in prose,
   not in tables, not in summaries, not in findings. Use commas,
   colons, semicolons, full stops, or parentheses instead. This is
   not optional. Every em dash is a failure.

2. ALWAYS present calculation results visually: charts, tables, or
   artifacts rather than prose paragraphs of numbers. If the client
   supports React artifacts, use recharts with the Below280 palette
   (#2e0a4a, #12ebf2, #ff5c05). If not, use well-formatted tables.
   Include a results table with the option to copy as CSV.
   The B280_LCA_Dashboard.jsx template in the repository shows the
   expected layout: category selector, bar charts for scenarios,
   tornado for sensitivity, horizontal bars for contributions,
   and a table with CSV export. Use this pattern.

3. BEFORE running any calculation, check what impact methods are
   available (list_methods) and ASK the user which one to use.
   Do not assume. Common options:
     - 'EN15804+A2 (EF 3.1)' for EPD work (38 categories)
     - 'EF v3.1' for general European LCA
   If the user says 'EPD' or 'EN15804', use the first. If they say
   'EF' or don't specify, ask.

4. Keep responses concise. Results go in artifacts, not prose.

5. CONVERSATION FIRST. This is the hardest rule to follow because
   your training biases you toward doing maximal work rather than
   asking a short question. Resist that bias. Asking is not a
   failure. Asking is faster, cheaper, and more accurate than
   guessing.

   BEFORE doing multi-step work, ask what the user actually wants.
   A single clarifying question saves 10 unnecessary tool calls.

   Specific triggers to STOP AND ASK:
     - choosing an impact method
     - validating or auditing a model
     - deleting anything
     - deciding the database family
     - picking a background process from multiple candidates
     - choosing parameters for sensitivity (which ones? what %)
     - deciding how to visualise results
     - ANY request that could be interpreted multiple ways

   If the user asks for one thing, do that thing. Do not chain
   extra tools 'while you are at it'. Do not build visualisations
   that were not requested. Do not run analyses that were not
   asked for. If something useful could be done next, suggest it
   in one sentence and wait.

   The correct response to ambiguity is a question, not a guess.

6. AMBIGUOUS FLOWS. When searching for a background process and
   getting multiple candidates, do NOT silently pick one. Present
   the options and ask the user to choose. This is critical for:
     - Electricity (regional grid mixes vary enormously)
     - Transport (vehicle type, EURO class, mode)
     - Chemicals (production routes, geographic variants)
     - Metals (primary vs secondary, region)
   Show the user the name, location, and a brief description of
   each candidate. Let them decide. The choice of background
   process often matters more than any parameter value.

FOLDER CONVENTIONS
------------------
When building models, organise processes and flows in a folder
starting with '00: ' (e.g. '00: My Project'). This is a useful
convention that keeps model content separate from background
databases. Ask the user what they want to call their folder.

Do NOT describe this as a 'Below280 convention'. It is a general
best practice for anyone using this tool.

When checking or reviewing an existing model, ask the user which
folder (category) their model is in. Then use extract_model or
audit_model on that folder.

Subfolders:
  00: My Project/Bridges     → bridge processes and flows
  00: My Project/Modules/A1  → lifecycle stage processes
  00: My Project/Shared Flows → custom product flows

SETUP & TROUBLESHOOTING
-----------------------
1. The IPC server must be running in openLCA:
   Tools > Developer Tools > IPC Server > green play button, port 8080.

2. After creating or modifying anything via this MCP, the user must
   press the REFRESH button in openLCA (circular arrow in toolbar)
   to see changes in the GUI.

3. openLCA must stay open while this MCP is running.

SCALING (CRITICAL)
------------------
openLCA scales processes automatically to meet demand. A process
outputting 1 kg feeding one that needs 5 kg is correct: openLCA
runs it 5 times. NEVER flag amount differences between connected
processes. Same-property unit conversions (MJ/kWh, kg/t) are also
handled automatically.

IMPACT METHODS
--------------
- For EPD: 'EN15804+A2 (EF 3.1)' (38 categories, full method).
  NOT 'Environment | EN15804+A2 (EF v3.1)' (20 categories, wrong).
- For general LCA: 'EF v3.1'.
- Match names exactly. 'EF 3.1' and 'EF v3.1' are different.

DATABASE FAMILIES
-----------------
Different databases use different flow property names. Before
building any model or creating flows, establish which family:

1. ASK the user: 'Is this an ecoinvent-family database (ecoinvent,
   EN15804GD, HiQLCD, BAFU) or FLCAC (LCA Commons, US LCI, USEEIO)?'
2. If they answer → call set_database_family with their answer.
3. If they say 'don't know' → call database_info, which auto-detects
   by checking flow property names. The result appears as
   'database_family' in the response.
4. If auto-detect returns 'unknown' → tell the user the detection
   was inconclusive and ask if they want to proceed with ecoinvent
   conventions as the default. If they want certainty, search for
   a known flow property like 'Duration' (FLCAC) or 'Time'
   (ecoinvent) using the flow property list.

  ecoinvent family: uses 'Time', 'Mass transport', 'Volume'.
  FLCAC family: uses 'Duration', 'Goods transport (mass*distance)',
    'Normal Volume', plus 'Power', 'Mole', 'Radioactivity'.

Once set, the mapping stays for the whole conversation.

CHECKING A MODEL
-----------------
When asked to 'check', 'review', or 'validate' a model, there
are three tiers. Do NOT stop at tier 1 and report success.
Explain all three tiers to the user and ask which they want.

Tier 1 - Structural validation:
  validate_system and audit_model. Do links resolve? Are units
  and providers present? Any duplicate exchanges or orphaned
  parameters? This catches mechanical errors only. A clean
  result here does NOT mean the model is correct.

Tier 2 - Source comparison:
  Compare the model's exchanges against the original data source
  (a paper, spreadsheet, LCI report). ASK the user to provide
  the source. Then use extract_model and compare exchange by
  exchange: quantities, units, and whether anything in the
  source is missing from the model. This catches transcription
  errors, unit conversion mistakes, and missing inputs.

Tier 3 - Plausibility:
  Do the numbers make physical/chemical sense? Are mass balances
  reasonable? Are energy inputs in the right order of magnitude?
  This requires domain knowledge. Flag anything that looks
  implausible and explain why, but acknowledge when you are
  uncertain.

The default should be: run tier 1, then ask the user if they
have a source document for tier 2, then offer tier 3 as a
domain review. Never present tier 1 alone as 'the model
checks out'.

REFERENCE DOCUMENTATION
------------------------
Search in this order:
1. Below280 Knowledge Base: https://below280.com/knowledge-base/
   Scripting: https://below280.com/knowledge-base/openlca-scripting/
2. openLCA Manual: https://greendelta.github.io/openLCA2-manual/introduction/index.html

CALCULATION PATTERNS
--------------------
- Calculations target ProductSystem objects, never bare Processes.
- Always dispose results after use.
- ParameterRedef via CalculationSetup for scenarios/sensitivity.
- Contribution analysis: get_tech_flows() then get_total_impacts_of(tf).
"""


class OpenLCAMCPServer:

    def __init__(self):
        self.server = Server("openLCA-MCP")
        self.client = None
        self.lca = None

    # ── initialisation ───────────────────────────────────────

    async def initialise(self) -> bool:
        port = int(os.getenv("OLCA_PORT", "8080"))
        logger.info(f"Connecting to openLCA on port {port}")
        try:
            self.client = Client(port)
            processes = self.client.get_descriptors(o.Process)
            logger.info(f"Connected: {len(processes)} processes")
            self.lca = LCAFunctions(self.client)
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    # ── tool definitions ─────────────────────────────────────

    def setup_handlers(self):

        @self.server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            return [
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
                        "IMPORTANT: Read this first. Operational instructions, "
                        "openLCA knowledge, reference links, and visualisation "
                        "guidance for the LCA assistant."
                    ),
                    mimeType="text/plain",
                ),
            ]

        @self.server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            if uri == "lca://database/info" and self.lca:
                return json.dumps(self.lca.get_database_info(), indent=2)

            if uri == "lca://knowledge/instructions":
                return ASSISTANT_INSTRUCTIONS

            return f"Unknown resource: {uri}"

        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
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
                ),
                # ── model building tools ─────────────────
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
                            "waste": {
                                "type": "boolean",
                                "description": "True for waste treatment bridges (default: false)",
                                "default": False,
                            },
                        },
                        "required": ["name", "unit"],
                    },
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
                        "NOTE: openLCA scales processes automatically."
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
                                            "description": "Numeric amount (ignored if formula is set)",
                                            "default": 0,
                                        },
                                        "formula": {
                                            "type": "string",
                                            "description": "Parameter formula (optional, overrides amount)",
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
                                    },
                                    "required": ["flow_id", "unit", "is_input"],
                                },
                            },
                            "parameters": {
                                "type": "array",
                                "description": "Process-scoped parameters (optional)",
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
                            "description": {
                                "type": "string",
                                "description": "Process description (optional)",
                            },
                        },
                        "required": ["name", "category", "exchanges"],
                    },
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
                ),
                Tool(
                    name="create_system",
                    description=(
                        "Create a product system from a process. This auto-links "
                        "the supply chain so the system is ready for calculation. "
                        "Optionally set the target amount, unit, and flow property. "
                        "Convention: the source process should be in a folder "
                        "starting with '00: '."
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
                        },
                        "required": ["system", "method"],
                    },
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
                        },
                        "required": ["system", "method"],
                    },
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
                        },
                        "required": ["system", "method"],
                    },
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
                        },
                        "required": ["system", "method"],
                    },
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
                        },
                        "required": ["system", "method", "scenarios"],
                    },
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
                                    "Path for the results CSV (optional, "
                                    "auto-generated from method name if omitted)"
                                ),
                            },
                        },
                        "required": ["system", "method", "csv_path"],
                    },
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
                        },
                        "required": ["system", "method", "parameters"],
                    },
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
                                    "Path for the results CSV (optional, "
                                    "auto-generated from method name if omitted)"
                                ),
                            },
                        },
                        "required": ["system", "method", "csv_path"],
                    },
                ),
                Tool(
                    name="search_processes",
                    description=(
                        "Search for processes by name and/or category folder. "
                        "Returns process IDs, names, and categories. Shows "
                        "total_matches so you know if results were truncated."
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
                            "limit": {
                                "type": "integer",
                                "description": "Maximum results (default: 20)",
                                "default": 20,
                            },
                        },
                        "required": ["search_term"],
                    },
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
                ),
            ]

        # ── tool dispatch ────────────────────────────────────

        # Tools whose results should be presented as artifacts
        ARTIFACT_TOOLS = {
            "calculate", "contribution_analysis", "monte_carlo",
            "inventory_flows", "scenarios", "sensitivity",
        }

        PRESENTATION_HINT = (
            "ACTION REQUIRED: Present these results visually. If your "
            "environment supports React artifacts, use recharts with "
            "palette #2e0a4a, #12ebf2, #ff5c05 and include a category "
            "selector and results table with CSV export. If not, use "
            "a well-formatted table. Write at most two sentences of "
            "summary. Do not narrate the numbers as prose."
        )

        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict
        ) -> list[types.TextContent]:

            if not self.lca:
                return [TextContent(
                    type="text",
                    text="openLCA is not connected. Check the IPC server is running.",
                )]

            try:
                result = self._dispatch(name, arguments)

                if name in ARTIFACT_TOOLS:
                    # Compact format: instruction first, then minimal JSON
                    # This structure discourages narration and encourages
                    # artifact creation
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

                    return [TextContent(
                        type="text",
                        text=(
                            f"{PRESENTATION_HINT}\n\n"
                            f"{summary}\n\n"
                            f"{json.dumps(result, separators=(',', ':'))}"
                        ),
                    )]
                else:
                    # Exploration/build tools: readable JSON
                    return [TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )]

            except Exception as e:
                logger.error(f"Tool {name} failed: {e}", exc_info=True)
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": str(e), "tool": name}),
                )]

    def _dispatch(self, name: str, args: dict) -> dict:
        """Route tool calls to LCA functions."""

        if name == "database_info":
            return self.lca.get_database_info()

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
                args.get("waste", False))

        elif name == "create_process":
            return self.lca.create_process(
                args["name"],
                args["category"],
                args["exchanges"],
                args.get("parameters"),
                args.get("description", ""))

        elif name == "edit_process":
            return self.lca.edit_process(
                args["process_id"],
                args.get("add_exchanges"),
                args.get("update_exchanges"),
                args.get("remove_exchanges"),
                args.get("add_parameters"),
                args.get("update_parameters"),
                args.get("description"),
                args.get("category"))

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
                args["system"], args["method"])

        elif name == "contribution_analysis":
            return self.lca.contribution_analysis(
                args["system"],
                args["method"],
                args.get("threshold_pct", 0.1),
                args.get("max_contributors", 30),
                args.get("categories"))

        elif name == "monte_carlo":
            return self.lca.monte_carlo(
                args["system"],
                args["method"],
                args.get("iterations", 1000))

        elif name == "inventory_flows":
            return self.lca.inventory_flows(
                args["system"],
                args["method"],
                max_flows=args.get("max_flows", 50))

        elif name == "data_quality":
            return self.lca.get_data_quality(args["process_id"])

        elif name == "scenarios":
            return self.lca.run_scenarios(
                args["system"], args["method"], args["scenarios"])

        elif name == "scenarios_csv":
            return self.lca.run_scenarios_csv(
                args["system"],
                args["method"],
                args["csv_path"],
                args.get("output_path", ""))

        elif name == "sensitivity":
            return self.lca.run_sensitivity(
                args["system"],
                args["method"],
                args["parameters"],
                args.get("variation_pct", 20.0))

        elif name == "sensitivity_csv":
            return self.lca.run_sensitivity_csv(
                args["system"],
                args["method"],
                args["csv_path"],
                args.get("variation_pct", 20.0),
                args.get("output_path", ""))

        elif name == "search_processes":
            return self.lca.search_processes(
                args["search_term"],
                args.get("category_filter", ""),
                args.get("limit", 20))

        elif name == "search_flows":
            return self.lca.search_flows(
                args.get("search_term", ""),
                args.get("category_filter", ""),
                args.get("limit", 20))

        elif name == "process_details":
            return self.lca.get_process_details(args["process_id"])

        else:
            return {"error": f"Unknown tool: {name}"}

    # ── server lifecycle ─────────────────────────────────────

    async def run(self):
        if not await self.initialise():
            logger.error("Cannot start without openLCA connection")
            return

        self.setup_handlers()
        logger.info("openLCA MCP server ready")

        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="openLCA-MCP",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )


def main():
    server = OpenLCAMCPServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
