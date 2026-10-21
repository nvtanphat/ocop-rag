"""Package OCOP GraphRAG with UTF-8 filenames and source-lock verification.

Never rename source PDFs to ASCII aliases: the approved source registry is the
canonical relative path contract.  A ZIP is accepted only if its member names
AND stored source bytes match the registry+lock.  The command performs no OCR,
no inference and no data modifications to the source tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocop_contracts.registry import compare_lock, load_registry, snapshot
SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "_smoke", "_scan_smoke", "reports", "dist", ".tox", "coverage", "htmlcov", "archive"}
SKIP_FILES = {".DS_Store", ".env", ".npmrc", ".pypirc"}
SKIP_EXTENSIONS = {".pem", ".key", ".p12", ".sqlite", ".sqlite3", ".db"}
# Derived indexes, OCR caches and ephemeral user runtime state are never source releases.
SKIP_PREFIXES = (("data", "processed"), ("data", "runtime"), ("data", "review"), ("data", "private"),
                 ("outputs",), ("models",), (".cache",), ("tmp",), ("temp",))


def package(root: Path, output: Path) -> dict:
    root = root.resolve()
    output = output.resolve()
    sources = load_registry(root / "configs/ocop_sources.json")
    locked = json.loads((root / "configs/ocop_sources.lock.json").read_text(encoding="utf-8"))
    compare_lock(snapshot(root, sources), locked)
    members: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if (any(part in SKIP_DIRS for part in rel.parts) or path.name in SKIP_FILES
                or (path.name.startswith('.env.') and path.name != '.env.example')
                or path.suffix.casefold() in SKIP_EXTENSIONS
                or any(rel.parts[:len(prefix)] == prefix for prefix in SKIP_PREFIXES)):
            continue
        if path.resolve() == output:
            continue
        # Python zipfile encodes non-ASCII names using UTF-8, unlike ad-hoc
        # conversions using a platform-default single-byte code page.
        name = (Path(root.name) / rel).as_posix()
        members.append((name, path))
    members.sort(key=lambda x: x[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for name, path in members:
            archive.write(path, arcname=name)
    checks = {s.path: s.source_id for s in sources}
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("ZIP contains duplicate members")
        expected_names = {(Path(root.name) / x).as_posix() for x in checks}
        if not expected_names.issubset(names):
            missing = sorted(expected_names.difference(names))
            raise RuntimeError(f"ZIP lost approved PDF Unicode filenames: {missing}")
        digest_by_id = {v["source_id"]: v["sha256"] for v in locked["sources"]}
        for rel, source_id in checks.items():
            h = hashlib.sha256()
            with archive.open((Path(root.name) / rel).as_posix()) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            if h.hexdigest() != digest_by_id[source_id]:
                raise RuntimeError(f"ZIP source corruption: {source_id}")
    return {"archive": str(output), "members": len(members), "source_pdfs_verified": len(checks), "source_lock": locked["aggregate_sha256"]}


def main() -> None:
    p = argparse.ArgumentParser(description="Package OCOP GraphRAG safely with Unicode PDF source verification")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(package(args.root, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
