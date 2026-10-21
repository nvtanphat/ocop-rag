"""Compatibility import; implementation lives in ocop_ocr.legend_proposals."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.legend_proposals")
