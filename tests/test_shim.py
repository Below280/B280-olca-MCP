"""The old import path still works, with a deprecation warning."""

import importlib
import sys
import warnings


def test_functions_shim_reexports_the_engine_and_warns():
    sys.modules.pop("b280_olca_mcp.functions", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        module = importlib.import_module("b280_olca_mcp.functions")
    from olcabasic.engine import Engine
    assert module.LCAFunctions is Engine
    assert any(issubclass(w.category, DeprecationWarning)
               and "olcabasic.engine" in str(w.message) for w in caught)


def test_ipc_reference_is_still_importable():
    from b280_olca_mcp.ipc_reference import IPC_PROTOCOL_REFERENCE
    assert "JSON-RPC" in IPC_PROTOCOL_REFERENCE


def test_server_does_not_import_the_shim():
    import b280_olca_mcp.server as server
    source = open(server.__file__, encoding="utf-8").read()
    assert "from .functions import" not in source
