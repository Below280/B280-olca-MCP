# Example: Reviewing and Auditing a Model

This shows the tool sequence for checking an existing model against an LCI or for structural issues.

## User prompt

> Can you check my model in the 00: Widget Model folder? Here's what the LCI should have: 1 kg NaOH, 1 kg HDPE, 3 kWh electricity, 2 kg water, producing 1 kg product.

## What happens

### Step 1: Extract the model

**Tool:** `extract_model`
```json
{"category": "00: Widget Model"}
```

Returns all processes, exchanges, parameters, and flows in the folder.

### Step 2: The assistant compares against the LCI

The assistant reads the extracted model data and compares each exchange against the user's LCI specification. It checks:
- Are all five flows present (4 inputs + 1 output)?
- Do the amounts match?
- Are the units correct?
- Are providers set on all inputs?

The assistant reports any discrepancies. It understands that openLCA scales processes, so a bridge outputting 1 kg feeding an exchange that needs 2 kg is correct.

### Step 3: If the user asks for a structural audit

**Tool:** `audit_model`
```json
{"category": "00: Widget Model"}
```

Returns findings grouped by severity:
- **Errors:** missing quantitative references
- **Warnings:** zero amounts without formulas, missing units
- **Info:** missing providers, consumed flows not produced in-model

### Step 4: If the user asks for system validation

**Tool:** `validate_system`
```json
{"system": "Widget production"}
```

Checks linking, runs a test calculation, reports whether the system produces non-zero results.

## Key point

These three tools serve different purposes:
- `extract_model` gives the assistant the raw data to reason about
- `audit_model` runs automated structural checks
- `validate_system` tests whether the product system actually calculates

The assistant calls them only when asked. It does not chain them automatically.
