"""Compatibility import; implementation lives in ocop_contracts.registry."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_contracts.registry")
