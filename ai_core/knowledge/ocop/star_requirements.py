"""Unverified star thresholds and option-level minimum requirements.

An image marker needs its own sheet's literal legend; neither OCR scores nor
these candidates may be used to rank products or assess a dossier.
"""
from __future__ import annotations
import re
from ocop_contracts.ratings import asterisk_quantifier, level_class
from collections import defaultdict
from ocop_contracts.ids import stable_id
from .contracts import EntityType

SHEET = re.compile(r'^\s*(\d{1,2})[.)]\s*(?:Bộ\s+sản\s+phẩm\s*:|'
                   r'Sản\s+phẩm\s+(?=[^:\n]+\n\s*\(\s*Sản\s+phẩm\s*:))',re.I|re.M)
LEGEND = re.compile(r'Dấu\s+sao\s+là\s+yêu\s+cầu\s+tối\s+thiểu',re.I)
MAPPING = re.compile(r'(?<!\*)(\*'+asterisk_quantifier()+r')(?!\*)\s*[-–—:]\s*('+level_class(certified=True)+r')\s*sao',re.I)
MARKER = re.compile(r'(?<!\*)\*'+asterisk_quantifier()+r'(?!\*)')
THRESHOLD = re.compile(r'đạt\s+(?:từ\s+(\d+)\s+đến\s+(dưới\s+)?(\d+)|dưới\s+(\d+))',re.I)


