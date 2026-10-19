from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

from ai_core.domain.ocop_models import SourceDocument
from ai_core.processing.ocop.registry import snapshot


def _source_pdf(path:Path,*,scanned_first_page:bool=False)->None:
    import fitz
    from PIL import Image,ImageDraw

    path.parent.mkdir(parents=True,exist_ok=True)
    image_stream=None
    if scanned_first_page:
        image=Image.new("RGB",(600,800),"white")
        ImageDraw.Draw(image).text((35,45),"Scanned page for OCOP smoke test",fill="black")
        image_stream=io.BytesIO()
        image.save(image_stream,format="PNG")
    with fitz.open() as document:
        for page_number in range(1,4):
            page=document.new_page(width=450,height=600)
            if scanned_first_page and page_number==1:
                page.insert_image(page.rect,stream=image_stream.getvalue())
                continue
            for line in range(8):
                page.insert_text((35,55+line*35),
                    f"Page {page_number} legal content line {line}: local OCOP products and criteria.",
                    fontsize=11)
        document.save(path)


def _locked_project(root:Path)->list[SourceDocument]:
    native_path=root/"data/raw/ocop/native.pdf"
    scan_path=root/"data/raw/ocop/scanned.pdf"
    _source_pdf(native_path)
    _source_pdf(scan_path,scanned_first_page=True)
    sources=[
        SourceDocument(source_id="VN.TEST.NATIVE",path="data/raw/ocop/native.pdf",
                       source_kind="ocop_framework"),
        SourceDocument(source_id="VN.TEST.SCAN",path="data/raw/ocop/scanned.pdf",
                       source_kind="ocop_framework"),
    ]
    (root/"configs").mkdir(parents=True,exist_ok=True)
    registry=root/"configs/ocop_sources.json"
    registry.write_text(json.dumps({"schema_version":1,"sources":[
        source.model_dump(mode="json") for source in sources]}),encoding="utf-8")
    (root/"configs/ocop_sources.lock.json").write_text(
        json.dumps(snapshot(root,sources)),encoding="utf-8")
    return sources


def test_run_pipeline_processes_only_selected_pages_and_stays_partial(tmp_path,monkeypatch):
    import ai_core.processing.ocop.easy_viet_ocr as ocr_module
    import ai_core.processing.ocop.pdf_pipeline as pipeline
    from ai_core.processing.ocop.ocr_types import OCRResult

    root=tmp_path/"project"
    sources=_locked_project(root)
    real_find_spec=importlib.util.find_spec
    monkeypatch.setattr(importlib.util,"find_spec",lambda name:
        object() if name in {"easyocr","vietocr"} else real_find_spec(name))
    monkeypatch.setattr(ocr_module,"runtime_signature",lambda:{"engine":"test-double"})
    ocr_calls=[]

    def fake_ocr(*args,**kwargs):
        ocr_calls.append(True)
        return OCRResult([{"block_id":"ocr:test","text":"Văn bản quét thử nghiệm",
            "bbox":[20,20,240,50],"method":"mock","confidence":0.9,"order":0}],
            "easyocr_vietocr",[]),[]

    monkeypatch.setattr(pipeline,"run_easy_viet_ocr",fake_ocr)
    pages={("VN.TEST.NATIVE",2),("VN.TEST.SCAN",1)}
    output=root/"data/processed/ocop/pages"
    manifest=pipeline.run_pipeline(root,
        registry=root/"configs/ocop_sources.json",lock=root/"configs/ocop_sources.lock.json",
        output=output,cache_dir=root/"data/processed/ocop/cache",dpi=110,pages=pages)

    assert manifest["complete"] is False
    assert manifest["counts"]["pages"]==2
    assert {tuple((row["source_id"],row["pdf_page"])) for row in manifest["debug_page_selection"]}==pages
    assert ocr_calls==[True,True]  # discarded canonical warm-up, then the requested scan
    assert manifest['ocr_warmup']['executed'] is True
    assert manifest['ocr_warmup']['cache_written'] is False
    again=pipeline.run_pipeline(root,
        registry=root/'configs/ocop_sources.json',lock=root/'configs/ocop_sources.lock.json',
        output=output,cache_dir=root/'data/processed/ocop/cache',dpi=110,pages=pages)
    assert again['ocr_warmup']['executed'] is False
    assert ocr_calls==[True,True]
    actual=[]
    for source in manifest["sources"]:
        actual.extend(json.loads(line) for line in (output/source["artifact"]).read_text(encoding="utf-8").splitlines())
    assert {(row["source_id"],row["pdf_page"]) for row in actual}==pages
    assert all(row.get("source_sha256") for row in actual)

    from ai_core.processing.ocop.knowledge_extract import extract_artifacts
    knowledge=root/"data/processed/ocop/knowledge"
    knowledge_manifest=extract_artifacts(root,input_dir=output,output_dir=knowledge,max_pages=len(pages))
    assert knowledge_manifest["complete"] is False

    from ai_core.retrieval.ocop.index_pipeline import build_index
    index=root/"data/processed/ocop/index"
    with pytest.raises(RuntimeError,match="corpus incomplete"):
        build_index(knowledge=knowledge,index_dir=index)
    index_manifest=build_index(knowledge=knowledge,index_dir=index,allow_partial=True)
    assert index_manifest["status"]=="partial_debug_not_production"
    assert index_manifest["source_complete"] is False

    from ai_core.graph.ocop.builder import build_graph
    graph=root/"data/processed/ocop/graph"
    with pytest.raises(ValueError,match="manifest incomplete"):
        build_graph(knowledge,graph)
    graph_manifest=build_graph(knowledge,graph,allow_partial=True)
    assert graph_manifest["status"]=="partial_debug_not_production"
    from ai_core.graph.ocop.integrity import validate_graph_snapshot
    with pytest.raises(ValueError,match="not ready"):
        validate_graph_snapshot(graph)
    assert validate_graph_snapshot(graph,allow_partial=True)["status"]=="partial_debug_not_production"

    from ai_core.system.pipeline import OcopSystemPipeline
    from ai_core.processing.ocop.artifact_cache import PARSER_VERSION
    from ai_core.processing.ocop.knowledge_extract import VERSION as KNOWLEDGE_VERSION
    (root/"data/processed/ocop/pages/manifest.json").write_text(json.dumps({
        **manifest,"parser_version":PARSER_VERSION}),encoding="utf-8")
    knowledge_manifest["pipeline_version"]=KNOWLEDGE_VERSION
    knowledge_manifest["source_snapshot_sha256"]=manifest["input_snapshot_sha256"]
    (knowledge/"manifest.json").write_text(json.dumps(knowledge_manifest),encoding="utf-8")
    status=OcopSystemPipeline(root).status()
    assert status["state"]=="not_ready"
    assert status["lineage_ok"] is False
