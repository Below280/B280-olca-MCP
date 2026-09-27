# Release notes — v1.16.0

Released: 2026-09-26

## Exchanges keep the unit you give them

Exchanges were written with a unit but no flow property. openLCA then used the flow's reference property, and a unit that isn't in it was silently replaced by that property's reference unit. In testing, after a concrete flow's reference changed from volume to mass, an input of 0.2 m3 was stored as 0.2 kg. The results hid it, because the producing process's output changed from 1 m3 to 1 kg in the same way.

- `create_process`, `edit_process` (added exchanges and unit changes) and `create_product_system` (target unit) now set the flow property that the unit belongs to.
- A unit the flow has no property for is an error listing the units it does allow, instead of a warning followed by a silent substitution. Unit synonyms are recognised.

## Shared parameters and formula parameters (from 1.15)

- `run_scenarios` and `run_sensitivity` now redefine every copy of a parameter. Previously a name used in several processes was changed in only one of them. The CSV scenario and sensitivity tools use the same code.
- New `create_global_parameter` tool, for input parameters (a value) or dependent parameters (a formula). `create_process` accepts formula parameters.
- `create_global_parameter` now reports `changed` correctly for formula parameters. 1.15.0 compared the value openLCA stores on a formula parameter and flagged identical formulas as changed.

## Deleting flows safely

openLCA deletes a flow through IPC even while process exchanges or characterisation factors still point at it, which leaves those processes and methods broken.

- New `find_flow_usage` tool: lists the processes that produce or use a flow, and for elementary flows the impact categories that characterise it. openLCA's IPC server has no 'where used' query (the desktop Usage view runs inside openLCA), so it asks openLCA for the flow's providers first, then reads processes: preferred folders first, eight at a time, stopping as soon as enough uses are found.
- `delete_entity` runs this check before deleting a flow and refuses at the first use it finds, naming it. A flow that really is unused needs a full read of the database before it can be deleted.

## Pedigree scores and comments

- `create_process` and `edit_process` accept `dq_entry` (pedigree scores such as `(1;2;1;1;3)`) on exchanges, and `edit_process` can update them.
- Scores are checked before anything is written: whole numbers from 1 to 5, one per indicator of the process's flow data quality system. A process with scored exchanges must have a flow schema, and an unknown schema name is an error rather than a warning.
- `edit_process` now keeps comments on added exchanges (previously only `create_process` did), and can update them.
- `list_dq_systems` lists indicators in position order, with their position. Pedigree scores follow that order, and the stored order can differ: in the US EPA Flow Pedigree Matrix it put Temporal Correlation first, where position 1 is Flow Reliability.

## Upstream tree with data quality

- New `upstream_tree` tool: a multi-level contribution tree for one impact category, walked with openLCA's upstream tree. Each branch has its upstream result, its share of the total, and the pedigree scores on the exchange linking it to its parent, with indicator names. Each level keeps the top branches and groups the rest as 'other'.
- It handles both conventions openLCA versions use for the root of the upstream path.

## Editing flows

- New `edit_flow` tool: add or update a flow's properties, or change its reference property. A property is given as a relation such as 1 m3 = 2400 kg; either unit may belong to the property being added, and `edit_flow` works out openLCA's conversion factor. Changing the reference rescales every factor so exchanges keep their meaning. Properties are never removed, because removing one in use breaks exchanges and IPC can't tell where a flow is used.

## Tool count

35 tools (32 in 1.15.0).
