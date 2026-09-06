# v1.13.3

## EPD workflow: multi-process module folders

The EPD model building workflow now supports multiple processes per lifecycle module. Instead of creating a single process per stage (A1, A2, A3 etc.), the assistant creates as many sub-processes as the LCI data warrants in each module folder, feeding into a final aggregating process per stage.

Sub-processes use a pipe separator (`A1 | Cement supply`), the final module process uses a colon (`A1: Raw material supply`). Product systems target the final process, which pulls in the sub-processes through process links automatically.

If a module has only one activity, a single process is created as before.

## Data quality schema support

New `list_dq_systems` tool lists all Data Quality systems available in the database.

`create_process` now accepts optional `flow_schema` and `process_schema` parameters (name or UUID of a DQ system). When set, the process is created with `exchange_dq_system` and/or `dq_system` already assigned, saving manual setup in the openLCA GUI.

The EPD workflow now includes Step 2b: after creating the folder structure, the assistant checks for available DQ systems and asks the user whether to apply them to all processes in the model. If the database has no DQ systems, or the user declines, the step is skipped silently.

## Install

```
pip install --upgrade b280-olca-mcp
```

[PyPI](https://pypi.org/project/b280-olca-mcp/1.13.3/) · [MCP Registry](https://registry.modelcontextprotocol.io) · [Tool reference](https://github.com/Below280/B280-olca-MCP/blob/main/docs/tools.md)
