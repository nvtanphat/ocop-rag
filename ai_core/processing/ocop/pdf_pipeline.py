"""PDF production-oriented PDF pages → PageArtifact JSONL (no DB writes).

Resumable page cache, immutable locked input, per-page failure quarantine.
LLMs cannot invent scores or verify OCR at this stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
from collections import Counter
from importlib.metadata import version, PackageNotFoundError
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from ai_core.domain.ocop_models import PageArtifact,ReviewStatus
from ai_core.processing.ocop.artifact_cache import PARSER_VERSION,build_cache_key,cache_path,load_json,write_json
from ai_core.processing.ocop.pdf_loader import checked_sources
from ai_core.processing.ocop.registry import sha256_file
from ai_core.processing.ocop.native_extractor import extract_native
from ai_core.processing.ocop.ocr_extractor import run_ocr,tesseract_runtime_signature
from ai_core.processing.ocop.layout import layout_page
from ai_core.processing.ocop.table_parser import native_tables,raster_tables
from ai_core.processing.ocop.structure_engine import ppstructure_tables
from ai_core.processing.ocop.document_vl import run_vl
from ai_core.processing.ocop.pdf_quality import score_page_quality
from ai_core.processing.ocop.score_cell_ocr import recover_scoring_cells
from ai_core.processing.ocop.profiler import profile_pdf
from ai_core.processing.ocop.table_continuity import possible_continuations

LOG=logging.getLogger(__name__)
ROOT=Path(__file__).resolve().parents[3]


def _render(page,dpi:int):
    from PIL import Image
    pix=page.get_pixmap(matrix=__import__("fitz").Matrix(dpi/72,dpi/72),alpha=False,colorspace=__import__("fitz").csRGB)
    return Image.frombytes("RGB",[pix.width,pix.height],pix.samples)


def _validate_boxes(blocks,tables,width,height):
    """Clamp small PDF producer text-bbox overflow; preserve unmodified coordinates.

    A native PDF text-line bbox can extend slightly past CropBox/MediaBox even
    while the text content is legible. Out-of-page anchors are unusable for UI;
    keep bbox_original and warning rather than quarantining the page.
    """
    clipped=0
    for obj in [*blocks,*tables,*(c for t in tables for c in t["cells"])]:
        box=obj["bbox"]
        if box is None:
            continue
        try:
            x0,y0,x1,y1=[float(v) for v in box]
        except (TypeError,ValueError) as exc:
            raise ValueError(f"invalid_source_bbox: {box}") from exc
        if not all(math.isfinite(v) for v in (x0,y0,x1,y1,width,height)):
            raise ValueError(f"invalid_source_bbox: {box} nonfinite")
        if x0>x1 or y0>y1 or x1 < 0 or y1 < 0 or x0>width or y0>height:
            raise ValueError(f"invalid_source_bbox: {box} width={width} height={height}")
        normalized=[round(max(0,min(width,x0)),2),round(max(0,min(height,y0)),2),
                    round(max(0,min(width,x1)),2),round(max(0,min(height,y1)),2)]
        if any(abs(a-b)>.01 for a,b in zip(box,normalized)):
            obj["bbox_original"]=box
            obj["bbox"]=normalized
            clipped+=1
    return clipped


def extract_page(page,profile:dict, *,source_id:str,dpi:int=260,
                 ocr_engine:str="auto",enable_ocr:bool=True,enable_tables:bool=True,table_engine:str="auto",
                 refine_score_cells:bool=False, preprocess:bool=False) -> dict:
    native=extract_native(page)
    if ocr_engine not in ("auto", "paddle", "tesseract", "paddle_vl", "easyocr", "easyocr_vietocr", "ensemble"):
        raise ValueError(f"unsupported OCR engine: {ocr_engine}")
    if table_engine not in ("auto", "opencv", "ppstructure", "paddle_vl"):
        raise ValueError(f"unsupported table engine: {table_engine}")
    use_ocr=enable_ocr and bool(profile["needs_ocr_review"])
    # Do not count signing metadata as source text on scanned pages.
    if profile["page_class"]=="ocr_candidate":
        native=[b for b in native if not profile["largest_image_area_ratio"]>=.7]
    blocks=native
    ocr_words=[]
    warnings=[]
    engine="native"
    vl_tables=None
    prepared=None
    working_page=page
    if use_ocr:
        pic=_render(page,dpi)
        original_pic=pic
        if preprocess:
            from types import SimpleNamespace
            from ai_core.processing.ocop.raster_preprocess import prepare_raster
            prepared=prepare_raster(pic)
            pic=prepared.image
            working_page=SimpleNamespace(rect=SimpleNamespace(
                width=page.rect.width*pic.width/prepared.source_size[0],
                height=page.rect.height*pic.height/prepared.source_size[1]))
        if ocr_engine == "paddle_vl":
            response,vl_tables=run_vl(pic,working_page,version=os.getenv("OCOP_PADDLE_VL_VERSION","v1.6"))
        else:
            response=run_ocr(pic,working_page,ocr_engine)
        blocks=response.blocks
        ocr_words=response.word_blocks or []
        engine=response.engine
        warnings+=response.warnings
        if not blocks:
            warnings.append("empty_ocr_result")
    elif profile["needs_ocr_review"]:
        warnings.append("ocr_required_but_not_executed")
    # Detect tables independently of text/OCR status.
    tables=[]
    if enable_tables:
        if not use_ocr:
            if table_engine in ("paddle_vl", "ppstructure"):
                pic=_render(page,dpi)
                if table_engine=="paddle_vl":
                    _,tables=run_vl(pic,page,version=os.getenv("OCOP_PADDLE_VL_VERSION","v1.6"))
                else:
                    tables=ppstructure_tables(pic,page)
            else:
                tables=native_tables(page)
        elif blocks:
            if vl_tables is not None:
                tables=vl_tables
            elif table_engine=="paddle_vl":
                _,tables=run_vl(pic,working_page,version=os.getenv("OCOP_PADDLE_VL_VERSION","v1.6"))
            elif table_engine=="ppstructure":
                tables=ppstructure_tables(pic,working_page)
            elif table_engine=="auto":
                try:
                    from importlib.util import find_spec
                    if find_spec("paddleocr") is not None:
                        tables=ppstructure_tables(pic,working_page)
                    if not tables:
                        if find_spec("paddleocr") is not None:
                            warnings.append("ppstructure_empty_using_raster_candidate")
                        tables=raster_tables(pic,working_page,ocr_words or blocks)
                except Exception as exc:
                    warnings.append(f"ppstructure_fallback:{type(exc).__name__}")
                    tables=raster_tables(pic,working_page,ocr_words or blocks)
            elif table_engine=="opencv":
                tables=raster_tables(pic,working_page,ocr_words or blocks)
            else:
                raise ValueError(f"unknown table engine: {table_engine}")
        if not tables and (profile["page_class"] in ("ocr_candidate","mixed_or_native_with_images")):
            warnings.append("table_detection_unverified_or_empty")
    refined={}
    if use_ocr and tables and (refine_score_cells or engine in ("tesseract", "ensemble")):
        refined=recover_scoring_cells(pic,working_page,tables,fill_empty=True,fill_invalid=True,
                                     image_view="deskewed" if prepared is not None else "source")
    if prepared is not None:
        from ai_core.processing.ocop.raster_preprocess import restore_geometry
        restore_geometry(prepared,blocks+ocr_words,tables,page.rect.width,page.rect.height)
        if tables and (refine_score_cells or engine in ("tesseract", "ensemble")) and prepared.angle_degrees:
            refined["source_view_score_recovery"]=recover_scoring_cells(
                original_pic,page,tables,fill_empty=True,fill_invalid=True,image_view="source")
    if use_ocr and engine == "ensemble" and tables:
        from ai_core.processing.ocop.ocr_consensus import refine_table_regions
        marker_words=None
        if prepared is not None and prepared.angle_degrees:
            marker_response=run_ocr(pic,working_page,"tesseract")
            marker_words=marker_response.word_blocks or []
            restore_geometry(prepared,marker_words,[],page.rect.width,page.rect.height)
        refined["table_text_consensus"]=refine_table_regions(
            _render(page,350),page,blocks,tables,marker_words=marker_words)
        ocr_words=list(blocks)
    blocks,layout_warnings=layout_page(blocks,page.rect.width,page.rect.height,
                                     preserve_order=engine in ("easyocr", "easyocr_vietocr", "ensemble", "paddle_vl"))
    warnings+=layout_warnings
    if any("merged_extent_unknown" in cell and cell["merged_extent_unknown"] for t in tables for cell in t["cells"]):
        warnings.append("possible_merged_table_cells")
    clipped=_validate_boxes(blocks+ocr_words,tables,page.rect.width,page.rect.height)
    if clipped:
        warnings.append(f"pdf_bbox_clipped:{clipped}")
    text="\n".join(b["text"] for b in blocks if b["text"].strip())
    if use_ocr and not text:
        status=ReviewStatus.NEEDS_REVIEW
    elif profile["needs_ocr_review"] and not use_ocr:
        status=ReviewStatus.NEEDS_REVIEW
    elif use_ocr or tables or warnings:
        status=ReviewStatus.NEEDS_REVIEW
    else:
        status=ReviewStatus.MACHINE_EXTRACTED
    confidences=[b["confidence"] for b in blocks if b["confidence"] is not None]
    artifact=PageArtifact(source_id=source_id,pdf_page=profile["pdf_page"],
        width_pt=profile["width_pt"],height_pt=profile["height_pt"],
        extracted_text=text,blocks=blocks,extraction_method=engine,review_status=status)
    payload=artifact.model_dump(mode="json")
    quality=score_page_quality(profile,blocks,tables,ocr_words)
    payload.update({"profile":profile,"tables":tables,"warnings":sorted(set(warnings)),
                    "preprocessing":prepared.metadata() if prepared is not None else None,
                    "page_quality":{**quality,**refined},
                    "ocr_engine":engine if use_ocr else None,"ocr_words":ocr_words,
                    "ocr_confidence_mean":round(sum(confidences)/len(confidences),4) if confidences else None,
                    "needs_human_verification":bool(use_ocr or tables or warnings)})
    return payload



def _cache_hash(artifact: dict) -> str:
    """Detect accidental/tampered page-cache contents (not a cryptographic signature)."""
    body={k:v for k,v in artifact.items() if k != "_cache_integrity_sha256"}
    packed=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _valid_cached_page(artifact: dict, source_id: str, profile: dict, source_sha256: str | None = None) -> bool:
    if not isinstance(artifact,dict) or artifact.get("quarantined"):
        return False
    digest=artifact.get("_cache_integrity_sha256")
    if not isinstance(digest,str) or len(digest)!=64:
        return False
    try:
        if digest != _cache_hash(artifact):
            return False
        PageArtifact.model_validate({k:artifact[k] for k in PageArtifact.model_fields if k in artifact})
        if artifact.get("source_id")!=source_id or artifact.get("pdf_page")!=profile["pdf_page"]:
            return False
        if source_sha256 is not None and artifact.get("source_sha256") != source_sha256:
            return False
        if (abs(artifact["width_pt"]-profile["width_pt"])>.02
                or abs(artifact["height_pt"]-profile["height_pt"])>.02):
            return False
        # Require the exact page classification that determined whether OCR was run.
        if artifact.get("profile")!=profile:
            return False
        if not isinstance(artifact.get("tables"),list) or not isinstance(artifact.get("blocks"),list):
            return False
    except (KeyError,ValueError,TypeError,OverflowError):
        return False
    return True


def _page_job(job: tuple) -> dict:
    """Independent process, no shared PyMuPDF objects (PyMuPDF is not thread safe)."""
    (filename,source_id,profile,cache_location,force,dpi,engine,ocr,tables,table_engine,score_refine,*digests)=job
    digest = digests[0] if digests else sha256_file(Path(filename))
    preprocess = bool(digests[1]) if len(digests)>1 else False
    cachefile=Path(cache_location)
    art=None if force else load_json(cachefile)
    if art is not None and not _valid_cached_page(art,source_id,profile,digest):
        art=None
    if art is not None:
        return art
    import fitz
    try:
        with fitz.open(filename) as d:
            art=extract_page(d.load_page(profile["pdf_page"]-1),profile,source_id=source_id,
                             dpi=dpi,ocr_engine=engine,enable_ocr=ocr,
                             enable_tables=tables,table_engine=table_engine,
                              refine_score_cells=score_refine,preprocess=preprocess)
    except Exception as exc:
        LOG.exception("page failed source=%s page=%s",source_id,profile["pdf_page"])
        art=PageArtifact(source_id=source_id,pdf_page=profile["pdf_page"],
            width_pt=profile["width_pt"],height_pt=profile["height_pt"],
            review_status=ReviewStatus.NEEDS_REVIEW).model_dump(mode="json")
        art.update({"profile":profile,"tables":[],"ocr_engine":None,
            "warnings":[f"quarantined:{type(exc).__name__}:{str(exc)[:220]}"],
            "needs_human_verification":True,"quarantined":True})
    art["source_sha256"] = digest
    if not art.get("quarantined"):
        art["_cache_integrity_sha256"]=_cache_hash(art)
        write_json(cachefile,art)
    return art



def _record_page(fh, art, counts):
    status="quarantined" if art.get("quarantined") else art["review_status"]
    counts[status]+=1
    counts["ocr_executed"]+=int(art.get("ocr_engine") is not None)
    counts["tables_detected"]+=len(art.get("tables",[]))
    quality=art.get("page_quality") or {}
    counts["table_cells_detected"]+=quality.get("table_cells",0)
    counts["table_cells_with_text"]+=quality.get("table_cells_with_text",0)
    counts["table_cells_with_bbox"]+=quality.get("table_cells_with_bbox",0)
    counts["possible_score_cells_without_text"]+=quality.get("potential_score_cells_blank",0)
    counts["pages"]+=1
    if art.get("warnings"):
        counts["pages_with_warnings"]+=1
    fh.write(json.dumps(art,ensure_ascii=False)+"\n")


def run_pipeline(root:Path, *, registry:Path, lock:Path,output:Path,cache_dir:Path,
                 engine:str="auto",dpi:int=260,ocr:bool=True,tables:bool=True,table_engine:str="auto",
                 max_pages:int|None=None,source_filter:str|None=None,force:bool=False,workers:int=1,
                 refine_score_cells:bool=False,preprocess:bool=False)->dict:
    if not 100<=dpi<=450:
        raise ValueError("dpi must be within 100-450")
    if refine_score_cells:
        from importlib.util import find_spec
        if find_spec('pytesseract') is None:
            raise RuntimeError('score-cell OCR requires pytesseract; install .[ocr] or disable refinement')
    vl_requested = (ocr and engine == "paddle_vl") or (tables and table_engine == "paddle_vl")
    if vl_requested:
        from importlib.util import find_spec
        if find_spec("paddleocr") is None:
            raise RuntimeError('PaddleOCR-VL requires PaddleOCR 3.x and its model dependencies; '
                               'install optional model stack or choose Tesseract/OpenCV')
        if workers > 1:
            raise ValueError('PaddleOCR-VL 0.9B is memory-intensive: use workers=1 per model instance')
    if max_pages is not None and max_pages<1:
        raise ValueError("max_pages must be positive")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    import fitz
    # Avoid Tesseract/OpenMP oversubscription and subprocess deadlock on small laptops.
    os.environ.setdefault("OMP_THREAD_LIMIT","1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
    root=root.resolve()
    sources,locked=checked_sources(root,registry,lock)
    if source_filter:
        sources=[s for s in sources if s.source_id==source_filter]
        if not sources:
            raise ValueError(f"unknown source_id: {source_filter}")
    cache_dir.mkdir(parents=True,exist_ok=True)
    output.mkdir(parents=True,exist_ok=True)
    def package_version(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return "absent"
    model_version=(f"paddle_vl_version={os.getenv('OCOP_PADDLE_VL_VERSION','v1.6')};"
                   f"paddleocr={package_version('paddleocr')};"
                   f"pytesseract={package_version('pytesseract')};"
                   f"fitz={fitz.VersionBind};"
                   f"opencv={package_version('opencv-python-headless')};"
                   f"table={table_engine};score_refinement={refine_score_cells}")
    if vl_requested:
        from ai_core.processing.ocop.document_vl import load_vl_model, runtime_signature
        vl_version=os.getenv("OCOP_PADDLE_VL_VERSION","v1.6")
        runtime=runtime_signature(vl_version)
        model_version += ";paddle_vl_runtime=" + json.dumps(runtime,sort_keys=True)
        try:
            load_vl_model(vl_version)
        except Exception as exc:
            raise RuntimeError(f"paddleocr_vl_model_load_failed:{type(exc).__name__}:{str(exc)[:180]}") from exc
    if (ocr and engine in ("auto", "tesseract", "ensemble")) or refine_score_cells:
        runtime = tesseract_runtime_signature()
        if ocr and engine in ("tesseract", "ensemble"):
            if not runtime['available']:
                raise RuntimeError('Tesseract executable missing; install Tesseract with vie and eng traineddata')
            missing = [lang for lang in ('vie', 'eng') if not runtime['traineddata'].get(lang)]
            if missing:
                raise RuntimeError('missing_ocr_languages:' + ','.join(missing))
        model_version += ";tesseract_runtime=" + json.dumps(runtime, sort_keys=True)
    if ocr and engine in ("easyocr", "easyocr_vietocr", "ensemble"):
        from ai_core.processing.ocop.easy_viet_ocr import runtime_signature
        model_version += ";easy_runtime=" + json.dumps(runtime_signature(engine), sort_keys=True)
    if preprocess:
        from ai_core.processing.ocop import raster_preprocess
        model_version += ";preprocess=" + sha256_file(Path(raster_preprocess.__file__))
    counts=Counter()
    expected_all=0
    manifest={"schema_version":2,"parser_version":PARSER_VERSION,"input_snapshot_sha256":locked["aggregate_sha256"],
              "status":"processed_not_legally_verified","engine_requested":engine,"dpi":dpi,
              "ocr_enabled":ocr,"table_detection_enabled":tables,"table_engine_requested":table_engine,"score_refinement_enabled":refine_score_cells,
              "preprocess_enabled":preprocess,"model_versions":model_version,"sources":[],"counts":{}}
    inspected=0
    for source in sources:
        filepath=(root/source.path).resolve()
        digest=next(item["sha256"] for item in locked["sources"] if item["source_id"]==source.source_id)
        # Source-locked profile cache: repeated full ingestion must not scan
        # every PDF page a second time just to learn native/image page type.
        profile_file=cache_dir/"_profiles"/f"{digest}.profile.json"
        profile_cache=load_json(profile_file)
        if (isinstance(profile_cache,dict) and profile_cache.get("sha256")==digest
                and profile_cache.get("source_id")==source.source_id
                and profile_cache.get("profile_version")=="ocop-profile-v3"
                and isinstance(profile_cache.get("pages"),list)
                and len(profile_cache["pages"])>0
                and profile_cache.get("pages_sha256")==hashlib.sha256(json.dumps(
                    profile_cache["pages"],sort_keys=True,ensure_ascii=False,
                    separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
                and all(x.get("pdf_page")==i+1 for i,x in enumerate(profile_cache["pages"]))):
            profiles=profile_cache["pages"]
        else:
            profiles=profile_pdf(filepath,source.source_id)
            write_json(profile_file,{"sha256":digest,"source_id":source.source_id,
                                     "profile_version":"ocop-profile-v3","pages":profiles,
                                     "pages_sha256":hashlib.sha256(json.dumps(
                                         profiles,sort_keys=True,ensure_ascii=False,
                                         separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()})
        expected_all+=len(profiles)
        name=hashlib.sha256(source.source_id.encode()).hexdigest()[:12]
        output_path=output/f"{name}.pages.jsonl"
        # Resume uses per-page validated cache; JSONL output rebuilt atomically.
        tmp_path=output_path.with_suffix(".tmp")
        source_counts=Counter()
        continuations=[]
        prev_art=None
        try:
            allowed = []
            for profile in profiles:
                if max_pages is not None and inspected >= max_pages:
                    break
                inspected += 1
                key=build_cache_key(digest,profile["pdf_page"],dpi=dpi,ocr_engine=engine,
                                    extract_ocr=ocr,detect_tables=tables,model_version=model_version)
                target=cache_path(cache_dir,source.source_id,key)
                allowed.append((str(filepath),source.source_id,profile,str(target),force,dpi,engine,ocr,tables,table_engine,refine_score_cells,digest,preprocess))
            if workers == 1:
                results = map(_page_job,allowed)
                with tmp_path.open("w",encoding="utf-8") as fh:
                    for art in results:
                        _record_page(fh,art,source_counts)
                        if prev_art is not None:
                            continuations.extend(possible_continuations(prev_art,art))
                        prev_art=art
                    fh.flush()
                    os.fsync(fh.fileno())
            else:
                with ProcessPoolExecutor(max_workers=workers,mp_context=get_context("spawn")) as pool:
                    with tmp_path.open("w",encoding="utf-8") as fh:
                        for art in pool.map(_page_job,allowed,chunksize=1):
                            _record_page(fh,art,source_counts)
                            if prev_art is not None:
                                continuations.extend(possible_continuations(prev_art,art))
                            prev_art=art
                        fh.flush()
                        os.fsync(fh.fileno())
            tmp_path.replace(output_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        cont_file=output/f"{name}.continuations.jsonl"
        if continuations:
            cont_file.write_text("".join(json.dumps(c,ensure_ascii=False)+"\n" for c in continuations),encoding="utf-8")
        else:
            cont_file.unlink(missing_ok=True)
        source_counts["cross_page_table_candidates"]=len(continuations)
        if not source_counts["pages"]:
            break
        counts.update(source_counts)
        manifest["sources"].append({"source_id":source.source_id,"source_sha256":digest,"page_count_expected":len(profiles),
                                    "pages_processed":source_counts["pages"],"artifact":output_path.name,
                                    "counts":dict(source_counts)})
        if max_pages is not None and inspected>=max_pages:
            break
    manifest["counts"]=dict(counts)
    manifest["expected_total_pages"] = expected_all
    manifest["complete"]=bool(not source_filter and not max_pages and counts["pages"]==expected_all and counts["quarantined"]==0 and (ocr or all(s["counts"].get("ocr_executed",0)==0 and s["counts"].get("needs_review",0)==0 for s in manifest["sources"])))
    write_json(output/"manifest.json",manifest)
    return manifest


def main():
    p=argparse.ArgumentParser(description="OCOP PDF: source-locked page OCR/layout/table extraction")
    p.add_argument("--root",type=Path,default=ROOT)
    p.add_argument("--registry",default="configs/ocop_sources.json")
    p.add_argument("--lock-file",default="configs/ocop_sources.lock.json")
    p.add_argument("--output",default="data/processed/ocop/pages")
    p.add_argument("--cache",default="data/processed/ocop/cache")
    p.add_argument("--engine",choices=["auto","paddle","tesseract","paddle_vl","easyocr","easyocr_vietocr","ensemble"],default="auto")
    p.add_argument("--dpi",type=int,default=260)
    p.add_argument("--preprocess",action="store_true",help="Conservative deskew with inverse source geometry")
    p.add_argument("--table-engine",choices=["auto","opencv","ppstructure","paddle_vl"],default="auto")
    p.add_argument("--without-ocr",action="store_true")
    p.add_argument("--without-tables",action="store_true")
    p.add_argument("--refine-score-cells",action="store_true",help="Read narrow score cells separately; unverified candidates only")
    p.add_argument("--max-pages",type=int)
    p.add_argument("--source-id")
    p.add_argument("--force",action="store_true")
    p.add_argument("--workers",type=int,default=1,help="PDF OCR page workers (processes, not threads)")
    args=p.parse_args()
    root=args.root.resolve()
    def resolve(path):
        candidate=Path(path)
        return candidate if candidate.is_absolute() else root/candidate
    data=run_pipeline(root,registry=resolve(args.registry),lock=resolve(args.lock_file),
        output=resolve(args.output),cache_dir=resolve(args.cache),engine=args.engine,dpi=args.dpi,
        ocr=not args.without_ocr,tables=not args.without_tables,table_engine=args.table_engine,
        max_pages=args.max_pages,source_filter=args.source_id,force=args.force,workers=args.workers,
          refine_score_cells=args.refine_score_cells,preprocess=args.preprocess)
    print(json.dumps({"sources":len(data["sources"]),"counts":data["counts"],
                      "complete":data["complete"],"output":str(resolve(args.output))},ensure_ascii=False))

if __name__=="__main__":
    main()
