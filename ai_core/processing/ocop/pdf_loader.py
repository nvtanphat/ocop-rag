"""Compatibility import; implementation lives in ocop_contracts.pdf_loader."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_contracts.pdf_loader")
