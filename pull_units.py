"""
Pull all units, unit groups, and flow properties from the connected
openLCA database. Diagnoses MCP server compatibility and outputs a
ready-to-paste UNIT_FP_MAP for the connected database.

Run with: python pull_units.py

Outputs:
  units_report.json   - structured data
  units_report.txt    - human-readable summary with fix instructions
"""

from olca_ipc import Client
import olca_schema as o
import json

client = Client(8080)

# ── Flow Properties ──────────────────────────────────────────
print("Pulling flow properties...")
fp_descriptors = list(client.get_descriptors(o.FlowProperty))
flow_properties = {}
fp_to_unit_group = {}

for fp_ref in fp_descriptors:
    fp = client.get(o.FlowProperty, fp_ref.id)
    ug_id = fp.unit_group.id if getattr(fp, "unit_group", None) else None
    ug_name = fp.unit_group.name if getattr(fp, "unit_group", None) else None
    flow_properties[fp.name] = {
        "id": fp.id,
        "name": fp.name,
        "category": getattr(fp, "category", ""),
        "unit_group_id": ug_id,
        "unit_group_name": ug_name,
    }
    if ug_id:
        fp_to_unit_group.setdefault(ug_id, []).append(fp.name)

print(f"  Found {len(flow_properties)} flow properties")

# ── Unit Groups ──────────────────────────────────────────────
print("Pulling unit groups...")
ug_descriptors = list(client.get_descriptors(o.UnitGroup))
unit_groups = {}
all_units = {}

for ug_ref in ug_descriptors:
    ug = client.get(o.UnitGroup, ug_ref.id)
    if not ug:
        continue

    units_in_group = []
    if ug.units:
        for u in ug.units:
            unit_data = {
                "id": u.id,
                "name": u.name,
                "conversion_factor": getattr(u, "conversion_factor", None),
                "is_ref_unit": getattr(u, "reference_unit", False),
            }
            units_in_group.append(unit_data)

            # Track ALL flow properties for this unit (via unit group)
            fps_for_this_unit = fp_to_unit_group.get(ug.id, [])
            all_units[u.name] = {
                "unit_group": ug.name,
                "unit_group_id": ug.id,
                "flow_properties": sorted(fps_for_this_unit),
            }

    unit_groups[ug.name] = {
        "id": ug.id,
        "name": ug.name,
        "category": getattr(ug, "category", ""),
        "flow_properties": sorted(fp_to_unit_group.get(ug.id, [])),
        "unit_count": len(units_in_group),
        "units": units_in_group,
    }

print(f"  Found {len(unit_groups)} unit groups, {len(all_units)} total units")

# ── MCP UNIT_FP_MAP check ───────────────────────────────────
MCP_MAP = {
    "kg": "Mass", "g": "Mass", "t": "Mass",
    "kWh": "Energy", "MJ": "Energy", "GJ": "Energy",
    "t*km": "Goods transport (mass*distance)",
    "tkm": "Goods transport (mass*distance)",
    "m3": "Volume", "l": "Volume",
    "m2": "Area",
    "hr": "Time", "h": "Time", "s": "Time", "min": "Time",
    "Item(s)": "Number of items",
    "km": "Length", "m": "Length", "p": "Mass",
}

print("\nChecking MCP server UNIT_FP_MAP against this database...")

ok = []
fixable = []
broken = []
missing_units = []

for unit_name, expected_fp in MCP_MAP.items():
    if unit_name not in all_units:
        missing_units.append({"unit": unit_name, "expected_fp": expected_fp})
        continue

    unit_info = all_units[unit_name]
    available_fps = unit_info["flow_properties"]

    # Check if expected FP exists in the database
    fp_exists = expected_fp in flow_properties

    # Check if expected FP is one of the valid FPs for this unit
    if expected_fp in available_fps:
        ok.append({
            "unit": unit_name,
            "fp": expected_fp,
            "all_fps": available_fps,
        })
    elif fp_exists:
        # FP exists but isn't linked to this unit's group
        broken.append({
            "unit": unit_name,
            "expected_fp": expected_fp,
            "available_fps": available_fps,
            "reason": f"'{expected_fp}' exists but uses a different unit group",
        })
    else:
        # FP doesn't exist in database at all
        fixable.append({
            "unit": unit_name,
            "expected_fp": expected_fp,
            "available_fps": available_fps,
            "suggestion": available_fps[0] if available_fps else None,
        })

# ── Build a database-specific UNIT_FP_MAP ────────────────────
# Pick the most common/generic FP name for each unit
PREFERRED_FP_ORDER = [
    "Mass", "Energy", "Volume", "Area", "Length",
    "Number of items", "Goods transport (mass*distance)",
    "Time", "Duration", "Net calorific value", "Gross calorific value",
    "Normal Volume", "Person transport", "Vehicle transport",
    "Power", "Radioactivity", "Mole", "Molar mass",
]

