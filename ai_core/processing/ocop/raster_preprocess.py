"""Compatibility import; implementation lives in ocop_ocr.raster_preprocess."""
import importlib
import sys

sys.modules[__name__] = importlib.import_module("ocop_ocr.raster_preprocess")
