"""
The client python_exec hands to its code: free to read and calculate,
and accountable for every write.

The Python route can do anything olcaBASIC has no command for, and run
R, Fortran or whatever else is installed. What it cannot do is make its
work count without the checks everything else passes:

  - every write (save, delete, product system built, file attached) is
    recorded and reported back with the result;
  - a write may only touch the model's own folders, those whose top
    folder starts with '00: ', so background data such as ecoinvent is
    never edited;
  - each product system holding a process the code changed is marked
    out of date and unvalidated, so CALCULATE, CONTRIBUTION, the EPD
    commands and the rest refuse it until it is built again and passes
    VALIDATE. The bridge rule and the structure check also read the
    database itself at those gates, so they hold even for a write made
    some other way.

Writes made through session.run() are olcaBASIC's own and already
checked; they are not recorded again.
"""

import contextlib
from typing import Dict, List, Optional

import olca_schema as o

MODEL_PREFIX = "00: "

# JSON-RPC methods that change the database or the server.
WRITE_METHODS = {
    "data/put": "save",
    "data/delete": "delete",
    "data/create/system": "build system",
    "data/put/source-file": "attach file",
    "runtime/shutdown": "shut down",
}


class WriteRefused(PermissionError):
    """A write the Python route may not make."""


def _in_model_folder(category: Optional[str]) -> bool:
    return (category or "").strip("/").startswith(MODEL_PREFIX)


def _type_name(thing) -> str:
    if isinstance(thing, type):
        return thing.__name__
    rt = getattr(thing, "ref_type", None)
    if rt is not None:
        return getattr(rt, "value", str(rt))
    return type(thing).__name__


def _schema_class(type_name: str):
    return getattr(o, type_name, None)


class CheckedClient:
    """Wraps an olca_ipc client. Reads pass straight through."""

    def __init__(self, client):
        self._client = client
        self._paused = 0
        self.writes: List[Dict] = []

    # ── plumbing ─────────────────────────────────────────────

    def __getattr__(self, name):
        return getattr(self._client, name)

    @contextlib.contextmanager
    def olcabasic_turn(self):
        """While olcaBASIC itself runs (session.run), its writes are its
        own and already checked."""
        self._paused += 1
        try:
            yield
        finally:
            self._paused -= 1

    def _record(self, action: str, type_name: str, entity_id: str,
                name: str = "", category: str = ""):
        if self._paused:
            return
        self.writes.append({"action": action, "type": type_name,
                            "id": entity_id, "name": name or "",
                            "folder": category or ""})

    def _stored_category(self, type_name: str, entity_id: str):
        """(exists, category) of what the database holds now."""
        cls = _schema_class(type_name)
        if cls is None or not entity_id:
            return False, None
        try:
            stored = self._client.get(cls, entity_id)
        except Exception:
            stored = None
        if stored is None:
            return False, None
        return True, getattr(stored, "category", None)

    def _check_folder(self, action: str, type_name: str, entity_id: str,
                      name: str, new_category: Optional[str]):
        if self._paused:
            return
        exists, old = self._stored_category(type_name, entity_id)
        if exists and not _in_model_folder(old):
            raise WriteRefused(
                f"Refused to {action} the {type_name} '{name}': it is in "
                f"'{old or 'the top folder'}', not in a model folder (one "
                f"whose top folder starts with '{MODEL_PREFIX}'). The Python "
                f"route does not edit background data. Copy it into a "
                f"model folder first, or use olcaBASIC.")
        if action == "save" and not _in_model_folder(new_category):
            raise WriteRefused(
                f"Refused to save the {type_name} '{name}' in "
                f"'{new_category or 'the top folder'}': the Python route "
                f"writes only in model folders, whose top folder starts "
                f"with '{MODEL_PREFIX}'. Set its category, for example "
                f"'{MODEL_PREFIX}My model'.")

    # ── the writing methods of olca_ipc.Client ───────────────

    def put(self, entity):
        type_name = type(entity).__name__
        name = getattr(entity, "name", "") or ""
        category = getattr(entity, "category", None)
        self._check_folder("save", type_name, getattr(entity, "id", ""),
                           name, category)
        out = self._client.put(entity)
        entity_id = getattr(out, "id", None) or getattr(entity, "id", "")
        self._record("save", type_name, entity_id, name, category or "")
        return out

    def delete(self, entity):
        type_name = _type_name(entity)
        entity_id = getattr(entity, "id", "")
        exists, category = self._stored_category(type_name, entity_id)
        name = getattr(entity, "name", "") or ""
        self._check_folder("delete", type_name, entity_id, name, category)
        out = self._client.delete(entity)
        self._record("delete", type_name, entity_id, name, category or "")
        return out

    def create_product_system(self, process, config=None):
        pid = getattr(process, "id", "")
        name = getattr(process, "name", "") or ""
        exists, category = self._stored_category("Process", pid)
        if not self._paused and not _in_model_folder(category):
            raise WriteRefused(
                f"Refused to build a product system for '{name}': the "
                f"process is not in a model folder (top folder starting "
                f"with '{MODEL_PREFIX}').")
        out = (self._client.create_product_system(process, config)
               if config is not None
               else self._client.create_product_system(process))
        self._record("build system", "ProductSystem",
                     getattr(out, "id", "") or "", name, category or "")
        return out

    def put_source_file(self, *args, **kwargs):
        if not self._paused:
            raise WriteRefused(
                "Attach files with olcaBASIC: MAKE SOURCE ... ATTACH or "
                "EDIT SOURCE ... ATTACH.")
        return self._client.put_source_file(*args, **kwargs)

    def rpc_call(self, method: str, params=None):
        action = WRITE_METHODS.get(method)
        if action is None or self._paused:
            return self._client.rpc_call(method, params)
        if method in ("runtime/shutdown", "data/put/source-file"):
            raise WriteRefused(
                f"Refused: '{method}' is not open to the Python route.")
        params = params or {}
        if method == "data/create/system":
            ref = params.get("process") or {}
            exists, category = self._stored_category(
                "Process", ref.get("@id", ""))
            if not _in_model_folder(category):
                raise WriteRefused(
                    "Refused to build a product system for a process that "
                    f"is not in a model folder ('{MODEL_PREFIX}...').")
            data, err = self._client.rpc_call(method, params)
            if not err:
                self._record(action, "ProductSystem",
                             (data or {}).get("@id", ""),
                             ref.get("name", ""), category or "")
            return data, err
        type_name = params.get("@type", "")
        entity_id = params.get("@id", "")
        name = params.get("name", "")
        category = params.get("category")
        self._check_folder(action, type_name, entity_id, name,
                           category if action == "save" else None)
        if action == "delete":
            _, category = self._stored_category(type_name, entity_id)
        data, err = self._client.rpc_call(method, params)
        if not err:
            self._record(action, type_name, entity_id, name, category or "")
        return data, err


