"""Compatibility import; implementation lives in ocop_ocr.artifact_cache."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.artifact_cache")
