"""PDF production-oriented PDF pages → PageArtifact JSONL (no DB writes).

Resumable page cache, immutable locked input, per-page failure quarantine.
LLMs cannot invent scores or verify OCR at this stage.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import logging
import math
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import multiprocessing
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

from ocop_contracts.models import PageArtifact, ReviewStatus
from ocop_ocr.artifact_cache import PARSER_VERSION, build_cache_key, cache_path, load_json, write_json
from ocop_contracts.pdf_loader import checked_sources
from ocop_contracts.registry import sha256_file
from ocop_ocr.native_extractor import extract_native
from ocop_contracts.layout import join_blocks_by_line, layout_page
from ocop_ocr.table_parser import native_tables
from ocop_ocr.easy_viet_ocr import ENGINE, run_easy_viet_ocr
from ocop_ocr.pdf_quality import score_page_quality, refresh_attention
from ocop_ocr.raster_preprocess import prepare_raster, restore_geometry
from ocop_ocr.profiler import profile_pdf
from ocop_contracts.ids import code_fingerprint
from ocop_ocr.ocr_postcorrect import postcorrect_artifact
from ocop_ocr.table_continuity import possible_continuations

LOG = logging.getLogger(__name__)
PROFILE_VERSION = code_fingerprint("profile", [Path(__file__).resolve().parent / "profiler.py"])
ROOT = Path(__file__).resolve().parents[2]


def _render(page, dpi: int):
    from PIL import Image

    pix = page.get_pixmap(
        matrix=__import__("fitz").Matrix(dpi / 72, dpi / 72), alpha=False, colorspace=__import__("fitz").csRGB
    )
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _validate_boxes(blocks, tables, width, height):
    """Clamp small PDF producer text-bbox overflow; preserve unmodified coordinates.

    A native PDF text-line bbox can extend slightly past CropBox/MediaBox even
    while the text content is legible. Out-of-page anchors are unusable for UI;
    keep bbox_original and warning rather than quarantining the page.
    """
    clipped = 0
    for obj in [*blocks, *tables, *(c for t in tables for c in t["cells"])]:
        box = obj["bbox"]
        if box is None:
            continue
        try:
            x0, y0, x1, y1 = [float(v) for v in box]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_source_bbox: {box}") from exc
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1, width, height)):
            raise ValueError(f"invalid_source_bbox: {box} nonfinite")
        if x0 > x1 or y0 > y1 or x1 < 0 or y1 < 0 or x0 > width or y0 > height:
            raise ValueError(f"invalid_source_bbox: {box} width={width} height={height}")
        normalized = [
            round(max(0, min(width, x0)), 2),
            round(max(0, min(height, y0)), 2),
            round(max(0, min(width, x1)), 2),
            round(max(0, min(height, y1)), 2),
        ]
        if any(abs(a - b) > 0.01 for a, b in zip(box, normalized)):
            obj["bbox_original"] = box
            obj["bbox"] = normalized
            clipped += 1
    return clipped


def extract_page(
    page,
    profile: dict,
    *,
    source_id: str,
    dpi: int = 300,
    enable_ocr: bool = True,
    enable_tables: bool = True,
    trace: dict | None = None,
) -> dict:
    native = extract_native(page)
    use_ocr = enable_ocr and bool(profile["needs_ocr_review"])
    # Do not count signing metadata as source text on scanned pages.
    if profile["page_class"] == "ocr_candidate":
        native = [b for b in native if not profile["largest_image_area_ratio"] >= 0.7]
    blocks = native
    ocr_words = []
    ocr_noise_candidates = []
    warnings = []
    engine = "native"
    ocr_tables = []
    prepared = None
    working_page = page
    pic = None
    if use_ocr or trace is not None:
        pic = _render(page, dpi)
        if trace is not None:
            trace["source_render"] = pic.copy()
            trace["ocr_executed"] = bool(use_ocr)
    if use_ocr:
        from types import SimpleNamespace

        prepared = prepare_raster(pic)
        pic = prepared.image
        if trace is not None:
            trace["preprocessed_render"] = pic.copy()
            trace["preprocessing_metadata"] = prepared.metadata()
        working_page = SimpleNamespace(
            rect=SimpleNamespace(
                width=page.rect.width * pic.width / prepared.source_size[0],
                height=page.rect.height * pic.height / prepared.source_size[1],
            )
        )
        response, ocr_tables = run_easy_viet_ocr(pic, working_page, detect_tables=enable_tables, trace=trace)
        blocks = response.blocks
        ocr_words = response.word_blocks or []
        ocr_noise_candidates = response.noise_candidates or []
        engine = ENGINE
        warnings += response.warnings
        if not blocks:
            warnings.append("empty_ocr_result")
    elif profile["needs_ocr_review"]:
        warnings.append("ocr_required_but_not_executed")
    if trace is not None:
        trace["tables_before_geometry_restoration"] = deepcopy(ocr_tables)
    tables = []
    if enable_tables:
        if use_ocr:
            tables = ocr_tables
        elif not profile["needs_ocr_review"]:
            tables = native_tables(page)
        if not tables and (profile["page_class"] in ("ocr_candidate", "mixed_or_native_with_images")):
            warnings.append("table_detection_unverified_or_empty")
    if prepared is not None:
        restore_geometry(prepared, blocks + ocr_words, tables, page.rect.width, page.rect.height)
    if trace is not None:
        trace["blocks_after_geometry_restoration"] = deepcopy(blocks)
        trace["tables_after_geometry_restoration"] = deepcopy(tables)
    blocks, layout_warnings = layout_page(blocks, page.rect.width, page.rect.height)
    if trace is not None:
        trace["blocks_after_reading_order"] = deepcopy(blocks)
    warnings += layout_warnings
    if any(
        "merged_extent_unknown" in cell and cell["merged_extent_unknown"]
        for t in tables
        for cell in t["cells"]
    ):
        warnings.append("possible_merged_table_cells")
    clipped = _validate_boxes(blocks + ocr_words, tables, page.rect.width, page.rect.height)
    if clipped:
        warnings.append(f"pdf_bbox_clipped:{clipped}")
    text = join_blocks_by_line(blocks)
    if use_ocr and not text:
        status = ReviewStatus.NEEDS_REVIEW
    elif profile["needs_ocr_review"] and not use_ocr:
        status = ReviewStatus.NEEDS_REVIEW
    elif use_ocr or tables or warnings:
        status = ReviewStatus.NEEDS_REVIEW
    else:
        status = ReviewStatus.MACHINE_EXTRACTED
    confidences = [b["confidence"] for b in blocks if b["confidence"] is not None]
    artifact = PageArtifact(
        source_id=source_id,
        pdf_page=profile["pdf_page"],
        width_pt=profile["width_pt"],
        height_pt=profile["height_pt"],
        extracted_text=text,
        blocks=blocks,
        extraction_method=engine,
        review_status=status,
    )
    payload = artifact.model_dump(mode="json")
    quality = score_page_quality(profile, blocks, tables, ocr_words)
    payload.update(
        {
            "profile": profile,
            "tables": tables,
            "warnings": sorted(set(warnings)),
            "preprocessing": prepared.metadata() if prepared is not None else None,
            "page_quality": quality,
            "ocr_engine": engine if use_ocr else None,
            "ocr_words": ocr_words,
            "ocr_noise_candidates": ocr_noise_candidates,
            "ocr_confidence_mean": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "needs_human_verification": bool(use_ocr or tables or warnings),
        }
    )
    refresh_attention(payload)
    if trace is not None:
        trace["page_artifact"] = deepcopy(payload)
    return payload


def _cache_hash(artifact: dict) -> str:
    """Detect accidental/tampered page-cache contents (not a cryptographic signature)."""
    body = {k: v for k, v in artifact.items() if k != "_cache_integrity_sha256"}
    packed = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _valid_cached_page(
    artifact: dict, source_id: str, profile: dict, source_sha256: str | None = None
) -> bool:
    if not isinstance(artifact, dict) or artifact.get("quarantined"):
        return False
    digest = artifact.get("_cache_integrity_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return False
    try:
        if digest != _cache_hash(artifact):
            return False
        PageArtifact.model_validate({k: artifact[k] for k in PageArtifact.model_fields if k in artifact})
        if artifact.get("source_id") != source_id or artifact.get("pdf_page") != profile["pdf_page"]:
            return False
        if source_sha256 is not None and artifact.get("source_sha256") != source_sha256:
            return False
        if (
            abs(artifact["width_pt"] - profile["width_pt"]) > 0.02
            or abs(artifact["height_pt"] - profile["height_pt"]) > 0.02
        ):
            return False
        # Require the exact page classification that determined whether OCR was run.
        if artifact.get("profile") != profile:
            return False
        if not isinstance(artifact.get("tables"), list) or not isinstance(artifact.get("blocks"), list):
            return False
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    return True


def _page_job(job: tuple, *, before_ocr=None) -> dict:
    """Independent process, no shared PyMuPDF objects (PyMuPDF is not thread safe)."""
    (filename, source_id, profile, cache_location, force, dpi, ocr, tables, *digests) = job
    digest = digests[0] if digests else sha256_file(Path(filename))
    cachefile = Path(cache_location)
    art = None if force else load_json(cachefile)
    if art is not None and not _valid_cached_page(art, source_id, profile, digest):
        art = None
    if art is not None:
        return art
    if ocr and profile.get("needs_ocr_review") and before_ocr is not None:
        before_ocr()
    import fitz

    try:
        with fitz.open(filename) as d:
            art = extract_page(
                d.load_page(profile["pdf_page"] - 1),
                profile,
                source_id=source_id,
                dpi=dpi,
                enable_ocr=ocr,
                enable_tables=tables,
            )
    except Exception as exc:
        LOG.exception("page failed source=%s page=%s", source_id, profile["pdf_page"])
        art = PageArtifact(
            source_id=source_id,
            pdf_page=profile["pdf_page"],
            width_pt=profile["width_pt"],
            height_pt=profile["height_pt"],
            review_status=ReviewStatus.NEEDS_REVIEW,
        ).model_dump(mode="json")
        art.update(
            {
                "profile": profile,
                "tables": [],
                "ocr_engine": None,
                "warnings": [f"quarantined:{type(exc).__name__}:{str(exc)[:220]}"],
                "needs_human_verification": True,
                "quarantined": True,
            }
        )
    art["source_sha256"] = digest
    if not art.get("quarantined"):
        from .legend_proposals import annotate_page_images

        annotate_page_images(filename, art, digests[1] if len(digests) > 1 else "ocop_framework")
        art["_cache_integrity_sha256"] = _cache_hash(art)
        write_json(cachefile, art)
    return art


def _record_page(fh, art, counts):
    refresh_attention(art)
    status = "quarantined" if art.get("quarantined") else art["review_status"]
    counts[status] += 1
    counts["ocr_executed"] += int(art.get("ocr_engine") is not None)
    counts["tables_detected"] += len(art.get("tables", []))
    quality = art.get("page_quality") or {}
    counts["table_cells_detected"] += quality.get("table_cells", 0)
    counts["table_cells_with_text"] += quality.get("table_cells_with_text", 0)
    counts["table_cells_with_bbox"] += quality.get("table_cells_with_bbox", 0)
    counts["possible_score_cells_without_text"] += quality.get("potential_score_cells_blank", 0)
    counts["pages"] += 1
    if art.get("warnings"):
        counts["pages_with_warnings"] += 1
    fh.write(json.dumps(art, ensure_ascii=False) + "\n")


def _source_profiles(filepath: Path, source_id: str, digest: str, cache_dir: Path) -> list[dict]:
    # Source-locked profile cache: repeated full ingestion must not scan
    # every PDF page a second time just to learn native/image page type.
    profile_file = cache_dir / "_profiles" / f"{digest}.profile.json"
    profile_cache = load_json(profile_file)
    if (
        isinstance(profile_cache, dict)
        and profile_cache.get("sha256") == digest
        and profile_cache.get("source_id") == source_id
        and profile_cache.get("profile_version") == PROFILE_VERSION
        and isinstance(profile_cache.get("pages"), list)
        and len(profile_cache["pages"]) > 0
        and profile_cache.get("pages_sha256")
        == hashlib.sha256(
            json.dumps(
                profile_cache["pages"],
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        and all(x.get("pdf_page") == i + 1 for i, x in enumerate(profile_cache["pages"]))
    ):
        profiles = profile_cache["pages"]
    else:
        profiles = profile_pdf(filepath, source_id)
        write_json(
            profile_file,
            {
                "sha256": digest,
                "source_id": source_id,
                "profile_version": PROFILE_VERSION,
                "pages": profiles,
                "pages_sha256": hashlib.sha256(
                    json.dumps(
                        profiles, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ).encode("utf-8")
                ).hexdigest(),
            },
        )
    return profiles


def _postcorrection_model(root: Path, sources, locked: dict, cache_dir: Path):
    """Diacritic model from every locked source's native-text pages; OCR pages never train it."""
    import fitz
    from ocop_ocr.ocr_postcorrect import DiacriticModel

    lines = []
    for source in sources:
        filepath = (root / source.path).resolve()
        digest = next(item["sha256"] for item in locked["sources"] if item["source_id"] == source.source_id)
        native = [
            p["pdf_page"]
            for p in _source_profiles(filepath, source.source_id, digest, cache_dir)
            if p["page_class"] == "native_text"
        ]
        if native:
            with fitz.open(filepath) as document:
                for number in native:
                    lines.extend(document.load_page(number - 1).get_text().splitlines())
    return DiacriticModel.from_lines(lines)


