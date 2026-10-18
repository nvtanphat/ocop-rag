"""Native PDF table extraction plus conservative OpenCV raster grid detection.

Never infer a scoring option or fix an ambiguous merged cell. Raster cell
segmentation is candidate-only and must be reviewed against the source PDF.
"""
from __future__ import annotations

import numpy as np


def _bbox(rect):
    return [round(float(v), 2) for v in rect]


def native_tables(page) -> list[dict]:
    tables = []
    if not hasattr(page, "find_tables"):
        return tables
    try:
        finder=page.find_tables()
    except (RuntimeError, ValueError, TypeError):
        return tables
    for ix, table in enumerate(finder.tables):
        matrix = table.extract() or []
        cells = []
        # PyMuPDF's table.cells is column-major. Using r*col_count+c here
        # wrongly associates the bounding boxes with text in another column.
        # table.rows[r].cells[c] is indexed in the SAME order as extract().
        rows = [row.cells for row in table.rows]
        # Table.rows slots are keyed by the sorted unique cell left edges.
        # A None slot covered by a preceding owner's extent is a colspan.
        column_starts = sorted({box[0] for row in rows for box in row if box is not None})
        row_starts = []
        for row in rows:
            boxes = [box for box in row if box is not None]
            row_starts.append(min(box[1] for box in boxes) if boxes else None)
        for r in range(table.row_count):
            for c in range(table.col_count):
                box = rows[r][c] if r < len(rows) and c < len(rows[r]) else None
                if box is None:  # covered by a merged cell, not a blank owner
                    continue
                value = matrix[r][c] if r < len(matrix) and c < len(matrix[r]) else None
                # A native table rowspan is geometrically observable: a cell
                # from row r extends into one or more following row bands.
                covers = 1
                for j in range(r + 1, len(rows)):
                    if row_starts[j] is None or box[3] <= row_starts[j] + 1.0:
                        break
                    if c < len(rows[j]) and rows[j][c] is not None:
                        break
                    covers += 1
                colspan = 1
                for j in range(c + 1, min(len(column_starts), len(rows[r]))):
                    if column_starts[j] >= box[2] - 1.0 or rows[r][j] is not None:
                        break
                    colspan += 1
                cells.append({"row":r,"col":c,"bbox":_bbox(box),"text":value or "",
                              "rowspan":covers,"colspan":colspan,"merged_extent_unknown":False,
                              "review_status":"needs_review"})
        tables.append({"table_id":f"table:native:{ix}", "method":"native_fitz",
                       "bbox":_bbox(table.bbox),"row_count":table.row_count,
                       "col_count":table.col_count, "cells":cells,"review_status":"needs_review"})
    return tables


def _line_centers(projection: np.ndarray, min_count: int) -> list[int]:
    ids=np.flatnonzero(projection>=min_count)
    groups=[]
    for x in ids:
        if not groups or x>groups[-1][-1]+2:
            groups.append([int(x)])
        else:
            groups[-1].append(int(x))
    return [int(np.median(g)) for g in groups]


def _merge_nearby(values: list[int], distance: int) -> list[int]:
    """Fuse multiple pixel edges of one PDF ruling without collapsing rows."""
    out=[]
    for value in sorted(values):
        if out and value - out[-1][-1] <= distance:
            out[-1].append(value)
        else:
            out.append([value])
    return [int(np.median(group)) for group in out]


