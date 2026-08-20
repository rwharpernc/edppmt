"""Self-update: checks GitHub Releases for a newer EDPPMT build, downloads
it, and stages it over the current install (never touching sessions.json,
which — like the update/backup folders below — isn't part of the
distributed release zip; see store.py and scripts/package.mjs).

Runs in a background thread (network I/O) and never touches Tkinter
directly — it hands the new version string to a plain callback, which the
caller marshals onto the main thread (see load.py). Staged files only take
effect on EDMC's next restart; nothing here reloads running code.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import datetime
from typing import Callable, Optional, Tuple
from zipfile import ZipFile

import requests
from config import appname, config

from . import __version__

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

RELEASES_API_URL = "https://api.github.com/repos/rwharpernc/edppmt/releases/latest"
RELEASES_PAGE_URL = "https://github.com/rwharpernc/edppmt/releases/latest"
REQUEST_TIMEOUT_S = 15
DOWNLOAD_TIMEOUT_S = 60
HEADERS = {"User-Agent": "EDPPMT-auto-update"}

CONFIG_AUTO_UPDATE = "edppmt_auto_update"
CONFIG_LAST_VERSION = "edppmt_last_version"

UPDATES_DIRNAME = "updates"
BACKUPS_DIRNAME = "backups"
BACKUPS_KEEP = 3
# Dev handbrake: drop a file with this name in the plugin folder to disable
# auto-update for that install, regardless of the Settings checkbox — e.g.
# for a folder you're actively hand-editing/testing builds in.
DISABLE_SENTINEL = "disable-auto-update.txt"

# Never touched by backup or apply, even though they live inside plugin_dir.
_OWN_DATA_FILES = {"sessions.json"}
_OWN_DIRS = {UPDATES_DIRNAME, BACKUPS_DIRNAME, "__pycache__"}


def _parse_version(value: str) -> Optional[Tuple[int, ...]]:
    try:
        parts = tuple(int(p) for p in value.strip().lstrip("vV").split("."))
    except ValueError:
        return None
    return parts if parts else None


def _pad(a: Tuple[int, ...], b: Tuple[int, ...]) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    length = max(len(a), len(b))
    return a + (0,) * (length - len(a)), b + (0,) * (length - len(b))


def check_applied_update() -> Optional[str]:
    """Compares the running version against the version recorded on the
    previous run and records the current one for next time.

    Returns the current version string if it differs from what was
    previously recorded (i.e. a staged update just took effect on this
    restart), or None on the first-ever run or when nothing changed.
    """
    previous = config.get_str(CONFIG_LAST_VERSION)
    config.set(CONFIG_LAST_VERSION, __version__)
    if previous and previous != __version__:
        return __version__
    return None


class UpdateManager:
    """Checks once, downloads/stages at most once, per EDMC run."""

    def __init__(
        self,
        plugin_dir: str,
        on_ready: Callable[[str], None],
        on_downloading: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._plugin_dir = plugin_dir
        self._updates_dir = os.path.join(plugin_dir, UPDATES_DIRNAME)
        self._backups_dir = os.path.join(plugin_dir, BACKUPS_DIRNAME)
        self._on_ready = on_ready
        self._on_downloading = on_downloading

    def check_async(self) -> None:
        if os.path.exists(os.path.join(self._plugin_dir, DISABLE_SENTINEL)):
            logger.info("Auto-update disabled by %s", DISABLE_SENTINEL)
            return
        if not config.get_bool(CONFIG_AUTO_UPDATE, default=True):
            logger.info("Auto-update disabled in Settings")
            return
        threading.Thread(target=self._check, name="EDPPMT-update-check", daemon=True).start()

    def _check(self) -> None:
        current = _parse_version(__version__)
        if current is None:
            logger.warning("Could not parse current version %r; skipping update check", __version__)
            return

        try:
            resp = requests.get(RELEASES_API_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.debug("Update check failed", exc_info=True)
            return

        if data.get("draft") or data.get("prerelease"):
            return

        remote = _parse_version(str(data.get("tag_name", "")))
        if remote is None:
            logger.debug("Could not parse remote version %r", data.get("tag_name"))
            return

        current_p, remote_p = _pad(current, remote)
        if remote_p <= current_p:
            logger.info("EDPPMT up to date (v%s)", __version__)
            return

        remote_str = ".".join(str(p) for p in remote)
        assets = data.get("assets") or []
        download_url = next(
            (a.get("browser_download_url") for a in assets if str(a.get("name", "")).endswith(".zip")),
            None,
        )
        if not download_url:
            logger.warning("Release v%s has no .zip asset to download", remote_str)
            return

        logger.info("Downloading EDPPMT v%s (current: v%s)", remote_str, __version__)
        self._download_and_stage(download_url, remote_str)

    def _download_and_stage(self, url: str, version: str) -> None:
        os.makedirs(self._updates_dir, exist_ok=True)
        zip_path = os.path.join(self._updates_dir, f"EDPPMT-v{version}.zip")

        if self._on_downloading is not None:
            self._on_downloading(version)

        try:
            resp = requests.get(url, headers=HEADERS, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
            resp.raise_for_status()
            with open(zip_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
        except Exception:
            logger.warning("Failed to download v%s update", version, exc_info=True)
            return

        try:
            self._backup_current()
            self._apply(zip_path)
        except Exception:
            logger.warning("Failed to stage v%s update", version, exc_info=True)
            return

        logger.info("EDPPMT v%s staged — restart EDMC to apply", version)
        self._on_ready(version)

    def _backup_current(self) -> None:
        os.makedirs(self._backups_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = os.path.join(self._backups_dir, f"{stamp}.zip")

        with ZipFile(backup_path, "w") as zf:
            for root, dirs, files in os.walk(self._plugin_dir):
                dirs[:] = [d for d in dirs if d not in _OWN_DIRS]
                for name in files:
                    if name in _OWN_DATA_FILES or name.endswith((".pyc", ".pyo")):
                        continue
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, self._plugin_dir))

        self._trim_backups()

    def _trim_backups(self) -> None:
        backups = sorted(
            (os.path.join(self._backups_dir, f) for f in os.listdir(self._backups_dir)),
            key=os.path.getctime,
        )
        for stale in backups[:-BACKUPS_KEEP]:
            try:
                os.remove(stale)
            except OSError:
                logger.debug("Could not remove stale backup %s", stale, exc_info=True)

    def _apply(self, zip_path: str) -> None:
        with ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # Release zips contain a top-level EDPPMT/ folder (see
            # scripts/package.mjs), so strip it — plugin_dir *is* that
            # folder already.
            prefix = names[0].split("/", 1)[0] + "/" if names and "/" in names[0] else ""

            for member in zf.infolist():
                relative = member.filename[len(prefix):] if prefix and member.filename.startswith(prefix) else member.filename
                if not relative or relative in _OWN_DATA_FILES:
                    continue

                target = os.path.join(self._plugin_dir, relative)
                if member.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue

                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
