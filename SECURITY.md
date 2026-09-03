# Security Policy

## Reporting a Vulnerability

If you discover a security issue in the Below280 openLCA MCP server, please report it privately rather than opening a public issue.

**Report via GitHub:** go to the [Security Advisories page](https://github.com/Below280/B280-olca-MCP/security/advisories/new) for this repository and submit a private vulnerability report. This keeps the report within GitHub's secure disclosure workflow and avoids exposing details publicly.

Please include:

- A description of the vulnerability
- Steps to reproduce it
- The version of the server and MCP client you were using
- Any relevant logs or screenshots

We will acknowledge your report within 5 working days and aim to provide a fix or mitigation within 30 days. We ask that you give us reasonable time to address the issue before any public disclosure.

## Scope

This policy covers the MCP server code, its tool implementations, and the interaction between the server and openLCA via IPC. It includes but is not limited to:

- Unintended data exposure through tool responses
- File path traversal via CSV tool inputs or outputs
- Deletion or modification of openLCA data without appropriate confirmation
- Vulnerabilities in dependency handling

General bugs that do not have a security impact should be reported as normal issues.

## Supported Versions

Security fixes will be applied to the latest release on the `main` branch. We do not maintain older release branches at this time.
