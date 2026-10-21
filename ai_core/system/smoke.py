"""Run selected OCOP PDF pages through the complete local debug pipeline."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from ocop_contracts.registry import load_registry

ROOT=Path(__file__).resolve().parents[2]


def _parse_page(value:str)->tuple[str,int]:
    source_id,separator,page=value.rpartition(":")
    if not separator or not source_id.strip():
        raise argparse.ArgumentTypeError("page must use SOURCE_ID:PAGE")
    try:
        number=int(page)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("page number must be a positive integer") from exc
    if number<1:
        raise argparse.ArgumentTypeError("page number must be a positive integer")
    return source_id.strip(),number


def _jsonl(path:Path)->list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _render_sources(root:Path,pages:set[tuple[str,int]],dpi:int)->dict[tuple[str,int],Path]:
    import fitz

    sources={source.source_id:source for source in load_registry(root/"configs"/"ocop_sources.json")}
    target=root/"debug_renders"
    target.mkdir(parents=True,exist_ok=True)
    renders={}
    for source_id,page_number in sorted(pages):
        source=sources[source_id]
        filepath=(root/source.path).resolve()
        with fitz.open(filepath) as document:
            page=document.load_page(page_number-1)
            pixmap=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
            name=f"{hashlib.sha256(source_id.encode()).hexdigest()[:12]}-p{page_number}.png"
            destination=target/name
            pixmap.save(destination)
            renders[(source_id,page_number)]=destination
    return renders


def _copy_project_inputs(project_root:Path,output_root:Path)->None:
    shutil.copytree(project_root/"configs",output_root/"configs")
    shutil.copytree(project_root/"data"/"raw",output_root/"data"/"raw")


def _report(root:Path,pages_manifest:dict,knowledge_manifest:dict,index_manifest:dict,
            graph_manifest:dict,questions:list[str],answers:list,rendered:dict)->None:
    print(f"Smoke artifact root: {root}")
    print("\n1. PDF / OCR / layout")
    page_records=[]
    for source in pages_manifest.get("sources",[]):
        page_records.extend(_jsonl(root/"data"/"processed"/"ocop"/"pages"/source["artifact"]))
    for page in page_records:
        cells=[cell for table in page.get("tables",[]) for cell in table.get("cells",[])]
        key=(page["source_id"],page["pdf_page"])
        print(f"  {key[0]} p.{key[1]}: blocks={len(page.get('blocks',[]))}, "
              f"tables={len(page.get('tables',[]))}, cells={len(cells)}, "
              f"noise_candidates={len(page.get('ocr_noise_candidates',[]))}, "
              f"warnings={page.get('warnings',[])}, render={rendered.get(key)}")

    print("\n2. Diacritic post-correction")
    total_changes=0
    for page in page_records:
        page_changes=0
        for block in page.get("blocks",[]):
            changes=block.get("postcorrections") or []
            page_changes+=len(changes)
            for change in changes:
                print(f"  {page['source_id']} p.{page['pdf_page']} {block.get('block_id')}: "
                      f"{change.get('from')} -> {change.get('to')}; raw={block.get('ocr_raw_text')!r}")
        total_changes+=page_changes
        print(f"  {page['source_id']} p.{page['pdf_page']}: {page_changes} replacements; "
              f"model={((page.get('postcorrection') or {}).get('model_sha256'))}")
    print(f"  Total replacements: {total_changes}")

    print("\n3. EvidenceUnit extraction")
    units=_jsonl(root/"data"/"processed"/"ocop"/"knowledge"/"evidence_units.jsonl")
    kinds=Counter(row.get("unit_kind","unknown") for row in units)
    print(f"  pages={knowledge_manifest.get('counts',{}).get('pages',0)}, units={len(units)}, "
          f"by kind={dict(sorted(kinds.items()))}, complete={knowledge_manifest.get('complete')}")
    print(f"  entities={len(_jsonl(root/'data'/'processed'/'ocop'/'knowledge'/'entities.jsonl'))}, "
          f"relations={len(_jsonl(root/'data'/'processed'/'ocop'/'knowledge'/'relations.jsonl'))}")

    print("\n4. Entity / relation graph")
    print(f"  nodes={graph_manifest.get('counts',{}).get('nodes',0)}, "
          f"edges={graph_manifest.get('counts',{}).get('edges',0)}, "
          f"status={graph_manifest.get('status')}")

    print("\n5. Chunking / BM25 index")
    chunks=_jsonl(root/"data"/"processed"/"ocop"/"index"/"chunks.jsonl")
    print(f"  chunks={len(chunks)}, bm25={index_manifest.get('bm25',{}).get('documents',0)}, "
          f"status={index_manifest.get('status')}")

    print("\n6. Agent answers and citations")
    for question,response in zip(questions,answers):
        payload=response.model_dump(mode="json")
        print(f"  Q: {question}\n  A: {payload['answer']}\n  status={payload['status']}")
        for citation in payload.get("citations",[]):
            spans=citation.get("source_spans") or []
            bbox=citation.get("bbox") or next((span.get("bbox") or span.get("table_bbox")
                                                 for span in spans if span.get("bbox") or span.get("table_bbox")),None)
            source_sha=citation.get("source_sha256") or next((span.get("source_sha256") for span in spans
                                                               if span.get("source_sha256")),None)
            print("    citation: " + json.dumps({
                "source_id":citation.get("source_id"),"pdf_page":citation.get("pdf_page"),
                "evidence_unit_id":citation.get("evidence_unit_id"),"chunk_id":citation.get("chunk_id"),
                "bbox":bbox,"source_sha256":source_sha,
                "review_status":citation.get("review_status")},ensure_ascii=False))


def main()->None:
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,"reconfigure",None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser(description="Run chosen OCOP pages through OCR, evidence, index, graph and agent")
    parser.add_argument("--project-root",type=Path,default=ROOT,
                        help="Source checkout containing configs/ and data/raw/ (default: this checkout)")
    parser.add_argument("--root-out",type=Path,
                        help="New artifact root outside the source checkout (default: a retained temp directory)")
    parser.add_argument("--reuse-root-out",action="store_true",
                        help="Reuse an existing --root-out with copied configs/raw and validated source hashes")
    parser.add_argument("--page",action="append",type=_parse_page,required=True,
                        metavar="SOURCE_ID:PAGE",help="Selected PDF page; repeat for additional pages")
    parser.add_argument("--ocr-dataset", type=Path, required=True, help="Previously produced OCR dataset")
    parser.add_argument("--question",action="append",default=[],
                        help="Question to ask the local OCOP agent; repeatable")
    parser.add_argument("--dpi",type=int,default=110,
                        help="OCR and inspection render DPI (100-450; default: 110)")
    parser.add_argument("--clean",action="store_true",
                        help="Remove the newly created artifact root after reporting")
    args=parser.parse_args()

    project_root=args.project_root.resolve()
    pages=set(args.page)
    if not pages:
        parser.error("provide at least one --page SOURCE_ID:PAGE")
    if not 100<=args.dpi<=450:
        parser.error("--dpi must be within 100-450")
    created_by_us=False
    if args.root_out:
        output_root=args.root_out.resolve()
        if output_root==project_root or project_root in output_root.parents:
            parser.error("--root-out must be outside the source checkout to keep it free of processed artifacts")
        if output_root.exists():
            if not args.reuse_root_out:
                parser.error(f"--root-out already exists: {output_root}; pass --reuse-root-out to reuse it")
            if args.clean:
                parser.error("--clean cannot remove a reused --root-out")
            try:
                from ocop_contracts.pdf_loader import checked_sources
                checked_sources(output_root,output_root/"configs"/"ocop_sources.json",
                                output_root/"configs"/"ocop_sources.lock.json")
            except (RuntimeError,ValueError,FileNotFoundError,OSError) as exc:
                parser.error(f"existing --root-out does not contain a valid copied OCOP source set: {exc}")
            created_by_us=False
        else:
            output_root.mkdir(parents=True)
            created_by_us=True
    else:
        if args.reuse_root_out:
            parser.error("--reuse-root-out requires --root-out")
        output_root=Path(tempfile.mkdtemp(prefix="ocop-smoke-"))
        created_by_us=True
    try:
        if created_by_us:
            _copy_project_inputs(project_root,output_root)
        processed=output_root/"data"/"processed"/"ocop"
        pages_dir=processed/"pages"
        from ocop_contracts.dataset import read_dataset
        from ocop_contracts.pdf_loader import checked_sources
        _, locked = checked_sources(output_root, output_root / "configs/ocop_sources.json",
                                    output_root / "configs/ocop_sources.lock.json")
        dataset_manifest, dataset_pages = read_dataset(args.ocr_dataset, locked, require_complete=False)
        selected = [p for p in dataset_pages if (p["source_id"], p["pdf_page"]) in pages]
        if {(p["source_id"], p["pdf_page"]) for p in selected} != pages:
            raise RuntimeError("OCR dataset does not contain every selected pilot page")
        pages_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for sid in sorted({p["source_id"] for p in selected}):
            filename = hashlib.sha256(sid.encode()).hexdigest()[:12] + ".pages.jsonl"
            chosen = [p for p in selected if p["source_id"] == sid]
            (pages_dir / filename).write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in chosen),
                                                encoding="utf-8")
            records.append({"source_id": sid, "artifact": filename})
        page_manifest = {"schema_version": 2, "complete": False, "sources": records,
                         "input_snapshot_sha256": locked["aggregate_sha256"],
                         "dataset_digest": dataset_manifest["dataset_digest"],
                         "ocr_version": dataset_manifest["ocr_version"], "counts": {"pages": len(selected)}}
        (pages_dir / "manifest.json").write_text(json.dumps(page_manifest), encoding="utf-8")
        rendered=_render_sources(output_root,pages,args.dpi)

        from ai_core.processing.ocop.knowledge_extract import extract_artifacts
        knowledge_dir=processed/"knowledge"
        knowledge_manifest=extract_artifacts(output_root,input_dir=pages_dir,
            output_dir=knowledge_dir,max_pages=len(pages))

        from ai_core.graph.ocop.builder import build_graph
        graph_manifest=build_graph(knowledge_dir,processed/"graph",allow_partial=True)

        from ai_core.retrieval.ocop.index_pipeline import build_index
        index_dir=processed/"index"
        index_manifest=build_index(knowledge=knowledge_dir,index_dir=index_dir,allow_partial=True)

        from ai_core.orchestration.ocop.workflow import OcopAgent
        agent=OcopAgent(output_root,llm=None,allow_partial_debug=True)
        answers=[agent.ask(question) for question in args.question]
        _report(output_root,page_manifest,knowledge_manifest,index_manifest,graph_manifest,
                args.question,answers,rendered)

        from ai_core.system.pipeline import OcopSystemPipeline
        system_status=OcopSystemPipeline(output_root).status()
        print(f"\nPartial artifact root system status: {system_status['state']}")
    finally:
        if args.clean and created_by_us:
            shutil.rmtree(output_root)
            print(f"Cleaned smoke artifact root: {output_root}")


if __name__=="__main__":
    main()
