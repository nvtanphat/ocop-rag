"""PaddleOCR PP-StructureV3 adapter with lossless HTML row/col/merge metadata.

Table cells without explicit pixel coordinates retain bbox=None; never fabricate
positions. All extracted score options are NEEDS_REVIEW until verified against PDF.
"""
from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
from typing import Any


class _TableHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[]
        self.current_row=None
        self.cell=None
        self.parts=[]

    @staticmethod
    def _span(attrs, key):
        raw=attrs.get(key,"1")
        try:
            span=int(raw)
        except (TypeError,ValueError) as exc:
            raise ValueError(f"invalid_table_{key}_span") from exc
        if not 1 <= span <= 64:
            raise ValueError(f"invalid_table_{key}_span")
        return span

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ("br","p","div","li") and self.cell is not None:
            self.parts.append(" ")
        if tag=="tr":
            self.current_row=[]
        elif tag in ("td","th") and self.current_row is not None:
            self.cell={"rowspan":self._span(attrs,"rowspan"),
                       "colspan":self._span(attrs,"colspan"),
                       "header":tag=="th"}
            self.parts=[]

    def handle_data(self,data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.cell["text"]=" ".join("".join(self.parts).split())
            self.current_row.append(self.cell)
            self.cell=None
        elif tag=="tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row=None


def parse_html_cells(html:str)->tuple[list[dict],int,int]:
    p=_TableHTML();p.feed(html)
    if len(p.rows)>500:
        raise ValueError("table_row_limit_exceeded")
    occupancy=set();cells=[];max_col=0
    for r,row in enumerate(p.rows):
        col=0
        for raw in row:
            while (r,col) in occupancy:
                col+=1
            rs=raw["rowspan"];cs=raw["colspan"]
            if r+rs>len(p.rows):
                raise ValueError("table_rowspan_outside_table")
            if col+cs>128:
                raise ValueError("table_column_span_limit_exceeded")
            for rr in range(r,r+rs):
                for cc in range(col,col+cs):
                    if (rr,cc) in occupancy:
                        raise ValueError("table_cell_span_overlap")
                    occupancy.add((rr,cc))
            cells.append({"row":r,"col":col,"rowspan":rs,"colspan":cs,
                          "bbox":None,"text":raw["text"],"is_header":raw["header"],
                          "merged_extent_unknown":False,"review_status":"needs_review"})
            max_col=max(max_col,col+cs);col+=cs
    return cells,len(p.rows),max_col


@lru_cache(maxsize=1)
def _get_model():
    from paddleocr import PPStructureV3
    return PPStructureV3()


def ppstructure_tables(image, page, model:Any=None):
    if model is None:
        model=_get_model()
    import numpy as np
    if not hasattr(model,"predict"):
        raise RuntimeError("PPStructureV3.predict not available; check pinned PaddleOCR 3.x")
    w,h=image.size
    out=[]
    for item in model.predict(np.asarray(image.convert("RGB"))):
        j=getattr(item,"json",item)
        if callable(j):
            j=j()
        if not isinstance(j,dict):
            raise RuntimeError("unsupported PPStructureV3 output format")
        root=j.get("res",j)
        if not isinstance(root,dict):
            raise RuntimeError("unsupported PPStructureV3 res payload")
        for tbl in root.get("table_res_list",[]):
            if not isinstance(tbl,dict):
                continue
            bbox=tbl.get("table_region_bbox") or tbl.get("bbox")
            if bbox is None:
                continue
            a=[float(x) for x in np.asarray(bbox).reshape(-1)]
            if len(a)!=4:
                continue
            a=[round(a[0]/w*page.rect.width,2),round(a[1]/h*page.rect.height,2),
               round(a[2]/w*page.rect.width,2),round(a[3]/h*page.rect.height,2)]
            html=str(tbl.get("pred_html") or tbl.get("html") or "")
            cells,rows,cols=parse_html_cells(html)
            cell_boxes=tbl.get("cell_box_list") or []
            if len(cell_boxes)==len(cells):
                for cell,box in zip(cells,cell_boxes):
                    pix=[float(x) for x in np.asarray(box).reshape(-1)]
                    if len(pix)==4:
                        cell["bbox"]=[round(pix[0]/w*page.rect.width,2),
                                      round(pix[1]/h*page.rect.height,2),
                                      round(pix[2]/w*page.rect.width,2),
                                      round(pix[3]/h*page.rect.height,2)]
            out.append({"table_id":f"table:ppstructure:{len(out)}","method":"ppstructurev3",
                        "bbox":a,"row_count":rows or None,"col_count":cols or None,"cells":cells,
                        "html":html,"review_status":"needs_review",
                        "warnings":["ppstructure_html_needs_source_verification",
                                    "missing_individual_cell_boxes" if cells and not all(c['bbox'] for c in cells)
                                    else "review_scores_and_asterisks"]})
    return out
