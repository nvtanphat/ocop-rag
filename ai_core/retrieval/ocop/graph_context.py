"""Attach only checked structural parents to original child passages."""
import re

from ai_core.graph.ocop.lookup import GraphEvidence


def enrich_chunks(chunks, graph_dir, *, allow_partial_debug=False):
    graph=GraphEvidence(graph_dir,allow_partial_debug=allow_partial_debug)
    incoming={}
    for edge in graph.edges:
        if edge['relation_type'] in {'HAS_CRITERION','HAS_SUBCRITERION','HAS_OPTION','HAS_CONDITION',
                                     'HAS_ARTICLE','HAS_CLAUSE','HAS_POINT'}:
            incoming.setdefault(edge['target_entity_id'],[]).append(edge)
    for chunk in chunks:
        uid=chunk['evidence_unit_id'];row_ids=set(chunk.get('row_ids',[]))
        def overlaps(ref):
            if ref.get('evidence_unit_id')!=uid:return False
            if row_ids:return ref.get('row') in row_ids
            backing=graph.units.get(uid,{}).get('properties',{}).get('evidence_text','')
            quote=ref.get('quote','')
            start=backing.find(quote) if quote else -1
            if start<0:return False
            return (chunk.get('char_start',0) or 0)<start+len(quote) and (
                chunk.get('char_end') or len(backing))>start
        candidates=[n for n in graph.nodes.values() if n['source_id']==chunk['source_id'] and
            n['node_type'] in {'Criterion','ScoreOption','Condition','Article','Clause','Point'} and
            any(overlaps(ref) for ref in n.get('citations',[]))]
        # Notes inherit the nearest observed criterion within the same table.
        if row_ids:
            def heading_rows(node):
                return [ref['row'] for ref in node.get('citations',[]) if
                        ref.get('evidence_unit_id')==uid and isinstance(ref.get('row'),int) and
                        node['label'] in ref.get('quote','')]
            preceding=[n for n in graph.nodes.values() if n['source_id']==chunk['source_id'] and
                n['node_type']=='Criterion' and re.match(r'^\d+\.\d+',n['label']) and
                any(row<=min(row_ids) for row in heading_rows(n))]
            if preceding:
                candidates.append(max(preceding,key=lambda n:max(row for row in heading_rows(n) if row<=min(row_ids))))
        parents={n['node_id'] for n in candidates};used=[]
        while True:
            edges=[edge for identity in list(parents) for edge in incoming.get(identity,[])
                   if edge['source_entity_id'] not in parents]
            if not edges:break
            used.extend(edges);parents.update(e['source_entity_id'] for e in edges)
        structural=[graph.nodes[i] for i in sorted(parents)
                    if graph.nodes[i]['node_type'] in {'CriterionSheet','Criterion','Article','Clause','Point'}]
        if not structural:continue
        labels=list(dict.fromkeys(n['label'] for n in structural))
        prefix='Ngữ cảnh cấu trúc từ graph: '+'; '.join(labels)+'\n'
        chunk['text_for_bm25']=prefix+chunk['text_for_bm25']
        chunk['text_for_embedding']=prefix+chunk['text_for_embedding']
        codes=[m.group(0) for n in structural for m in [re.match(r'\d{1,2}\.\d{1,2}',n['label'])] if m]
        chunk.setdefault('context',{}).update({'criterion_codes':list(dict.fromkeys(codes)),
            'parent_graph_node_ids':[n['node_id'] for n in structural],
            'graph_edge_ids':list(dict.fromkeys(e['edge_id'] for e in used)),
            'parent_source_spans':[ref for n in structural for ref in n.get('citations',[])]})
    return chunks
