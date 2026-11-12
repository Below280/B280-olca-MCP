"""
The shortcut suite: programs an assistant in a hurry might send, each
trying one way round a rule. Every one must be refused with a line and
a hint, and must leave the database exactly as it was.

The same cases run through a Session (olcaBASIC, tests/test_shortcuts.py)
and through the MCP's olcabasic_run (B280-olca-MCP, tests/
test_shortcuts.py): this file is kept identical in both repositories,
like fake_client.py.

A case has:
    setup     programs that must run without error first (the honest
              part of the work), or functions (client, session) that
              prepare the database or the session
    program   the shortcut
    at        text of the line the error must point at
    message   pieces the error message must hold
    hint      pieces the hint must hold
"""

import datetime
from dataclasses import dataclass, field
from typing import Callable, List, Tuple, Union

import olca_schema as o

from fake_client import (ELECTRICITY, EPD_METHOD, LANDFILL, STEEL, TRANSPORT,
                         FakeClient, add_epd_methods, seed_ecoinvent_like)

EF = "EF v3.1"
TODAY = datetime.date(2026, 11, 12)      # the EPD rules look at data age


# ── the honest programs the shortcuts start from ─────────────

FOLDERS = '''CONFIRM DELETE ON
SET PROCESS FOLDER "00: Test"
SET FLOW FOLDER "00: Test"
'''

BRIDGES = f'''BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "GB"
END BRIDGE
BRIDGE "steel", kg
  PROVIDER "{STEEL}"
END BRIDGE
'''

B_ELEC = "BRIDGE | electricity | kWh"
B_STEEL = "BRIDGE | steel | kg"


def widget(steel="0.8", extra=""):
    return FOLDERS + BRIDGES + f'''LET elec = 2.5
MAKE PROCESS "Widget"
  OUTPUT MAKE FLOW "Widget", 1, kg, PRODUCT
  INPUT USE PROCESS "{B_ELEC}", elec, kWh
  INPUT USE PROCESS "{B_STEEL}", {steel}, kg
{extra}END PROCESS
'''


SYSTEM = 'SYSTEM "Widget"\nVALIDATE "Widget"\n'
CALC = f'CALCULATE "Widget" USING "{EF}"'

EPD_FOLDER = "00: Test EPD"
SECONDARY = 'DATA SECONDARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024'
PRIMARY = 'DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025'
RATINGS = ('RATING GEOGRAPHY "Good" REASON "Synthetic data, same region"\n'
           '  RATING TECHNOLOGY "Good" REASON "Synthetic data"\n'
           '  RATING TIME "Fair" REASON "Synthetic data"')
EXEMPT = ('  EXEMPT C AND D\n    INTEGRATED "Cast into the structure"\n'
          '    NOT IDENTIFIABLE "Chemically transformed"\n'
          '    END OF LIFE SCENARIOS "See the EPD of the structure"\n'
          '  END EXEMPT\n')


def epd_block(modules="A1, A2, A3, C1, C2, C3, C4, D", extra="",
              biogenic="NO"):
    return (f'EPD "Test block"\n'
            f'  PROGRAMME "IES" GPI "5.1.0"\n'
            f'  PCR "Test PCR" VERSION "1.0"\n'
            f'  DATABASE "synthetic" VERSION "1"\n'
            f'  DECLARED UNIT 1, kg\n'
            f'  METHOD "{EPD_METHOD}"\n'
            f'  FOLDER "{EPD_FOLDER}"\n'
            f'  MODULES {modules}\n'
            f'  BIOGENIC CARBON {biogenic}\n{extra}END EPD\n')