_WORKER_WARMED = False


def _worker_init(ocr: bool):
    if ocr:
        import torch

        torch.set_num_threads(2)


def _worker_page(job, *, warmup_job=None):
    def warmup():
        global _WORKER_WARMED
        if _WORKER_WARMED:
            return
        if warmup_job is None:
            raise RuntimeError("missing canonical OCR warmup page")
        filename, source_id, profile, dpi, tables = warmup_job
        import fitz

        with fitz.open(filename) as document:
            extract_page(
                document[profile["pdf_page"] - 1],
                profile,
                source_id=source_id,
                dpi=dpi,
                enable_ocr=True,
                enable_tables=tables,
            )
        _WORKER_WARMED = True

    return _page_job(job, before_ocr=warmup)


def run_pipeline(
    root: Path, *, registry: Path, lock: Path, output: Path, cache_dir: Path, workers: int = 1, **options
) -> dict:
    """Legacy Python calls default to serial; independent CLI defaults to three."""
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    if workers == 1:
        _worker_init(options.get("ocr", True))
        return _run_pipeline(
            root, registry=registry, lock=lock, output=output, cache_dir=cache_dir, **options
        )
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_worker_init,
        initargs=(options.get("ocr", True),),
    ) as executor:
        return _run_pipeline(
            root,
            registry=registry,
            lock=lock,
            output=output,
            cache_dir=cache_dir,
            executor=executor,
            **options,
        )


