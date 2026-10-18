"""evidence extraction: PageArtifact -> source-grounded OCOP EvidenceUnits, entities and relations.

This is extraction, not legal approval. OCR candidates are retained with provenance
and review flags. There is deliberately no LLM/model/network dependency here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ai_core.domain.ocop_ids import stable_id, content_sha256
from ai_core.domain.ocop_models import EvidenceUnit, SourceSpan, ReviewStatus
from ai_core.processing.ocop.registry import load_registry
from ai_core.processing.ocop.business_candidates import candidates
from ai_core.processing.ocop.temporal_candidates import temporal_candidates
from ai_core.knowledge.ocop.extractor import extract_semantics
from ai_core.knowledge.ocop.llm_proposals import propose
from ai_core.knowledge.ocop.quality import audit_knowledge
from ai_core.knowledge.ocop.contracts import BusinessEntity, BusinessRelation, validate_business_graph

ROOT = Path(__file__).resolve().parents[3]
VERSION = "ocop-evidence-v3.4-source-anchors"
LEGAL_START = re.compile(r"^\s*(Điều\s+\d+[a-zđ]?(?:[.:]\s*.*)?|Chương\s+[IVXLCDM0-9]+\b.*|Mục\s+\d+\b.*|PHỤ\s*LỤC\s*[IVXLCDM0-9]*\b.*|Mẫu\s*(?:số)?\s*0?[1-9]\b.*)\s*$", re.IGNORECASE)
LEGAL_REFERENCE = re.compile(r"\b\d{1,4}/20\d{2}/(?:QĐ-TTg|NĐ-CP|NQ-CP|QH\d+|QĐ-UBND|TT-[A-ZĐ]+)\b",re.IGNORECASE)
YEAR = re.compile(r"\b(?:năm\s+)?(20\d{2})\b",re.IGNORECASE)
STAR = re.compile(r"\b([1-5])\s*(?:sao|\*)\b",re.IGNORECASE)
FORM = re.compile(r"\bMẫu\s*(?:số)?\s*0?([1-9])\b",re.IGNORECASE)
TERMS = {"chứng nhận": "certificate", "hợp tác xã": "organization", "doanh nghiệp": "organization", "thực phẩm": "food", "sản phẩm": "product", "an toàn thực phẩm": "food_safety", "truy xuất nguồn gốc": "traceability", "tiêu chí": "criterion", "chấm điểm": "scoring", "phụ lục": "annex"}


def _jsonl_atomic(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix(path.suffix+".tmp")
    count=0
    with tmp.open("w",encoding="utf-8",newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec,ensure_ascii=False,sort_keys=True,default=str)+"\n")
            count+=1
    os.replace(tmp,path)
    return count


def _span(page: dict, *, bbox=None, table_id=None, cell_id=None, block_id=None) -> SourceSpan:
    return SourceSpan(pdf_page=page["pdf_page"], bbox=tuple(bbox) if bbox is not None else None,
                      table_id=table_id,cell_id=cell_id,block_id=block_id,
                      source_sha256=page.get("source_sha256"))


def _unit(page:dict, kind:str,ordinal:str,text:str,*,structured:dict|None=None,spans:list[SourceSpan]|None=None,parent:str|None=None)->dict:
    # Stable even when OCR text changes, keyed by document/page/unit position.
    unit_id=stable_id("evidence",page["source_id"],[page["pdf_page"],kind,ordinal],revision=VERSION)
    raw_status=page.get("review_status","needs_review")
    if raw_status not in ("machine_extracted","verified"):
        status=ReviewStatus.NEEDS_REVIEW
    else:
        status=ReviewStatus.MACHINE_EXTRACTED
    record=EvidenceUnit(unit_id=unit_id,source_id=page["source_id"],unit_kind=kind,parent_unit_id=parent,
       hierarchy_path=[page["source_id"],str(page["pdf_page"]),kind,ordinal],text=text,
       structured=structured or {},spans=spans or [_span(page)],extractor_version=VERSION,
       review_status=status,unit_hash=content_sha256(text)).model_dump(mode="json")
    return record


def _segments(text:str)->list[tuple[str,str]]:
    """Section-aware splitting; retains all nonblank source text, including OCR noise."""
    lines=text.splitlines()
    segments=[];buf=[];kind="paragraph";idx=0
    def flush():
        nonlocal buf,idx
        value="\n".join(buf).strip()
        if value:
            segments.append((kind,value))
            idx+=1
        buf=[]
    for line in lines:
        clean=line.strip()
        if not clean:
            continue
        m=LEGAL_START.match(clean)
        if m:
            flush()
            low=clean.casefold()
            kind=("article" if low.startswith("điều") else "annex" if "phụ" in low and "lục" in low
                  else "form" if low.startswith("mẫu") else "section")
            buf.append(clean)
        else:
            buf.append(clean)
            if len("\n".join(buf))>=1800 and kind in ("paragraph","section"):
                flush();kind="paragraph"
    flush()
    return segments


def _segments_with_line_indices(text:str):
    """Attach original page line offsets to each section-aware segment."""
    source_lines=text.splitlines()
    cursor=0
    for kind,body in _segments(text):
        indices=[]
        for segment_line in body.splitlines():
            while cursor < len(source_lines) and source_lines[cursor].strip()!=segment_line:
                cursor+=1
            if cursor >= len(source_lines):
                yield kind,body,[]
                break
            indices.append(cursor)
            cursor+=1
        else:
            yield kind,body,indices


def _segment_spans(page:dict, line_indices:list[int])->list[SourceSpan]:
    """Map segment lines to exact page blocks when the text stream agrees."""
    text=page.get("extracted_text","")
    source_blocks=[block for block in page.get("blocks",[])
                   if isinstance(block,dict) and isinstance(block.get("text"),str)
                   and block["text"].strip()]
    if not source_blocks or "\r" in text:
        return [_span(page)]
    if "\n".join(block["text"] for block in source_blocks)!=text:
        return [_span(page)]

    line_blocks=[]
    for block in source_blocks:
        line_blocks.extend([block]*len(block["text"].split("\n")))
    if not line_indices or any(index < 0 or index >= len(line_blocks) for index in line_indices):
        return [_span(page)]

    spans=[]
    seen=set()
    for line_index in line_indices:
        block=line_blocks[line_index]
        key=(line_index,block.get("block_id"))
        if key in seen:
            continue
        seen.add(key)
        spans.append(_span(page,bbox=block.get("bbox"),block_id=block.get("block_id")))
    return spans or [_span(page)]


def page_units(page:dict, *, source_kind:str="") -> list[dict]:
    """Creates page root, structural units, and independent table evidence units."""
    text=page.get("extracted_text","")
    root=_unit(page,"page","root",text[:5000],structured={
        "source_kind":source_kind,"extraction_method":page.get("extraction_method"),
        "warnings":page.get("warnings",[]),"text_length":len(text),
        "table_count":len(page.get("tables",[])),"has_ocr":bool(page.get("ocr_engine"))})
    units=[root]
    if not text.strip() and not page.get("tables"):
        return units
    active_legal_heading=None
    for i,(kind,body,line_indices) in enumerate(_segments_with_line_indices(text)):
        # Preserve only headings seen on this very page: do not infer absent
        # cross-page legislation or invent article numbers from OCR noise.
        first=body.splitlines()[0][:180]
        structured={"source_kind":source_kind,"heading":first}
        if kind in ("article","annex","form","section"):
            active_legal_heading=first
        elif active_legal_heading is not None:
            structured['legal_heading']=active_legal_heading
            structured['legal_heading_origin']='same_page_previous_segment'
        units.append(_unit(page,kind,str(i),body,parent=root["unit_id"],
             structured=structured,spans=_segment_spans(page,line_indices)))
    for i,table in enumerate(page.get("tables",[])):
        cells=table.get("cells",[])
        # Stable row-major table text, preserve coordinate and row/column.
        cells_sorted=sorted(cells,key=lambda x:(x.get("row",0),x.get("col",0)))
        rows={}
        for c in cells_sorted:
            rows.setdefault(int(c.get("row",0)),[]).append(str(c.get("text") or "").strip())
        txt="\n".join(" | ".join(r) for _,r in sorted(rows.items())).strip()
        if not txt:
            txt=f"[Phát hiện vùng bảng trên trang PDF {page['pdf_page']} nhưng chưa nhận dạng được nội dung]"
        table_id=str(table.get("table_id") or f"table:{i}")
        candidate=("criterion_table_candidate" if source_kind in ("ocop_framework","ocop_historical","ocop_amendment") else "table")
        units.append(_unit(page,candidate,str(i),txt,parent=root["unit_id"],
            structured={"source_kind":source_kind,"table_id":table_id,"cells":cells_sorted,
                "row_count":table.get("row_count"),"col_count":table.get("col_count"),
                "method":table.get("method"),"candidate_only":True,"warnings":table.get("warnings",[])},
            spans=[_span(page,bbox=table.get("bbox"),table_id=table_id)]))
    return units


def extract_entities_relations(units:list[dict],sources:dict[str,dict])->tuple[list[dict],list[dict]]:
    """Source-anchored entity and relation candidates; no fabricated cross-document links."""
    entities={};relations={}
    def entity(sid:str,etype:str,key:str,display:str,unit_id:str)->str:
        eid=stable_id("entity",sid,[etype,key.casefold()])
        rec=entities.setdefault(eid,{"entity_id":eid,"source_id":sid,"entity_type":etype,"name":display,
                                   "evidence_unit_ids":[],"review_status":"machine_extracted"})
        if unit_id not in rec["evidence_unit_ids"]:
            rec["evidence_unit_ids"].append(unit_id)
        return eid
    def rel(sid:str,reltype:str,start:str,end:str,uid:str)->None:
        if start==end:
            return
        rid=stable_id("relation",sid,[reltype,start,end,uid])
        relations[rid]={"relation_id":rid,"source_id":sid,"relation_type":reltype,
                        "source_entity_id":start,"target_entity_id":end,"evidence_unit_id":uid,
                        "review_status":"needs_review"}
    for u in units:
        sid=u["source_id"];uid=u["unit_id"];body=u["text"]
        if u["unit_kind"]=="page":
            continue
        docid=entity(sid,"source_document",sid,sources.get(sid,{}).get("document_number") or sid,uid)
        eu=entity(sid,"evidence_unit",uid, u["unit_kind"]+" — "+(body[:90] if body else ""),uid)
        rel(sid,"CONTAINS",docid,eu,uid)
        for val in dict.fromkeys(LEGAL_REFERENCE.findall(body)):
            rid=entity(sid,"regulation_reference",val,val,uid);rel(sid,"REFERENCES",eu,rid,uid)
        for num in dict.fromkeys(FORM.findall(body)):
            val=f"Mẫu {num}";rid=entity(sid,"form_reference",num,val,uid)
            rel(sid,"MENTIONS",eu,rid,uid)
        if u["unit_kind"]=="criterion_table_candidate":
            rid=entity(sid,"criterion_table_candidate",uid,"Bảng tiêu chí — trang "+str(u["spans"][0]["pdf_page"]),uid)
            rel(sid,"HAS_CRITERION_CANDIDATE",eu,rid,uid)
        # Static topic mention candidates; no external entity-linking assumptions.
        for term,typ in TERMS.items():
            if term in body.casefold():
                rid=entity(sid,"topic",typ,term,uid)
                rel(sid,"MENTIONS",eu,rid,uid)
    return list(entities.values()),list(relations.values())


def extract_artifacts(root:Path,*,input_dir:Path,output_dir:Path,max_pages:int|None=None,
                      semantic_client=None, semantic_max_units:int=50)->dict:
    manifest=json.loads((input_dir/"manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("complete") and max_pages is None:
        raise RuntimeError("PDF PageArtifact manifest not complete")
    source_info={s.source_id:s.model_dump(mode="json") for s in load_registry(root/"configs/ocop_sources.json")}
    snapshot=manifest["input_snapshot_sha256"]
    semantic_profile = ("none" if semantic_client is None else f"{semantic_client.model}:{semantic_max_units}")
    version=hashlib.sha256((VERSION+"|"+snapshot+"|"+semantic_profile).encode()).hexdigest()[:20]
    output_dir.mkdir(parents=True,exist_ok=True)
    units_file=output_dir/"evidence_units.jsonl";facts_file=output_dir/"domain_facts.jsonl"
    entities_file=output_dir/"entities.jsonl";relations_file=output_dir/"relations.jsonl"
    files_by_source={s["source_id"]:input_dir/s["artifact"] for s in manifest["sources"]}
    counts=Counter();all_units=[];facts=[]
    stop=False
    for sid in sorted(files_by_source):
        path=files_by_source[sid]
        with path.open(encoding="utf-8") as f:
            for line in f:
                if max_pages is not None and counts["pages"]>=max_pages:
                    stop=True;break
                page=json.loads(line)
                if page["source_id"]!=sid:
                    raise ValueError("PageArtifact source mismatch")
                generated=page_units(page,source_kind=source_info[sid]["source_kind"])
                all_units.extend(generated)
                counts["pages"]+=1
                counts["tables"]+=len(page.get("tables",[]))
                counts["units"]+=len(generated)
                counts["ocr_pages"]+=int(bool(page.get("ocr_engine")))
                for u in generated:
                    if u["unit_kind"] in ("form","article","annex","criterion_table_candidate"):
                        facts.append({"fact_id":stable_id("fact",sid,[u["unit_id"]]),
                          "fact_type":u["unit_kind"],"evidence_unit_id":u["unit_id"],
                          "source_id":sid,"text":u["text"][:3000],
                          "review_status":u["review_status"],"spans":u["spans"],
                          "structured":{k:v for k,v in u["structured"].items() if k!="cells"}})
        if stop:break
    domain_candidates=candidates(all_units,{sid:row["source_kind"] for sid,row in source_info.items()})
    domain_candidates["temporal_candidates"]=temporal_candidates(all_units)
    semantics=extract_semantics(all_units,{sid:row["source_kind"] for sid,row in source_info.items()},domain_candidates)
    llm_stats={"enabled":semantic_client is not None, "model":semantic_profile, "processed_unit_count":0, "errors":0}
    if semantic_client is not None:
        proposed=propose(all_units,semantic_client,max_units=semantic_max_units)
        for category,name in (("entities","business_entities"),("relations","business_relations"),("rules","business_rules")):
            semantics[name]=sorted(semantics[name]+proposed[category],key=lambda row: next((row[k] for k in ("entity_id","relation_id","rule_id") if k in row),""))
        llm_stats["processed_unit_count"]=proposed["processed_unit_count"]
        llm_stats["errors"]=len(proposed["errors"])
        semantics["business_llm_errors"]=proposed["errors"]
    # Validate the combined graph, including any opt-in LLM proposals; isolated
    # validation per extractor is insufficient once datasets are merged.
    validate_business_graph(
        [BusinessEntity.model_validate(row) for row in semantics['business_entities']],
        [BusinessRelation.model_validate(row) for row in semantics['business_relations']],
    )
    quality = audit_knowledge(all_units,semantics)
    quality_tmp=output_dir/'business_quality.json.tmp'
    quality_tmp.write_text(json.dumps(quality,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    os.replace(quality_tmp,output_dir/'business_quality.json')
    ents,rels=extract_entities_relations(all_units,source_info)
    counts["facts"]=len(facts);counts["entities"]=len(ents);counts["relations"]=len(rels)
    counts.update({key:len(values) for key,values in domain_candidates.items()})
    for path,data in ((units_file,all_units),(facts_file,facts),(entities_file,ents),(relations_file,rels)):
        _jsonl_atomic(path,data)
    for name,items in domain_candidates.items():
        _jsonl_atomic(output_dir/f"{name}.jsonl",items)
    for name,items in semantics.items():
        counts[name]=_jsonl_atomic(output_dir/f"{name}.jsonl",items)
    summary={"pipeline_version":VERSION,"corpus_version":version,"semantic_proposals":llm_stats,"source_snapshot_sha256":snapshot,
        "counts":dict(sorted(counts.items())),"business_quality":"business_quality.json","complete":(not stop and counts["pages"]==manifest["counts"]["pages"]),
        "status":"machine_extracted_not_verified","files":{
            "evidence_units":units_file.name,"domain_facts":facts_file.name,
            "entities":entities_file.name,"relations":relations_file.name,
            **{name:f"{name}.jsonl" for name in domain_candidates},
            **{name:f"{name}.jsonl" for name in semantics}}}
    tmp=output_dir/"manifest.tmp"
    tmp.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,output_dir/"manifest.json")
    return summary


def main():
    ap=argparse.ArgumentParser(description="evidence extraction: extract OCOP evidence and graph candidates from page artifacts")
    ap.add_argument("--root",type=Path,default=ROOT)
    ap.add_argument("--input",type=Path,default=Path("data/processed/ocop/pages"))
    ap.add_argument("--output",type=Path,default=Path("data/processed/ocop/knowledge"))
    ap.add_argument("--max-pages",type=int)
    args=ap.parse_args()
    root=args.root.resolve()
    local=lambda p: p if p.is_absolute() else root/p
    result=extract_artifacts(root,input_dir=local(args.input),output_dir=local(args.output),max_pages=args.max_pages)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
