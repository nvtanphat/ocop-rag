"""Query model loading and inference share a bounded CPU runtime, without real weights."""

import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from types import ModuleType, SimpleNamespace

import pytest

from ai_core.retrieval.ocop import search as module


@pytest.fixture
def runtime_probe(monkeypatch):
    events = []

    def reader(*args, backend="mmap", **kwargs):
        events.append(("reader", backend))
        return object()

    def constructor(model, **kwargs):
        events.append(("constructor", model))
        modeling.safe_open("synthetic.safetensors", framework="pt")
        return object()

    modeling = ModuleType("transformers.modeling_utils")
    modeling.safe_open = reader
    transformers = ModuleType("transformers")
    transformers.modeling_utils = modeling
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "transformers.modeling_utils", modeling)
    monkeypatch.setitem(sys.modules, "safetensors", SimpleNamespace(safe_open=reader))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda n: events.append(("threads", n))))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=constructor))
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    runtime = sys.modules.get("ai_core.retrieval.ocop.model_runtime")
    if runtime is not None:
        monkeypatch.setattr(runtime, "_CPU_THREADS", None)
    loader = module._load_reranker
    loader.cache_clear()
    module._RERANK_CACHE.clear()
    yield SimpleNamespace(events=events, modeling=modeling, reader=reader)
    loader.cache_clear()
    module._RERANK_CACHE.clear()


def test_reranker_configures_cpu_before_constructing_weights(runtime_probe):
    module._load_reranker("synthetic-reranker")
    assert runtime_probe.events[0] == ("threads", module.get_settings().retrieval.rerank_threads)


@pytest.mark.parametrize("fail", [False, True])
def test_windows_tensor_reader_uses_pread_and_restores_transformers_alias(runtime_probe, monkeypatch, fail):
    if fail:
        def constructor(*args, **kwargs):
            runtime_probe.modeling.safe_open("synthetic.safetensors", framework="pt")
            raise OSError("synthetic load failure")

        monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=constructor))
        with pytest.raises(OSError):
            module._load_reranker("synthetic-reranker")
    else:
        module._load_reranker("synthetic-reranker")
    assert ("reader", "pread") in runtime_probe.events
    assert runtime_probe.modeling.safe_open is runtime_probe.reader


def test_unsupported_tensor_reader_fails_before_constructing_weights(runtime_probe, monkeypatch):
    def old_reader(filename, framework, device=None):
        return object()

    monkeypatch.setitem(sys.modules, "safetensors", SimpleNamespace(safe_open=old_reader))
    with pytest.raises(RuntimeError, match="safetensors"):
        module._load_reranker("synthetic-reranker")
    assert not any(event[0] == "constructor" for event in runtime_probe.events)


@pytest.mark.parametrize("backend,system", [("mmap", "Windows"), ("auto", "Linux")])
def test_mmap_selection_keeps_the_original_reader(runtime_probe, monkeypatch, backend, system):
    monkeypatch.setattr(module.get_settings().retrieval, "tensor_reader_backend", backend)
    monkeypatch.setattr(platform, "system", lambda: system)
    module._load_reranker("synthetic-reranker")
    assert ("reader", "mmap") in runtime_probe.events
    assert runtime_probe.modeling.safe_open is runtime_probe.reader


def test_thread_configuration_change_requires_restart(runtime_probe, monkeypatch):
    module._load_reranker("synthetic-reranker")
    settings = module.get_settings().retrieval
    monkeypatch.setattr(settings, "rerank_threads", settings.rerank_threads + 1)
    with pytest.raises(RuntimeError, match="restart"):
        module._load_reranker("different-synthetic-reranker")
    assert sum(event[0] == "threads" for event in runtime_probe.events) == 1


