"""Compatibility import; implementation lives in ocop_ocr.pdf_quality."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.pdf_quality")
