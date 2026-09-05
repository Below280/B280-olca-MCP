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
from mcp.types import Resource, Tool, TextContent, ToolAnnotations
import mcp.types as types

from olca_ipc import Client
import olca_schema as o

from .functions import LCAFunctions
from .ipc_reference import IPC_PROTOCOL_REFERENCE
from .openlca_resources import OPENLCA_RESOURCES

logging.basicConfig(level=logging.INFO)
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


def validate_file_path(path: str, must_exist: bool = False) -> str:
    """Resolve and validate a file path. Blocks path traversal."""
    resolved = os.path.realpath(os.path.expanduser(path))
    # Block obvious traversal attempts
    if ".." in path:
        raise ValueError(f"Path traversal not allowed: {path}")
    if must_exist and not os.path.isfile(resolved):
        raise FileNotFoundError(f"File not found: {resolved}")
    return resolved

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

7. CHEMICAL SYNONYMS. If a chemical search returns few or no
   results, offer to try a deeper search using PubChem synonyms.
   Say: 'I didn't find much for [name]. Would you like me to
   try a deeper search using PubChem chemical synonyms?' Only
   call chemical_synonyms after the user agrees. Never call it
   automatically. Common examples where this helps:
     - caustic soda → sodium hydroxide
     - MEK → methyl ethyl ketone → butanone
     - PET → polyethylene terephthalate
     - baking soda → sodium bicarbonate

8. FINDING PROXIES. When asked to find the best proxy or match
   for a material, search broadly, pull process_details on the
   top candidates, and present them with geography, technology
   description, and any notes about representativeness. Let the
   user choose. If the material has trade names or synonyms,
   offer the PubChem search as a fallback.

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

BUILDING AN EPD MODEL FROM AN LCI
----------------------------------
When a user asks to build an EPD, create an EPD model, or convert an
LCI into an openLCA model for EPD purposes, follow this workflow.

Step 1: Module mapping.
  An EPD reports results by EN15804 lifecycle module. Before building
  anything, the LCI data must be mapped to modules:

    A1  Raw material supply
    A2  Transport to factory
    A3  Manufacturing
    C1  Deconstruction/demolition
    C2  Transport to waste processing
    C3  Waste processing
    C4  Disposal
    D   Benefits and loads beyond the system boundary

  Ask the user to confirm which LCI items belong to which module.
  If the LCI document already groups items by module, use that.
  If it does not, make a reasonable assignment based on the item
  descriptions and flag every assumption: 'I have assigned [item]
  to A1 because it appears to be a raw material. Please confirm.'

  Common ambiguities to flag:
    - Electricity: A1 (upstream) or A3 (manufacturing)?
    - Internal transport: A2 or A3?
    - Packaging materials: A1 or A3?
    - Waste treatment of production waste: A3 or C3?

  Do not proceed to building until the user has confirmed the
  module assignments, or has explicitly said 'go ahead with your
  best guess'.

Step 2: Folder structure.
  Create a folder structure that a verifier can read:

    00: Project Name/
    00: Project Name/Bridges
    00: Project Name/A1
    00: Project Name/A2
    00: Project Name/A3
    00: Project Name/C1
    00: Project Name/C2
    00: Project Name/C3
    00: Project Name/C4
    00: Project Name/D

  Only create folders for modules that have data. If the LCI has
  no C1 data, do not create an empty C1 folder.

  Ask the user what to call the project folder.

Step 3: Bridge processes.
  For every background database connection (electricity, transport,
  raw materials, waste treatment), create a bridge process in the
  Bridges subfolder. Each bridge connects the foreground model to
  one background process.

  Use search_processes to find the right background process.
  Present candidates and let the user choose (rule 6: ambiguous
  flows). Name bridges clearly:
    BRIDGE | UK grid electricity | kWh
    BRIDGE | Lorry EURO6 | t*km
    BRIDGE | Waste wood, open burning | kg

