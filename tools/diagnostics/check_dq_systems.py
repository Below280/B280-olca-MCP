"""
Test script: DQ system (flow schema) detection and assignment via IPC.

Run with openLCA's IPC server active on port 8080:
    python test_dq_systems.py

What it does:
  1. Lists all DQ systems in the database
  2. Shows which ones are suitable as flow schemas
  3. Creates a throwaway test process with exchange_dq_system set
  4. Reads it back to verify the field stuck
  5. Cleans up the test process

If this works, we know the MCP can safely offer flow schema
assignment during create_process.
"""

from olca_ipc import Client
import olca_schema as o
import sys


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"Connecting to openLCA IPC on port {port}...")

    try:
        client = Client(port)
    except Exception as e:
        print(f"ERROR: Could not connect to IPC server: {e}")
        print("Make sure openLCA is running with IPC server on port", port)
        return

    # ── Step 1: List all DQ systems ──────────────────────────
    print("\n=== DQ Systems in database ===")
    dq_descriptors = list(client.get_descriptors(o.DQSystem))

    if not dq_descriptors:
        print("No DQ systems found. Nothing to set as flow schema.")
        print("RESULT: Skip flow schema feature for this database.")
        return

    for i, dq in enumerate(dq_descriptors):
        print(f"  [{i+1}] {dq.name}  (id: {dq.id})")

    # ── Step 2: Fetch full details to see which have indicators ──
    print("\n=== DQ System details ===")
    suitable = []
    for dq_desc in dq_descriptors:
        dq_full = client.get(o.DQSystem, dq_desc.id)
        if not dq_full:
            print(f"  {dq_desc.name}: could not load full object")
            continue

        indicator_count = len(dq_full.indicators) if dq_full.indicators else 0
        has_uncertainties = getattr(dq_full, "has_uncertainties", None)
        print(f"  {dq_full.name}")
        print(f"    Indicators: {indicator_count}")
        print(f"    Has uncertainties: {has_uncertainties}")
        if dq_full.indicators:
            for ind in dq_full.indicators[:5]:
                print(f"      - {ind.name} ({len(ind.scores) if ind.scores else 0} scores)")

        suitable.append(dq_desc)

    if not suitable:
        print("\nNo usable DQ systems found.")
        return

    # ── Step 3: Create a test process with exchange_dq_system ──
    print("\n=== Creating test process with flow schema ===")
    test_dq = suitable[0]  # Use first available
    print(f"  Using DQ system: {test_dq.name}")

    # Create a minimal test flow
    test_flow = o.Flow()
    test_flow.id = "aaaaaaaa-test-dq-flow-000000000001"
    test_flow.name = "__TEST_DQ_FLOW (delete me)"
    test_flow.flow_type = o.FlowType.PRODUCT_FLOW

    # Find Mass flow property
    fp_ref = None
    for fp in client.get_descriptors(o.FlowProperty):
        if fp.name == "Mass":
            fp_ref = fp
            break
    if not fp_ref:
        print("  WARNING: No 'Mass' flow property found, trying first available")
        fps = list(client.get_descriptors(o.FlowProperty))
        if fps:
            fp_ref = fps[0]

    if fp_ref:
        test_flow.flow_properties = [o.FlowPropertyFactor(
            flow_property=fp_ref,
            conversion_factor=1.0,
            is_ref_flow_property=True,
        )]

    client.put(test_flow)
    print(f"  Created test flow: {test_flow.name}")

    # Create test process with exchange_dq_system set
    test_proc = o.Process()
    test_proc.id = "aaaaaaaa-test-dq-proc-000000000001"
    test_proc.name = "__TEST_DQ_PROCESS (delete me)"
    test_proc.process_type = o.ProcessType.UNIT_PROCESS
    test_proc.description = "Test process for DQ system assignment. Safe to delete."

    # Set the flow schema (exchange_dq_system)
    test_proc.exchange_dq_system = o.Ref(
        id=test_dq.id,
        name=test_dq.name,
        ref_type=o.RefType.DQSystem,
    )

    # Also try setting process schema
    test_proc.dq_system = o.Ref(
        id=test_dq.id,
        name=test_dq.name,
        ref_type=o.RefType.DQSystem,
    )

    # Add a simple exchange
    qref = o.Exchange()
    qref.internal_id = 1
    qref.flow = o.Ref(
        id=test_flow.id,
        name=test_flow.name,
        ref_type=o.RefType.Flow,
    )
    qref.amount = 1.0
    qref.is_input = False
    qref.is_quantitative_reference = True
    qref.is_avoided_product = False
    test_proc.exchanges = [qref]
    test_proc.last_internal_id = 1
    test_proc.quantitative_reference = qref

    proc_ref = client.put(test_proc)
    print(f"  Created test process: {proc_ref.name}")

    # ── Step 4: Read back and verify ─────────────────────────
    print("\n=== Verifying DQ system assignment ===")
    readback = client.get(o.Process, test_proc.id)
    if not readback:
        print("  ERROR: Could not read back test process")
    else:
        exch_dq = getattr(readback, "exchange_dq_system", None)
        proc_dq = getattr(readback, "dq_system", None)

        if exch_dq:
            print(f"  Flow schema (exchange_dq_system): {exch_dq.name} ✓")
        else:
            print("  Flow schema (exchange_dq_system): NOT SET ✗")

        if proc_dq:
            print(f"  Process schema (dq_system): {proc_dq.name} ✓")
        else:
            print("  Process schema (dq_system): NOT SET ✗")

    # ── Step 5: Clean up ─────────────────────────────────────
    print("\n=== Cleaning up ===")
    try:
        client.delete(readback)
        print("  Deleted test process ✓")
    except Exception as e:
        print(f"  Could not delete test process: {e}")
        print("  Delete '__TEST_DQ_PROCESS (delete me)' manually.")

    try:
        flow_obj = client.get(o.Flow, test_flow.id)
        if flow_obj:
            client.delete(flow_obj)
            print("  Deleted test flow ✓")
    except Exception as e:
        print(f"  Could not delete test flow: {e}")
        print("  Delete '__TEST_DQ_FLOW (delete me)' manually.")

    # ── Summary ──────────────────────────────────────────────
    print("\n=== Summary ===")
    print(f"  DQ systems found: {len(dq_descriptors)}")
    exch_ok = exch_dq is not None if readback else False
    proc_ok = proc_dq is not None if readback else False
    print(f"  exchange_dq_system assignment: {'WORKS' if exch_ok else 'FAILED'}")
    print(f"  dq_system assignment: {'WORKS' if proc_ok else 'FAILED'}")

    if exch_ok:
        print("\n  Ready to implement in MCP: create_process can accept")
        print("  a flow_schema parameter and set exchange_dq_system.")
    else:
        print("\n  Flow schema assignment did not persist via IPC.")
        print("  May need a different approach or newer olca-schema.")


if __name__ == "__main__":
    main()