def epd_bridges(electricity="RESIDUAL", steel_data=SECONDARY):
    return f'''BRIDGE "Steel", kg
  PROVIDER "{STEEL}"
  {steel_data}
  {RATINGS}
END BRIDGE
BRIDGE "Electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "GB"
  ELECTRICITY {electricity}
  COUNTRY "GB"
  ENERGY SOURCE "Test mix"
  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {RATINGS}
END BRIDGE
BRIDGE "Lorry", t*km
  PROVIDER "{TRANSPORT}"
  DATA PRIMARY SOURCE "Database" PROVIDER "synthetic 1" YEAR 2024
  {RATINGS}
END BRIDGE
BRIDGE "Landfill", kg WASTE
  PROVIDER "{LANDFILL}"
  {SECONDARY}
  {RATINGS}
END BRIDGE
'''


MODULE_A1 = f'''MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1.1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", 1.1, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE
'''

MODULE_A2 = f'''MODULE A2
  MAKE PROCESS "Transport to factory"
    {PRIMARY}
    OUTPUT MAKE FLOW "Transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", 0.2, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
'''

MODULE_A3 = f'''MODULE A3
  MAKE PROCESS "Manufacturing"
    {PRIMARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Electricity | kWh", 2, kWh
  END PROCESS
  TOTAL "Manufacturing"
END MODULE
'''

MODULES_C_AND_D = f'''MODULE C1
  TOTAL "Deconstruction"
END MODULE
MODULE C2
  MAKE PROCESS "Transport to waste processing"
    {SECONDARY}
    OUTPUT MAKE FLOW "Waste transport, done", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Lorry | t*km", 0.05, t*km
  END PROCESS
  TOTAL "Transport"
END MODULE
MODULE C3
  TOTAL "Waste processing"
END MODULE
MODULE C4
  MAKE PROCESS "Landfilling"
    {SECONDARY}
    OUTPUT MAKE FLOW "Disposal, done", 1, kg, PRODUCT
    OUTPUT USE PROCESS "BRIDGE | Landfill | kg", 0.2, kg
  END PROCESS
  TOTAL "Disposal"
END MODULE
MODULE D
  NET FLOW "Steel scrap", 0.8, kg QUALITY 80%
  MAKE PROCESS "Avoided steel"
    {SECONDARY}
    OUTPUT MAKE FLOW "Credit", 1, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Steel | kg", -0.5, kg
  END PROCESS
  TOTAL "Benefits beyond the system boundary"
END MODULE
'''

FULL_EPD = MODULE_A1 + MODULE_A2 + MODULE_A3 + MODULES_C_AND_D


# ── things a program cannot do for itself ────────────────────

def twin_flows(client, session):
    """Two flows of one name, in two folders."""
    client.add_flow("shared blend", "Mass", category="00: Supplier A/Flows")
    client.add_flow("shared blend", "Mass", category="00: Supplier B/Flows")


def break_widget(client, session):
    """Take the reference product away, so VALIDATE fails."""
    proc = client.by_name(o.Process, "Widget")[0]
    for ex in proc.exchanges:
        ex.is_quantitative_reference = False


def reset(client, session):
    """What olcabasic_reset (or RESET) does."""
    session.reset()


def new_session(client, session):
    """Leave the session as a new one starts: nothing remembered about
    which systems were checked or changed."""
    session.reset()
    session.runtime.validation.clear()
    session.runtime.stale_systems.clear()
    session.runtime.revalidate.clear()


ADD_STEEL = (f'EDIT PROCESS "Widget"\n'
             f'  ADD INPUT USE PROCESS "{B_STEEL}", 0.1, kg\nEND EDIT')


