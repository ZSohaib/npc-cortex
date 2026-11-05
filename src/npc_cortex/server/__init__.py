"""Network bridge: expose a runtime to non-Python engines over HTTP+JSON.

See ``docs/PROTOCOL.md`` for the wire format. Stdlib only.
"""

from __future__ import annotations

from .bridge import BridgeServer

__all__ = ["BridgeServer"]