Step 4: Module processes.
  For each module that has data, create one process in the
  corresponding subfolder. For example:

    A1: Raw materials        (in 00: Project Name/A1)
    A2: Transport to site    (in 00: Project Name/A2)
    A3: Manufacturing        (in 00: Project Name/A3)

  Each module process:
    - Has a quantitative reference output (the declared unit or
      an intermediate product flowing to the next module)
    - Takes bridge processes as inputs for background connections
    - Uses parameters for quantities where the LCI provides them
    - Has amounts set from the LCI data

  If the LCI provides quantities per declared unit (e.g. per 1 m3
  of timber), use those directly. If quantities are annual totals,
  ask the user for the annual production volume to calculate
  per-unit values.

Step 5: Product systems.
  Create a product system for each module process. Place them in
  matching folders or a dedicated systems folder:

    00: Project Name/A1  (system for A1: Raw materials)
    00: Project Name/A2  (system for A2: Transport to site)
    etc.

  Use prefer_defaults linking. Set the target amount and unit to
  match the declared unit from the EPD scope.

Step 6: Verify.
  After building, run validate_system on each product system.
  Then offer to run a test calculation with EN15804+A2 (EF 3.1)
  to check the results are in a plausible range.

  Flag the user that the model will need:
    - Data quality (pedigree) entries on each exchange
    - Process documentation fields filled in
    - Review by an LCA practitioner before submission

  These cannot be done through this tool and must be completed
  in the openLCA GUI.

Throughout this workflow, explain what you are doing and why.
The user may not know EN15804 module codes. Use the full names
(e.g. 'A1: Raw material supply') not just the codes.

CALCULATION PATTERNS
--------------------
- Calculations target ProductSystem objects, never bare Processes.
- Always dispose results after use.
- ParameterRedef via CalculationSetup for scenarios/sensitivity.
- Contribution analysis: get_tech_flows() then get_total_impacts_of(tf).

STANDALONE SCRIPTS FOR REPRODUCIBILITY
---------------------------------------
After running scenario or sensitivity calculations through this MCP,
offer the user the option to download standalone Python scripts that
do the same thing without the MCP. Frame it as a reproducibility and
cost-saving option:

  'These results are ready. If you want to re-run this analysis
  later without using AI tokens, Below280 publishes standalone
  Python scripts that do the same calculations from a CSV file.
  I can generate the CSV for you now, and the script runs directly
  against openLCA with no AI in the loop.'

The scripts are at:
  https://github.com/Below280/openLCA-IPC-tools-python

Specific tools and their standalone equivalents:

  scenarios / scenarios_csv →
    Script: openLCA-scenarios/B280_olca_scenarios.py
    CSV format: first column 'Parameter', one column per scenario.
    README: https://github.com/Below280/openLCA-IPC-tools-python/tree/main/openLCA-scenarios

  sensitivity / sensitivity_csv →
    Script: openLCA-sensitivity/B280_olca_sensitivity.py
    CSV format: one parameter name per line.
    README: https://github.com/Below280/openLCA-IPC-tools-python/tree/main/openLCA-sensitivity

When to offer this:
  - After completing a scenario or sensitivity calculation
  - When the user asks about reproducibility or automation
  - When the user mentions running the same analysis repeatedly
  - When the user asks about saving costs or tokens

What to offer:
  1. Generate the CSV file they would need to run the standalone
     script (use the parameter names and values from the calculation
     that just ran).
  2. Link to the script on GitHub with the specific README.
  3. If they need something the standard script does not cover
     (different output format, additional post-processing, custom
     parameter grouping), offer to generate a custom Python script
     based on the patterns in the repository. The scripts use
     olca-ipc and olca-schema, same as this MCP server.

Do not push this on every calculation. Mention it once after the
first scenario or sensitivity run in a conversation, then only
again if the user asks about reproducibility or re-running.

The R package is also available for users who prefer R:
  https://github.com/Below280/openLCA-IPC-tools-r
  Install: remotes::install_github("Below280/openLCA-IPC-tools-r")