class CheckedSession:
    """The Session as python_exec code sees it: session.run is olcaBASIC
    and checked already, so its writes are not recorded twice."""

    def __init__(self, session, checked: CheckedClient):
        self._session = session
        self._checked = checked

    def __getattr__(self, name):
        if name == "client":
            return self._checked
        return getattr(self._session, name)

    def run(self, *args, **kwargs):
        with self._checked.olcabasic_turn():
            return self._session.run(*args, **kwargs)


def settle(session, writes: List[Dict]) -> Dict:
    """After the code has run: forget what the engine remembers about
    the database, and mark every product system that holds a changed
    process (or was itself built or changed from Python) as out of date
    and unvalidated. Returns {"systems": [names], "notes": [lines]}."""
    interp = session.interpreter
    engine = session.engine
    engine.clear_caches()
    notes: List[str] = []
    marked: List[str] = []

    class _Lines:
        interactive = False

        def write(self, text=""):
            notes.append(str(text).strip())

        def data(self, *a, **k):
            pass

    old_out = interp.out
    interp.out = _Lines()
    try:
        seen = set()
        for w in writes:
            key = (w["type"], w["id"])
            if key in seen or not w["id"]:
                continue
            seen.add(key)
            if w["type"] == "Process":
                engine.forget_system_members()
                before = set(session.runtime.stale_systems)
                interp._mark_stale(w["id"], w["name"] or w["id"],
                                   f"{w['action']} from Python")
                for sid in set(session.runtime.stale_systems) - before:
                    marked.append(session.runtime.stale_systems[sid]["name"])
            elif w["type"] == "ProductSystem":
                engine.forget_system_members(w["id"])
                interp._forget_validation(w["id"])
                if w["name"]:
                    session.runtime.revalidate.add(w["name"])
                    marked.append(w["name"])
    finally:
        interp.out = old_out
    return {"systems": sorted(set(marked)), "notes": [n for n in notes if n]}