def pick_best_fp(fps):
    """Pick the most generic flow property from a list."""
    for preferred in PREFERRED_FP_ORDER:
        if preferred in fps:
            return preferred
    return fps[0] if fps else None

# Common units people would use in model building
COMMON_UNITS = [
    "kg", "g", "t", "mg", "lb av", "oz av", "sh tn", "long tn",
    "kWh", "MJ", "GJ", "kJ", "J", "Wh", "MWh", "btu",
    "m3", "l", "ml", "cm3", "dm3", "gal (US liq)",
    "m2", "km2", "ha", "ft2",
    "km", "m", "cm", "mm", "mi", "ft", "in", "nmi",
    "h", "min", "s", "d", "a",
    "t*km", "kg*km", "t*nmi", "t*mi",
    "p*km", "p*mi",
    "Item(s)", "Dozen(s)",
    "kW", "MW", "W",
    "Bq", "kBq",
    "mol",
]

db_map = {}
for unit_name in COMMON_UNITS:
    if unit_name in all_units:
        fps = all_units[unit_name]["flow_properties"]
        best = pick_best_fp(fps)
        if best:
            db_map[unit_name] = best

# ── Output ───────────────────────────────────────────────────
report = {
    "flow_properties": flow_properties,
    "unit_groups": unit_groups,
    "all_units": all_units,
    "mcp_check": {
        "ok": ok,
        "fixable": fixable,
        "broken": broken,
        "missing_units": missing_units,
    },
    "suggested_map": db_map,
}

with open("units_report.json", "w") as f:
    json.dump(report, f, indent=2)

# Human-readable summary
lines = []
lines.append("=" * 70)
lines.append("UNIT DIAGNOSTIC REPORT")
lines.append("=" * 70)

lines.append(f"\nFlow properties: {len(flow_properties)}")
for name in sorted(flow_properties.keys()):
    fp = flow_properties[name]
    lines.append(f"  {name}")
    lines.append(f"    Unit group: {fp['unit_group_name']}")

lines.append(f"\nUnit groups: {len(unit_groups)}")
for name in sorted(unit_groups.keys()):
    ug = unit_groups[name]
    unit_names = [u["name"] for u in ug["units"]]
    fps = ug["flow_properties"]
    lines.append(f"  {name}")
    lines.append(f"    Flow properties: {', '.join(fps)}")
    lines.append(f"    Units: {', '.join(unit_names)}")

lines.append(f"\nTotal units: {len(all_units)}")

lines.append("\n" + "=" * 70)
lines.append("MCP SERVER COMPATIBILITY CHECK")
lines.append("=" * 70)

lines.append(f"\nOK ({len(ok)}):")
for entry in ok:
    extra = ""
    if len(entry["all_fps"]) > 1:
        others = [f for f in entry["all_fps"] if f != entry["fp"]]
        extra = f"  (also valid: {', '.join(others)})"
    lines.append(f"  {entry['unit']} -> {entry['fp']}{extra}")

if fixable:
    lines.append(f"\nNEEDS FIX ({len(fixable)}):")
    lines.append("  These units exist but the MCP's flow property name doesn't.")
    for entry in fixable:
        lines.append(f"  {entry['unit']}: MCP expects '{entry['expected_fp']}'")
        lines.append(f"    Available: {', '.join(entry['available_fps'])}")
        if entry["suggestion"]:
            lines.append(f"    Suggested: '{entry['suggestion']}'")

if broken:
    lines.append(f"\nBROKEN ({len(broken)}):")
    for entry in broken:
        lines.append(f"  {entry['unit']}: {entry['reason']}")
        lines.append(f"    Available: {', '.join(entry['available_fps'])}")

if missing_units:
    lines.append(f"\nMISSING UNITS ({len(missing_units)}):")
    lines.append("  These unit names are in the MCP map but don't exist in the database.")
    lines.append("  These are usually aliases and can be removed from the map.")
    for entry in missing_units:
        lines.append(f"  {entry['unit']} (expected FP: {entry['expected_fp']})")

lines.append("\n" + "=" * 70)
lines.append("READY-TO-PASTE UNIT_FP_MAP FOR THIS DATABASE")
lines.append("=" * 70)
lines.append("")
lines.append("Replace UNIT_FP_MAP in lca_functions.py with this:")
lines.append("")
lines.append("    UNIT_FP_MAP = {")
for unit_name, fp_name in sorted(db_map.items()):
    lines.append(f'        "{unit_name}": "{fp_name}",')
lines.append("    }")

report_text = "\n".join(lines)

with open("units_report.txt", "w") as f:
    f.write(report_text)

print(report_text)
print(f"\nFull report saved to: units_report.json")
print(f"Summary saved to: units_report.txt")
