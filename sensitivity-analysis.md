# Example: Sensitivity Analysis

This shows the tool sequence for identifying which parameters have the most influence on results.

## User prompt

> Vary the electricity and transport parameters by 10% and show me which matters more.

## What happens

### Step 1: The assistant confirms the impact method

User has already selected 'EF v3.1' earlier in the conversation.

### Step 2: Run sensitivity

**Tool:** `sensitivity`
```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "parameters": ["electricity_kwh", "transport_km"],
  "variation_pct": 10
}
```

### Step 3: Present results

The assistant creates a React artifact with:
- Tornado diagram showing each parameter's influence on each impact category, sorted by range
- Results table with baseline, -10%, and +10% values
- CSV export

## Expected output structure

```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "variation_pct": 10,
  "baseline": {
    "Climate change": {"amount": 12.3, "unit": "kg CO2-eq"},
    "Acidification": {"amount": 0.045, "unit": "mol H+-eq"}
  },
  "sensitivity": {
    "electricity_kwh": {
      "baseline_value": 3.0,
      "minus": {"Climate change": 11.8, "Acidification": 0.043},
      "plus": {"Climate change": 12.8, "Acidification": 0.047}
    },
    "transport_km": {
      "baseline_value": 100,
      "minus": {"Climate change": 12.1, "Acidification": 0.044},
      "plus": {"Climate change": 12.5, "Acidification": 0.046}
    }
  },
  "tested": ["electricity_kwh", "transport_km"],
  "missing": []
}
```

In this example, electricity has a wider range than transport for climate change, so the tornado diagram shows it at the top.
