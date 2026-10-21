from pathlib import Path
import json
import subprocess
import sys
import time
from ai_core.orchestration.ocop.llm import load_env_file


def run_sequential_check(project_root: Path, base_dir: Path, output_dir: Path, pages: list[int]):
    """Run sequential 1-worker OCR and compare against parallel dataset."""
    args = [
        sys.executable, "-m", "ocop_ocr", "run",
        "--root", str(project_root),
        "--dataset", str(output_dir),
        "--workers", "1",
        "--dpi", "300"
    ]
    for number in pages:
        args.extend(["--page", f"VN.OCOP.QD26.2026:{number}"])
    tick = time.monotonic()
    result = subprocess.run(args, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)

    def load(folder):
        return {
            (r["source_id"], r["pdf_page"]): r
            for file in folder.glob("*.pages.jsonl")
            for r in map(json.loads, file.read_text(encoding="utf-8").splitlines())
        }

    sequential = load(output_dir / "_raw")
    parallel = load(base_dir / "ocr-dataset-round2-71/_raw")
    rows = []
    for key, value in sequential.items():
        before = parallel.get(key)
        if not before:
            continue
        differences = [
            k for k in value.keys() | before.keys()
            if k != "_cache_integrity_sha256" and value.get(k) != before.get(k)
        ]
        blocks = lambda page: [(b["text"], b.get("bbox")) for b in page["blocks"]]
        rows.append({
            "source_id": key[0],
            "pdf_page": key[1],
            "different_fields": differences,
            "block_text_bbox_equal": blocks(value) == blocks(before)
        })
    report = {
        "workers": 1,
        "dpi": 300,
        "seconds": round(time.monotonic() - tick, 3),
        "pages": rows,
        "exact_except_cache_integrity": all(not r["different_fields"] for r in rows)
    }
    return report


if __name__ == "__main__":
    load_env_file()
    root = Path(__file__).resolve().parents[2]
    base = Path("D:/AgentAI/OCOP-RAG")
    out = base / "ocr-dataset-sequential-five"
    report = run_sequential_check(root, base, out, [1, 7, 18, 28, 29])
    (base / "pilot-evidence/sequential-five.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
