"""Independent OCR command line; never invokes RAG extraction."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

from ocop_contracts.dataset import DEFAULT_DATASET, read_dataset
from ocop_contracts.locking import process_lock
from ocop_contracts.pdf_loader import checked_sources
from .review import create_dataset, export_markdown, import_markdown, recover_import


def _write_run_state(dataset, state):
    staging = dataset / 'run-state.json.tmp'
    with staging.open('w', encoding='utf-8') as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    staging.replace(dataset / 'run-state.json')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="OCOP OCR -> dataset -> Markdown review")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "export", "import", "status"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
        command.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
        if name == "run":
            command.add_argument("--cache", type=Path)
            command.add_argument("--dpi", type=int, default=300)
            command.add_argument("--page", action="append", help="SOURCE_ID:PAGE (pilot only)")
            command.add_argument("--without-ocr", action="store_true")
            command.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    root, dataset = args.root.resolve(), args.dataset.resolve()
    registry, lock = root / "configs/ocop_sources.json", root / "configs/ocop_sources.lock.json"
    with process_lock(dataset / ".ocr.lock"):
        if args.command == "run":
            from .pdf_pipeline import run_pipeline, _parse_page
            if (dataset / "manifest.json").exists():
                parser.error("dataset already published; choose a new --dataset to preserve review history")
            raw = dataset / "_raw"
            state = {'status': 'running', 'pid': os.getpid(),
                     'started_at': datetime.now(timezone.utc).isoformat(),
                     'requested_pages': args.page, 'workers': args.workers, 'dpi': args.dpi}
            _write_run_state(dataset, state)
            try:
                raw_manifest = run_pipeline(root, registry=registry, lock=lock, output=raw,
                         cache_dir=args.cache or dataset / "_cache", dpi=args.dpi,
                         ocr=not args.without_ocr,
                         workers=args.workers,
                         pages={_parse_page(p) for p in args.page} if args.page else None,
                         apply_postcorrection=False)
            except BaseException as exc:
                _write_run_state(dataset, {**state, 'status': 'failed',
                                         'error': f'{type(exc).__name__}: {exc}'})
                raise
            if raw_manifest.get("errors"):
                _write_run_state(dataset, {**state, 'status': 'failed',
                                         'errors': raw_manifest['errors']})
                print(json.dumps({"complete": False, "errors": raw_manifest["errors"],
                                  "raw_manifest": str(raw / "manifest.json"),
                                  "action": "rerun the same command to retry failed pages using the page cache"},
                                 ensure_ascii=False, indent=2))
                raise SystemExit(1)
            result = create_dataset(raw, dataset)
            _write_run_state(dataset, {**state, 'status': 'published'})
        elif args.command == "export":
            result = {"exported_pages": export_markdown(dataset, pdf_root=root, registry=registry, lock=lock)}
        elif args.command == "import":
            recover_import(dataset)
            _, locked = checked_sources(root, registry, lock)
            read_dataset(dataset, locked, require_complete=False)
            result = import_markdown(dataset)
        else:
            if not (dataset / 'manifest.json').exists():
                state_file = dataset / 'run-state.json'
                state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
                # Holding .ocr.lock proves no OCR publisher is currently running.
                if state.get('status') == 'running':
                    state['status'] = 'interrupted'
                raw_file = dataset / '_raw/manifest.json'
                raw = json.loads(raw_file.read_text(encoding='utf-8')) if raw_file.exists() else {}
                print(json.dumps({'complete': False, 'run': state,
                                  'errors': raw.get('errors', []),
                                  'action': 'rerun the same command to resume using the page cache'},
                                 ensure_ascii=False, indent=2))
                return
            _, locked = checked_sources(root, registry, lock)
            manifest, pages = read_dataset(dataset, locked, require_complete=False)
            result = {"complete": manifest["complete"], "pages": len(pages),
                      "da_duyet": manifest["da_duyet"], "dataset_digest": manifest["dataset_digest"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
