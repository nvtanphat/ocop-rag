"""Semantic tier of the router: the intent whose example utterances a question most resembles.

Rules (vocabulary in ``configs/ocop_language.yaml``) decide first. Where they find no signal, a question is compared by
embedding similarity with the example utterances of ``configs/ocop_router_examples.yaml`` (the pattern of Semantic Router):
the closest intent wins only when it is both close enough and clearly ahead of the next one. Anything less is no proposal,
and the router falls through to the model tier or to its deterministic default.

The embedding model is the one the retrieval index was built with, loaded through the same cached loader, so an API that
serves hybrid retrieval already holds it. Every failure (no dense index, model missing, bad file) yields no proposal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "configs" / "ocop_router_examples.yaml"


@dataclass(frozen=True)
class Proposal:
    intent: str
    score: float  # similarity of the closest example of the winning intent
    margin: float  # lead over the best example of any other intent


class SemanticRouter:
    def __init__(self, examples: dict[str, list[str]], encode: Callable[[list[str]], "np.ndarray"]):
        self._encode = encode
        self._labels = [intent for intent, texts in examples.items() for _ in texts]
        self._vectors = np.asarray(encode([t for texts in examples.values() for t in texts]), dtype=float)

    def classify(self, text: str) -> Proposal | None:
        vector = np.asarray(self._encode([text]), dtype=float)[0]
        best: dict[str, float] = {}
        for label, similarity in zip(self._labels, self._vectors @ vector):
            best[label] = max(best.get(label, -1.0), float(similarity))
        ranked = sorted(best.items(), key=lambda item: -item[1])
        if len(ranked) < 2:
            return None
        return Proposal(ranked[0][0], ranked[0][1], ranked[0][1] - ranked[1][1])


def load_examples(path: Path = EXAMPLES) -> dict[str, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(intent): [str(t) for t in texts] for intent, texts in (data.get("intents") or {}).items()}


@lru_cache(maxsize=2)
def _router(model_id: str, revision: str | None, stamp: int) -> SemanticRouter:
    from ai_core.retrieval.ocop import model_runtime
    from ai_core.retrieval.ocop.index_pipeline import _encode, _load_embedding

    def encode(texts: list[str]):
        with model_runtime.inference():
            with model_runtime.tensor_reader():
                model = _load_embedding(model_id, revision)
            return _encode(model, texts, True)

    return SemanticRouter(load_examples(), encode)


def for_index(index_dir: Path) -> Callable[[str], Proposal | None]:
    """A classifier over the embedding model of ``index_dir``; it proposes nothing when that model is unavailable."""

    def classify(text: str) -> Proposal | None:
        try:
            manifest = json.loads((Path(index_dir) / "manifest.json").read_text(encoding="utf-8"))
            dense = manifest.get("dense") or {}
            if not dense.get("enabled"):
                return None
            return _router(dense["model_id"], dense.get("revision"), EXAMPLES.stat().st_mtime_ns).classify(text)
        except Exception:  # noqa: BLE001 - a missing model, index or file must never fail a question
            return None

    return classify