def fixed_amount_process(client, session):
    """A database process with fixed amounts and an emission: what
    PARAMETERISE ... ALL would rewrite."""
    flows = {f.name: f for f in client.store["Flow"].values()}
    out = client.add_flow("test grid mix", "Energy", category="D:Test supply")
    provider = next(p for p in client.store["Process"].values()
                    if p.name == ELECTRICITY)

    def ref(flow):
        return o.Ref(id=flow.id, name=flow.name, ref_type=o.RefType.Flow)

    kwh, kg = client._unit_ref("kWh"), client._unit_ref("kg")
    client.put(o.Process(
        id="mix-0001", name="test grid mix, one source",
        category="D:Test supply", last_internal_id=3,
        process_type=o.ProcessType.UNIT_PROCESS,
        exchanges=[
            o.Exchange(internal_id=1, amount=1.0, is_input=False,
                       flow=ref(out), unit=kwh,
                       is_quantitative_reference=True),
            o.Exchange(internal_id=2, amount=1.0, is_input=True, unit=kwh,
                       flow=ref(flows["test electricity, medium voltage"]),
                       default_provider=o.Ref(
                           id=provider.id, name=provider.name,
                           ref_type=o.RefType.Process)),
            o.Exchange(internal_id=3, amount=0.001, is_input=False,
                       flow=ref(flows["Carbon dioxide, fossil"]), unit=kg),
        ]))


# ── the cases ────────────────────────────────────────────────

@dataclass
class Shortcut:
    key: str
    rule: str
    program: str
    at: str
    message: Tuple[str, ...]
    hint: Tuple[str, ...]
    setup: List[Union[str, Callable]] = field(default_factory=list)
    database: str = "standard"        # standard, epd or unknown family


