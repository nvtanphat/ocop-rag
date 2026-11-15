"""Limit peak CPU inference allocations without resizing the source image."""

import os
from pathlib import Path
import tempfile

from ocop_contracts.locking import process_lock


def inference_slot(path: Path | None = None):
    # One machine-wide slot: CRAFT/layout allocations must not overlap across
    # page workers (or independent OCR runs) on memory-constrained machines.
    path = path or Path(
        os.getenv("OCOP_OCR_PEAK_LOCK", str(Path(tempfile.gettempdir()) / "ocop-ocr-peak.lock"))
    )
    return process_lock(path, wait_timeout=1800)
