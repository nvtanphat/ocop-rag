"""Domain candidate extraction from OCOP evidence units.

Prototype only: these are machine-extracted row/form/recognition candidates and
are NOT eligible for automatic legal scoring without a later validation gate.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from ai_core.domain.ocop_ids import stable_id

FORM_HEADER=re.compile(r"\bM[ẫâ]u\s*(?:s[ốo])?\s*0?([1-3])\b",re.I)
AMOUNT=re.compile(r"(?<!\d)(\d{1,3})(?:[,.]0+)?\s*(?:điểm)?\s*$",re.I)
STARS=re.compile(r"(?<!\d)([1-5])\s*sao\b",re.I)


def _row_text(cells: list[dict])->list[dict]:
    """Return literal cells and geometry-supported merged-cell references.

    A rowspan is accepted ONLY when the native/layout engine explicitly
    recorded it. Empty cells without merge geometry remain unknown.
    """
    rows=defaultdict(list)
    for cell in cells:
        if cell.get("text") is not None:
            rows[int(cell.get("row",0))].append(cell)
    resolved={}
    for row_no, members in sorted(rows.items()):
        for cell in sorted(members,key=lambda c:int(c.get("col",0))):
            col=int(cell.get("col",0))
            resolved[(row_no,col)]={"text":str(cell.get("text") or "").strip(),
                "row":row_no,"col":col,"inherited":False,"bbox":cell.get("bbox")}
            span=int(cell.get("rowspan") or 1)
            if span>1 and not cell.get("merged_extent_unknown") and str(cell.get("text") or "").strip():
                for future in range(row_no+1,row_no+span):
                    if (future,col) not in resolved:
                        resolved[(future,col)]={"text":str(cell["text"]).strip(),
                            "row":row_no,"col":col,"inherited":True,"bbox":cell.get("bbox")}
    result=[]
    for row_no,members in sorted(rows.items()):
        cells_here=sorted(members,key=lambda c:int(c.get("col",0)))
        original=" | ".join(str(c.get("text") or "").strip() for c in cells_here if str(c.get("text") or "").strip())
        result.append({"row":row_no,"cells":cells_here,"text":original,
            "resolved_columns":{str(k[1]):v for k,v in resolved.items() if k[0]==row_no}})
    return result


def candidates(units:list[dict],source_kinds:dict[str,str])->dict[str,list[dict]]:
    out={"criterion_candidates":[],"form_candidates":[],"recognition_candidates":[],"taxonomy_candidates":[]}
    seen_forms=set()
    for unit in units:
        sid=unit["source_id"];uid=unit["unit_id"];kind=source_kinds.get(sid,"")
        page=unit["spans"][0]["pdf_page"]
        if kind=="ocop_framework" and unit["unit_kind"]=="form":
            m=FORM_HEADER.search(unit["text"][:140]);key=(sid,m.group(1)) if m else (sid,uid)
            if key not in seen_forms:
                seen_forms.add(key)
                lines=[line.strip() for line in unit["text"].splitlines() if line.strip()]
                out["form_candidates"].append({"candidate_id":stable_id("form_candidate",sid,[str(key[1])]),
                      "source_id":sid,"evidence_unit_id":uid,"pdf_page":page,
                      "form_number":int(m.group(1)) if m else None,"title":lines[0][:240] if lines else "",
                      "fields_candidate":[x[:220] for x in lines[1:] if x.endswith(":") or ":" in x][:35],
                      "review_status":"needs_review"})
        if kind in ("ocop_framework","ocop_historical","ocop_amendment") and unit["unit_kind"]=="annex":
            out["taxonomy_candidates"].append({"candidate_id":stable_id("tax_candidate",sid,[uid]),
                "source_id":sid,"evidence_unit_id":uid,"pdf_page":page,
                "heading":unit["text"].splitlines()[0][:220],"review_status":"needs_review"})
        if unit["unit_kind"] not in ("criterion_table_candidate","table"):
            continue
        rows=_row_text(unit.get("structured",{}).get("cells",[]))
        if kind in ("ocop_framework","ocop_historical","ocop_amendment"):
            for row in rows:
                if not row["text"]:continue
                vals=[str(x.get("text") or "").strip() for x in row["cells"]]
                score=None
                # Read numeric score only if the last cell has a single obvious number.
                if vals:
                    m=AMOUNT.fullmatch(vals[-1])
                    if m and int(m.group(1))<=100:score=int(m.group(1))
                last_column=max((int(c.get('col',0)) for c in row['cells']),default=0)
                cropped_options=[opt for c in row["cells"] if int(c.get("col",-1))==last_column
                                 for opt in c.get("score_ocr_candidates",[])]
                # Keep crop OCR as an *alternative*, never promote it to the canonical score.
                candidate_score=max(cropped_options,key=lambda x:x.get("confidence",0)) if cropped_options else None
                out["criterion_candidates"].append({
                    "candidate_id":stable_id("criterion_candidate",sid,[uid,row["row"]]),
                    "source_id":sid,"evidence_unit_id":uid,"pdf_page":page,
                    "table_id":unit["structured"].get("table_id"),"row":row["row"],
                    "label_candidate":row["text"][:700],"score_candidate":score,
                    "crop_score_candidate":candidate_score,
                    "review_status":"needs_review"})
        elif kind=="recognition_decision":
            for row in rows:
                if not row["text"]:continue
                match=STARS.search(row["text"])
                out["recognition_candidates"].append({"candidate_id":stable_id("recognition_candidate",sid,[uid,row["row"]]),
                    "source_id":sid,"evidence_unit_id":uid,"pdf_page":page,
                    "row_text":row["text"][:1200],
                    "resolved_columns":row["resolved_columns"],
                    "row":row["row"],"table_id":unit["structured"].get("table_id"),"star_candidate":int(match.group(1)) if match else None,
                    "review_status":"needs_review"})
    return out