def raster_tables(image, page, blocks: list[dict], *, min_cells: int=4) -> list[dict]:
    """Detect ruled grids from full raster; report table candidates for review.

    Works without a trained table model, including offline Windows laptops.
    Complex colspan/rowspan is *not* inferred when rule segments are missing.
    """
    import cv2
    cv2.setNumThreads(1)
    rgb=np.asarray(image.convert("RGB"))
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    hh,ww=gray.shape
    if min(hh,ww)<120:
        return []
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV,25,12)
    h_kernel=cv2.getStructuringElement(cv2.MORPH_RECT,(max(24,ww//55),1))
    v_kernel=cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(24,hh//70)))
    hlines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,h_kernel)
    vlines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,v_kernel)
    joined=cv2.dilate(cv2.bitwise_or(hlines,vlines),np.ones((3,3),dtype=np.uint8))
    n,_,stats,_=cv2.connectedComponentsWithStats(joined)
    candidates=[]
    for i in range(1,n):
        x,y,w,h,area=map(int,stats[i])
        if w < ww*0.24 or h < hh*0.035 or area < 400:
            continue
        # Restrict to region: expensive grid inference on a whole page may create false cells.
        subh=hlines[y:y+h,x:x+w]
        subv=vlines[y:y+h,x:x+w]
        # Use *regional* support. Real OCOP scoring columns are narrow and
        # vertical rulings break at merged rows: .45 was losing the entire
        # two-column table in QD26/2026 page 28.
        xs=_merge_nearby(_line_centers((subv>0).sum(axis=0),max(12,int(h*.12))),max(11,ww//90))
        ys=_merge_nearby(_line_centers((subh>0).sum(axis=1),max(12,int(w*.16))),max(5,hh//260))
        if len(xs)<3 or len(ys)<3 or (len(xs)-1)*(len(ys)-1)<min_cells:
            continue
        if len(xs)>70 or len(ys)>160:
            continue
        cells=[]
        for row,(a,b) in enumerate(zip(ys,ys[1:])):
            for col,(left,right) in enumerate(zip(xs,xs[1:])):
                if right-left<8 or b-a<8:
                    continue
                # Check border connectivity; missing grid segment may indicate merged cell.
                lh = np.count_nonzero(subh[a,max(0,left):right+1])/max(right-left+1,1)
                rh = np.count_nonzero(subh[b,max(0,left):right+1])/max(right-left+1,1)
                lv = np.count_nonzero(subv[a:b+1,left])/max(b-a+1,1)
                rv = np.count_nonzero(subv[a:b+1,right])/max(b-a+1,1)
                uncertain=min(lh,rh,lv,rv)<.5
                # Coordinates mapping; preserve raw OCR text in source block in addition to cell snippets.
                x0,y0,x1,y1=x+left,y+a,x+right,y+b
                pdfbox=[x0/ww*page.rect.width,y0/hh*page.rect.height,
                        x1/ww*page.rect.width,y1/hh*page.rect.height]
                snippets=[]
                for blk in blocks:
                    bb=blk["bbox"]
                    mx,my=(bb[0]+bb[2])/2,(bb[1]+bb[3])/2
                    if pdfbox[0]<=mx<=pdfbox[2] and pdfbox[1]<=my<=pdfbox[3]:
                        snippets.append(blk["text"])
                cells.append({"row":row,"col":col,"bbox":_bbox(pdfbox),
                              "text":" ".join(snippets),"merged_extent_unknown":bool(uncertain),
                              "review_status":"needs_review"})
        if len(cells)<min_cells:
            continue
        tablebox=[(x+xs[0])/ww*page.rect.width,(y+ys[0])/hh*page.rect.height,
                  (x+xs[-1])/ww*page.rect.width,(y+ys[-1])/hh*page.rect.height]
        candidates.append({"table_id":f"table:raster:{len(candidates)}", "method":"opencv_grid_candidate",
                           "bbox":_bbox(tablebox),"row_count":len(ys)-1,"col_count":len(xs)-1,
                           "cells":cells,"review_status":"needs_review",
                           "warnings":["grid_cells_are_candidates_only","review_merged_cells_and_asterisks"],
                           "extraction_quality":{"observed_row_rules":len(ys),
                             "observed_column_rules":len(xs),
                             "bbox_method":"detected_pixel_rulings"}})
    if not candidates:
        # OCR tables often have *horizontal ruling only*, with columns separated
        # by whitespace. Keep a table REGION candidate rather than invent cells.
        long_lines=[]
        for yy in range(hh):
            line=hlines[yy]
            pts=np.flatnonzero(line>0)
            if len(pts)>=ww*.42:
                long_lines.append((yy,int(pts[0]),int(pts[-1])))
        bands=[]
        for yi,x0,x1 in long_lines:
            if bands and yi-bands[-1][-1][0]<=4:
                bands[-1].append((yi,x0,x1))
            else:
                bands.append([(yi,x0,x1)])
        representative=[(int(np.median([q[0] for q in b])),min(q[1] for q in b),max(q[2] for q in b)) for b in bands]
        # >= 5 row rules is a useful recall-first signal; never claim cells.
        if len(representative)>=5:
            y0=representative[0][0]
            y1=representative[-1][0]
            if y1-y0>hh*.06:
                x0=min(t[1] for t in representative)
                x1=max(t[2] for t in representative)
                # Recover the scoring column from *partial* vertical rulings.
                # This handles merged-cell tables where no connected component
                # includes more than a few horizontal rules. Never infer spans.
                sub_v=vlines[y0:y1+1,x0:x1+1]
                v_support=max(12,int((y1-y0)*.12))
                xlines=_merge_nearby(_line_centers((sub_v>0).sum(axis=0),v_support),
                                     max(11,ww//90))
                if len(xlines)>=3 and len(xlines)<=15:
                    cells=[]
                    for row,(top,bottom) in enumerate(zip(representative,representative[1:])):
                        ya,yb=top[0],bottom[0]
                        if yb-ya<8:
                            continue
                        for col,(a,b) in enumerate(zip(xlines,xlines[1:])):
                            if b-a<8:
                                continue
                            box=[(x0+a)/ww*page.rect.width,ya/hh*page.rect.height,
                                 (x0+b)/ww*page.rect.width,yb/hh*page.rect.height]
                            snippets=[]
                            for word in blocks:
                                wb=word['bbox']
                                mx,my=(wb[0]+wb[2])/2,(wb[1]+wb[3])/2
                                if box[0]<=mx<=box[2] and box[1]<=my<=box[3]:
                                    snippets.append(str(word['text']))
                            cells.append({'row':row,'col':col,'bbox':_bbox(box),
                                'text':' '.join(snippets),'merged_extent_unknown':True,
                                'review_status':'needs_review'})
                    if len(cells)>=min_cells:
                        candidates.append({'table_id':'table:raster:partial_grid:0',
                            'method':'opencv_partial_grid_candidate',
                            'bbox':_bbox([(x0+xlines[0])/ww*page.rect.width,
                                y0/hh*page.rect.height,(x0+xlines[-1])/ww*page.rect.width,
                                y1/hh*page.rect.height]),
                            'row_count':len(representative)-1,'col_count':len(xlines)-1,
                            'cells':cells,'review_status':'needs_review',
                            'warnings':['partial_grid_merges_unresolved','verify_scores_and_asterisks']})
                if not candidates:
                    candidates.append({"table_id":"table:raster:unruled:0",
                  "method":"opencv_horizontal_rulings_candidate",
                  "bbox":_bbox([x0/ww*page.rect.width,y0/hh*page.rect.height,
                                x1/ww*page.rect.width,y1/hh*page.rect.height]),
                  "row_count":len(representative)-1,"col_count":None,
                  "cells":[],"review_status":"needs_review",
                  "warnings":["columns_not_inferred","table_area_candidate_only", "review_scoring_options_from_pdf"]})
    # Prefer larger candidate first; candidate is never an official parsed table.
    candidates.sort(key=lambda t: (t["bbox"][2]-t["bbox"][0])*(t["bbox"][3]-t["bbox"][1]),reverse=True)
    return candidates