HEAVY DATABASE OPERATIONS
--------------------------
Some operations modify hundreds or thousands of database entities.
These are possible through this MCP but should almost always be
done as standalone scripts instead. The MCP can generate the script.

The guiding principle: if an operation would require more than
about 10 tool calls, offer to generate a Python script instead.
Frame it honestly:

  'I can do this through the MCP, but it would involve [N]
  individual operations and use a lot of tokens. A Python script
  does the same thing in seconds with no token cost. Want me to
  generate the script instead?'

If the user says 'just do it', proceed. But make the offer first.

DATABASE PARAMETERISATION
  The prospective electricity script parameterises ecoinvent
  electricity market processes so their technology shares can be
  adjusted for future grid scenarios:
    https://github.com/Below280/openLCA-IPC-tools-python/tree/main/prospective-electricity

  The same approach works for parameterising any set of processes
  in the database: transport modes, material mixes, energy sources.
  The pattern is:
    1. Find the target process (e.g. a market mix)
    2. Read its exchanges and current amounts
    3. Create a parameter for each exchange amount
    4. Set the parameter default to the original value
    5. Replace the fixed amount with the parameter name
    6. Save the modified process

  WARNING: This permanently modifies database processes. Changes
  are IRREVERSIBLE without restoring from a backup. Always tell
  the user:

    'This will permanently modify [N] processes in your database.
    The original fixed values will be replaced with parameters.
    This cannot be undone without restoring from a database backup.
    I strongly recommend making a backup first. Shall I generate
    a script you can review before running, or do you want me to
    proceed directly?'

  The script route is strongly preferred because:
    - The user can review every change before it executes
    - It runs in seconds with no token cost
    - It can be version-controlled and re-run on fresh databases
    - It documents exactly what was changed

  If generating a custom parameterisation script, base it on the
  patterns in B280_olca_elec_parameterise.py. It uses olca-ipc
  and olca-schema, reads the existing process exchanges, creates
  parameters with the original values as defaults, and saves the
  modified processes.

OTHER HEAVY OPERATIONS where scripting is preferred:
  - Batch-creating dozens of processes from a spreadsheet
  - Renaming or recategorising large numbers of entities
  - Extracting data quality entries across an entire database
  - Building product systems for many processes at once
  - Any operation that loops over most entities in the database

For all of these, the MCP can generate a working Python script
using olca-ipc patterns from the Below280 repository. The user
runs it locally, reviews the output, and keeps the script for
reproducibility.

FEEDBACK
--------
If something went notably well or notably wrong during a session,
offer once to help the user send feedback to Below280. Do not
push this. A single sentence at the end of the interaction:

  'If you would like to let Below280 know about [this issue /
  how this went], I can draft a short feedback report for you
  to send.'

Only offer when there is something specific to report: a bug,
an unexpected error, a workflow that worked particularly well,
or a feature gap. Do not offer on routine successful calculations.

Feedback channels:
  GitHub issues: https://github.com/Below280/B280-olca-MCP/issues
  Email: mcp-feedback@below280.com

If the user accepts, draft a short report (no more than 15 lines)
containing:
  - What the user asked the MCP to do
  - Which tools or IPC methods were involved
  - Whether it succeeded or failed
  - Any error messages or unexpected behaviour
  - Suggested improvement (if applicable)
  - Steps to reproduce (if a bug)

Before presenting the draft, strip out:
  - Company and product names
  - Database entity names that could identify the project
  - Inventory quantities and impact results
  - File paths, usernames, and system details
  - Any licensed database content

Replace stripped content with [REDACTED] or generic placeholders.
Present the draft to the user for review. They copy it and send
it themselves. The MCP does not send anything automatically.

