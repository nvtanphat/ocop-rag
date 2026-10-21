"""Prechecked synthetic snapshots for scope/filter tests, not graph acceptance tests.

Review labels are supplied by each existing fabricated test; none represents an
approval of real OCOP data. Real builder/check integration is tested separately.
"""
import json

from ocop_contracts.ids import content_sha256
from ai_core.graph.ocop.builder import SCHEMA_REVISION


def write_lookup_graph(index, rows):
    manifest_path=index/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    version=manifest['corpus_version']
    manifest['source_knowledge_version']=version
    manifest_path.write_text(json.dumps(manifest),encoding='utf8')
    graph=index.parent/'graph'
    snapshot=graph/'snapshots'/'synthetic-filter-fixture'
    snapshot.mkdir(parents=True,exist_ok=True)
    nodes=[]
    kinds={'form_candidates':'FormTemplate','recognition_candidates':'RecognitionRecord',
           'criterion_candidates':'Criterion','taxonomy_candidates':'ProductSubgroup',
           'evidence_requirement_candidates':'EvidenceRequirement'}
    for i,row in enumerate(rows):
        uid=row.get('evidence_unit_id') or f'synthetic-unit-{i}'
        source=row['source_id']
        text=row.get('text') or row.get('row_text') or row.get('label_candidate') or row.get('title') or 'Synthetic form'
        spans=[{**span,'bbox':span.get('bbox',[0,0,100,100]),'source_sha256':'a'*64,
                'source_id':source,'evidence_unit_id':uid}
               for span in row.get('source_spans',[{'pdf_page':i+1}])]
        base={'source_id':source,'evidence_unit_ids':[uid], 'review_status':row.get('review_status','needs_review'),
              'check':'passed','origin':'deterministic','citations':spans}
        nodes.append({**base,'node_id':f'unit-{i}','node_type':'EvidenceUnit','label':'paragraph',
            'properties':{'evidence_text':text,'source_spans':spans,'unit_kind':'paragraph','source_order':i}})
        nodes.append({**base,'node_id':f'fact-{i}','node_type':kinds[row['record_kind']],
            'label':row.get('label_candidate') or row.get('title') or text,
            'properties':{**row,'evidence_unit_id':uid}})
    digests={}
    for name,items in [('nodes',nodes),('edges',[])]:
        data=''.join(json.dumps(item,ensure_ascii=False)+'\n' for item in items).encode('utf8')
        (snapshot/f'{name}.jsonl').write_bytes(data)
        (graph/f'{name}.jsonl').write_bytes(data)
        digests[f'{name}.jsonl']=content_sha256(data)
    header={'status':'local_ready','graph_version':'synthetic-filter-fixture','schema_revision':SCHEMA_REVISION,
            'source_knowledge_version':version,'checks':{'fixture_only':True},'file_sha256':digests}
    for target in (graph,snapshot):
        (target/'manifest.json').write_text(json.dumps(header),encoding='utf8')


def build_legal_graph(index, units):
    from ai_core.graph.ocop.builder import build_graph
    from ai_core.knowledge.ocop.extractor import extract_semantics
    from ai_core.processing.ocop.business_candidates import candidates
    knowledge=index.parent/'knowledge'
    knowledge.mkdir(exist_ok=True)
    manifest=json.loads((index/'manifest.json').read_text(encoding='utf8'))
    version=manifest['corpus_version']
    manifest['source_knowledge_version']=version
    (index/'manifest.json').write_text(json.dumps(manifest),encoding='utf8')
    kinds={u['source_id']:'ocop_framework' for u in units}
    semantics=extract_semantics(units,kinds,candidates(units,kinds))
    for name,rows in {'evidence_units':units,**semantics}.items():
        (knowledge/f'{name}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'
            for r in rows),encoding='utf8')
    (knowledge/'manifest.json').write_text(json.dumps({'complete':True,'corpus_version':version}),encoding='utf8')
    build_graph(knowledge,index.parent/'graph')
