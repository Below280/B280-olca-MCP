"""
The shortcut suite: an assistant cutting corners, through olcabasic_run.

Each case sends one program that tries a way round a rule (see
shortcut_cases.py, which is the same file as in olcaBASIC's tests).
The reply must be a refusal with a line and a hint, and the database
must be exactly as it was. The cases also run through a plain Session
in olcaBASIC's own tests, so the rules do not depend on this server.
"""

import pytest

import shortcut_cases as sc
from conftest import Harness, make_server
from olcabasic.workflows.epd import EpdWorkflow


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr(EpdWorkflow, "today", staticmethod(lambda: sc.TODAY))


def harness_for(case):
    client = sc.database(case.database)
    return client, Harness(make_server(client))


@pytest.mark.parametrize("case", sc.CASES, ids=[c.key for c in sc.CASES])
def test_the_shortcut_is_refused_through_olcabasic_run(case):
    client, harness = harness_for(case)
    reply = sc.play(case, client, harness.server.session,
                    lambda code: harness.call("olcabasic_run", {"code": code}))
    # the reply is the JSON shape of every olcabasic_run call
    assert set(reply) >= {"ok", "text", "data", "errors", "warnings"}
    assert "Error: Line" in reply["text"] or "Parse error" in reply["text"]


@pytest.mark.parametrize("case", sc.CASES, ids=[c.key for c in sc.CASES])
def test_a_dry_run_does_not_get_round_it_either(case):
    """dry_run checks a program without touching openLCA. Whatever it
    says, the database is the same afterwards, and running the program
    for real is still refused."""
    client, harness = harness_for(case)
    session = harness.server.session
    for step in case.setup:
        if callable(step):
            step(client, session)
        else:
            assert harness.call("olcabasic_run", {"code": step})["ok"]
    before = sc.snapshot(client)
    harness.call("olcabasic_run", {"code": case.program, "dry_run": True})
    assert sc.snapshot(client) == before
    assert not harness.call("olcabasic_run", {"code": case.program})["ok"]
    assert sc.snapshot(client) == before


def test_every_rule_of_the_design_has_a_case():
    assert {case.rule for case in sc.CASES} == set(sc.RULES)


def test_the_cases_are_the_ones_olcabasic_tests(tmp_path):
    """shortcut_cases.py is a copy of the file in olcaBASIC's tests. If
    olcaBASIC is installed from a source tree, the two must be equal."""
    import os
    import olcabasic
    theirs = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(olcabasic.__file__))), "tests", "shortcut_cases.py")
    if not os.path.exists(theirs):
        pytest.skip("olcaBASIC is not installed from a source tree")
    mine = os.path.join(os.path.dirname(__file__), "shortcut_cases.py")
    with open(mine, encoding="utf-8") as a, open(theirs, encoding="utf-8") as b:
        assert a.read() == b.read()
