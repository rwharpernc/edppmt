"""EDMCOverlay transport: draws text/shapes on top of the game window via a
separate, optional helper app (https://github.com/inorton/EDMCOverlay) that
listens on a local TCP socket and renders whatever it's sent. EDPPMT never
installs or launches that app itself — it's the user's own tool to have
running; this module just knows how to talk to it if it is.

Protocol (confirmed against inorton/EDMCOverlay's own `edmcoverlay.py`
client): connect, send one JSON object + "\n", e.g.
`{"id": "x", "text": "hi", "color": "red", "x": 200, "y": 100, "ttl": 4}`.
No response is read back — sends are fire-and-forget.

IMPORTANT — the connection must stay open for as long as its graphics
should stay visible. Confirmed against EDMCOverlay's own server source
(`OverlayJsonServer.ServerThread`): each TCP connection gets a `clientId`,
and every graphic sent over it is tagged with that id; the `ttl` field
*does* control expiry independently (`InternalGraphic.Update` sets
`expires = DateTime.Now.AddSeconds(g.TTL)` on every resend), but the
server's `finally` block additionally wipes *all* graphics owned by a
`clientId` the instant that connection disconnects — regardless of their
ttl. A connect-send-immediately-close-per-message client (this module's
original design) therefore has every single graphic deleted moments after
it arrives, independent of the ttl passed. `OverlayClient` now holds one
persistent connection open for its whole lifetime instead (reconnecting
lazily if it drops), matching how bgol/LandingPad's own working client
(`lpads/overlay.py`) does it.

Kept generic (not interdiction-specific) so other overlay features can
reuse it without touching this module — see interdiction.py and landing.py
for the current consumers.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from dataclasses import dataclass
from typing import Optional

from config import appname, config

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

_CFG_HOST = "edppmt_overlay_host"
_CFG_PORT = "edppmt_overlay_port"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "5010"

# Short — this is a local-loopback connection to an app that's either
# running (near-instant) or not (fails fast); a long timeout would stall
# journal processing waiting on a helper app that isn't there.
CONNECT_TIMEOUT_S = 1.0


@dataclass
class OverlayConfig:
    host: str = DEFAULT_HOST
    port: str = DEFAULT_PORT


def load_config() -> OverlayConfig:
    return OverlayConfig(
        host=config.get_str(_CFG_HOST) or DEFAULT_HOST,
        port=config.get_str(_CFG_PORT) or DEFAULT_PORT,
    )


def save_config(cfg: OverlayConfig) -> None:
    config.set(_CFG_HOST, cfg.host)
    config.set(_CFG_PORT, cfg.port)


class OverlayClient:
    """Holds one persistent connection open for the client's whole lifetime
    (see the module docstring for why this is required, not just an
    optimization) rather than one per send. Config is only actually
    re-read when a (re)connect is needed — normally just once, on the
    first send — since re-reading it on every already-connected send would
    have no effect anyway (a live host/port change can't migrate an
    already-open socket); a Settings change to host/port takes effect on
    this client's *next* reconnect, e.g. after EDMCOverlay itself restarts,
    or via a fresh `OverlayClient` instance (the Settings "Test Overlay"/
    "Test Warning" buttons always construct one of those against whatever
    is currently in the dialog).

    Sends are serialized with a lock: `load.py` shares one `OverlayClient`
    instance across interdiction.py and landing.py, and each fires its
    render from its own background thread, so concurrent sends on the same
    socket are a real possibility, not just a theoretical one."""

    def __init__(self, cfg: Optional[OverlayConfig] = None) -> None:
        self._cfg = cfg
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def _connect_locked(self) -> socket.socket:
        cfg = self._cfg or load_config()
        try:
            port = int(cfg.port)
        except ValueError:
            port = int(DEFAULT_PORT)
        sock = socket.create_connection((cfg.host, port), timeout=CONNECT_TIMEOUT_S)
        self._sock = sock
        return sock

    def _send(self, payload: dict) -> None:
        """Raises OSError (e.g. EDMCOverlay isn't running, or the socket
        was reset) after trying once to reconnect - a single reconnect
        attempt covers "EDMCOverlay wasn't running yet" and "EDMCOverlay
        was restarted since our last send" without silently retrying
        forever on a send that's genuinely never going to land."""
        data = json.dumps(payload).encode("utf-8") + b"\n"
        with self._lock:
            sock = self._sock
            if sock is None:
                sock = self._connect_locked()
            try:
                sock.sendall(data)
                return
            except OSError:
                self._close_locked()
            sock = self._connect_locked()
            sock.sendall(data)

    def _close_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self) -> None:
        """Drops the connection (if any) so the next send reconnects fresh.
        Safe to call whether or not a connection is currently open."""
        with self._lock:
            self._close_locked()

    def send_message(
        self, msg_id: str, text: str, color: str, x: int, y: int, ttl: int = 8, size: str = "normal",
    ) -> None:
        """Raises on failure (e.g. EDMCOverlay isn't running) — callers
        decide whether that should be swallowed (live feature paths) or
        surfaced (the Settings "Test Warning" button)."""
        self._send({"id": msg_id, "text": text, "color": color, "x": x, "y": y, "ttl": ttl, "size": size})

    def send_shape(
        self, shape_id: str, shape: str, color: str, fill: str, x: int, y: int, w: int, h: int, ttl: int = 8,
        thickness: Optional[int] = None,
    ) -> None:
        """`fill`/`color` accept "#AARRGGBB" (alpha channel first) on both
        classic EDMCOverlay and EDMCModernOverlay - the translucent card
        backgrounds in interdiction.py/landing.py lean on this. `thickness`
        (border width) is an EDMCModernOverlay-only extension - included
        only when given, and harmless on classic EDMCOverlay (an unknown
        JSON field, silently ignored by its Newtonsoft.Json deserializer)."""
        payload = {
            "id": shape_id, "shape": shape, "color": color, "fill": fill, "x": x, "y": y, "w": w, "h": h, "ttl": ttl,
        }
        if thickness is not None:
            payload["thickness"] = thickness
        self._send(payload)

    def send_vector(
        self, shape_id: str, points: list, color: str, ttl: int = 8,
    ) -> None:
        """A "vect" shape: connected line segments through `points` (each a
        dict with "x"/"y", and optionally "color"/"marker"/"text" for a
        per-point decoration - "marker" is "cross" or "circle"). A single-
        point list draws just that point's marker/text with no line, which
        landing.py uses for the pad-diagram's active-pad indicator. An empty
        list draws nothing (used to clear a previously-sent id before its
        ttl naturally expires - see landing.py's diagram clear helpers)."""
        vector = [
            {
                "x": int(round(p["x"])),
                "y": int(round(p["y"])),
                **({"color": p["color"]} if p.get("color") else {}),
                **({"marker": p["marker"]} if p.get("marker") else {}),
                **({"text": p["text"]} if p.get("text") else {}),
            }
            for p in points
        ]
        self._send({"id": shape_id, "shape": "vect", "color": color, "vector": vector, "ttl": ttl})
