"""Compatibility import; implementation lives in ocop_contracts.ids."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_contracts.ids")
