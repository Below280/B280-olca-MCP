# Contributing to the Below280 openLCA MCP Server

We welcome contributions — bug reports, feature suggestions, documentation improvements, and pull requests.

## Reporting Bugs

Open a [GitHub issue](https://github.com/Below280/B280-olca-MCP/issues) with:

- What you were trying to do
- What happened instead
- The MCP client you were using (Claude Desktop, VS Code, etc.) and its version
- Your openLCA version and database type (e.g. ecoinvent 3.10 cut-off)
- Your Python version and operating system
- Any error messages or logs

If the issue involves a security vulnerability, please follow the process in [SECURITY.md](SECURITY.md) instead.

## Suggesting Features or New Tools

Open an issue describing the tool or feature, what LCA task it supports, and an example of how you would expect to use it. We are particularly interested in tools that support common practitioner workflows.

## Pull Requests

1. Fork the repository and create a branch from `main`.
2. Make your changes. If you are adding or modifying a tool, update `tools.md` to match.
3. Test against a running openLCA IPC server. We test with openLCA 2.x and the current `olca-ipc` release.
4. Open a pull request against `main` with a clear description of what the change does and why.

We will review pull requests as promptly as we can. For larger changes, it is worth opening an issue first to discuss the approach before writing the code.

## Licence

By contributing, you agree that your contributions will be licensed under the [Mozilla Public License 2.0](LICENSE), the same licence as the rest of this repository.

## Code of Conduct

Be respectful, constructive, and collaborative. We are a small team building tools for the LCA community and we appreciate every contribution.
