"""Bound query model memory and initialize CPU execution before loading weights."""

from __future__ import annotations

import inspect
import os
import platform
from contextlib import contextmanager
from functools import wraps
from threading import RLock

from ai_core.retrieval.ocop.settings import get_settings

_LOCK = RLock()
_CPU_THREADS: int | None = None


def _initialize_cpu() -> None:
    global _CPU_THREADS
    threads = get_settings().retrieval.rerank_threads
    if _CPU_THREADS is not None:
        if threads != _CPU_THREADS:
            raise RuntimeError("Query CPU thread configuration changed; restart the process")
        return
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["MKL_NUM_THREADS"] = str(threads)
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("torch is required for query embedding and reranking") from exc
    torch.set_num_threads(threads)
    _CPU_THREADS = threads


@contextmanager
def inference():
    """One CPU model operation at a time, including first-load cache misses."""
    with _LOCK:
        _initialize_cpu()
        yield


@contextmanager
def tensor_reader():
    """Scope the Transformers tensor reader; restore its alias even on load failure.

    Transformers 4.x imports safe_open directly. Safetensors' pread backend
    avoids the Windows mapped-storage fault without changing tensor values.
    The shared lock prevents another query load from observing a partial patch.
    """
    with _LOCK:
        backend = get_settings().retrieval.tensor_reader_backend
        if backend == "auto":
            backend = "pread" if platform.system() == "Windows" else "mmap"
        if backend == "mmap":
            yield
            return
        import safetensors

        if "backend" not in inspect.signature(safetensors.safe_open).parameters:
            raise RuntimeError("pread tensor loading requires safetensors>=0.8; install retrieval dependencies")
        from transformers import modeling_utils

        previous = modeling_utils.safe_open

        def open_tensor(*args, **kwargs):
            kwargs["backend"] = backend
            return previous(*args, **kwargs)

        modeling_utils.safe_open = open_tensor
        try:
            yield
        finally:
            modeling_utils.safe_open = previous


def model_loader(factory):
    """Serialize outside the cache so concurrent misses construct one model."""
    @wraps(factory)
    def load(*args, **kwargs):
        with inference(), tensor_reader():
            return factory(*args, **kwargs)

    for name in ("cache_clear", "cache_info", "cache_parameters"):
        if hasattr(factory, name):
            setattr(load, name, getattr(factory, name))
    return load
