"""Deterministic, structure-preserving child passages for OCOP sources.

No LLM-generated legal context or invented cells. Text offsets refer to the original
EvidenceUnit.text. Table row/cell coordinates are inherited from extracted source
structures, not guessed PDF positions. When a single row exceeds its budget it is
kept intact and explicitly marked over-budget (dense indexing must fail closed).

Without a local model tokenizer, token counts are *conservative estimates*, not
assertions about any specific embedding vocabulary. Real dense indexing separately
validates exact token lengths with the actual model tokenizer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from ai_core.domain.ocop_models import cell_display_text

TokenCount = Callable[[str], int]
LEGAL_HEADING = re.compile(r"^(?:Điều\s+\d+|Mẫu\s+(?:số\s+)?\d+|Phụ\s+lục\b|Chương\s+[IVX0-9]+|Mục\s+\d+)", re.I)
WORD = re.compile(r"\S+", re.UNICODE)
CLAUSE_START = re.compile(
    r"(?m)^[ \t]*(?:\d{1,2}[.)]|[A-Za-z\u00c0-\u024f][.)]|\(\d+\)|[\u2013\u2014-])[ \t]+"
)
_HEADER_CUES = (
    "stt", "tt", "số thứ tự", "tên sản phẩm", "tên chủ thể", "tổ chức/cá nhân",
    "địa chỉ", "điểm đánh giá", "điểm tối đa", "xếp loại", "phân hạng", "tiêu chí",
    "nội dung", "chỉ tiêu", "yêu cầu", "đánh giá", "loại hàng hóa",
    "tên nhóm hàng hóa", "mặt hàng", "cách ghi", "trường hợp",
    "cơ sở sản xuất kinh doanh", "mã số", "số, ký hiệu", "đơn vị đo", "cách thể hiện",
)


def estimated_tokens(s: str) -> int:
    """Deliberately conservative Unicode-aware *estimate*; not HF tokenization."""
    if not s:
        return 0
    # Conservative: Vietnamese subwords often require more than whitespace words.
    return max(len(s.split()), math.ceil(len(s.encode('utf-8')) / 5))


@dataclass(frozen=True)
class ChildPart:
    raw_text: str
    text: str
    char_start: int | None = None
    char_end: int | None = None
    row_ids: tuple[int, ...] = ()
    spans: tuple[dict, ...] = ()
    table_headers: tuple[str, ...] = ()
    heading: str | None = None
    over_budget: bool = False
    token_count: int = 0
    header_inferred: bool = False


def _legal_heading(unit: dict, source: str) -> str | None:
    structure = unit.get('structured') or {}
    inherited=str(structure.get('legal_heading') or '').strip()
    if (structure.get('legal_heading_origin')=='same_page_previous_segment'
            and LEGAL_HEADING.match(inherited)):
        return inherited[:180]
    raw = str(structure.get('heading') or '').strip()
    first = (source.splitlines() or [''])[0].strip()
    if LEGAL_HEADING.match(raw) and (raw in source or raw[:120] in source):
        return raw[:180]
    if LEGAL_HEADING.match(first):
        return first[:180] if len(first) <= 180 else first[:180].rsplit(' ', 1)[0]
    return None


def _base(unit: dict, meta: dict | None = None) -> str:
    span = (unit.get('spans') or [{'pdf_page': '?'}])[0]
    data = [f"Nguồn: {unit['source_id']}", f"trang PDF: {span['pdf_page']}",
            f"loại: {unit.get('unit_kind', 'unknown')}"]
    meta = meta or {}
    if meta.get('document_number'):
        data.append(f"văn bản: {meta['document_number']}")
    if meta.get('jurisdiction'):
        data.append(f"địa bàn: {meta['jurisdiction']}")
    return '; '.join(data) + '. '


def _plan_prose(unit: dict, *, max_words: int, overlap: int, budget: int,
                count: TokenCount, meta: dict | None) -> list[ChildPart]:
    source = unit['text']
    heading = _legal_heading(unit, source)
    prefix = _base(unit, meta)
    if heading:
        prefix += f"Ngữ cảnh cấu trúc: {heading}.\n"
    words = list(WORD.finditer(source))
    if not words:
        return []
    structural_starts={
        match.start()+len(match.group(0))-len(match.group(0).lstrip())
        for match in CLAUSE_START.finditer(source)
    }
    result=[]
    start=0
    while start<len(words):
        last=start
        # Never silently drop a single oversized Unicode token.
        for pos in range(start, min(len(words), start+max_words)):
            raw=source[words[start].start():words[pos].end()]
            projected=prefix+raw
            if pos>start and count(projected)>budget:
                break
            last=pos
            if count(projected)>budget:
                break
        # Prefer a legal clause/point boundary near the budget. Such a boundary
        # is a clean continuation point, so the next chunk need not overlap it.
        hard_boundary=False
        if last>start+3 and last<len(words)-1:
            threshold=start+max(1,int((last-start)*.65))
            for pos in range(last,threshold,-1):
                if words[pos].start() in structural_starts:
                    last=pos-1
                    hard_boundary=True
                    break
        if (not hard_boundary and last+1<len(words) and
                words[last+1].start() in structural_starts):
            hard_boundary=True
        # If no legal boundary fits, prefer a source line or sentence boundary.
        if last>start+3 and last<len(words)-1:
            threshold=start+max(1,int((last-start)*.65))
            if not hard_boundary:
                for pos in range(last,threshold-1,-1):
                    between=source[words[pos].end():words[pos+1].start()]
                    tail=words[pos].group()
                    if '\n' in between or tail.endswith(('.', '!', '?', ';', ':')):
                        last=pos
                        break
        a=words[start].start();b=words[last].end()
        raw=source[a:b]
        text=prefix+raw
        result.append(ChildPart(raw_text=raw,text=text,char_start=a,char_end=b,
                                heading=heading,token_count=count(text),over_budget=count(text)>budget))
        if last==len(words)-1:
            break
        nxt=last+1 if hard_boundary else max(start+1,last+1-overlap)
        start=nxt
    return result


def _table_data(unit: dict) -> tuple[str,list[tuple[int,str,list[dict]]],tuple[str,...],bool,tuple[int,...]]:
    source=unit['text']
    table=(unit.get('structured') or {})
    cells=table.get('cells') or []
    rows=[]
    if cells:
        grouped={}
        for c in cells:
            grouped.setdefault(int(c.get('row',0)),[]).append(c)
        for row_id, row_cells in sorted(grouped.items()):
            row_cells.sort(key=lambda c:int(c.get('col',0)))
            raw=' | '.join(cell_display_text(c) for c in row_cells)
            rows.append((row_id,raw,row_cells))
    else:
        for i,line in enumerate(source.splitlines()):
            if line.strip():
                rows.append((i,line.strip(),[]))
    if not rows:
        return '',[],(),False,()
    explicit_headers=tuple(r for rid,r,cs in rows if cs and any(c.get('is_header') or c.get('header') for c in cs))
    if explicit_headers:
        header_rows={rid for rid,r,cs in rows if cs and any(c.get('is_header') or c.get('header') for c in cs)}
        inferred=False
    elif len(rows)>1:
        # Table parsers may omit header flags, split header text across lines,
        # or include a title/preface row before the actual columns. Search only
        # the first few rows and require multiple independent column cues.
        candidates=[]
        for row_id,row_text,row_cells in rows[:3]:
            header_values=(
                [re.sub(r"\s+"," ",cell_display_text(c)).strip().casefold() for c in row_cells]
                if row_cells else
                [re.sub(r"\s+"," ",part).strip().casefold() for part in row_text.split("|")]
            )
            nonempty=[value for value in header_values if value]
            matched=[value for value in nonempty if any(cue in value for cue in _HEADER_CUES)]
            sequence=any(value in ("tt","stt","số thứ tự") for value in nonempty)
            if (len(nonempty)>=2 and len(matched)>=2 and
                    (len(matched)>=3 or sequence or len(matched)==len(nonempty))):
                candidates.append((len(matched),row_id,row_text))
        if candidates:
            _,header_row,header_text=max(candidates,key=lambda item:(item[0],-item[1]))
            header_rows={header_row}
            explicit_headers=(header_text,)
            inferred=True
        else:
            header_rows=set()
            inferred=False
    else:
        header_rows=set()
        inferred=False
    remaining=[(rid,raw,cs) for rid,raw,cs in rows if rid not in header_rows]
    if not remaining:
        remaining=rows
        header_rows=set()
    return source,remaining,explicit_headers,inferred,tuple(sorted(header_rows))


def _table_spans(unit:dict,row_cells:list[dict],header_cells:list[dict]=())->tuple[dict,...]:
    base=(unit.get('spans') or [{'pdf_page':1}])[0]
    table_id=(unit.get('structured') or {}).get('table_id') or base.get('table_id')
    found=[]
    seen=set()
    for cell in [*header_cells,*row_cells]:
        row=int(cell.get('row',0));col=int(cell.get('col',0))
        key=(row,col)
        if key in seen:continue
        seen.add(key)
        span={'pdf_page':base['pdf_page'],'table_id':table_id,
              'cell_id':cell.get('cell_id') or f"{table_id}:r{row}:c{col}"}
        if base.get('source_sha256') is not None:
            span['source_sha256']=base['source_sha256']
        if base.get('bbox') is not None:
            span['table_bbox']=base['bbox']
        if cell.get('bbox') is not None:
            span['bbox']=cell['bbox']
        found.append(span)
    return tuple(found or [base])


def _plan_table(unit:dict, *,max_words:int,budget:int,count:TokenCount,
                meta:dict|None)->list[ChildPart]:
    source, rows, headers, inferred, header_row_ids = _table_data(unit)
    if not rows:return []
    table=(unit.get('structured') or {})
    table_id=table.get('table_id') or (unit.get('spans') or [{}])[0].get('table_id')
    base=_base(unit,meta)
    legacy=f"Bảng từ {unit['source_id']}, trang {unit['spans'][0]['pdf_page']}"
    preface=base+legacy+(f"; mã bảng: {table_id}" if table_id else '')+'\n'
    header='\n'.join(headers)
    header_cells=[c for c in table.get('cells',[]) or [] if c.get('is_header') or c.get('header')]
    if not header_cells and inferred and table.get('cells'):
        header_ids=set(header_row_ids)
        header_cells=[c for c in table['cells'] if int(c.get('row',0)) in header_ids]
    # Each extracted source row remains atomic. Header labels are repeated,
    # and column-name/value pairs are included when coordinates are known.
    col_labels={int(c.get('col',0)):str(c.get('text') or '').strip() for c in header_cells}
    if not col_labels and headers:
        col_labels={i:val.strip() for i,val in enumerate(headers[0].split('|'))}

    # A cell merged down several rows (rowspan, from ruling geometry) belongs to every row it covers.
    covering:dict[int,list[dict]]={}
    for c in table.get('cells',[]) or []:
        for covered in range(int(c.get('row',0))+1,int(c.get('row',0))+int(c.get('rowspan') or 1)):
            covering.setdefault(covered,[]).append(c)

    def inherited(rid:int, cells:list[dict])->list[dict]:
        own={int(c.get('col',0)) for c in cells}
        return [c for c in covering.get(rid,[]) if int(c.get('col',0)) not in own]

    def enrich(raw:str, cells:list[dict], rid:int=-1)->str:
        if cells:
            pairs=[]
            for c in sorted([*cells,*inherited(rid,cells)],key=lambda c:int(c.get('col',0))):
                label=col_labels.get(int(c.get('col',0)))
                if label:
                    pairs.append(f"{label}: {str(c.get('text') or '').strip()}")
            if pairs:return raw+'\n'+' | '.join(pairs)
        return raw

    result=[]; buffer=[]

    def compose(items):
        return preface+(header+'\n' if header else '')+'\n'.join(enrich(raw,cs,rid) for rid,raw,cs in items)

    def flush():
        if not buffer:return
        content=compose(buffer)
        row_cells=[c for rid,_,cs in buffer for c in [*cs,*(inherited(rid,cs) if cs else [])]]
        rid=tuple(r for r,_,_ in buffer)
        # Only body row content is raw; header/context comes from the same source.
        raw='\n'.join(r for _,r,_ in buffer)
        result.append(ChildPart(raw_text=raw,text=content,row_ids=rid,
            spans=_table_spans(unit,row_cells,header_cells),table_headers=headers,
            token_count=count(content),over_budget=count(content)>budget,
            header_inferred=inferred))
        buffer.clear()

    for row in rows:
        row_id,raw_label,row_cells=row
        # Keep criterion headings, notes and options together until the next
        # numbered criterion; do not mix several unrelated criteria to fill a budget.
        criterion_start=bool(re.match(r'^\s*\d{1,2}\.\d{1,2}(?=[\s.,):]|$)',raw_label))
        starts_merged_group=any(int(cell.get('rowspan') or 1)>1 for cell in row_cells)
        if buffer and (starts_merged_group or criterion_start):
            # Begin a fresh child when source geometry starts another merged
            # row group, such as the next producer in a recognition table.
            flush()
        candidate=[*buffer,row]
        raw_word_count=sum(len(r.split()) for _,r,_ in candidate)
        if buffer and (raw_word_count>max_words or count(compose(candidate))>budget):
            flush()
        buffer.append(row)
        if count(compose(buffer))>budget or sum(len(r.split()) for _,r,_ in buffer)>max_words:
            flush()  # oversize row retained intact and flagged, never split cells
    flush()
    return result


def plan_chunks(unit:dict, *,max_words:int=200,overlap:int=24,token_budget:int=512,
                counter:TokenCount|None=None,source_metadata:dict|None=None)->list[ChildPart]:
    if max_words<30 or overlap<0 or overlap>=max_words:
        raise ValueError('invalid child size/overlap')
    if token_budget<64:
        raise ValueError('token_budget must be >=64 (includes source and legal context)')
    text=str(unit.get('text') or '')
    if not text.strip() or text.lstrip().startswith('[Phát hiện vùng bảng trên trang PDF'):
        return []
    unit={**unit,'text':text}
    count=counter or estimated_tokens
    if unit.get('unit_kind') in ('table','criterion_table_candidate'):
        return _plan_table(unit,max_words=max_words,budget=token_budget,count=count,meta=source_metadata)
    return _plan_prose(unit,max_words=max_words,overlap=overlap,budget=token_budget,
                       count=count,meta=source_metadata)
