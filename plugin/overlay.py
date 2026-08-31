"""EDMCOverlay transport: draws text/shapes on top of the game window via a
separate, optional helper app (https://github.com/inorton/EDMCOverlay) that
listens on a local TCP socket and renders whatever it's sent. EDPPMT never
installs or launches that app itself — it's the user's own tool to have
running; this module just knows how to talk to it if it is.

Protocol (confirmed against inorton/EDMCOverlay's own `edmcoverlay.py`
client): connect, send one JSON object + "\n", e.g.
`{"id": "x", "text": "hi", "color": "red", "x": 200, "y": 100, "ttl": 4}`.
No response is read back — sends are fire-and-forget.

Kept generic (not interdiction-specific) so a later overlay feature can
reuse it without touching this module — see interdiction.py for the first
(and currently only) consumer.
"""

from __future__ import annotations

import json
import logging
import os
import socket
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
    """Opens a short-lived connection per send rather than holding one open
    — EDMCOverlay messages are infrequent (interdiction warnings, at most a
    few per encounter), so there's no persistent-connection/threading
    complexity worth taking on for it. Config is re-read fresh on every send
    (host/port are rarely-set-and-forget, but this way Settings changes take
    effect immediately without a reload_config() call, and the same instance
    can be created once at plugin-start time)."""

    def __init__(self, cfg: Optional[OverlayConfig] = None) -> None:
        self._cfg = cfg

    def _send(self, payload: dict) -> None:
        cfg = self._cfg or load_config()
        try:
            port = int(cfg.port)
        except ValueError:
            port = int(DEFAULT_PORT)

        with socket.create_connection((cfg.host, port), timeout=CONNECT_TIMEOUT_S) as sock:
            sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")

    def send_message(
        self, msg_id: str, text: str, color: str, x: int, y: int, ttl: int = 8, size: str = "normal",
    ) -> None:
        """Raises on failure (e.g. EDMCOverlay isn't running) — callers
        decide whether that should be swallowed (live feature paths) or
        surfaced (the Settings "Test Warning" button)."""
        self._send({"id": msg_id, "text": text, "color": color, "x": x, "y": y, "ttl": ttl, "size": size})

    def send_shape(
        self, shape_id: str, shape: str, color: str, fill: str, x: int, y: int, w: int, h: int, ttl: int = 8,
    ) -> None:
        self._send(
            {"id": shape_id, "shape": shape, "color": color, "fill": fill, "x": x, "y": y, "w": w, "h": h, "ttl": ttl},
        )
