# v1.13.4

## Product system creation: six bug fixes

Fixes six bugs in `create_product_system` discovered during FLCAC v2 testing.

**BUG-01: target_amount defaults to 0.** The IPC call returns a product system with `target_amount = 0` unless explicitly set. The tool now reads the source process's quantitative reference amount and applies it as the default, so systems are immediately calculable.

**BUG-02: parallel calls crash openLCA.** Concurrent `create_system` calls caused openLCA's IPC server to crash or produce corrupt systems. Product system creation is now serialised with a threading lock. The assistant instructions also now prohibit parallel `create_system` calls.

**BUG-03: silent empty linking.** When using `only_defaults`, the tool silently returned zero linked providers if no default providers were set. It now returns a warning explaining the result and suggesting `prefer_defaults`.

**BUG-04/05: generic errors and timeouts.** On large databases, post-creation steps (reading back links, setting target amount) could timeout. If the system was created but post-processing failed, the tool now returns the `system_id` with `partial: true` instead of a generic error, so the system is not orphaned.

**BUG-06: duplicate systems.** Unlike `create_process`, there was no pre-flight check for existing product systems. The tool now checks for an existing system with the same name and returns `already_existed: true` instead of creating a duplicate.

## Install

```
pip install --upgrade b280-olca-mcp
```

[PyPI](https://pypi.org/project/b280-olca-mcp/1.13.4/) · [MCP Registry](https://registry.modelcontextprotocol.io) · [Tool reference](https://github.com/Below280/B280-olca-MCP/blob/main/docs/tools.md)
