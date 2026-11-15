"""The shared session store behaves like the in-process one, and survives workers and restarts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ai_core.orchestration.ocop.sessions import SessionStore, SqliteSessionStore, make_store


def _response(intent="EXACT_LOOKUP", slots=None, *, clarify=False, missing=()):
    return SimpleNamespace(
        intent=SimpleNamespace(value=intent),
        route=SimpleNamespace(
            slots=slots or {"document_code": "26/2026"},
            capabilities=["x"],
            needs_clarification=clarify,
            missing_slots=list(missing),
        ),
    )


def _turns():
    return [
        ("QĐ26/2026 Điều 6 tenant_id=ACME?", _response("EXACT_LOOKUP", {"document_code": "26/2026", "years": ["2026"]})),
        ("Còn năm 2023?", _response("CLARIFY", {"years": ["2023"]}, clarify=True, missing=["event_year"])),
        ("Cảm ơn", _response("CONVERSATION")),
        ("Còn Điều 7?", _response("EXACT_LOOKUP", {"document_code": "26/2026", "article_id": "7"})),
    ]


def test_sqlite_store_follows_the_same_state_machine_as_memory(tmp_path):
    memory_store, shared = SessionStore(), SqliteSessionStore(tmp_path / "s.sqlite3")
    for index, (query, response) in enumerate(_turns()):
        memory_store.save("s", query, response)
        shared.save("s", query, response)
        assert shared.get("s") == memory_store.get("s")
        if index == 0:
            assert "ACME" not in shared.get("s")["last_query"]
    assert shared.get("s")["slots"]["article_id"] == "7"


def test_state_is_shared_between_workers_and_survives_restart(tmp_path):
    path = tmp_path / "s.sqlite3"
    first, second = SqliteSessionStore(path), SqliteSessionStore(path)
    first.save("s", "QĐ26/2026 Điều 6?", _response())
    assert second.get("s")["slots"] == {"document_code": "26/2026"}
    assert SqliteSessionStore(path).get("s") == first.get("s")


def test_sessions_expire_and_are_capped(tmp_path):
    now = [1000.0]
    store = SqliteSessionStore(tmp_path / "s.sqlite3", ttl=10, limit=2, clock=lambda: now[0])
    store.save("old", "q", _response())
    now[0] += 11
    assert store.get("old") == {}
    for index in range(3):
        now[0] += 1
        store.save(f"k{index}", "q", _response())
    assert store.get("k0") == {} and store.get("k1") and store.get("k2")


def test_concurrent_turns_in_many_sessions_are_all_kept(tmp_path):
    store = SqliteSessionStore(tmp_path / "s.sqlite3", limit=100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: store.save(f"s{i}", f"q{i}", _response()), range(40)))
    assert all(store.get(f"s{i}") for i in range(40))


def test_store_is_selected_by_environment(tmp_path):
    assert isinstance(make_store({}), SessionStore)
    selected = make_store({"OCOP_SESSION_STORE": "sqlite", "OCOP_SESSION_DB": str(tmp_path / "x.sqlite3")})
    assert isinstance(selected, SqliteSessionStore)
    with pytest.raises(ValueError):
        make_store({"OCOP_SESSION_STORE": "redis"})
