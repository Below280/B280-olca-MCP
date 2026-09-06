# Using B280 openLCA MCP with ChatGPT

The B280 openLCA MCP Server can be connected to ChatGPT, allowing ChatGPT to interact with a locally running openLCA instance.

This enables workflows such as:

- Exploring openLCA databases
- Searching for processes and flows
- Creating product systems and LCA models
- Running calculations
- Comparing scenarios
- Performing sensitivity analysis
- Running Monte Carlo uncertainty analysis
- Analysing contributions
- Building EPD-style models
- Validating models and results

The B280 MCP Server runs locally and communicates with openLCA through the openLCA IPC API.

## Architecture

The connection is:

```text
ChatGPT
    |
    v
OpenAI Secure MCP Tunnel
    |
    v
B280 openLCA MCP Server
    |
    v
openLCA IPC API
    |
    v
openLCA + your local databases
```

This means openLCA and its databases can remain on your own computer. You do not need to expose the openLCA IPC API directly to the internet.

## Requirements

Before starting, you need:

- Python 3.10 or later
- openLCA 2.x
- B280 openLCA MCP Server
- An openLCA database
- openLCA IPC enabled
- Access to ChatGPT functionality that supports custom MCP servers

Install B280 from PyPI:

```bash
pip install b280-olca-mcp
```

Or install the latest development version from GitHub:

```bash
git clone https://github.com/Below280/B280-olca-MCP.git
cd B280-olca-MCP
pip install -e .
```

## 1. Start openLCA

Open the database you want to work with in openLCA.

Start the IPC server from openLCA:

Tools > Developer tools > IPC Server

The default configuration used by B280 is:

```text
http://localhost:8080
```

Keep openLCA running while using the MCP server.

## 2. Test B280 locally

Before connecting ChatGPT, check that B280 starts correctly:

```bash
python -m b280_olca_mcp
```

The MCP server uses the standard MCP `stdio` transport.

If B280 starts successfully, stop it before continuing. The Secure MCP Tunnel will launch the server itself when required.

## 3. Install the OpenAI Secure MCP Tunnel

ChatGPT cannot directly launch a local `stdio` MCP server.

OpenAI provides the Secure MCP Tunnel to bridge a local MCP server to ChatGPT without exposing the local MCP endpoint directly to the public internet.

Follow the current installation instructions in the OpenAI Secure MCP Tunnel repository:

https://github.com/openai/tunnel-client

The tunnel should be configured to launch:

```bash
python -m b280_olca_mcp
```

> **Note:** OpenAI's MCP and Secure MCP Tunnel functionality is evolving. The exact tunnel installation and ChatGPT configuration steps may change. Use the current OpenAI documentation for the tunnel rather than relying on copied commands that may become outdated.

## 4. Connect the tunnel to ChatGPT

Once the Secure MCP Tunnel is running, add the resulting MCP connection to ChatGPT using ChatGPT's custom MCP / developer functionality.

Follow OpenAI's current instructions here:

https://help.openai.com/en/articles/12584461

Availability of custom MCP functionality depends on the ChatGPT plan and workspace configuration.

## 5. Try B280 from ChatGPT

Once connected, ChatGPT should be able to discover the B280 MCP tools.

For example, try:

```text
What openLCA database is currently open?
```

Then:

```text
Search my openLCA database for UK electricity processes.
```

Or:

```text
Calculate the climate change impact of this product system.
```

More advanced examples include:

```text
Build an LCA model using 34 kWh of UK electricity,
5 kg of sodium hydroxide and 34 kWh of steam.
```

```text
Compare scenarios with transport distances of
100 km and 500 km.
```

```text
Run a sensitivity analysis on the electricity input.
```

```text
Run 1,000 Monte Carlo iterations and summarise
the uncertainty in the results.
```

ChatGPT can combine multiple B280 tools during a conversation, allowing an LCA workflow to be developed interactively rather than requiring every operation to be specified in advance.

## Security and data

B280 is designed to run alongside a local openLCA installation.

The openLCA IPC server normally remains accessible only on:

```text
localhost:8080
```

Do not expose the openLCA IPC port directly to the public internet.

When using ChatGPT, information returned by MCP tools may be passed to ChatGPT as part of the conversation. Consider your organisation's data policies before using confidential datasets, client information, proprietary models or commercially sensitive results with any external AI service.

The Secure MCP Tunnel provides connectivity to the local MCP server; it does not change the confidentiality requirements applicable to the data you choose to send to ChatGPT.

## Troubleshooting

### ChatGPT cannot see the B280 tools

Check that:

1. The Secure MCP Tunnel is running.
2. The tunnel is configured to launch `python -m b280_olca_mcp`.
3. B280 is installed in the Python environment used by the tunnel.
4. Your ChatGPT account or workspace supports custom MCP servers.

### B280 cannot connect to openLCA

Check that:

1. openLCA is running.
2. A database is open.
3. The IPC server has been started.
4. The IPC server is listening on port `8080`.

You can also test B280 independently of ChatGPT before troubleshooting the tunnel.

### A tool is available but ChatGPT does not use it

Ask ChatGPT explicitly to use the B280/openLCA tools for the operation.

For example:

```text
Use the B280 openLCA tools to search my currently open
database for electricity processes.
```

This can help distinguish an MCP connection problem from ChatGPT simply deciding that a tool was unnecessary.

## Other MCP clients

B280 uses the standard Model Context Protocol and is not specific to ChatGPT.

It can also be used with MCP-compatible clients including Claude Desktop, VS Code, Cursor and other clients capable of connecting to local or remote MCP servers.

See the main [README](../README.md) for installation and client-specific information.

## Status

ChatGPT support should currently be considered experimental.

The B280 MCP server itself uses standard MCP `stdio`; ChatGPT connectivity is provided through OpenAI's MCP infrastructure and Secure MCP Tunnel. Changes to ChatGPT or OpenAI's MCP support may therefore require updates to these instructions.

If you successfully use B280 with ChatGPT, or encounter a compatibility issue, please open an issue on the B280 repository:

https://github.com/Below280/B280-olca-MCP/issues
