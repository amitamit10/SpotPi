"""Sleep timer: trigger a playback action after a delay.

One timer per process. The HTTP layer supplies the callback that performs
the actual action (Spotify pause or service stop) so this module stays
free of I/O and is easy to test.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

ACTIONS = {"pause", "stop"}
MAX_SECONDS = 24 * 60 * 60

_lock = threading.Lock()
_timer: threading.Timer | None = None
_state: dict[str, Any] = {}


def status() -> dict[str, Any]:
    with _lock:
        if not _state:
            return {"active": False}
        remaining = max(0, round(_state["ends_at"] - time.time()))
        return {
            "active": True,
            "action": _state["action"],
            "ends_at": _state["ends_at"],
            "remaining_seconds": remaining,
        }


def start(seconds: float, action: str, callback: Callable[[str], None]) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(sorted(ACTIONS))}")
    if not 0 < seconds <= MAX_SECONDS:
        raise ValueError("timer must be between 1 second and 24 hours")

    def fire() -> None:
        global _timer
        with _lock:
            _state.clear()
            _timer = None
        try:
            callback(action)
        except Exception:
            pass

    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(seconds, fire)
        _timer.daemon = True
        _state.clear()
        _state.update({"action": action, "ends_at": time.time() + seconds})
        _timer.start()
    return status()


def cancel() -> dict[str, Any]:
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        _state.clear()
    return {"active": False}
