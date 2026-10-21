"""Compatibility import; implementation lives in ocop_ocr.native_extractor."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.native_extractor")
