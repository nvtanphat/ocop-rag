"""Compatibility import; implementation lives in ocop_ocr.easy_viet_ocr."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.easy_viet_ocr")
