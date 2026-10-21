"""Explicit Markdown review; PDF and raw OCR cache are never changed."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re

from ocop_contracts.dataset import SCHEMA_VERSION, dataset_file, digest_json
from ocop_contracts.layout import join_blocks_by_line
from ocop_contracts.registry import sha256_file
from .artifact_cache import write_json


def _jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _manifest(root: Path) -> dict:
    if (root / ".pending-import.json").exists():
        raise ValueError("OCR import interrupted; run import to recover")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported OCR dataset schema_version")
    return manifest


def _pages(root: Path, manifest: dict) -> list[tuple[dict, list[dict]]]:
    result = []
    for source in manifest["sources"]:
        file = dataset_file(root, source["artifact"])
        if sha256_file(file) != source["artifact_sha256"]:
            raise ValueError(f"dataset artifact digest mismatch: {file}")
        result.append((source, [json.loads(s) for s in file.read_text(encoding="utf-8").splitlines()]))
    return result


def _objects(page: dict):
    for index, block in enumerate(page.get("blocks", [])):
        yield f"block:{index}", block
    for table_index, table in enumerate(page.get("tables", [])):
        for cell_index, cell in enumerate(table.get("cells", [])):
            yield f"table:{table_index}:cell:{cell_index}", cell


def _publish_manifest(root: Path, manifest: dict, sources_pages) -> dict:
    manifest["da_duyet"] = sum(bool(page.get("reviewed")) for _, pages in sources_pages for page in pages)
    for source, _ in sources_pages:
        source["artifact_sha256"] = sha256_file(dataset_file(root, source["artifact"]))
    manifest["sources"] = [source for source, _ in sources_pages]
    corrections = root / "review/corrections.jsonl"
    manifest["corrections_sha256"] = (sha256_file(corrections) if corrections.is_file()
                                          else hashlib.sha256(b"").hexdigest())
    manifest["dataset_digest"] = digest_json({k: v for k, v in manifest.items() if k != "dataset_digest"})
    write_json(root / "manifest.json", manifest)
    return manifest


def create_dataset(input_dir: Path, root: Path) -> dict:
    """Publish raw parser output as a durable dataset. Never overwrite review work."""
    if (root / "manifest.json").exists():
        raise FileExistsError(f"dataset already exists: {root}; use a new dataset directory")
    original = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest = {"schema_version": SCHEMA_VERSION, "ocr_version": original["parser_version"],
                "complete": bool(original["complete"]), "sources": [], "da_duyet": 0,
                "input_snapshot_sha256": original.get("input_snapshot_sha256"),
                "counts": original.get("counts", {})}
    sources_pages = []
    for source in original["sources"]:
        sid = source["source_id"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", sid) or sid in {".", ".."}:
            raise ValueError(f"unsafe source_id: {sid}")
        pages = [json.loads(line) for line in dataset_file(input_dir, source["artifact"]).read_text(
            encoding="utf-8").splitlines()]
        for page in pages:
            page["ocr_hash"] = digest_json(page)
            page["reviewed"] = False
            for _, obj in _objects(page):
                obj["ocr_text"] = obj.get("text", "")
                obj["reviewed"] = False
        record = {"source_id": sid, "source_sha256": source["source_sha256"],
                  "page_count_expected": source["page_count_expected"],
                  "pages": [p["pdf_page"] for p in pages], "artifact": f"pages/{sid}.jsonl"}
        manifest["sources"].append(record)
        sources_pages.append((record, pages))
    # All input validation precedes publication.
    for source, pages in sources_pages:
        _jsonl(dataset_file(root, source["artifact"]), pages)
    return _publish_manifest(root, manifest, sources_pages)


def _encode(text) -> str:
    return html.escape(str(text), quote=False).replace("|", "&#124;").replace("\n", "&#10;").replace("\r", "&#13;")


def _markdown(page: dict) -> tuple[list[str], dict[int, str]]:
    """Stable skeleton with explicitly identified editable cells/lines."""
    warnings = page.get("ocr_attention", page.get("warnings", []))
    quality = page.get("page_quality", {})
    metadata = {"source_id": page["source_id"], "pdf_page": page["pdf_page"],
                "source_sha256": page["source_sha256"], "ocr_hash": page["ocr_hash"],
                "confidence": page.get("ocr_confidence_mean", quality.get("mean_block_ocr_confidence")), "warnings": warnings,
                "trang_thai": "da_duyet" if page.get("reviewed") else "chua_duyet"}
    lines = ["---", *[f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in metadata.items()],
             "---", "", f"![Trang PDF](../images/{page['source_id']}/p{page['pdf_page']:03d}.png)",
             "", "## Chữ", "", "| Khối | Chữ |", "| --- | --- |"]
    editable = {}
    for index, block in enumerate(page.get("blocks", [])):
        editable[len(lines)] = f"block:{index}"
        lines.append(f"| {index} | {_encode(block.get('text', ''))} |")
    for index, table in enumerate(page.get("tables", [])):
        lines.extend(["", f"## Bảng {index + 1}", ""])
        count = table["col_count"]
        lines.append("| Hàng | " + " | ".join(f"Cột {c + 1}" for c in range(count)) + " |")
        lines.append("| --- | " + " | ".join("---" for _ in range(count)) + " |")
        cells = {(c["row"], c["col"]): (i, c) for i, c in enumerate(table["cells"])}
        for row in range(table["row_count"]):
            labels = []
            locations = []
            for col in range(count):
                item = cells.get((row, col))
                if item is None:
                    labels.append("<!-- absent -->")
                    locations.append(None)
                else:
                    cell_index, cell = item
                    value = _encode(cell.get("text", ""))
                    if not value:
                        value = "<!-- blank -->"
                    labels.append(value)
                    locations.append(f"table:{index}:cell:{cell_index}")
            editable[len(lines)] = locations
            lines.append(f"| {row} | " + " | ".join(labels) + " |")
    return lines, editable


def export_markdown(root: Path, *, pdf_root: Path | None = None, registry: Path | None = None,
                    lock: Path | None = None) -> int:
    manifest = _manifest(root)
    sources_pages = _pages(root, manifest)
    source_paths = {}
    if pdf_root is not None:
        from ocop_contracts.pdf_loader import checked_sources
        sources, _ = checked_sources(pdf_root, registry, lock)
        source_paths = {s.source_id: pdf_root / s.path for s in sources}
    index = []
    for source, pages in sources_pages:
        for page in pages:
            relative = f"{source['source_id']}/p{page['pdf_page']:03d}.md"
            file = dataset_file(root / "review", relative)
            if file.exists():
                raise FileExistsError(f"review file exists; import edits before re-export: {file}")
            file.parent.mkdir(parents=True, exist_ok=True)
            lines, _ = _markdown(page)
            file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            if source_paths:
                import fitz
                pdf = source_paths[source["source_id"]]
                if sha256_file(pdf) != page["source_sha256"]:
                    raise ValueError(f"PDF SHA mismatch: {pdf}")
                pic = root / "review/images" / source["source_id"] / f"p{page['pdf_page']:03d}.png"
                pic.parent.mkdir(parents=True, exist_ok=True)
                with fitz.open(pdf) as document:
                    document[page["pdf_page"] - 1].get_pixmap(dpi=150, alpha=False).save(pic)
            attention = bool(page.get("ocr_attention") or page.get("warnings"))
            index.append((not attention, relative, page.get("reviewed", False)))
    index.sort()
    target = root / "review/INDEX.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Duyệt OCR\n\n" + "\n".join(
        f"- [{'x' if reviewed else ' '}] [{name}]({name})" for _, name, reviewed in index) + "\n", encoding="utf-8")
    return len(index)


def import_markdown(root: Path) -> dict:
    recover_import(root)
    manifest = _manifest(root)
    sources_pages = _pages(root, manifest)
    corrections = []
    for _, pages in sources_pages:
        for page in pages:
            file = dataset_file(root, f"review/{page['source_id']}/p{page['pdf_page']:03d}.md")
            expected, editable = _markdown(page)
            actual = file.read_text(encoding="utf-8").splitlines()
            if len(actual) != len(expected):
                raise ValueError(f"{file}:{min(len(actual), len(expected)) + 1}: changed block/row count")
            modified = deepcopy(page)
            objects = dict(_objects(modified))
            for number, (old, new) in enumerate(zip(expected, actual)):
                if old == new:
                    continue
                error = f"{file}:{number + 1}"
                if old.startswith("trang_thai:"):
                    try:
                        value = new.partition(":")[2].strip()
                        status = json.loads(value) if value.startswith('"') else value
                    except ValueError as exc:
                        raise ValueError(f"{error}: invalid trang_thai") from exc
                    if status not in {"da_duyet", "chua_duyet"}:
                        raise ValueError(f"{error}: invalid trang_thai")
                    modified["reviewed"] = status == "da_duyet"
                    continue
                if number not in editable:
                    label = "ocr_hash conflict" if old.startswith("ocr_hash:") else "changed immutable structure"
                    raise ValueError(f"{error}: {label}")
                parts = [p.strip() for p in new.split("|")]
                old_parts = [p.strip() for p in old.split("|")]
                if len(parts) != len(old_parts) or parts[:2] != old_parts[:2] or parts[-1] != "":
                    raise ValueError(f"{error}: changed row/column structure")
                locations = editable[number]
                if isinstance(locations, str):
                    locations = [locations]
                for column, location in enumerate(locations, 2):
                    if location is None:
                        if parts[column] != old_parts[column]:
                            raise ValueError(f"{error}: cannot add missing cell")
                        continue
                    text = parts[column]
                    objects[location]["text"] = "" if text == "<!-- blank -->" else html.unescape(text)
            for _, obj in _objects(modified):
                obj["reviewed"] = modified["reviewed"]
            if modified == page:
                continue
            modified["extracted_text"] = join_blocks_by_line(modified.get("blocks", []))
            corrections.append({"timestamp": datetime.now(timezone.utc).isoformat(),
                                "source_id": page["source_id"], "pdf_page": page["pdf_page"],
                                "source_sha256": page["source_sha256"], "ocr_hash": page["ocr_hash"],
                                "reviewed": modified["reviewed"],
                                "changes": [{"location": location, "old_text": old.get("text", ""),
                                             "text": objects[location].get("text", "")}
                                            for location, old in _objects(page)
                                            if old.get("text", "") != objects[location].get("text", "")]})
            page.clear()
            page.update(modified)
    # No filesystem mutations until EVERY Markdown file has validated.
    if not corrections:
        return manifest
    ledger = root / "review/corrections.jsonl"
    before = ledger.read_bytes() if ledger.exists() else b""
    # Durable intent precedes all writes. Recovery appends only the missing suffix
    # and re-materializes pages, preserving an append-only corrections ledger.
    write_json(root / ".pending-import.json", {
        "ledger_before_size": len(before), "ledger_before_sha256": hashlib.sha256(before).hexdigest(),
        "ledger_append": "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in corrections),
        "manifest": manifest, "sources_pages": sources_pages,
    })
    return recover_import(root)


def recover_import(root: Path) -> dict | None:
    pending = root / ".pending-import.json"
    if not pending.exists():
        return None
    intent = json.loads(pending.read_text(encoding="utf-8"))
    ledger = root / "review/corrections.jsonl"
    current = ledger.read_bytes() if ledger.exists() else b""
    size = intent["ledger_before_size"]
    append = intent["ledger_append"].encode("utf-8")
    if (hashlib.sha256(current[:size]).hexdigest() != intent["ledger_before_sha256"]
            or not append.startswith(current[size:])):
        raise ValueError("interrupted import ledger conflict; refusing to overwrite history")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("ab") as stream:
        stream.write(append[len(current) - size:])
        stream.flush()
        os.fsync(stream.fileno())
    for source, pages in intent["sources_pages"]:
        _jsonl(dataset_file(root, source["artifact"]), pages)
    manifest = _publish_manifest(root, intent["manifest"], intent["sources_pages"])
    pending.unlink()
    return manifest
