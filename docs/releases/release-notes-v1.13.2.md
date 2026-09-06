# v1.13.2

Everything that's changed since v1.11. This is a significant structural release.

## MCP resources

The server now exposes four MCP resources that AI clients can read on demand:

- **Assistant instructions** (`lca://knowledge/instructions`) — operational rules, workflows, EPD building guidance, and conventions. This is the knowledge base that shapes how the AI assistant behaves.
- **IPC protocol reference** (`lca://knowledge/ipc-protocol`) — complete JSON-RPC spec for all 60 openLCA IPC methods, with parameter formats, response structures, and curl examples. Enables the assistant to generate working client code for any programming language.
- **openLCA resources** (`lca://knowledge/openlca-resources`) — curated links to databases, documentation, forums, tutorials, and training. The assistant draws on this when users ask where to learn or find data.
- **Database info** (`lca://database/info`) — live database overview.

## EPD model building workflow

The assistant instructions now include a full guided workflow for building EN15804 EPD models from LCI data. The AI maps LCI items to lifecycle modules (A1–D), creates the folder structure, bridge processes, module processes, and product systems. Triggered by asking 'build an EPD from this LCI'.

## Standalone script generation

After running scenario or sensitivity calculations, the server now instructs the assistant to offer standalone Python scripts that do the same analysis without AI tokens. It generates the CSV input file and links to the tested scripts in the [openLCA-IPC-tools-python](https://github.com/Below280/openLCA-IPC-tools-python) repository. For heavy database operations (batch creates, mass renames, database parameterisation), the assistant offers to generate a custom Python script rather than chaining dozens of MCP tool calls.

## Integration with Below280 repositories

The server now formalises links to the other Below280 openLCA repositories. The assistant instructions reference tested implementations for [Python](https://github.com/Below280/openLCA-IPC-tools-python), [R](https://github.com/Below280/openLCA-IPC-tools-r), and [Fortran](https://github.com/Below280/openLCA-IPC-tools-fortran), and can direct users to the right repo for their language or workflow. For languages without a tested client, the assistant generates experimental code from the embedded IPC protocol spec.

## IPC protocol reference

A new embedded reference (`ipc_reference.py`) documents all 60 openLCA JSON-RPC IPC methods with parameter formats, response structures, and curl examples. This serves two purposes: it enables the assistant to generate client code for any language, and it acts as a single-file connector to the upstream openLCA API so the assistant knows the full set of IPC capabilities available, including any that the MCP server doesn't yet wrap as tools.

## Database family auto-detection

`database_info` now auto-detects whether the connected database is ecoinvent-family (ecoinvent, EN15804GD, HiQLCD, BAFU) or FLCAC-family (LCA Commons, US LCI, USEEIO) by checking which flow property names are present. Users no longer need to specify the family manually unless auto-detection is inconclusive. Once set, the mapping drives unit and flow property resolution for all model building tools.

## openLCA resources reference

A new separate module (`openlca_resources.py`) serves a curated, maintained link list covering databases (Nexus, ecoinvent, LCA Commons, GLAD, Tian Gong, BAFU), documentation (openLCA manual, API docs), forums (ask.openlca.org, Reddit), tutorials, case studies, and training courses. The assistant draws on this when users ask where to learn openLCA, find LCA data, or get help, rather than relying on training data that may be out of date.

## Auto-parametrisation naming convention

`create_process` auto-parametrises every bare exchange amount using a double-underscore naming convention:

```
NN_processname__flowname_unit
```

The double underscore between process name and flow name keeps the boundary visually distinct. Each segment is truncated to 10 characters, with spaces and commas normalised to underscores. The two-digit index prefix guarantees uniqueness within a process.

## Tool annotations

Every tool now carries MCP `ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so clients can auto-approve safe operations and prompt for destructive ones. Six annotation presets: READONLY, WRITE, DESTRUCTIVE, CALCULATE, FILE_WRITE, EXTERNAL.

## Help tool

New `help` tool with optional topic filter (explore, build, audit, calculate, scripting, epd, connect). Gives users a structured overview of what the server can do without reading the full documentation.

## Structural changes

- MCP 2.x handler API: migrated from `@self.server.list_tools()` decorators to `add_request_handler()`.
- Tool count: 30 → 31.
- `get_system_links` moved from Build to Audit.
- Documentation (tools.md, README) restructured to match: Explore (11), Build (6), Audit (5), Calculate (8), Meta (1).
- `pyproject.toml` now derives its version dynamically from `b280_olca_mcp/__init__.py`.

## Security fix

The CSV tools (`scenarios_csv`, `sensitivity_csv`) now validate all file paths through `validate_file_path`, which resolves the path and blocks directory traversal attempts. Previously, file paths from tool arguments were passed through without validation.

## Bug fix

Fixed a duplicate `annotations=` keyword on the `set_database_family` tool definition that caused a `SyntaxError` on startup with some Python versions.

## Tested with openLCA 2.6

All calculation patterns retested against openLCA 2.6 with ecoinvent databases.

## Install

```
pip install --upgrade b280-olca-mcp
```

[PyPI](https://pypi.org/project/b280-olca-mcp/1.13.2/) · [MCP Registry](https://registry.modelcontextprotocol.io) · [Tool reference](https://github.com/Below280/B280-olca-MCP/blob/main/docs/tools.md)
