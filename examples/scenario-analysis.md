# Example: Scenario Analysis

This shows the tool sequence when a user asks the assistant to compare scenarios.

## User prompt

> Compare two scenarios for my Widget system: one with 100 km transport and one with 500 km.

## What happens

### Step 1: The assistant asks which impact method to use

**Tool:** `list_methods`

The assistant presents the options. User picks 'EF v3.1'.

### Step 2: Run the scenarios

**Tool:** `scenarios`
```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "scenarios": {
    "Short haul (100 km)": {"transport_km": 100},
    "Long haul (500 km)": {"transport_km": 500}
  }
}
```

### Step 3: Present results

The assistant creates a React artifact with:
- Bar chart comparing the two scenarios per impact category
- Radar chart showing the normalised profile
- Results table with CSV export

## Expected output structure

```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "scenario_count": 2,
  "results": {
    "Short haul (100 km)": [
      {"category": "Climate change", "amount": 12.3, "unit": "kg CO2-eq"},
      {"category": "Acidification", "amount": 0.045, "unit": "mol H+-eq"}
    ],
    "Long haul (500 km)": [
      {"category": "Climate change", "amount": 14.8, "unit": "kg CO2-eq"},
      {"category": "Acidification", "amount": 0.062, "unit": "mol H+-eq"}
    ]
  }
}
```
