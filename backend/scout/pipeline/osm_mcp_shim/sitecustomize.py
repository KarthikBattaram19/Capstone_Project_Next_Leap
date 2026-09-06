"""User-Agent shim for the osm-mcp-server subprocess — loaded via PYTHONPATH, never imported by us.

Why this exists (verified 2026-09-06): the upstream server (PyPI ``osm-mcp-server`` 0.1.1)
opens one ``aiohttp.ClientSession()`` with no default headers and posts every Overpass query
with aiohttp's default User-Agent (``Python/3.12 aiohttp/3.x``). overpass-api.de answers
HTTP 406 to *any* User-Agent containing the word "aiohttp", so every Overpass call through
the server fails. Patching the server package is not an option (it lives in uv's cache and is
reinstalled on every ``uvx`` run), so ``OsmMcp`` starts the server with
``PYTHONPATH=<this directory>``: CPython imports a module named ``sitecustomize`` from
``sys.path`` at start-up, which is this file, which patches aiohttp before the server imports it.

There is deliberately no ``__init__.py`` here — this directory is not a package of ours, and
``scout`` never imports it.

Two patches, both on ``aiohttp.ClientSession`` (signature checked on aiohttp 3.14.3:
``__init__(self, base_url=None, *, ..., headers=None, ...)`` and
``post(self, url, *, data=None, **kwargs)``):

1. ``__init__`` gets a default ``User-Agent`` of ``scout-capstone/0.1 (<repo URL>)`` — no
   "aiohttp", no "python" in the string. A session that already sets its own User-Agent keeps it,
   and per-request headers (the server sends ``OSM-MCP-Server/1.0`` to Nominatim) still win.
2. ``post`` redirects ``https://overpass-api.de/api/interpreter`` to ``$OVERPASS_URL`` when that
   variable is set, so a public mirror (``https://overpass.kumi.systems/api/interpreter``,
   ``https://overpass.private.coffee/api/interpreter``) can stand in when the main host is down.
"""

from __future__ import annotations

import os
import sys

USER_AGENT = "scout-capstone/0.1 (https://github.com/KarthikBattaram19/Capstone_Project_Next_Leap)"
OVERPASS_MAIN = "https://overpass-api.de/api/interpreter"

try:
    import aiohttp
    from multidict import CIMultiDict
except ImportError:  # pragma: no cover - a Python without aiohttp has nothing to patch
    aiohttp = None  # type: ignore[assignment]

if aiohttp is not None and not getattr(aiohttp.ClientSession, "_scout_shim", False):
    _orig_init = aiohttp.ClientSession.__init__
    _orig_post = aiohttp.ClientSession.post

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        headers = CIMultiDict(kwargs.get("headers") or {})
        headers.setdefault("User-Agent", USER_AGENT)
        kwargs["headers"] = headers
        _orig_init(self, *args, **kwargs)

    def _post(self, url, *, data=None, **kwargs):  # type: ignore[no-untyped-def]
        mirror = os.environ.get("OVERPASS_URL")
        if mirror and str(url) == OVERPASS_MAIN:
            url = mirror
        return _orig_post(self, url, data=data, **kwargs)

    aiohttp.ClientSession.__init__ = _init  # type: ignore[method-assign]
    aiohttp.ClientSession.post = _post  # type: ignore[method-assign]
    aiohttp.ClientSession._scout_shim = True  # type: ignore[attr-defined]
    # One line on stderr so the run log shows the shim was in force and where Overpass went.
    print(
        f"scout osm shim active: User-Agent={USER_AGENT!r}; "
        f"OVERPASS_URL={os.environ.get('OVERPASS_URL') or '(unset: overpass-api.de)'}",
        file=sys.stderr,
    )