CASES: List[Shortcut] = [

    # every background input goes through a bridge
    Shortcut(
        "background process straight in a process", "bridges",
        setup=[FOLDERS],
        program=f'''MAKE PROCESS "Quick widget"
  OUTPUT MAKE FLOW "Quick widget", 1, kg, PRODUCT
  INPUT USE PROCESS "{STEEL}", 0.8, kg
END PROCESS''',
        at=f'INPUT USE PROCESS "{STEEL}"',
        message=("is a background process", "goes through a bridge"),
        hint=("BRIDGE", "PROVIDER", "END BRIDGE")),
    Shortcut(
        "background process added with EDIT PROCESS", "bridges",
        setup=[widget()],
        program=f'''EDIT PROCESS "Widget"
  ADD INPUT USE PROCESS "{STEEL}", 0.1, kg
END EDIT''',
        at="ADD INPUT USE PROCESS",
        message=("is a background process",),
        hint=("BRIDGE",)),
    Shortcut(
        "background process added with LINK", "bridges",
        setup=[widget()],
        program=f'LINK PROCESS "{STEEL}" TO PROCESS "Widget" WITH 0.1, kg',
        at="LINK PROCESS",
        message=("is a background process",),
        hint=("BRIDGE",)),
    Shortcut(
        "background process straight in an EPD module", "bridges",
        database="epd",
        setup=[epd_block()],
        program=f'''MODULE A1
  MAKE PROCESS "Steel supply"
    {SECONDARY}
    OUTPUT MAKE FLOW "Steel, supplied", 1.1, kg, PRODUCT
    INPUT USE PROCESS "{STEEL}", 1.1, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''',
        at=f'INPUT USE PROCESS "{STEEL}"',
        message=("is a background process", "Inside MODULE A1"),
        hint=("Make a bridge to it first",)),

    # names
    Shortcut(
        "a process name that several processes share", "names",
        setup=[FOLDERS],
        program=f'''BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}"
END BRIDGE''',
        at='BRIDGE "electricity", kWh',
        message=("matches 3 processes",),
        hint=("LOCATION",)),
    Shortcut(
        "a flow name that several flows share", "names",
        setup=[twin_flows, FOLDERS],
        program='''MAKE PROCESS "Mixer"
  OUTPUT MAKE FLOW "Mix", 1, kg, PRODUCT
  INPUT USE FLOW "shared blend", 2, kg
END PROCESS''',
        at='INPUT USE FLOW "shared blend"',
        message=("matches 2 flows",),
        hint=("FOLDER", "UUID")),
    Shortcut(
        "a method name that is nearly right", "names",
        setup=[widget() + SYSTEM],
        program='CALCULATE "Widget" USING "EF 3.1"',
        at="CALCULATE",
        message=("No impact method is called 'EF 3.1'",),
        hint=('"EF v3.1"',)),

    # blocks and systems that no longer match
    Shortcut(
        "a changed block run again", "changed block",
        setup=[widget() + SYSTEM],
        program=widget(steel="0.9"),
        at='MAKE PROCESS "Widget"',
        message=("differs from this block",
                 "amount is 0.8 in the database and 0.9 in the block"),
        hint=('EDIT PROCESS "Widget"', 'DELETE PROCESS "Widget"')),
    Shortcut(
        "a changed block that would make a new flow", "changed block",
        setup=[widget() + SYSTEM],
        program=widget(extra='  OUTPUT MAKE FLOW "Offcut", 0.2, kg\n'),
        at='MAKE PROCESS "Widget"',
        message=("differs from this block",
                 'OUTPUT MAKE FLOW "Offcut" would create a flow'),
        hint=('EDIT PROCESS "Widget"',)),
    Shortcut(
        "a bridge block that now names another provider", "changed block",
        setup=[FOLDERS + BRIDGES],
        program=f'''BRIDGE "electricity", kWh
  PROVIDER "{ELECTRICITY}" LOCATION "DE"
END BRIDGE''',
        at='BRIDGE "electricity", kWh',
        message=("the bridge exists and passes on", "[GB]", "[DE]"),
        hint=('EDIT PROCESS "BRIDGE | electricity | kWh"',)),
    Shortcut(
        "a calculation on a stale system", "stale system",
        setup=[widget() + SYSTEM,
               f'EDIT PROCESS "Widget"\n  UPDATE INPUT "{B_STEEL}", 1.5, kg\n'
               f'END EDIT'],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' is out of date", "EDIT PROCESS"),
        hint=('DELETE SYSTEM "Widget"', 'VALIDATE "Widget"')),
    Shortcut(
        "a rebuilt system calculated before VALIDATE", "stale system",
        setup=[widget() + SYSTEM,
               f'EDIT PROCESS "Widget"\n  UPDATE INPUT "{B_STEEL}", 1.5, kg\n'
               f'END EDIT',
               'DELETE SYSTEM "Widget"\nSYSTEM "Widget"'],
        program=CALC,
        at="CALCULATE",
        message=("has not passed VALIDATE since",),
        hint=('VALIDATE "Widget"',)),
    Shortcut(
        "a calculation after a failed VALIDATE", "validation",
        setup=[widget() + 'SYSTEM "Widget"\n', break_widget,
               'VALIDATE "Widget"'],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' failed VALIDATE earlier in this session",),
        hint=('DELETE SYSTEM "Widget"', "VALIDATE")),
    Shortcut(
        "a failed VALIDATE, then RESET", "validation",
        setup=[widget() + 'SYSTEM "Widget"\n', break_widget,
               'VALIDATE "Widget"', reset],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' failed VALIDATE just now",),
        hint=('DELETE SYSTEM "Widget"', "VALIDATE")),
    Shortcut(
        "a failed VALIDATE, then a new session", "validation",
        setup=[widget() + 'SYSTEM "Widget"\n', break_widget,
               'VALIDATE "Widget"', new_session],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' failed VALIDATE just now",),
        hint=('DELETE SYSTEM "Widget"', "VALIDATE")),
    Shortcut(
        "an input added, then RESET", "stale system",
        setup=[widget() + SYSTEM, ADD_STEEL, reset],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' is out of date",),
        hint=('DELETE SYSTEM "Widget"', 'VALIDATE "Widget"')),
    Shortcut(
        "an input added, then a new session", "stale system",
        setup=[widget() + SYSTEM, ADD_STEEL, new_session],
        program=CALC,
        at="CALCULATE",
        message=("'Widget' is out of date", "has no link"),
        hint=('DELETE SYSTEM "Widget"', 'VALIDATE "Widget"')),

    # EPD and programme rules
    Shortcut(
        "a module using another module's process", "EPD modules",
        database="epd",
        setup=[epd_block() + epd_bridges() + MODULE_A1],
        program=f'''MODULE A3
  MAKE PROCESS "Manufacturing"
    {PRIMARY}
    OUTPUT MAKE FLOW "Block, at gate", 1, kg, PRODUCT
    INPUT USE PROCESS "A1 | Steel supply", 1.1, kg
  END PROCESS
  TOTAL "Manufacturing"
END MODULE''',
        at='INPUT USE PROCESS "A1 | Steel supply"',
        message=("belongs to module A1", "counted in both modules"),
        hint=("MODULE A3",)),
    Shortcut(
        "EPD CHECK SKIP under a programme", "programme",
        database="epd",
        setup=[epd_block() + epd_bridges() + FULL_EPD, "EPD SYSTEMS"],
        program='EPD CHECK SKIP "Checked by hand"',
        at="EPD CHECK SKIP",
        message=('not allowed under PROGRAMME "IES"',),
        hint=("Run EPD CHECK",)),
    Shortcut(
        "consumption-mix electricity in A3", "programme",
        database="epd",
        setup=[epd_block() + epd_bridges(electricity="CONSUMPTION")],
        program=MODULE_A3,
        at='INPUT USE PROCESS "BRIDGE | Electricity | kWh"',
        message=("consumption-mix electricity bridge", "direct control"),
        hint=("ELECTRICITY RESIDUAL",)),
    Shortcut(
        "a proxy share over 10%", "programme",
        database="epd",
        setup=[epd_block() + epd_bridges(
                   steel_data='DATA PROXY SOURCE "Database" PROVIDER '
                              '"synthetic 1" YEAR 2019 REASON "Other alloy"')
               + FULL_EPD,
               "EPD SYSTEMS\nEPD CHECK\nEPD CALCULATE"],
        program="EPD DATA QUALITY",
        at="EPD DATA QUALITY",
        message=("EPD DATA QUALITY found", "no override"),
        hint=("EPD DATA QUALITY again",)),
    Shortcut(
        "the C and D exemption with biogenic carbon", "programme",
        database="epd",
        program=epd_block(modules="A1, A2, A3", extra=EXEMPT, biogenic="YES"),
        at="BIOGENIC CARBON YES",
        message=("biogenic carbon",),
        hint=("Remove the EXEMPT block",)),

    # flows, factors, uncertainty, allocation
    Shortcut(
        "an OUTPUT that creates a flow by itself", "flows",
        setup=[FOLDERS],
        program='''MAKE PROCESS "Mill"
  OUTPUT MAKE FLOW "Flour", 1, kg, PRODUCT
  OUTPUT "Bran", 0.2, kg
END PROCESS''',
        at='OUTPUT "Bran"',
        message=("No flow is called 'Bran'",),
        hint=('OUTPUT MAKE FLOW "Bran"',)),
    Shortcut(
        "a new emission with no characterisation factor", "factors",
        setup=[widget(extra='  OUTPUT MAKE FLOW "Mystery gas", 0.1, kg '
                            'TO AIR\n') + SYSTEM],
        program=CALC,
        at="CALCULATE",
        message=("no characterisation factor for 'Mystery gas'",),
        hint=('IGNORE FACTORS "Mystery gas"',)),
    Shortcut(
        "Monte Carlo with nothing uncertain", "uncertainty",
        setup=[widget() + SYSTEM],
        program=f'MONTECARLO "Widget" USING "{EF}" RUNS 20',
        at="MONTECARLO",
        message=("nothing in 'Widget' is uncertain",),
        hint=("UNCERTAINTY",)),
    Shortcut(
        "allocation without factors", "allocation",
        setup=[widget(extra='  OUTPUT MAKE FLOW "Offcut", 0.2, kg\n')
               + SYSTEM],
        program=CALC + " ALLOCATE PHYSICAL",
        at="CALCULATE",
        message=("'Widget' has 2 products",
                 "no PHYSICAL allocation factors"),
        hint=("ALLOCATION PHYSICAL", "ALLOCATE NONE")),

    # commands that need a person
    Shortcut(
        "PARAMETERISE ... ALL", "needs a person",
        setup=[fixed_amount_process],
        program='PARAMETERISE PROCESS "test grid mix, one source" ALL '
                'CONFIRM',
        at="PARAMETERISE PROCESS",
        message=("needs an answer from the keyboard",),
        hint=("olcaBASIC terminal",)),
    Shortcut(
        "editing a method olcaBASIC did not make", "needs a person",
        program=f'''EDIT METHOD "{EF}"
  DESCRIPTION "Adjusted"
END METHOD''',
        at=f'EDIT METHOD "{EF}"',
        message=("was not made by olcaBASIC",),
        hint=("olcaBASIC terminal", "cannot be done through a Session")),
    Shortcut(
        "editing such a method with CONFIRM", "needs a person",
        program=f'''EDIT METHOD "{EF}" CONFIRM
  DESCRIPTION "Adjusted"
END METHOD''',
        at=f'EDIT METHOD "{EF}"',
        message=("needs an answer from the keyboard",),
        hint=("olcaBASIC terminal",)),

    # arguments that used to have a silent default
    Shortcut(
        "SENSITIVITY without BY", "no silent defaults",
        setup=[widget() + SYSTEM],
        program=f'''SENSITIVITY ON "Widget" USING "{EF}"
  VARY elec
END SENSITIVITY''',
        at="SENSITIVITY ON",
        message=("SENSITIVITY needs BY",),
        hint=("BY 10%",)),
    Shortcut(
        "MAKE FLOW without a database family", "no silent defaults",
        database="unknown family",
        program='MAKE FLOW "Thing", kg, PRODUCT',
        at="MAKE FLOW",
        message=("The database family is not known",),
        hint=('DATABASE FAMILY "ecoinvent"',)),
]

