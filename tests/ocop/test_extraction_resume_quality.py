"""Coverage and resumability through the public extraction contract."""

import json

from ai_core.knowledge.ocop.llm_proposals import propose


class Client:
    model = "synthetic-resume"

    def __init__(self):
        self.calls = []
        self.fail = None

    def chat(self, system, user, **kwargs):
        self.calls.append(user)
        if self.fail and self.fail in user:
            raise RuntimeError("synthetic transient failure")
        return json.dumps({"entities": [], "relations": [], "rules": []})


def units(count):
    return [
        {
            "source_id": "SYNTHETIC",
            "unit_id": f"unit:{i}",
            "unit_kind": "paragraph",
            "text": f"Synthetic evidence item {i}.",
        }
        for i in range(count)
    ]


def test_default_extraction_covers_every_eligible_unit(tmp_path):
    output = propose(units(63), Client(), cache_dir=tmp_path)
    assert output["processed_unit_count"] == 63
    assert output["omissions"] == []


def test_explicit_budget_is_not_subject_to_a_corpus_size_ceiling(tmp_path):
    assert propose(units(1), Client(), max_units=100_001, cache_dir=tmp_path)["processed_unit_count"] == 1


def test_resume_retries_failed_unit_and_reuses_completed_responses(tmp_path):
    client = Client()
    client.fail = "item 0."
    first = propose(units(2), client, cache_dir=tmp_path)
    statuses = {r["evidence_unit_id"]: r["status"] for r in first["unit_statuses"]}
    assert statuses == {"unit:0": "failed", "unit:1": "processed"}
    assert first["processed_unit_count"] == 1
    assert first["chunk_errors"][0]["chunk_start"] == 0
    assert first["omissions"] == [{"evidence_unit_id": "unit:0", "reason": "semantic_unit_failed"}]
    client.calls.clear()
    client.fail = None
    second = propose(units(2), client, cache_dir=tmp_path)
    assert len(client.calls) == 1 and "item 0." in client.calls[0]
    assert second["processed_unit_count"] == 2 and second["omissions"] == []


def test_corrupt_response_cache_is_recovered_on_resume(tmp_path):
    client = Client()
    propose(units(1), client, cache_dir=tmp_path)
    next(tmp_path.glob("*.json")).write_text("{", encoding="utf-8")
    client.calls.clear()
    recovered = propose(units(1), client, cache_dir=tmp_path)
    assert recovered["processed_unit_count"] == 1
    assert recovered["errors"] == [] and len(client.calls) == 1
