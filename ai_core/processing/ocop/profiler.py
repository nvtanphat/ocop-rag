"""Compatibility import; implementation lives in ocop_ocr.profiler."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.profiler")
