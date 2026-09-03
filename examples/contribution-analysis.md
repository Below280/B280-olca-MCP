# Example: Contribution Analysis

This shows the tool sequence for identifying which processes in the supply chain drive each impact category.

## User prompt

> Which processes contribute most to climate change in my system?

## What happens

### Step 1: The assistant confirms the impact method

User picks 'EF v3.1'.

### Step 2: Run contribution analysis

**Tool:** `contribution_analysis`
```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "categories": ["Climate change"],
  "threshold_pct": 0.1,
  "max_contributors": 15
}
```

Filtering to just 'Climate change' keeps the response focused. Omitting `categories` would analyse all impact categories.

### Step 3: Present results

The assistant creates a React artifact with:
- Horizontal bar chart of top contributors with percentages
- Total and coverage percentage

## Expected output structure

```json
{
  "system": "Widget production",
  "method": "EF v3.1",
  "threshold_pct": 0.1,
  "categories_analysed": 1,
  "categories": {
    "Climate change": {
      "total": 12.3,
      "unit": "kg CO2-eq",
      "contributor_count": 6,
      "covered_pct": 94.5,
      "contributors": [
        {"process": "HDPE granulate production", "amount": 4.2, "pct": 34.1},
        {"process": "electricity, low voltage", "amount": 3.8, "pct": 30.9},
        {"process": "sodium hydroxide, membrane cell", "amount": 2.1, "pct": 17.1},
        {"process": "tap water production", "amount": 0.9, "pct": 7.3},
        {"process": "transport, freight lorry", "amount": 0.4, "pct": 3.3},
        {"process": "other", "amount": 0.2, "pct": 1.8}
      ]
    }
  }
}
```

The 80% coverage rule (common in EPD work) is easy to check from these numbers: HDPE + electricity + NaOH = 82.1%, so three processes cover the threshold.