def _run_pipeline(
    root: Path,
    *,
    registry: Path,
    lock: Path,
    output: Path,
    cache_dir: Path,
    dpi: int = 300,
    ocr: bool = True,
    tables: bool = True,
    max_pages: int | None = None,
    source_filter: str | None = None,
    pages: set[tuple[str, int]] | None = None,
    force: bool = False,
    apply_postcorrection: bool = True,
    executor=None,
) -> dict:
    if not 100 <= dpi <= 450:
        raise ValueError("dpi must be within 100-450")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be positive")
    import fitz

    # Bound native inference thread pools on small machines.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    root = root.resolve()
    sources, locked = checked_sources(root, registry, lock)
    locked_sources = list(sources)
    cache_dir.mkdir(parents=True, exist_ok=True)
    selected_pages = None
    if pages is not None:
        selected_pages = set()
        for item in pages:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0].strip()
                or not isinstance(item[1], int)
                or isinstance(item[1], bool)
                or item[1] < 1
            ):
                raise ValueError("pages must contain (source_id, positive_pdf_page) pairs")
            selected_pages.add((item[0], item[1]))
        if not selected_pages:
            raise ValueError("pages must select at least one PDF page")
        known_sources = {source.source_id for source in sources}
        unknown = {source_id for source_id, _ in selected_pages} - known_sources
        if unknown:
            raise ValueError(f"unknown source_id in pages: {sorted(unknown)}")
        if source_filter and any(source_id != source_filter for source_id, _ in selected_pages):
            raise ValueError("pages selection conflicts with source_filter")
    postcorrection = (
        _postcorrection_model(root, sources, locked, cache_dir) if ocr and apply_postcorrection else None
    )
    if source_filter:
        sources = [s for s in sources if s.source_id == source_filter]
        if not sources:
            raise ValueError(f"unknown source_id: {source_filter}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    def package_version(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return "absent"

    ocr_runtime = None
    if ocr:
        from importlib.util import find_spec

        if find_spec("easyocr") is None or find_spec("vietocr") is None:
            raise RuntimeError("scan OCR requires EasyOCR and VietOCR; install the .[easy_vietocr] extra")
        try:
            from ocop_ocr.easy_viet_ocr import runtime_signature, asset_signature

            ocr_runtime = asset_signature() if executor is not None else runtime_signature()
        except Exception as exc:
            raise RuntimeError(
                f"easy_viet_ocr_model_load_failed:{type(exc).__name__}:{str(exc)[:180]}"
            ) from exc
    model_version = (
        f"easyocr={package_version('easyocr')};vietocr={package_version('vietocr')};"
        f"fitz={fitz.VersionBind};opencv={package_version('opencv-python-headless')}"
    )
    if ocr_runtime is not None:
        model_version += ";easy_viet_runtime=" + json.dumps(ocr_runtime, sort_keys=True)
    from ocop_ocr import raster_preprocess

    model_version += ";deskew=" + sha256_file(Path(raster_preprocess.__file__))
    counts = Counter()
    expected_all = 0
    manifest = {
        "schema_version": 2,
        "parser_version": PARSER_VERSION,
        "input_snapshot_sha256": locked["aggregate_sha256"],
        "status": "processed_not_legally_verified",
        "engine_requested": ENGINE if ocr else "native_only",
        "dpi": dpi,
        "ocr_enabled": ocr,
        "table_detection_enabled": tables,
        "ocr_runtime_signature": ocr_runtime,
        "model_versions": model_version,
        "sources": [],
        "counts": {},
        "errors": [],
        "ocr_postcorrection_model_sha256": postcorrection.sha256 if postcorrection else None,
    }
    manifest["ocr_warmup"] = {
        "executed": False,
        "policy": "canonical_locked_scan_discard_v1",
        "cache_written": False,
        "page_artifact_written": False,
    }

    def warmup():
        if manifest["ocr_warmup"]["executed"]:
            return
        for spec in sorted(locked_sources, key=lambda s: s.source_id):
            filename = (root / spec.path).resolve()
            digest = next(s["sha256"] for s in locked["sources"] if s["source_id"] == spec.source_id)
            profile = next(
                (
                    p
                    for p in _source_profiles(filename, spec.source_id, digest, cache_dir)
                    if p.get("needs_ocr_review")
                ),
                None,
            )
            if profile is None:
                continue
            started = time.monotonic()
            with fitz.open(filename) as document:
                extract_page(
                    document[profile["pdf_page"] - 1],
                    profile,
                    source_id=spec.source_id,
                    dpi=dpi,
                    enable_ocr=True,
                    enable_tables=tables,
                )
            manifest["ocr_warmup"].update(
                executed=True,
                source_id=spec.source_id,
                pdf_page=profile["pdf_page"],
                source_sha256=digest,
                dpi=dpi,
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
            return
        raise RuntimeError("OCR requested but no canonical locked scan available for warmup")

    if selected_pages is not None:
        manifest["debug_page_selection"] = [
            {"source_id": source_id, "pdf_page": page} for source_id, page in sorted(selected_pages)
        ]
    profiles_by_source = {}
    for source in sources:
        if selected_pages is not None and not any(sid == source.source_id for sid, _ in selected_pages):
            continue
        filepath = (root / source.path).resolve()
        digest = next(item["sha256"] for item in locked["sources"] if item["source_id"] == source.source_id)
        profiles = _source_profiles(filepath, source.source_id, digest, cache_dir)
        profiles_by_source[source.source_id] = profiles
    if selected_pages is not None:
        available = {
            (source_id, profile["pdf_page"])
            for source_id, profiles in profiles_by_source.items()
            for profile in profiles
        }
        missing = selected_pages - available
        if missing:
            raise ValueError(f"PDF page selection is out of range: {sorted(missing)}")
    inspected = 0
    warmup_job = None
    if executor is not None and ocr:
        for spec in sorted(locked_sources, key=lambda s: s.source_id):
            filename = (root / spec.path).resolve()
            digest = next(s["sha256"] for s in locked["sources"] if s["source_id"] == spec.source_id)
            profile = next(
                (
                    p
                    for p in _source_profiles(filename, spec.source_id, digest, cache_dir)
                    if p.get("needs_ocr_review")
                ),
                None,
            )
            if profile is not None:
                warmup_job = (str(filename), spec.source_id, profile, dpi, tables)
                break
        manifest["ocr_warmup"]["policy"] = "canonical_locked_scan_per_worker_discard_v1"
    for source in sources:
        if selected_pages is not None and source.source_id not in profiles_by_source:
            continue
        filepath = (root / source.path).resolve()
        digest = next(item["sha256"] for item in locked["sources"] if item["source_id"] == source.source_id)
        profiles = profiles_by_source.get(source.source_id)
        if profiles is None:
            profiles = _source_profiles(filepath, source.source_id, digest, cache_dir)
        expected_all += len(profiles)
        name = hashlib.sha256(source.source_id.encode()).hexdigest()[:12]
        output_path = output / f"{name}.pages.jsonl"
        # Resume uses per-page validated cache; JSONL output rebuilt atomically.
        tmp_path = output_path.with_suffix(".tmp")
        source_counts = Counter()
        continuations = []
        prev_art = None
        try:
            allowed = []
            selected_profiles = (
                profiles
                if selected_pages is None
                else [
                    profile
                    for profile in profiles
                    if (source.source_id, profile["pdf_page"]) in selected_pages
                ]
            )
            for profile in selected_profiles:
                if max_pages is not None and inspected >= max_pages:
                    break
                inspected += 1
                key = build_cache_key(
                    digest,
                    profile["pdf_page"],
                    dpi=dpi,
                    ocr_engine=ENGINE if ocr else "native_only",
                    extract_ocr=ocr,
                    detect_tables=tables,
                    model_version=model_version,
                )
                target = cache_path(cache_dir, source.source_id, key)
                allowed.append(
                    (
                        str(filepath),
                        source.source_id,
                        profile,
                        str(target),
                        force,
                        dpi,
                        ocr,
                        tables,
                        digest,
                        source.source_kind.value,
                    )
                )
            with tmp_path.open("w", encoding="utf-8") as fh:
                results = (
                    executor.map(partial(_worker_page, warmup_job=warmup_job), allowed)
                    if executor is not None
                    else (_page_job(job, before_ocr=warmup) for job in allowed)
                )
                for art in results:
                    if art.get("quarantined"):
                        manifest["errors"].append(
                            {
                                "source_id": art["source_id"],
                                "pdf_page": art["pdf_page"],
                                "warnings": art.get("warnings", []),
                            }
                        )
                    if postcorrection is not None:
                        # Applied after the page cache, which keeps the raw OCR transcription.
                        art = postcorrect_artifact(art, postcorrection)
                    _record_page(fh, art, source_counts)
                    if prev_art is not None:
                        continuations.extend(possible_continuations(prev_art, art))
                    prev_art = art
                fh.flush()
                os.fsync(fh.fileno())
            tmp_path.replace(output_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        cont_file = output / f"{name}.continuations.jsonl"
        if continuations:
            cont_file.write_text(
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in continuations), encoding="utf-8"
            )
        else:
            cont_file.unlink(missing_ok=True)
        source_counts["cross_page_table_candidates"] = len(continuations)
        if not source_counts["pages"]:
            break
        counts.update(source_counts)
        manifest["sources"].append(
            {
                "source_id": source.source_id,
                "source_sha256": digest,
                "page_count_expected": len(profiles),
                "pages_processed": source_counts["pages"],
                "artifact": output_path.name,
                "counts": dict(source_counts),
            }
        )
        if max_pages is not None and inspected >= max_pages:
            break
    manifest["counts"] = dict(counts)
    manifest["expected_total_pages"] = expected_all
    manifest["complete"] = bool(
        selected_pages is None
        and not source_filter
        and not max_pages
        and counts["pages"] == expected_all
        and counts["quarantined"] == 0
        and (
            ocr
            or all(
                s["counts"].get("ocr_executed", 0) == 0 and s["counts"].get("needs_review", 0) == 0
                for s in manifest["sources"]
            )
        )
    )
    write_json(output / "manifest.json", manifest)
    return manifest


def _parse_page(value: str) -> tuple[str, int]:
    source_id, separator, page = value.rpartition(":")
    if not separator or not source_id.strip():
        raise argparse.ArgumentTypeError("page must use SOURCE_ID:PAGE")
    try:
        number = int(page)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("page number must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("page number must be a positive integer")
    return source_id.strip(), number


def main():
    p = argparse.ArgumentParser(description="OCOP PDF: source-locked page OCR/layout/table extraction")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--registry", default="configs/ocop_sources.json")
    p.add_argument("--lock-file", default="configs/ocop_sources.lock.json")
    p.add_argument("--output", default="data/processed/ocop/pages")
    p.add_argument("--cache", default="data/processed/ocop/cache")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--without-ocr", action="store_true")
    p.add_argument("--without-tables", action="store_true")
    p.add_argument("--max-pages", type=int)
    p.add_argument("--source-id")
    p.add_argument(
        "--page",
        action="append",
        type=_parse_page,
        default=None,
        metavar="SOURCE_ID:PAGE",
        help="Process one PDF page (repeatable; debug-only partial output)",
    )
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    root = args.root.resolve()

    def resolve(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else root / candidate

    data = run_pipeline(
        root,
        registry=resolve(args.registry),
        lock=resolve(args.lock_file),
        output=resolve(args.output),
        cache_dir=resolve(args.cache),
        dpi=args.dpi,
        ocr=not args.without_ocr,
        tables=not args.without_tables,
        max_pages=args.max_pages,
        source_filter=args.source_id,
        pages=set(args.page) if args.page is not None else None,
        force=args.force,
    )
    print(
        json.dumps(
            {
                "sources": len(data["sources"]),
                "counts": data["counts"],
                "complete": data["complete"],
                "output": str(resolve(args.output)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
