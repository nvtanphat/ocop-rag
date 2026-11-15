"""Conversation-memory stores for the public API.

They keep only conversational scope (slots, intent, capabilities) and a masked copy of the last question;
never authority, tenant or dossier content. ``SessionStore`` lives in one process; ``SqliteSessionStore``
shares the same state between worker processes on one host and survives restarts. Select with
``OCOP_SESSION_STORE=memory|sqlite`` (and ``OCOP_SESSION_DB``).
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from time import monotonic, time
from typing import Any, Mapping

from ai_core.orchestration.ocop import memory
from ai_core.orchestration.ocop.privacy import redact

TTL_SECONDS = 3600.0
MAX_SESSIONS = 512
UNANSWERED_INTENTS = frozenset({"CLARIFY", "OUT_OF_SCOPE"})


def next_state(prior: dict[str, Any], query: str, response: Any) -> dict[str, Any]:
    """Conversation state after one turn; shared by every store so they cannot drift apart."""
    if response.intent.value == "CONVERSATION":
        # Social traffic refreshes TTL but cannot age evidence, overwrite
        # the active query, or consume a pending clarification.
        state = copy.deepcopy(prior)
        state["dialogue"] = {"acts": list(getattr(getattr(response.route, "dialogue", None), "acts", []))}
        return state
    answered = not (
        getattr(response.route, "needs_clarification", False) or response.intent.value in UNANSWERED_INTENTS
    )
    if answered:
        return {
            "last_query": redact(getattr(response, "standalone_query", None) or query),
            "slots": dict(response.route.slots),
            "intent": response.intent.value,
            "capabilities": list(response.route.capabilities),
            "memory": memory.update(
                prior.get("memory"),
                slots=response.route.slots,
                standalone=redact(getattr(response, "standalone_query", None) or query),
                citations=list(getattr(response, "citations", None) or []),
                corpus_version=getattr(response, "corpus_version", None),
            ),
        }
    # A turn that only asked for clarification (or was out of scope) did not establish a topic: keep the scope the
    # conversation had, remember what is still unresolved.
    state = {k: v for k, v in prior.items() if k != "unresolved"}
    state["unresolved"] = {
        "question": redact(query),
        "missing_slots": list(getattr(response.route, "missing_slots", [])),
    }
    return state


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
            return copy.deepcopy(item[1])

    def save(self, session_id: str | None, query: str, response: Any) -> None:
        if not session_id:
            return
        with self._lock:
            stamp, prior = self._items.get(session_id, (0.0, {}))
            if self._clock() - stamp > self._ttl:
                prior = {}
            self._items[session_id] = (self._clock(), next_state(prior, query, response))
            self._items.move_to_end(session_id)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)


class SqliteSessionStore:
    """Session state in a SQLite file: shared by worker processes on one host and kept across restarts.

    Every update is one ``BEGIN IMMEDIATE`` transaction, so concurrent turns of a session are applied one after
    another instead of overwriting each other. Several hosts need a networked store behind the same get/save.
    """

    def __init__(self, path: Path, *, ttl: float = TTL_SECONDS, limit: int = MAX_SESSIONS, clock=time):
        self._path, self._ttl, self._limit, self._clock = Path(path), ttl, limit, clock
        self._path.parent.mkdir(parents=True, exist_ok=True)
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(id TEXT PRIMARY KEY, updated REAL NOT NULL, state TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS sessions_updated ON sessions (updated)")
        finally:
            db.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10, isolation_level=None)

    def _read(self, db: sqlite3.Connection, session_id: str) -> dict[str, Any]:
        row = db.execute("SELECT updated, state FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None or self._clock() - row[0] > self._ttl:
            return {}
        return json.loads(row[1])

    def get(self, session_id: str | None) -> dict[str, Any]:
        if not session_id:
            return {}
        db = self._connect()
        try:
            return self._read(db, session_id)
        finally:
            db.close()

    def save(self, session_id: str | None, query: str, response: Any) -> None:
        if not session_id:
            return
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            state = next_state(self._read(db, session_id), query, response)
            now = self._clock()
            db.execute(
                "INSERT INTO sessions (id, updated, state) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated = excluded.updated, state = excluded.state",
                (session_id, now, json.dumps(state, ensure_ascii=False)),
            )
            db.execute("DELETE FROM sessions WHERE updated < ?", (now - self._ttl,))
            db.execute(
                "DELETE FROM sessions WHERE id IN "
                "(SELECT id FROM sessions ORDER BY updated DESC LIMIT -1 OFFSET ?)",
                (self._limit,),
            )
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()


def make_store(env: Mapping[str, str] | None = None, *, root: Path | None = None):
    env = os.environ if env is None else env
    kind = env.get("OCOP_SESSION_STORE", "memory").strip().lower()
    if kind == "memory":
        return SessionStore()
    if kind == "sqlite":
        base = Path(env.get("OCOP_ROOT") or root or Path(__file__).resolve().parents[3])
        path = Path(env.get("OCOP_SESSION_DB") or base / "data" / "processed" / "ocop" / "sessions.sqlite3")
        return SqliteSessionStore(path)
    raise ValueError("OCOP_SESSION_STORE must be 'memory' or 'sqlite'")


default_store = make_store()