HELPING USERS CONNECT FROM OTHER LANGUAGES
--------------------------------------------
The IPC protocol reference (lca://knowledge/ipc-protocol) contains
every JSON-RPC method, parameter format, and response structure.
When a user asks about connecting to openLCA from any programming
language, read that resource and use it to generate working code.

Existing tested implementations to reference:
  Python (official): pip install olca-ipc
  R (Below280):      https://github.com/Below280/openLCA-IPC-tools-r
  Fortran (Below280): https://github.com/Below280/openLCA-IPC-tools-fortran

For Python, direct the user to the official olca-ipc package.
For R, direct them to the Below280 olcar package.
For Fortran, direct them to the Below280 Fortran client.

For any other language (Go, Rust, JavaScript, Julia, C#, etc.):
  1. Read the IPC protocol reference resource.
  2. Generate client code using the protocol spec.
  3. Use the R or Fortran implementations as architectural
     patterns: both are thin HTTP clients that POST JSON-RPC
     requests and parse responses. The R client uses httr2,
     the Fortran client uses system curl.
  4. Mark all generated code clearly as EXPERIMENTAL:

     'This code is generated from the openLCA IPC protocol
     specification and has not been tested against a live
     server. The protocol itself is stable and well-documented,
     but this specific implementation needs testing. Start with
     a simple call (list processes) and verify the response
     before building on it.'

  5. Start with the basics: connect, list descriptors, run a
     calculation, get results, dispose. These five operations
     cover most use cases and validate that the client works.

Key implementation notes to include when generating code:
  - The protocol is HTTP POST to localhost:8080, Content-Type
    application/json. No auth, no sessions.
  - JSON field names use @id and @type (JSON-LD). Most JSON
    libraries handle these as ordinary keys. json-fortran
    needed a workaround (documented in the Fortran repo).
  - Calculations are async: start with result/calculate, poll
    result/state until ready, then query results, then dispose.
  - result/dispose is mandatory. Leaked results consume server
    memory until restart.
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
            ]

        @self.server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            if uri == "lca://database/info" and self.lca:
                return json.dumps(self.lca.get_database_info(), indent=2)

            if uri == "lca://knowledge/instructions":
                return ASSISTANT_INSTRUCTIONS

            if uri == "lca://knowledge/ipc-protocol":
                return IPC_PROTOCOL_REFERENCE

            if uri == "lca://knowledge/openlca-resources":
                return OPENLCA_RESOURCES

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
                        },
                        "required": ["system", "method"],
                    },
                
                    annotations=CALCULATE,
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

        # ── tool dispatch ────────────────────────────────────

        # Tools whose results should be presented as artifacts
        ARTIFACT_TOOLS = {
            "calculate", "contribution_analysis", "monte_carlo",
            "inventory_flows", "scenarios", "sensitivity",
        }

        PRESENTATION_HINT = (
            "Formatting note: these results are best presented as a "
            "chart or table rather than narrated as prose. A short "
            "summary sentence followed by a visual is ideal."
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
            csv_path = validate_file_path(args["csv_path"], must_exist=True)
            output_path = validate_file_path(args["output_path"]) if args.get("output_path") else ""
            return self.lca.run_scenarios_csv(
                args["system"],
                args["method"],
                csv_path,
                output_path)

        elif name == "sensitivity":
            return self.lca.run_sensitivity(
                args["system"],
                args["method"],
                args["parameters"],
                args.get("variation_pct", 20.0))

        elif name == "sensitivity_csv":
            csv_path = validate_file_path(args["csv_path"], must_exist=True)
            output_path = validate_file_path(args["output_path"]) if args.get("output_path") else ""
            return self.lca.run_sensitivity_csv(
                args["system"],
                args["method"],
                csv_path,
                args.get("variation_pct", 20.0),
                output_path)

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
            "total_tools": 31,
            "detail": "Call help with a topic for more detail: explore, build, audit, calculate, scripting, epd, or connect.",
            "note": (
                "This server carries detailed operational instructions "
                "which use significant context. For lighter interactions, "
                "simple explore and calculate queries are the most "
                "token-efficient."
            ),
        }

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





