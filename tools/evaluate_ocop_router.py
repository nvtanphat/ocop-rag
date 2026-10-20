"""Reproducible curated intent/slot policy evaluation (NOT OCOP SOTA benchmark).

Usage: python tools/evaluate_ocop_router.py [path/to/jsonl]
Fixture labels are manually curated regression targets, not verified real-user gold.
"""

from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_core.orchestration.ocop.router import route_query
from ai_core.orchestration.ocop.contracts import Intent


def evaluate(path: Path) -> dict:
    samples = [json.loads(line) for line in path.read_text(encoding="utf8").splitlines() if line.strip()]
    tp = Counter()
    fp = Counter()
    fn = Counter()
    pairs = Counter()
    slot_total = slot_right = correct = 0
    for sample in samples:
        route = route_query(sample["query"], session=sample.get("session"))
        gold = sample["intent"]
        pred = route.intent.value
        pairs[(gold, pred)] += 1
        if gold == pred:
            correct += 1
            tp[gold] += 1
        else:
            fp[pred] += 1
            fn[gold] += 1
        for k, v in sample.get("slots", {}).items():
            slot_total += 1
            slot_right += int(route.slots.get(k) == v)
    labels = [x.value for x in Intent]
    metrics = {}
    for label in labels:
        p = tp[label] / (tp[label] + fp[label]) if tp[label] + fp[label] else 0
        r = tp[label] / (tp[label] + fn[label]) if tp[label] + fn[label] else 0
        metrics[label] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(2 * p * r / (p + r), 4) if p + r else 0,
        }
    return {
        "dataset": "curated_synthetic_router_regression_NOT_SOTA",
        "samples": len(samples),
        "intent_accuracy": round(correct / len(samples), 4) if samples else None,
        "macro_f1": round(sum(x["f1"] for x in metrics.values()) / len(labels), 4),
        "slot_exact_accuracy": round(slot_right / slot_total, 4) if slot_total else None,
        "slots_checked": slot_total,
        "by_intent": metrics,
        "errors": [{"gold": a, "predicted": b, "count": n} for (a, b), n in sorted(pairs.items()) if a != b],
    }


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/ocop/fixtures/ocop_router_eval.jsonl"
    print(json.dumps(evaluate(path), ensure_ascii=False, indent=2))
