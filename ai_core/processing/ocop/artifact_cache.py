"""Version-aware immutable per-page JSON cache with atomic writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

PARSER_VERSION = "ocop-pdf-v7.0.0"


def build_cache_key(file_sha256: str, page: int, *, dpi: int, ocr_engine: str,
                    extract_ocr: bool, detect_tables: bool, model_version: str = "auto") -> str:
    payload={"source_sha256":file_sha256,"page":page,"dpi":dpi,"engine":ocr_engine,
             "ocr":extract_ocr,"tables":detect_tables,"version":PARSER_VERSION,"ocr_model":model_version}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def cache_path(cache_root: Path, source_id: str, key: str) -> Path:
    safe=hashlib.sha256(source_id.encode()).hexdigest()[:16]
    return cache_root/safe/f"{key}.json"


def write_json(path:Path, payload:dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f".{os.getpid()}.tmp")
    try:
        with temp.open("w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,sort_keys=True,indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_json(path:Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):
        return None
