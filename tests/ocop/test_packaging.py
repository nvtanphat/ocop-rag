"""Source archive integrity and Unicode filename regression tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from tools.package_ocop import package


def test_unicode_source_path_and_locked_bytes_survive_zip(tmp_path):
    root = tmp_path / "OCOP-RAG"
    (root / "configs").mkdir(parents=True)
    path = Path("data/raw/ocop/sectoral/111-2021-NĐ-CP.pdf")
    pdf = root / path
    pdf.parent.mkdir(parents=True)
    data = b"%PDF-1.4\noriginal signed pdf bytes\n"
    pdf.write_bytes(data)
    entry = {"source_id": "VN.ND.111.2021", "path": path.as_posix(), "source_kind": "labeling_amendment"}
    (root / "configs/ocop_sources.json").write_text(
        json.dumps({"schema_version": 1, "sources": [entry]}), encoding="utf-8"
    )
    from ocop_contracts.registry import snapshot, load_registry

    lock = snapshot(root, load_registry(root / "configs/ocop_sources.json"))
    (root / "configs/ocop_sources.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    out = tmp_path / "package.zip"
    result = package(root, out)
    assert result["source_pdfs_verified"] == 1
    with ZipFile(out) as z:
        member = "OCOP-RAG/" + path.as_posix()
        assert member in z.namelist()
        assert z.read(member) == data
        assert z.getinfo(member).flag_bits & 0x800  # UTF-8 filename flag
        assert hashlib.sha256(z.read(member)).hexdigest() == lock["sources"][0]["sha256"]


def test_current_release_excludes_all_derived_and_runtime_data(tmp_path):
    root = tmp_path / "OCOP-GraphRAG"
    (root / "configs").mkdir(parents=True)
    pdf = root / "data/raw/ocop/central_current/26-ttg-2026.signed.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\nlocked\n")
    from ocop_contracts.registry import snapshot, load_registry

    entry = {
        "source_id": "VN.OCOP.QD26.2026",
        "path": pdf.relative_to(root).as_posix(),
        "source_kind": "ocop_framework",
    }
    (root / "configs/ocop_sources.json").write_text(
        json.dumps({"schema_version": 1, "sources": [entry]}), encoding="utf-8"
    )
    lock = snapshot(root, load_registry(root / "configs/ocop_sources.json"))
    (root / "configs/ocop_sources.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    for rel in (
        "data/processed/ocop/pages/manifest.json",
        "data/runtime/private/session.sqlite",
        "data/private/ocop/dossiers/customer.json",
        ".env",
        ".env.production",
        "frontend/.env.local",
        "secrets/service.key",
        "reports/evaluation/out.json",
        "data/review/ocop/needs_review.jsonl",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
    output = tmp_path / "clean.zip"
    package(root, output)
    with ZipFile(output) as z:
        names = z.namelist()
        assert any("/data/raw/ocop/" in n for n in names)
        assert all("/data/processed/" not in n for n in names)
        assert all("/data/runtime/" not in n for n in names)
        assert all("/data/review/" not in n for n in names)
        assert all("/data/private/" not in n for n in names)
        assert all("/reports/" not in n for n in names)
        assert all(not n.endswith((".env", ".env.production", ".env.local", ".key")) for n in names)
