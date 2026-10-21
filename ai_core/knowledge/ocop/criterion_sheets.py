"""Source-defined sheets and candidate score trees, never a scoring engine."""
from __future__ import annotations
import re
from collections import defaultdict
from ocop_contracts.ids import stable_id
from .contracts import EntityType
from .star_requirements import SHEET


def _norm(text):
    return ' '.join(text.split()).casefold()


def extract_criterion_sheets(units,kinds,candidates,index,entities,relations,omitted,add,link,ref):
    headers=defaultdict(dict)

    def attach(eid,ev):
        if ev not in entities[eid].evidence:
            entities[eid].evidence.append(ev)

    def identity(kind,sid,key):
        return stable_id('biz_entity',sid,[kind.value,key],revision='business')

    def sheet(sid,number,label,record,ev):
        return add(EntityType.CRITERION_SHEET,label,record,ev,key=f'sheet:{number}',attributes={
            'sheet_number':number,'group_candidate':None,'subgroup_candidate':None})

    for u in units:
        sid=u['source_id']
        if kinds.get(sid)!='ocop_framework' or not u.get('spans'):
            continue
        page=int(u['spans'][0]['pdf_page']);text=u.get('text') or ''
        record={'source_id':sid,'evidence_unit_id':u['unit_id'],'pdf_page':page}
        if u['unit_kind']=='article':
            match=re.search(r'(\d+)\s+nhóm\s+sản\s+phẩm\s*:\s*(.*?)(?:\.\s*Danh\s+mục)',text,re.I|re.S)
            if match:
                labels=[v.strip() for v in match[2].split(';') if v.strip()]
                if len(labels)!=int(match[1]):
                    # OCR may turn the separator after the complete category
                    # "đồ uống" into a comma. Preserve every literal label.
                    labels=[v.strip() for v in re.split(r';|(?<=uống),\s*(?=(?:dược|được)\s+liệu\b)',match[2],flags=re.I) if v.strip()]
                    if len(labels)==int(match[1]):
                        omitted['product_group_nonstandard_separator']+=1
                if len(labels)!=int(match[1]):
                    omitted['product_group_list_count_mismatch']+=1
                else:
                    for label in labels:
                        ev=ref(record,index,text=label)
                        group=add(EntityType.PRODUCT_GROUP,' '.join(label.split()),record,ev,key=f'group:{_norm(label)}')
                        doc=identity(EntityType.SOURCE_DOCUMENT,sid,f'document:{sid}')
                        if doc in entities:
                            attach(doc,ev);link('DEFINES_GROUP',doc,group,ev)
        # Index entries are explicit numbered rows, not assumed form pages.
        for cell in u.get('structured',{}).get('cells',[]):
            label=str(cell.get('text') or '').strip()
            if not re.match(r'^Bộ\s+sản\s+phẩm\s*:',label,re.I):
                continue
            same=[c for c in u['structured']['cells'] if c['row']==cell['row'] and c['col']<cell['col']]
            number=next((str(c['text']).strip() for c in same if re.fullmatch(r'\d{1,2}',str(c.get('text','')).strip())),None)
            if number:
                row={**record,'row':cell['row'],'table_id':u['structured'].get('table_id')}
                ev=ref(row,index)
                sheet(sid,number,label,row,ev)
            elif same:
                row={**record,'row':cell['row'],'table_id':u['structured'].get('table_id')}
                ev=ref(row,index)
                add(EntityType.CRITERION_SHEET,label,row,ev,key=f'unknown-sheet:{u["unit_id"]}:{cell["row"]}',
                    attributes={'sheet_number':None,'group_candidate':None,'subgroup_candidate':None})
                omitted['sheet_index_missing_number']+=1
        header=SHEET.search(text) if u['unit_kind']!='page' else None
        if not header:
            continue
        ev=ref(record,index,text=text)
        number=header[1]
        sheet_id=sheet(sid,number,text[header.start():].splitlines()[0],record,ev)
        headers[sid][page]=(number,sheet_id,ev)
        classification=re.search(r'\(\s*Sản\s+phẩm\s*:\s*(.*?)\.\s*Nhóm\s*:\s*([^\)]+)',text,re.I|re.S)
        if classification:
            group_text,subgroup_text=(v.strip() for v in classification.groups())
            group=add(EntityType.PRODUCT_GROUP,' '.join(group_text.split()),record,ev,key=f'group:{_norm(group_text)}')
            sub=add(EntityType.PRODUCT_SUBGROUP,' '.join(subgroup_text.split()),record,ev,
                    key=f'subgroup:{_norm(group_text)}:{_norm(subgroup_text)}')
            link('HAS_SUBGROUP',group,sub,ev);link('USES_SHEET',sub,sheet_id,ev)
            entities[sheet_id].attributes.update(group_candidate=' '.join(group_text.split()),
                                                 subgroup_candidate=' '.join(subgroup_text.split()))
        else:
            omitted['sheet_header_missing_classification']+=1

    missing=sum(1 for entity in entities.values()
        if entity.kind==EntityType.CRITERION_SHEET and
        (entity.attributes.get('group_candidate') is None or entity.attributes.get('subgroup_candidate') is None))
    if missing:
        omitted['sheet_missing_group_or_subgroup']+=missing
    rows=defaultdict(list)
    for row in candidates.get('criterion_candidates',[]):
        rows[(row['source_id'],row['evidence_unit_id'],row.get('table_id'))].append(row)
    states={}
    for (sid,uid,table_id),records in sorted(rows.items(),key=lambda item:(item[0][0],
            int(index[item[0][1]]['spans'][0]['pdf_page']),str(item[0][2]))):
        page=int(index[uid]['spans'][0]['pdf_page'])
        starts=[p for p in headers[sid] if p<=page]
        if not starts:
            continue
        start=max(starts);number,sheet_id,header_ev=headers[sid][start]
        state=states.get(sid)
        if not state or state['sheet']!=sheet_id:
            state={'sheet':sheet_id,'part':None,'numbers':{},'parent':None,'page':page,'table':table_id}
        elif (page,table_id)!=(state['page'],state['table']):
            hints=index[uid].get('structured',{}).get('table_continuity',[])
            continuous=any(h['from_pdf_page']==state['page'] and h['from_table_id']==state['table'] for h in hints)
            if not continuous:
                state['parent']=None;state['part']=None;state['numbers']={}
                omitted['score_table_without_continuity']+=1
        states[sid]=state
        state.update(page=page,table=table_id)

        def connect(relation,parent,child,ev):
            primary=entities[parent].evidence[0]
            anchors=[primary] if primary.pdf_page!=page else []
            attach(parent,ev)
            for anchor in anchors:
                attach(child,anchor)
            link(relation,parent,child,ev,extra_evidence=anchors)

        for row in sorted(records,key=lambda r:int(r['row'])):
            ev=ref(row,index)
            cid=identity(EntityType.CRITERION,sid,f'numbered:{row["candidate_id"]}')
            oid=identity(EntityType.SCORE_OPTION,sid,f'score-option:{row["candidate_id"]}')
            label=str(row.get('label_candidate') or '').split('|')[0].strip()
            if (cid not in entities and oid not in entities and state['parent'] and len(label)>=2 and any(c.isalpha() for c in label)
                and not re.match(r'^(?:gh[iị]\s+ch[úủ]|chú\s+ý|yêu\s+cầu|lưu\s+ý|ch[iỉ]\s+áp\s+dụng|tổng\s+cộng|các\s+tiêu\s+chí|thang\s+điểm)\b|^\(',label,re.I)):
                score=row.get('score_candidate')
                if not isinstance(score,int) or isinstance(score,bool) or not 0<=score<=100:
                    score=None
                oid=add(EntityType.SCORE_OPTION,label,row,ev,key=f'score-option:{row["candidate_id"]}',
                    attributes={'points_candidate':score,'parent_identified':True,
                                'table_id':table_id,'row':row['row']})
            if cid in entities:
                criterion=entities[cid];criterion.attributes['sheet_number_candidate']=number
                part=criterion.attributes.get('part_letter')
                if part:
                    state['part']=cid;state['parent']=cid
                    connect('HAS_CRITERION',sheet_id,cid,ev)
                else:
                    match=re.match(r'\s*(\d+(?:\.\d+)*)',criterion.label)
                    if not match:
                        continue
                    key=match[1];parent_key=key.rsplit('.',1)[0] if '.' in key else None
                    parent=state['numbers'].get(parent_key) if parent_key else state['part']
                    if parent:
                        connect('HAS_SUBCRITERION',parent,cid,ev)
                    else:
                        omitted['criterion_without_part_or_numbered_parent']+=1
                    state['numbers'][key]=cid;state['parent']=cid
            elif oid in entities:
                entities[oid].attributes['sheet_number_candidate']=number
                parent=state['parent']
                if parent:
                    entities[oid].attributes['parent_identified']=True
                    connect('HAS_OPTION',parent,oid,ev)
                else:
                    omitted['score_option_without_continuation_parent']+=1
