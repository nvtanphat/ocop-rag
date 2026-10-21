"""Compatibility import; implementation lives in ocop_ocr.layout_regions."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.layout_regions")