# The rules the design names (3.3). Every one has at least one case.
RULES = ("bridges", "names", "changed block", "stale system", "validation",
         "EPD modules", "programme", "flows", "factors", "uncertainty",
         "allocation", "needs a person", "no silent defaults")


# ── playing a case ───────────────────────────────────────────

def database(kind: str) -> FakeClient:
    if kind == "unknown family":
        client = FakeClient()
        group = client.add_unit_group("Units of mass", {"kg": 1.0}, "kg")
        client.add_flow_property("Mass", group)
        return client
    client = seed_ecoinvent_like()
    return add_epd_methods(client) if kind == "epd" else client


def snapshot(client) -> dict:
    """Everything the database holds."""
    return {kind: {uid: entity.to_dict() for uid, entity in table.items()}
            for kind, table in client.store.items()}


def line_of(program: str, text: str) -> int:
    for number, line in enumerate(program.splitlines(), 1):
        if text in line:
            return number
    raise AssertionError(f"{text!r} is not in the program")


def play(case: Shortcut, client, session, run):
    """Run the honest part, then the shortcut, and check the refusal.

    run(code) returns a dictionary with ok, text and errors (what
    Session.run(...).to_dict() and olcabasic_run both give)."""
    for step in case.setup:
        if callable(step):
            step(client, session)
            continue
        done = run(step)
        assert done["ok"], f"setup failed: {done['errors']}\n{done['text']}"
    before = snapshot(client)
    opened = client.undisposed()

    reply = run(case.program)

    assert not reply["ok"], f"not refused:\n{reply['text']}"
    assert len(reply["errors"]) == 1
    error = reply["errors"][0]
    assert error["line"] == line_of(case.program, case.at), error
    for piece in case.message:
        assert piece in error["message"], f"{piece!r} not in: {error}"
    for piece in case.hint:
        assert piece in error["hint"], f"{piece!r} not in: {error}"
    assert error["hint"], "a refusal says what to type instead"
    assert snapshot(client) == before, "the database was changed"
    assert client.undisposed() == opened, "a result was left open"
    return reply
