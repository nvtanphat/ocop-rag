"""Human decisions projected onto existing graph review_status, never extraction.

The append-only ledger is runtime state. Approving a business entity does not
approve its evidence units or its edges. All three require separate decisions.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time


def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def ledger_path(root):
    return Path(root)/'data/review/ocop_review_decisions.jsonl'


def ledger_digest(path):
    return hashlib.sha256(Path(path).read_bytes() if path and Path(path).is_file() else b'').hexdigest()


def _rows(path):
    if Path(path).is_file():
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip(): yield json.loads(line)


def latest_decisions(path):
    latest={}
    for row in _rows(path):
        stamp=datetime.fromisoformat(row['timestamp'])
        if stamp.tzinfo is None:
            raise ValueError('review timestamp must include timezone')
        old=latest.get(row['target_id'])
        if old is None or stamp>=datetime.fromisoformat(old['timestamp']):
            latest[row['target_id']]=row
    return latest


def candidate_snapshot(row, units):
    raw=deepcopy(row.get('machine_candidate') or row)
    citations=deepcopy(raw.get('citations') or [])
    if not citations:
        for uid in raw.get('evidence_unit_ids',[]):
            unit=units.get(uid,{})
            for span in unit.get('spans',[]):
                citations.append({**span,'source_id':unit.get('source_id'),
                                  'evidence_unit_id':uid,'quote':unit.get('text','')})
    for ref in citations:
        if not ref.get('quote'):
            ref['quote']=units.get(ref.get('evidence_unit_id'),{}).get('text','')
    return {'target_id':raw.get('node_id') or raw['edge_id'],
            'target_kind':'node' if 'node_id' in raw else 'edge',
            'type':raw.get('node_type') or raw['relation_type'],
            'source_id':raw['source_id'],'label':raw.get('label'),
            'properties':raw.get('properties',{}),
            'attribute_candidates':raw.get('attribute_candidates',[]),
            'attribute_claims':raw.get('attribute_claims',[]),
            'source_entity_id':raw.get('source_entity_id'),
            'target_entity_id':raw.get('target_entity_id'),
            'evidence_unit_ids':raw.get('evidence_unit_ids',[]),'citations':citations}


def content_hash(snapshot):
    # Unit IDs may change after extraction. The literal asserted content and
    # original source anchors, not a mutable status/version, determine staleness.
    body={k:v for k,v in snapshot.items() if k not in {'target_id','evidence_unit_ids'}}
    body['citations']=[{k:r.get(k) for k in ('source_id','pdf_page','bbox','quote','source_sha256')}
                       for r in snapshot['citations']]
    body['citations']=sorted(body['citations'],key=_json)
    return hashlib.sha256(_json(body).encode('utf-8')).hexdigest()


def priority(item):
    typ=item['type'];props=item['properties']
    if (typ in {'ScoreOption','RecognitionRecord','StarLevel','MINIMUM_FOR','AMENDS','REPLACES','SUSPENDS'}
        or typ=='RuleCandidate' and props.get('modality')=='temporal'
        or props.get('effective_from') is not None):
        return 'P1','score_star_or_temporal_assertion'
    if typ in {'REQUIRES_EVIDENCE','RESPONSIBLE_FOR','ProcedureStep'}:
        return 'P2','document_role_or_responsibility'
    return 'P3','source_structure_or_other_candidate'


def apply_decisions(nodes,edges,units,path):
    """Apply explicit matching human decisions, then enforce existing proof gates."""
    decisions=latest_decisions(path)
    desired={};unit_approval={uid for uid,u in units.items() if u.get('review_status')=='verified'}
    for row in [*nodes,*edges]:
        snap=candidate_snapshot(row,units);digest=content_hash(snap)
        decision=decisions.get(snap['target_id'])
        if not decision:
            continue
        row['machine_candidate']=deepcopy(row)
        row['human_review']={'content_hash':digest,'decision':decision['decision'],
                             'reviewer':decision['reviewer'],'timestamp':decision['timestamp']}
        if decision['content_hash']!=digest:
            row['review_status']='needs_review'
            row['human_review']['state']='stale_content_needs_review'
            continue
        if decision['decision']=='reject':
            row['review_status']='rejected';row['human_review']['state']='rejected'
            if row.get('node_type')=='EvidenceUnit':
                unit_approval.difference_update(row.get('evidence_unit_ids',[]))
            continue
        if decision['decision'] not in {'approve','correct'}:
            raise ValueError('invalid decision in review ledger')
        desired[snap['target_id']]=row
        if decision['decision']=='correct':
            corrected=decision['correction']
            if 'label' in corrected: row['label']=corrected['label']
            if 'properties' in corrected:
                row.setdefault('properties',{}).update(corrected['properties'])
            row['human_review']['asserted_correction']=deepcopy(corrected)
        if row.get('node_type')=='EvidenceUnit':
            unit_approval.update(row.get('evidence_unit_ids',[]))
    by_id={n['node_id']:n for n in nodes}
    for row in nodes:
        if row['node_id'] not in desired: continue
        proof=bool(row.get('evidence_unit_ids')) and set(row['evidence_unit_ids'])<=unit_approval
        row['review_status']='verified' if proof else 'needs_review'
        row['human_review']['state']='applied' if proof else 'waiting_for_evidence_review'
        if proof: row['check']='human_verified'
    for row in edges:
        if row['edge_id'] not in desired: continue
        proof=(bool(row.get('evidence_unit_ids')) and set(row['evidence_unit_ids'])<=unit_approval
               and all(by_id.get(i,{}).get('review_status')=='verified'
                       for i in (row['source_entity_id'],row['target_entity_id'])))
        row['review_status']='verified' if proof else 'needs_review'
        row['human_review']['state']='applied' if proof else 'waiting_for_endpoints_or_evidence'
        if proof: row['check']='human_verified'
    return {'ledger_sha256':ledger_digest(path),'decisions':len(decisions),
            'matched':len(desired),'verified_nodes':sum(n['review_status']=='verified' for n in nodes),
            'verified_edges':sum(e['review_status']=='verified' for e in edges),
            'evidence_policy':'explicit_whole_unit_approval_no_entity_cascade'}


def load_queue(root, *, graph_dir=None, knowledge_dir=None):
    root=Path(root);base=root/'data/processed/ocop'
    graph=Path(graph_dir) if graph_dir else base/'graph'
    knowledge=Path(knowledge_dir) if knowledge_dir else base/'knowledge'
    if (base/'.promoting').exists(): raise ValueError('corpus is being updated; retry review after promotion')
    if not (graph/'manifest.json').is_file(): return []
    from ai_core.graph.ocop.integrity import validate_graph_snapshot
    manifest=validate_graph_snapshot(graph,allow_partial=True)
    from ai_core.graph.ocop.builder import SCHEMA_REVISION
    if manifest.get('schema_revision')!=SCHEMA_REVISION:
        raise ValueError('graph schema changed; rebuild corpus before human review')
    immutable=graph/'snapshots'/manifest['graph_version']
    if immutable.is_dir(): graph=immutable
    units={u['unit_id']:u for u in _rows(knowledge/'evidence_units.jsonl')}
    knowledge_manifest=json.loads((knowledge/'manifest.json').read_text(encoding='utf-8'))
    if knowledge_manifest.get('corpus_version')!=manifest.get('source_knowledge_version'):
        raise ValueError('graph and knowledge versions differ; rebuild corpus before human review')
    decisions=latest_decisions(ledger_path(root));items=[]
    attention={r['target_id']:r for r in _rows(root/'data/review/ocop_review_attention.jsonl')}
    regions={}
    for region in _rows(root/'data/review/ocop_review_attention_regions.jsonl'):
        regions.setdefault((region.get('source_id'),region.get('pdf_page')),[]).append(region)
    quality_path=knowledge/'business_quality.json'
    quality=json.loads(quality_path.read_text(encoding='utf-8')) if quality_path.is_file() else {}
    affected=set()
    def anchors(value):
        if isinstance(value,dict):
            if value.get('evidence_unit_id'): affected.add(value['evidence_unit_id'])
            for member in value.values(): anchors(member)
        elif isinstance(value,list):
            for member in value: anchors(member)
    anchors(quality.get('arithmetic_mismatches',[]))
    anchors([v for v in quality.get('arithmetic_incomplete',[])
             if v.get('reason')!='missing_parts_or_reference'])
    anchors([v for v in quality.get('shapes',{}).get('violations',[]) if v.get('severity')!='pending_source'])
    graph_rows=[*_rows(graph/'nodes.jsonl'),*_rows(graph/'edges.jsonl')]
    current_ids={r.get('node_id') or r.get('edge_id') for r in graph_rows}
    previous={}
    for event in decisions.values():
        if event['target_id'] in current_ids:continue
        locator=event.get('target_locator',{})
        for span in locator.get('source_pages',[]):
            key=(locator.get('source_id'),locator.get('type'),span.get('pdf_page'),span.get('source_sha256'))
            if key not in previous or datetime.fromisoformat(event['timestamp'])>datetime.fromisoformat(previous[key]['timestamp']):previous[key]=event
    for row in graph_rows:
        item=candidate_snapshot(row,units);item['content_hash']=content_hash(item)
        p,reason=priority(item);reasons=[reason]
        if item['target_id'] in attention:
            p=min(p,'P2');reasons.append(attention[item['target_id']].get('reason','manual_inspection_requested'))
        for ref in item['citations']:
            for region in regions.get((ref.get('source_id'),ref.get('pdf_page')),[]):
                if not region.get('source_sha256') or region['source_sha256']!=ref.get('source_sha256'):
                    continue
                a,b=ref.get('bbox'),region.get('bbox')
                if a and b and min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]):
                    p=min(p,'P2')
                    reason=region.get('reason','source_region_needs_inspection')
                    if reason not in reasons:reasons.append(reason)
        if affected.intersection(item['evidence_unit_ids']):
            p=min(p,'P2');reasons.append('quality_mismatch_requires_review')
        if any(v is None for k,v in item['properties'].items() if 'points' in k or 'score' in k):
            reasons.append('missing_ocr_value')
        decision=decisions.get(item['target_id'])
        state=row.get('human_review',{}).get('state','unreviewed')
        if decision and decision['content_hash']!=item['content_hash']:
            state='stale_content_needs_review';reasons.append('needs_rereview');p=min(p,'P2')
        prior=None
        if decision is None:
            matches=[previous[(item['source_id'],item['type'],r.get('pdf_page'),r.get('source_sha256'))]
                     for r in item['citations']
                     if (item['source_id'],item['type'],r.get('pdf_page'),r.get('source_sha256')) in previous]
            if matches:
                prior=max(matches,key=lambda d:datetime.fromisoformat(d['timestamp']))
                state='stale_content_needs_review';reasons.append('needs_rereview');p=min(p,'P2')
        item.update(priority=p,reasons=reasons,state=state,review_status=row['review_status'],
                    check=row['check'], origin=row['origin'],
                    **({'check_reason':row['check_reason']} if row['check']=='failed' else {}),
                    human_review=deepcopy(row.get('human_review',{})),
                    latest_decision=deepcopy(decision or prior))
        for index,ref in enumerate(item['citations']):
            key=hashlib.sha256(_json({k:ref.get(k) for k in ('source_sha256','pdf_page','bbox')}).encode()).hexdigest()
            ref['crop_path']=str(root/'data/runtime/ocop/review_crops'/f'{key}.png')
            ref['crop_index']=index
        items.append(item)
    by_id={i['target_id']:i for i in items}
    proof_ids={uid:i['target_id'] for i in items if i['type']=='EvidenceUnit'
               for uid in i['evidence_unit_ids']}
    for item in items:
        required={proof_ids[u] for u in item['evidence_unit_ids'] if u in proof_ids}
        required.update(i for i in (item['source_entity_id'],item['target_entity_id']) if i)
        item['dependencies']=[{'target_id':i,'label':by_id[i]['label'],'type':by_id[i]['type'],
                               'review_status':by_id[i]['review_status']}
                              for i in sorted(required) if i!=item['target_id'] and i in by_id]
    return sorted(items,key=lambda i:(i['priority'],i['type'],i['target_id']))


def statistics(items):
    return {'total':len(items),'by_priority':dict(Counter(i['priority'] for i in items)),
            'by_type':dict(Counter(i['type'] for i in items)),
            'by_status':dict(Counter(i['review_status'] for i in items)),
            'by_state':dict(Counter(i['state'] for i in items))}


@contextmanager
def _write_lock(path):
    lock=Path(str(path)+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    for _ in range(100):
        try:
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError: time.sleep(.05)
    else: raise RuntimeError('review ledger is busy')
    try: yield
    finally:
        os.close(fd);lock.unlink()


def record_decision(root,target_id,digest,decision,reviewer,*,correction=None,notes=''):
    if decision not in {'approve','reject','correct'}: raise ValueError('invalid review decision')
    if not reviewer.strip() or len(reviewer)>160: raise ValueError('reviewer is required')
    if decision=='correct':
        if (not isinstance(correction,dict) or not correction or
            set(correction)-{'label','properties'} or
            ('properties' in correction and not isinstance(correction['properties'],dict)) or
            ('label' in correction and (not isinstance(correction['label'],str) or not correction['label'].strip()))):
            raise ValueError('correction must contain label and/or properties')
        _json(correction)
    elif correction is not None: raise ValueError('only correct accepts corrected values')
    path=ledger_path(root)
    with _write_lock(path):
        item=next((i for i in load_queue(root) if i['target_id']==target_id),None)
        if item is None: raise ValueError('review target does not exist in current corpus')
        if item['content_hash']!=digest: raise ValueError('stale content_hash; reload item before deciding')
        if decision=='correct' and item['type']=='EvidenceUnit':
            raise ValueError('approve or reject the literal evidence unit; correct the business assertion instead')
        row={'target_id':target_id,'content_hash':digest,'decision':decision,'correction':correction,
             'graph_version':json.loads((Path(root)/'data/processed/ocop/graph/manifest.json').read_text(encoding='utf-8'))['graph_version'],
             'reviewer':reviewer.strip(),'timestamp':datetime.now(timezone.utc).isoformat(),'notes':notes,
             'target_locator':{'source_id':item['source_id'],'type':item['type'],
                'source_pages':[{'pdf_page':r.get('pdf_page'),'source_sha256':r.get('source_sha256')}
                                for r in item['citations']]}}
        with path.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(_json(row)+'\n');stream.flush();os.fsync(stream.fileno())
    return row


def render_crop(root,item,index):
    from ocop_contracts.pdf_loader import checked_sources
    root=Path(root).resolve()
    sources,_=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    return _render_crop(root,item,index,sources,{})


def render_queue_crops(root,items):
    """One source-lock check per export; render from SHA-checked immutable bytes."""
    from ocop_contracts.pdf_loader import checked_sources
    root=Path(root).resolve()
    sources,_=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    source_bytes={};paths=set()
    for item in items:
        for index in range(len(item['citations'])):
            paths.add(str(_render_crop(root,item,index,sources,source_bytes)))
    return len(paths)


def _render_crop(root,item,index,sources,source_bytes):
    import fitz
    if not 0<=index<len(item['citations']): raise ValueError('citation index not found')
    ref=item['citations'][index]
    source=next((s for s in sources if s.source_id==ref['source_id']),None)
    if source is None: raise ValueError('source is not in locked public registry')
    pdf=(root/source.path).resolve()
    if not pdf.is_relative_to((root/'data/raw/ocop').resolve()):
        raise ValueError('source path outside public OCOP tree')
    if source.source_id not in source_bytes:
        data=pdf.read_bytes();source_bytes[source.source_id]=(hashlib.sha256(data).hexdigest(),data)
    digest,data=source_bytes[source.source_id]
    if digest!=ref.get('source_sha256'): raise ValueError('citation source SHA does not match PDF')
    target=Path(ref['crop_path'])
    if not target.resolve().is_relative_to((root/'data/runtime/ocop/review_crops').resolve()):
        raise ValueError('invalid runtime crop path')
    if not target.is_file():
        with fitz.open(stream=data,filetype='pdf') as document:
            page=document[int(ref['pdf_page'])-1]
            box=fitz.Rect(ref['bbox']) if ref.get('bbox') else page.rect
            if box.is_empty or not page.rect.contains(box): raise ValueError('citation bbox outside PDF page')
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.stem+f'.{os.getpid()}.tmp.png')
            page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),clip=box).save(temp)
            os.replace(temp,target)
    return target


def rebuild_reviewed_graph(root):
    from ai_core.graph.ocop.builder import build_graph
    root=Path(root);base=root/'data/processed/ocop'
    with _write_lock(root/'data/review/ocop_graph_projection'):
        return build_graph(base/'knowledge',base/'graph',review_decisions=ledger_path(root))
