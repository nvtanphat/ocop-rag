"""Conservative cross-page table candidate linking, never automatic score merging."""
from __future__ import annotations


def possible_continuations(previous:dict,current:dict,*,min_columns:int=3)->list[dict]:
    if previous["source_id"] != current["source_id"]:
        return []
    if current["pdf_page"] != previous["pdf_page"] + 1:
        return []
    links=[]
    for pt in previous.get("tables",[]):
        for ct in current.get("tables",[]):
            if not pt.get("bbox") or not ct.get("bbox"):
                continue
            if pt["bbox"][3] < previous["height_pt"]*.82:
                continue
            if ct["bbox"][1] > current["height_pt"]*.25:
                continue
            pcols=pt.get("col_count");ccols=ct.get("col_count")
            # Unknown column counts make accidental cross-page links common.
            # Prefer no link over an unsupported connection.
            if (not pcols or not ccols or pcols<min_columns or ccols<min_columns
                or (pt.get("row_count") or 0)<3 or (ct.get("row_count") or 0)<3
                or abs(pcols-ccols)>1):
                continue
            links.append({"source_id":current["source_id"],
                          "from_pdf_page":previous["pdf_page"],
                          "to_pdf_page":current["pdf_page"],
                          "from_table_id":pt["table_id"],"to_table_id":ct["table_id"],
                          "status":"needs_review","reason":"adjacent_page_boundary_table_candidate"})
    return links
