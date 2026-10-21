"""Compatibility import; implementation lives in ocop_contracts.layout."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_contracts.layout")