def test_concurrent_first_requests_construct_one_reranker(runtime_probe, monkeypatch):
    ready = Barrier(2)
    calls = []

    def constructor(*args, **kwargs):
        calls.append(1)
        time.sleep(0.05)
        return object()

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=constructor))

    def load(_):
        ready.wait(timeout=2)
        return module._load_reranker("synthetic-shared-reranker")

    with ThreadPoolExecutor(max_workers=2) as pool:
        models = list(pool.map(load, range(2)))
    assert len(calls) == 1
    assert models[0] is models[1]


def dense_stubs(monkeypatch, events, encode):
    class Vector:
        def __len__(self):
            return 1

        def tolist(self):
            return [0.1]

    class Client:
        def __init__(self, **kwargs):
            pass

        def query_points(self, **kwargs):
            return SimpleNamespace(points=[])

    def embedding(*args):
        events.append(("embedding_constructor", None))
        return object()

    def encoding(*args):
        encode()
        return [Vector()]

    monkeypatch.setitem(sys.modules, "qdrant_client", SimpleNamespace(QdrantClient=Client, models=SimpleNamespace()))
    monkeypatch.setattr(module, "_load_embedding", embedding)
    monkeypatch.setattr(module, "_encode", encoding)
    return {"dense": {"enabled": True, "model_id": "synthetic-embedding", "dimension": 1,
                      "host": "unused", "port": 1, "collection": "unused"}}


def test_dense_configures_cpu_before_constructing_weights(runtime_probe, monkeypatch):
    manifest = dense_stubs(monkeypatch, runtime_probe.events, lambda: None)
    module._dense_hits("synthetic query", manifest, 1)
    assert runtime_probe.events[0] == ("threads", module.get_settings().retrieval.rerank_threads)


@pytest.mark.parametrize("mixed", [False, True])
def test_concurrent_inference_has_one_active_model_operation(runtime_probe, monkeypatch, mixed):
    ready = Barrier(2)
    mutex = Lock()
    active = 0
    peak = 0

    def operation():
        nonlocal active, peak
        with mutex:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with mutex:
            active -= 1

    class Model:
        tokenizer = None
        max_length = None

        def predict(self, pairs, **kwargs):
            operation()
            return [0.5] * len(pairs)

    model = Model()
    monkeypatch.setattr(module, "_load_reranker", lambda *args: model)
    manifest = dense_stubs(monkeypatch, runtime_probe.events, operation)

    def infer(index):
        ready.wait(timeout=2)
        if mixed and index == 1:
            return module._dense_hits("synthetic query", manifest, 1)
        return module._rerank(str(index), [{"chunk_id": str(index), "text": "synthetic passage"}],
                              "synthetic-reranker", pair_token_budget=64 + index * 64)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(infer, range(2)))
    assert peak == 1
    assert sum(event[0] == "threads" for event in runtime_probe.events) == 1


def test_reranker_cache_respects_effective_pair_budget(runtime_probe, monkeypatch):
    calls = []

    class Model:
        tokenizer = None
        max_length = None

        def predict(self, pairs, **kwargs):
            calls.append(self.max_length)
            return [float(self.max_length)] * len(pairs)

    model = Model()
    monkeypatch.setattr(module, "_load_reranker", lambda *args: model)
    scores = []
    for budget in (64, 128):
        result = module._rerank("same query", [{"chunk_id": "same", "text": "same passage"}],
                                "synthetic-reranker", pair_token_budget=budget)
        scores.append(result[0]["reranker_score"])
    assert scores == [64.0, 128.0]
    assert calls == [64, 128]


def test_cached_score_still_reports_pair_truncation(runtime_probe, monkeypatch):
    class Model:
        max_length = None

        def tokenizer(self, *args, **kwargs):
            return {"input_ids": list(range(200))}

        def predict(self, pairs, **kwargs):
            return [0.5] * len(pairs)

    monkeypatch.setattr(module, "_load_reranker", lambda *args: Model())
    for _ in range(2):
        result = module._rerank("same query", [{"chunk_id": "same", "text": "same long passage"}],
                                "synthetic-reranker", pair_token_budget=64)
        assert result[0].get("rerank_input_truncated") is True
