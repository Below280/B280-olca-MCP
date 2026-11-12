"""
Deprecated: the engine moved to olcaBASIC.

Up to v1.16.0 this module held LCAFunctions, the class that talks to
openLCA. From v2.0.0 it lives in olcaBASIC as olcabasic.engine.Engine,
and this module only re-exports it under the old name so that existing
imports keep working for one major version.

    # old
    from b280_olca_mcp.functions import LCAFunctions
    # new
    from olcabasic.engine import Engine
"""

import warnings

from olcabasic.engine import Engine

warnings.warn(
    "b280_olca_mcp.functions is deprecated and will be removed in "
    "B280-olca-MCP 3.0. Use 'from olcabasic.engine import Engine' "
    "(LCAFunctions is the same class under its old name).",
    DeprecationWarning,
    stacklevel=2,
)

LCAFunctions = Engine

__all__ = ["LCAFunctions", "Engine"]
