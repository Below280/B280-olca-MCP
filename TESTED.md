# Tested Configurations

Combinations this server has been tested against. Untested combinations
may work but are not guaranteed.

## openLCA versions

| Version | Status  | Notes |
|---------|---------|-------|
| 2.5     | Working |       |
| 2.6     | Working |       |

## Background databases

| Database                    | Status  | Notes |
|-----------------------------|---------|-------|
| ecoinvent 3.10              | Working |       |
| FLCAC (current, Sep 2026)   | Working | Semicolon-heavy flow names stress-tested parameter naming |

## AI models

| Model              | Status  | Notes |
|--------------------|---------|-------|
| Claude Opus 4.6    | Good    | Follows tool instructions reliably |
| Claude Opus 5      | Poor    | Tends to ramble and lose track of multi-step workflows |
