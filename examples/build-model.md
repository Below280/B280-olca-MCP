# Example: Building a Model from Conversation

This shows the tool sequence when a user asks the assistant to build an LCA model from a plain-language description.

## User prompt

> Make me a model with 1 kg sodium hydroxide, 1 kg HDPE, 3 kWh electricity, and 2 kg water. It produces 1 kg of my product.

## What happens

### Step 1: The assistant asks clarifying questions

- 'What should the product and process be called?'
- 'Is this an ecoinvent-family database or FLCAC?'

User answers: 'Call it Widget production. It's ecoinvent.'

### Step 2: Set database family

**Tool:** `set_database_family`
```json
{"family": "ecoinvent"}
```

### Step 3: Search for background processes

**Tool:** `search_processes` (called 4 times)
```json
{"search_term": "sodium hydroxide"}
{"search_term": "polyethylene high density granulate"}
{"search_term": "electricity low voltage"}
{"search_term": "tap water"}
```

The assistant reads the results, picks the most appropriate dataset for each input based on geography and technology.

### Step 4: Create the product flow

**Tool:** `create_flow`
```json
{
  "name": "Widget",
  "unit": "kg",
  "category": "00: Widget Model",
  "flow_type": "product"
}
```

### Step 5: Create bridge processes

**Tool:** `create_bridge` (called 4 times, one per input)
```json
{
  "name": "BRIDGE | sodium hydroxide | kg",
  "unit": "kg",
  "category": "00: Widget Model/Bridges",
  "provider_id": "03e89d55-..."
}
```
Repeated for HDPE, electricity (unit: kWh), and water.

### Step 6: Create the foreground process

**Tool:** `create_process`
```json
{
  "name": "Widget production",
  "category": "00: Widget Model",
  "exchanges": [
    {"flow_id": "<widget_flow_id>", "amount": 1, "unit": "kg", "is_input": false, "is_qref": true},
    {"flow_id": "<naoh_bridge_flow>", "amount": 1, "unit": "kg", "is_input": true, "provider_id": "<naoh_bridge_proc>"},
    {"flow_id": "<hdpe_bridge_flow>", "amount": 1, "unit": "kg", "is_input": true, "provider_id": "<hdpe_bridge_proc>"},
    {"flow_id": "<elec_bridge_flow>", "amount": 3, "unit": "kWh", "is_input": true, "provider_id": "<elec_bridge_proc>"},
    {"flow_id": "<water_bridge_flow>", "amount": 2, "unit": "kg", "is_input": true, "provider_id": "<water_bridge_proc>"}
  ]
}
```

### Step 7: Create the product system

**Tool:** `create_system`
```json
{
  "process": "Widget production",
  "linking": "prefer_defaults"
}
```

### Result

The model is now in openLCA under `00: Widget Model`, with a product system ready for calculation. The user can ask the assistant to run an LCA, compare scenarios, or check the model.
