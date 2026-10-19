"""Small source-citation helpers shared by extraction and graph materialization."""
from __future__ import annotations

import re


def union_bbox(rectangles: list[list[float] | tuple[float, ...]]) -> tuple[float, float, float, float] | None:
    valid=[r for r in rectangles if r and len(r)==4]
    if not valid:
        return None
    return (min(float(r[0]) for r in valid),min(float(r[1]) for r in valid),
            max(float(r[2]) for r in valid),max(float(r[3]) for r in valid))


def quote_bbox(unit: dict, page: int, quote: str) -> tuple[float, float, float, float] | None:
    """Map a literal quote to its line spans; fall back to the full unit extent."""
    text=str(unit.get("text") or "")
    spans=[s for s in unit.get("spans",[]) if int(s.get("pdf_page",-1))==int(page)]
    if not spans:
        return None
    lines=text.splitlines()
    positions=[m.span() for m in re.finditer(re.escape(quote),text)] if quote else []
    geometry=unit.get('structured',{}).get('quote_lines',[])
    if (positions and len(geometry)==len(lines) and
        all(g.get('text')==line and g.get('pdf_page')==page and g.get('bbox')
            for g,line in zip(geometry,lines))):
        indexes=set()
        for start,end in positions:
            indexes.update(range(text.count('\n',0,start),text.count('\n',0,max(start,end-1))+1))
        return union_bbox([geometry[i]['bbox'] for i in sorted(indexes)])
    if (positions and len(spans)==len(lines) and
        all(s.get("bbox") is not None and s.get("block_id") for s in spans)):
        indexes=set()
        for start,end in positions:
            first=text.count("\n",0,start)
            last=text.count("\n",0,max(start,end-1))
            indexes.update(range(first,last+1))
        if indexes and max(indexes)<len(spans):
            return union_bbox([spans[i]["bbox"] for i in sorted(indexes)])
    return union_bbox([s.get("bbox") for s in spans])


def row_quote_bbox(unit: dict, row: int) -> tuple[str, tuple[float, float, float, float] | None] | None:
    cells=[c for c in unit.get("structured",{}).get("cells",[])
           if int(c.get("row",-1))==int(row)]
    if not cells:
        return None
    quote=" | ".join(str(c.get("text") or "").strip()
                     for c in sorted(cells,key=lambda c:int(c.get("col",0)))
                     if str(c.get("text") or "").strip())
    bbox=union_bbox([c.get("bbox") for c in cells])
    return quote,bbox


def cell_at(unit: dict, row: int, col: int) -> dict | None:
    cells=[c for c in unit.get("structured",{}).get("cells",[])
           if int(c.get("row",-1))==int(row) and int(c.get("col",-1))==int(col)]
    return cells[0] if len(cells)==1 else None


def bbox_matches(left, right, *, tolerance: float = 0.01) -> bool:
    if left is None or right is None or len(left)!=4 or len(right)!=4:
        return False
    try:
        return all(abs(float(a)-float(b))<=tolerance for a,b in zip(left,right))
    except (TypeError,ValueError):
        return False
