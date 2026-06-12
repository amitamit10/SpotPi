"""Recently-played track history, persisted under /var/lib/<service>/."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_ENTRIES = 50

_lock = threading.Lock()


def history_file(service_name: str) -> Path:
    return Path("/var/lib") / service_name / "history.json"


def load_history(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
    except (OSError, ValueError):
        pass
    return []


def _write(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(entries), encoding="utf-8")
    os.replace(temp_path, path)


def record_track(path: Path, track: dict[str, Any], max_entries: int = MAX_ENTRIES) -> bool:
    """Prepend a track unless it matches the most recent entry.

    Returns True when a new entry was written. When the same track is seen
    again, metadata that arrived late (artist, album, cover) is backfilled
    into the existing entry instead.
    """
    name = (track.get("name") or "").strip()
    if not name:
        return False
    track_id = track.get("track_id") or ""

    with _lock:
        entries = load_history(path)
        if entries:
            last = entries[0]
            same = (track_id and last.get("track_id") == track_id) or (
                not track_id and last.get("name") == name
            )
            if same:
                backfilled = False
                for key in ("artists", "album", "cover_url"):
                    if track.get(key) and not last.get(key):
                        last[key] = track[key]
                        backfilled = True
                if backfilled:
                    _write(path, entries)
                return False
        entries.insert(0, {
            "track_id": track_id,
            "name": name,
            "artists": track.get("artists", "") or "",
            "album": track.get("album", "") or "",
            "cover_url": track.get("cover_url", "") or "",
            "played_at": datetime.now(timezone.utc).isoformat(),
        })
        _write(path, entries[:max_entries])
    return True


def clear_history(path: Path) -> None:
    with _lock:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