def extract_star_requirements(units, kinds, candidate_sets, index, entities,
                              omitted, add, link, ref, cell_ref, sentences):
    def attach(entity_id, evidence):
        if evidence not in entities[entity_id].evidence:
            entities[entity_id].evidence.append(evidence)

    def star(sid, level, ev, attrs=None):
        return add(EntityType.STAR_LEVEL,f'{level} sao',{'source_id':sid},ev,
            key=f'star-level:{level}',attributes={
                'star_level':level,'min_points':None,'max_points':None,
                'min_inclusive':None,'max_inclusive':None,
                'interpretation_verified':False, **(attrs or {})})

    article3 = {(e.source_id,r.evidence_unit_id) for e in entities.values()
                if e.kind == EntityType.ARTICLE and re.search(r'phân\s+hạng|xếp\s+hạng|bộ\s+tiêu\s+chí', str(e.attributes.get('title_candidate') or ''), re.I)
                for r in e.evidence}
    for unit in units:
        sid = unit['source_id']
        if kinds.get(sid) not in {'ocop_framework','ocop_historical'} or (sid,unit['unit_id']) not in article3:
            continue
        for statement in sentences(unit.get('text') or ''):
            level = re.search(r'\bhạng\s+('+level_class()+r')\s+sao',statement,re.I)
            score = THRESHOLD.search(statement)
            if not level or not score:
                continue
            lo = int(score[1]) if score[1] else None
            hi = int(score[3] or score[4])
            if not 0 <= hi <= 100 or (lo is not None and not 0 <= lo <= hi):
                omitted['invalid_star_threshold_candidate'] += 1
                continue
            record = {'source_id':sid,'evidence_unit_id':unit['unit_id'],
                      'pdf_page':unit['spans'][0]['pdf_page']}
            ev = ref(record,index,text=statement)
            star(sid,int(level[1]),ev,{'min_points':lo,'max_points':hi,
                                     'min_inclusive':True if lo is not None else None,
                                     'max_inclusive':not bool(score[2] or score[4])})

    pages = defaultdict(set)
    headers = defaultdict(dict)
    legends = defaultdict(list)
    boundaries = defaultdict(list)
    ambiguous_headers = defaultdict(set)
    for unit in units:
        sid = unit['source_id']
        if kinds.get(sid) not in {'ocop_framework','ocop_historical'} or not unit.get('spans'):
            continue
        page = int(unit['spans'][0]['pdf_page'])
        pages[sid].add(page)
        text = unit.get('text') or ''
        record = {'source_id':sid,'evidence_unit_id':unit['unit_id'],'pdf_page':page}
        if unit.get('unit_kind') != 'page' and re.search(r'^\s*Phụ\s+lục\s+[IVX]+\b',text,re.I|re.M):
            boundaries[sid].append(page)
        for header in SHEET.finditer(text) if unit.get('unit_kind') != 'page' else []:
            title=text[header.start():].splitlines()[0]
            ev=ref(record,index,text=title)
            key=(page,ev.bbox[1] if ev.bbox else 0)
            number=str(int(header[1]))
            if key in headers[sid] and headers[sid][key]!=number:
                ambiguous_headers[sid].add(key)
            headers[sid][key] = number
        if unit.get('unit_kind') != 'page' and LEGEND.search(text):
            observed = defaultdict(set)
            for match in MAPPING.finditer(text):
                observed[len(match[1])].add(int(match[2]))
            for proposal in unit.get('structured',{}).get('image_legend_candidates',[]):
                marker=str(proposal.get('text') or '')
                level=proposal.get('star_level_candidate')
                if MARKER.fullmatch(marker) and level in (3,4,5):
                    observed[len(marker)].add(level)
            mapping = {count:next(iter(levels)) for count,levels in observed.items() if len(levels)==1}
            if any(len(levels)>1 for levels in observed.values()):
                omitted['star_legend_mapping_conflict'] += 1
                continue
            if not mapping:
                omitted['star_legend_mapping_not_observed'] += 1
                continue
            record = {'source_id':sid,'evidence_unit_id':unit['unit_id'],'pdf_page':page}
            ev=ref(record,index,text=text)
            legends[sid].append(((page,ev.bbox[1] if ev.bbox else 0),mapping,ev))

    for row in candidate_sets.get('criterion_candidates',[]):
        sid = row['source_id']
        if kinds.get(sid) not in {'ocop_framework','ocop_historical'}:
            continue
        uid = row['evidence_unit_id']
        unit = index[uid]
        label = str(row.get('label_candidate') or '').split('|')[0].strip()
        if re.match(r'^(?:Yêu\s+cầu|Ghi\s+chú|Lưu\s+ý)\s*:',label,re.I):
            continue
        option_id = stable_id('biz_entity',sid,
            [EntityType.SCORE_OPTION.value,f'score-option:{row["candidate_id"]}'],revision='business')
        if option_id not in entities:
            continue
        cells = [c for c in unit.get('structured',{}).get('cells',[])
                 if int(c.get('row',-1)) == int(row.get('row',-2))]
        marks = {len(m):'ocr_text' for m in MARKER.findall(label)}
        for cell in cells:
            for marker in cell.get('image_marker_candidates') or []:
                text = str(marker.get('text') or '')
                if MARKER.fullmatch(text):
                    counts=cell.get('independent_marker_counts_candidate')
                    if counts is not None and len(text) not in counts:
                        omitted['option_star_geometry_disagreement']+=1
                        continue
                    marks.setdefault(len(text),'image_marker_candidate')
        if not marks:
            continue
        if len(marks) != 1:
            omitted['conflicting_option_star_markers'] += 1
            continue
        level, observed_in = next(iter(marks.items()))
        page = int(row.get('pdf_page') or unit['spans'][0]['pdf_page'])
        top=min((c['bbox'][1] for c in cells if c.get('bbox')),default=0)
        starts = [p for p in headers[sid] if p <= (page,top)]
        if not starts:
            omitted['option_star_missing_sheet_header'] += 1
            continue
        start = max(starts)
        if start in ambiguous_headers[sid] or any(start[0]<b<=page for b in boundaries[sid]):
            omitted['option_star_ambiguous_or_closed_sheet']+=1
            continue
        next_start = min((p for p in headers[sid] if p > start),default=(float('inf'),float('inf')))
        matches = [(p,mapping,ev) for p,mapping,ev in legends[sid]
                   if start <= p < next_start and level in mapping
                   and all(pn in pages[sid] for pn in range(start[0],max(page,p[0])+1))]
        if len(matches) != 1:
            omitted['option_star_missing_unambiguous_sheet_legend'] += 1
            continue
        _, mapping, note_ev = matches[0]
        # The marker may have been recovered from pixels rather than cell text;
        # cite the original option cell, never synthesize a starred quote.
        text_cells = [c for c in cells if str(c.get('text') or '').strip()]
        if not text_cells:
            omitted['option_star_missing_cell_evidence'] += 1
            continue
        cell = max(text_cells,key=lambda c:len(str(c['text'])))
        option_ev = cell_ref(row,index,int(row['row']),int(cell['col']))
        if option_ev is None:
            omitted['option_star_missing_cell_evidence'] += 1
            continue
        target = star(sid,mapping[level],note_ev)
        attach(target,option_ev)
        attach(option_id,option_ev)
        attach(option_id,note_ev)
        link('MINIMUM_FOR',option_id,target,option_ev,extra_evidence=[note_ev],attributes={
            'marker_observed':'*'*level,'marker_observed_in':observed_in,
            'interpretation_verified':False,'sheet_number_candidate':headers[sid][start]})
