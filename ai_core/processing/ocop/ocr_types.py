"""Compatibility import; implementation lives in ocop_ocr.ocr_types."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.ocr_types")
