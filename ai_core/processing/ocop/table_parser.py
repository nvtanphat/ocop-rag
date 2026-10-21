"""Compatibility import; implementation lives in ocop_ocr.table_parser."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.table_parser")
