"""Article/clause/point candidates with explicit, consecutive-page continuity."""
from __future__ import annotations
import re
from .contracts import EntityType

ARTICLE = re.compile(r'^\s*Điều\s+(\d+[a-zđ]?)[.:]?\s*(.*)', re.I)
CLAUSE = re.compile(r'^\s*(\d{1,2})[.)]\s+', re.M)
POINT = re.compile(r'^\s*([a-zđ])[.)]\s+', re.M | re.I)


def extract_article_tree(units, registry, index, entities, omitted, add, link, ref, document):
    states = {}

    def attach(entity_id, evidence):
        if evidence not in entities[entity_id].evidence:
            entities[entity_id].evidence.append(evidence)

    # Preserve the evidence extractor's intra-page order; pages may arrive in
    # different JSONL source order but must never carry state across a gap.
    ordered = sorted(enumerate(units), key=lambda item:(item[1]['source_id'],
        (item[1].get('spans') or [{}])[0].get('pdf_page',0), item[0]))
    for _, unit in ordered:
        sid = unit['source_id']
        kind = unit.get('unit_kind')
        if sid not in registry or kind == 'page' or not unit.get('spans'):
            continue
        page = int(unit['spans'][0]['pdf_page'])
        text = unit.get('text') or ''
        record = {'source_id':sid,'evidence_unit_id':unit['unit_id'],'pdf_page':page}
        state = states.get(sid)
        if state and page not in (state['page'],state['page']+1):
            states.pop(sid,None)
            state = None
        if kind not in ('article','paragraph'):
            states.pop(sid,None)
            continue
        heading = ARTICLE.match(text) if kind == 'article' else None
        if not heading and re.search(
                r'(?mi)^\s*\(?\s*(?:Phụ\s+l[ụu]c\b|(?:Ban\s+hành\s+)?Kèm\s+theo\s+(?:Quyết|Nghị)\s+định)',text):
            states.pop(sid,None)
            omitted['article_stopped_at_annex_banner']+=1
            continue
        if heading:
            ev = ref(record,index,text=text)
            article_no = heading[1]
            first_clause = CLAUSE.search(text,heading.end())
            title = text[heading.start():first_clause.start() if first_clause else heading.end()].strip()
            article = add(EntityType.ARTICLE,title,record,ev,key=f'article:{article_no}',
                          attributes={'article_number':article_no,'title_candidate':title})
            state = {'article':article,'number':article_no,'clause':None,'page':page}
            states[sid] = state
            link('HAS_ARTICLE',document(sid,ev),article,ev)
            body_start = first_clause.start() if first_clause else heading.end()
        elif kind == 'paragraph' and state:
            ev = ref(record,index,text=text)
            body_start = 0
            attach(state['article'],ev)
            link('HAS_ARTICLE',document(sid,ev),state['article'],ev)
        else:
            if CLAUSE.match(text) or POINT.match(text):
                omitted['article_continuation_without_parent'] += 1
            continue
        state['page'] = page
        body = text[body_start:]
        clauses = list(CLAUSE.finditer(body))
        # A page can start inside the previous clause's point list.
        fragments = [(None,body[:clauses[0].start()] if clauses else body)]
        fragments += [(m,body[m.start():clauses[i+1].start() if i+1<len(clauses) else len(body)])
                      for i,m in enumerate(clauses)]
        for match, fragment in fragments:
            fragment = fragment.strip()
            if not fragment:
                continue
            frag_ev = ref(record,index,text=fragment)
            if match:
                clause_no = match[1]
                clause = add(EntityType.CLAUSE,fragment[:350],record,frag_ev,
                             key=f'article:{state["number"]}:clause:{clause_no}',
                             attributes={'clause_number':clause_no,'article_number':state['number'],
                                         'position':int(clause_no)})
                state['clause'] = clause
                link('HAS_CLAUSE',state['article'],clause,frag_ev)
            elif state['clause']:
                clause = state['clause']
                attach(clause,frag_ev)
                link('HAS_CLAUSE',state['article'],clause,frag_ev)
            else:
                if POINT.match(fragment):
                    omitted['point_without_explicit_clause'] += 1
                continue
            points = list(POINT.finditer(fragment))
            for i, point in enumerate(points):
                literal = fragment[point.start():points[i+1].start() if i+1<len(points) else len(fragment)].strip()
                point_ev = ref(record,index,text=literal)
                letter = point[1].casefold()
                point_id = add(EntityType.POINT,literal[:350],record,point_ev,
                    key=f'{clause}:point:{letter}',attributes={'point_letter':letter})
                # Carry the parent anchor when the clause began on an earlier
                # page; neither the source text nor its page is reconstructed.
                anchors = [e for e in entities[clause].evidence if e.pdf_page != page]
                for anchor in anchors:
                    attach(point_id,anchor)
                link('HAS_POINT',clause,point_id,point_ev,extra_evidence=anchors)
