"""One conversation-memory store shared by the public and the debug API.

It keeps only conversational scope (slots, intent, capabilities) and a masked copy of the last question;
never authority, tenant or dossier content.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Any

from ai_core.orchestration.ocop.privacy import redact

TTL_SECONDS = 3600.0
MAX_SESSIONS = 512


class SessionStore:
    def __init__(self, *, ttl: float = TTL_SECONDS, limit: int = MAX_SESSIONS, clock=monotonic):
        self._ttl, self._limit, self._clock = ttl, limit, clock
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            return {}
        with self._lock:
            item = self._items.get(session_id)
            if item is None or self._clock() - item[0] > self._ttl:
                self._items.pop(session_id, None)
                return {}
            self._items.move_to_end(session_id)
            return dict(item[1])

    def save(self, session_id: str | None, query: str, response: Any) -> None:
        if not session_id:
            return
        with self._lock:
            self._items[session_id] = (self._clock(), {
                'last_query': redact(query),
                'slots': dict(response.route.slots),
                'intent': response.intent.value,
                'capabilities': list(response.route.capabilities),
            })
            self._items.move_to_end(session_id)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)


default_store = SessionStore()
