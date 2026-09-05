"""
openLCA IPC Protocol Reference
Served as an MCP resource so AI assistants can help users
connect to openLCA from any programming language.
"""

IPC_PROTOCOL_REFERENCE = """
openLCA IPC Protocol Reference
===============================

This document describes the complete openLCA JSON-RPC IPC protocol. Use it to
build an openLCA client in any language that can make HTTP POST requests and
parse JSON. The protocol is language-agnostic: the same requests work from
Python, R, Fortran, JavaScript, Go, Rust, Julia, or curl.

TRANSPORT
---------
HTTP POST to http://localhost:8080 (default port).
Content-Type: application/json.
No authentication. No sessions. Stateless except for calculation results.

REQUEST FORMAT
--------------
Every request is a JSON-RPC 2.0 object:

    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "data/get/descriptors",
        "params": {"@type": "Process"}
    }

- "id" is an incrementing integer, used to match responses.
- "method" is one of the methods listed below.
- "params" varies by method. Some methods take no params.

RESPONSE FORMAT
---------------
    {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [...]
    }

On error:
    {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32600, "message": "error description"}
    }

ENTITY TYPES
------------
These type strings are used in the @type field:
Process, ProductSystem, ImpactMethod, ImpactCategory, Flow, FlowProperty,
UnitGroup, Parameter, Actor, Source, Location, Currency, SocialIndicator,
DQSystem, Project

JSON-LD CONVENTIONS
-------------------
openLCA uses JSON-LD field names: @type for entity type, @id for UUID.
Most JSON libraries handle these as ordinary string keys. Some (like
json-fortran) treat @ as a path operator and need workarounds.

ENTITY REFERENCES
-----------------
When a method needs a reference to an entity, use:

    {"@type": "ProductSystem", "@id": "uuid-here"}

or:

    {"@type": "Process", "name": "steel production"}

or both. At least one of @id or name is required.


========================================================================
DATA ACCESS METHODS (15 methods)
========================================================================

data/get/descriptors
    params: {"@type": "Process"}
    returns: array of {\"@type\", \"@id\", \"name\", \"category\"}
    Lists all entities of a type. Lightweight (no exchange data).

data/get/descriptor
    params: {"@type": "Process", "@id": "uuid"} or {"@type": "Process", "name": "..."}
    returns: single descriptor object
    Gets one descriptor by ID or name.

data/get
    params: {"@type": "Process", "@id": "uuid"}
    returns: full entity object with all fields (exchanges, parameters, docs)
    Heavy call. Use descriptors for listing, get for detail.

data/get/all
    params: {"@type": "Parameter"}
    returns: array of full entity objects
    Gets every entity of a type. Use sparingly on large databases.

data/get/parameters
    params: {"@type": "ProductSystem", "@id": "uuid"}
    returns: array of parameter objects
    For ProductSystem: returns ParameterRedef objects (name, value, context).
    For Process: returns Parameter objects (name, value, formula, scope).

data/get/providers
    params: {} (all providers) or {"@type": "Flow", "@id": "uuid"}
    returns: array of TechFlow objects {provider: {}, flow: {}}
    Lists which processes provide which product/waste flows.

data/put
    params: full entity object with @type
    returns: descriptor of saved entity
    Inserts or updates. Send the complete object.

data/put/source-file
    params: {"source": {"@type": "Source", "@id": "uuid"},
             "file": {"name": "filename.pdf", "content": "base64-data"}}
    returns: "ok"
    Uploads a file attachment to a Source entity.

data/delete
    params: {"@type": "Process", "@id": "uuid"}
    returns: descriptor of deleted entity
    Deletes an entity. Takes the full entity or a ref.

data/create/system
    params: {"process": {"@type": "Process", "@id": "uuid"},
             "config": {"preferUnitProcesses": true,
                        "providerLinking": "PREFER_DEFAULTS"}}
    returns: descriptor of created ProductSystem
    Creates a linked product system from a process.
    providerLinking options: PREFER_DEFAULTS, ONLY_DEFAULTS,
    IGNORE_DEFAULTS, ONLY_LINK_PROVIDERS.


========================================================================
CALCULATION LIFECYCLE
========================================================================

Step 1: Start calculation
    method: result/calculate
    params: CalculationSetup (see below)
    returns: {"@id": "result-uuid", "isReady": false, "isScheduled": true}

Step 2: Poll until ready
    method: result/state
    params: {"@id": "result-uuid"}
    returns: {"@id": "...", "isReady": true/false, "isScheduled": true/false}
    Poll every 0.5-1 seconds until isReady is true.

Step 3: Query results (any of the result/* methods below)

Step 4: Dispose when finished
    method: result/dispose
    params: {"@id": "result-uuid"}
    CRITICAL: Always dispose. Results consume server memory until disposed
    or the server restarts. Use try/finally or equivalent.

CALCULATION SETUP FORMAT
------------------------
    {
        "target": {"@type": "ProductSystem", "@id": "system-uuid"},
        "impactMethod": {"@type": "ImpactMethod", "@id": "method-uuid"},
        "parameters": [
            {"name": "transport_km", "value": 500,
             "context": {"@type": "Process", "@id": "process-uuid"}},
            {"name": "electricity_kwh", "value": 200}
        ],
        "nwSet": null,
        "allocation": null
    }

- target must be a ProductSystem (not a bare Process).
- parameters is optional. Each entry overrides one parameter.
- context is optional per parameter: null for global, a Process ref for local.
- impactMethod is required for impact results; can be omitted for
  inventory-only calculations.

MONTE CARLO SIMULATION
-----------------------
    method: result/simulate
    params: same CalculationSetup as above
    returns: {"@id": "result-uuid", ...}

Then iterate:
    method: result/simulate/next
    params: {"@id": "result-uuid"}
    returns: state object

After each simulate/next, the result methods return values for
the current iteration. Call simulate/next repeatedly for N iterations,
querying results after each.


========================================================================
RESULT METHODS - STRUCTURE (4 methods)
========================================================================

result/demand
    params: {"@id": "result-uuid"}
    returns: TechFlowValue {techFlow: {provider, flow}, amount}

result/tech-flows
    params: {"@id": "result-uuid"}
    returns: array of TechFlow {provider: {@id, name}, flow: {@id, name}}

result/envi-flows
    params: {"@id": "result-uuid"}
    returns: array of EnviFlow {flow: {@id, name, category}, isInput: bool}

result/impact-categories
    params: {"@id": "result-uuid"}
    returns: array of Ref {@type, @id, name, category, refUnit}


========================================================================
RESULT METHODS - TECH FLOWS (5 methods)
========================================================================

result/total-requirements
    params: {"@id": "result-uuid"}
    returns: array of TechFlowValue

result/total-requirements-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: single TechFlowValue

result/scaling-factors
    params: {"@id": "result-uuid"}
    returns: array of TechFlowValue

result/scaled-tech-flows-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of TechFlowValue

result/unscaled-tech-flows-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of TechFlowValue


========================================================================
RESULT METHODS - INVENTORY (11 methods)
========================================================================

result/total-flows
    params: {"@id": "result-uuid"}
    returns: array of EnviFlowValue {enviFlow: {flow, isInput}, amount}

result/total-flow-value-of
    params: {"@id": "result-uuid", "enviFlow": {...}}
    returns: single EnviFlowValue

result/flow-contributions-of
    params: {"@id": "result-uuid", "enviFlow": {...}}
    returns: array of TechFlowValue (which processes contribute to this flow)

result/direct-interventions-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of EnviFlowValue (elementary flows of one process)

result/direct-intervention-of
    params: {"@id": "result-uuid", "enviFlow": {...}, "techFlow": {...}}
    returns: single EnviFlowValue

result/flow-intensities-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of EnviFlowValue (per unit of output)

result/flow-intensity-of
    params: {"@id": "result-uuid", "enviFlow": {...}, "techFlow": {...}}
    returns: single EnviFlowValue

result/total-interventions-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of EnviFlowValue (total upstream)

result/total-intervention-of
    params: {"@id": "result-uuid", "enviFlow": {...}, "techFlow": {...}}
    returns: single EnviFlowValue

result/upstream-interventions-of
    params: {"@id": "result-uuid", "enviFlow": {...},
             "path": "providerUUID::flowUUID/providerUUID::flowUUID"}
    returns: array of UpstreamNode {techFlow, result, requiredAmount}
    Path is a / separated chain of providerUUID::flowUUID pairs
    representing the upstream tree traversal from root to parent node.
    Empty or null path returns root-level children.

result/grouped-flow-results-of
    params: {"@id": "result-uuid", "enviFlow": {...}}
    returns: array of GroupValue {group, amount}


========================================================================
RESULT METHODS - IMPACTS (17 methods)
========================================================================

result/total-impacts
    params: {"@id": "result-uuid"}
    returns: array of ImpactValue
        {impactCategory: {@id, name, category, refUnit}, amount}
    The most commonly used result method. One value per impact category.

result/total-impact-value-of
    params: {"@id": "result-uuid",
             "impactCategory": {"@type": "ImpactCategory", "@id": "uuid"}}
    returns: single ImpactValue

result/total-impacts/normalized
    params: {"@id": "result-uuid"}
    returns: array of ImpactValue (normalised)

result/total-impacts/weighted
    params: {"@id": "result-uuid"}
    returns: array of ImpactValue (weighted)

result/impact-contributions-of
    params: {"@id": "result-uuid", "impactCategory": {...}}
    returns: array of TechFlowValue (contribution of each process)

result/direct-impacts-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of ImpactValue (direct impacts of one process)

result/direct-impact-of
    params: {"@id": "result-uuid", "impactCategory": {...}, "techFlow": {...}}
    returns: single ImpactValue

result/total-impacts-of-one
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of ImpactValue (impact intensities per unit of output)

result/impact-intensity-of
    params: {"@id": "result-uuid", "impactCategory": {...}, "techFlow": {...}}
    returns: single ImpactValue

result/total-impacts-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: array of ImpactValue (total upstream impacts of one process)

result/total-impact-of
    params: {"@id": "result-uuid", "impactCategory": {...}, "techFlow": {...}}
    returns: single ImpactValue

result/impact-factors-of
    params: {"@id": "result-uuid", "impactCategory": {...}}
    returns: array of EnviFlowValue (characterisation factors)

result/impact-factor-of
    params: {"@id": "result-uuid", "impactCategory": {...}, "enviFlow": {...}}
    returns: single EnviFlowValue

result/flow-impacts-of
    params: {"@id": "result-uuid", "impactCategory": {...}}
    returns: array of EnviFlowValue (elementary flow contributions to impact)

result/flow-impact-of
    params: {"@id": "result-uuid", "impactCategory": {...}, "enviFlow": {...}}
    returns: single EnviFlowValue

result/upstream-impacts-of
    params: {"@id": "result-uuid", "impactCategory": {...},
             "path": "providerUUID::flowUUID/providerUUID::flowUUID"}
    returns: array of UpstreamNode
    Same path format as upstream-interventions-of.

result/grouped-impact-results-of
    params: {"@id": "result-uuid", "impactCategory": {...}}
    returns: array of GroupValue {group, amount}


========================================================================
RESULT METHODS - COSTS (7 methods)
========================================================================

result/total-costs
    params: {"@id": "result-uuid"}
    returns: CostValue {amount, currency}

result/cost-contributions
    params: {"@id": "result-uuid"}
    returns: array of TechFlowValue

result/direct-costs-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: CostValue

result/cost-intensities-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: CostValue

result/total-costs-of
    params: {"@id": "result-uuid", "techFlow": {...}}
    returns: CostValue

result/upstream-costs-of
    params: {"@id": "result-uuid",
             "path": "providerUUID::flowUUID/..."}
    returns: array of UpstreamNode

result/grouped-cost-results
    params: {"@id": "result-uuid"}
    returns: array of GroupValue


========================================================================
RESULT METHODS - VISUALISATION (1 method)
========================================================================

result/sankey
    params: {"@id": "result-uuid", "config": SankeyRequest}
    returns: SankeyGraph object


========================================================================
KNOWN GOTCHAS
========================================================================

1. Calculations must target ProductSystem objects, never bare Process IDs.
   Create a product system first with data/create/system.

2. result/dispose MUST be called when finished. Results consume server
   memory. Use try/finally or equivalent error handling.

3. Entity field names use JSON-LD conventions: @id, @type. Some JSON
   libraries (notably json-fortran) treat @ as a path operator.
   Workaround: use raw string matching or a get-child-by-name function.

4. The path parameter for upstream tree traversal methods uses the format
   "providerUUID::flowUUID/providerUUID::flowUUID" - a / separated chain
   of provider::flow pairs from root to parent. Empty or null returns
   root-level children.

5. CalculationSetup does not accept number_of_runs as a constructor
   parameter. Set it as an attribute after construction, or omit it.

6. Impact method selection requires exact name matching. Substring
   matching risks picking the wrong variant (e.g. the 20-category
   "Environment | EN15804+A2" vs the 38-category "EN15804+A2 (EF v3.1)").

7. Unit conversions within the same flow property (e.g. MJ to kWh) are
   handled automatically by openLCA. Only build conversion factors into
   bridge processes where flow properties genuinely differ.

8. EN15804GD market processes have null process-level pedigree
   (dq_entry = null). Pedigree data is on individual exchanges only.


========================================================================
CURL EXAMPLES
========================================================================

List all product systems:

    curl -X POST http://localhost:8080 \\
      -H "Content-Type: application/json" \\
      -d '{"jsonrpc":"2.0","id":1,"method":"data/get/descriptors",
           "params":{"@type":"ProductSystem"}}'

Run a calculation:

    curl -X POST http://localhost:8080 \\
      -H "Content-Type: application/json" \\
      -d '{"jsonrpc":"2.0","id":2,"method":"result/calculate",
           "params":{"target":{"@type":"ProductSystem","@id":"SYSTEM-UUID"},
                     "impactMethod":{"@type":"ImpactMethod","@id":"METHOD-UUID"}}}'

Get total impacts (after calculation is ready):

    curl -X POST http://localhost:8080 \\
      -H "Content-Type: application/json" \\
      -d '{"jsonrpc":"2.0","id":3,"method":"result/total-impacts",
           "params":{"@id":"RESULT-UUID"}}'

Dispose result:

    curl -X POST http://localhost:8080 \\
      -H "Content-Type: application/json" \\
      -d '{"jsonrpc":"2.0","id":4,"method":"result/dispose",
           "params":{"@id":"RESULT-UUID"}}'


========================================================================
EXISTING CLIENT IMPLEMENTATIONS
========================================================================

Python: pip install olca-ipc (official, by GreenDelta)
R:      remotes::install_github("Below280/openLCA-IPC-tools-r") (by Below280)
Fortran: github.com/Below280/openLCA-IPC-tools-fortran (by Below280)

Source and documentation: https://below280.com/knowledge-base/openlca-scripting/
"""
