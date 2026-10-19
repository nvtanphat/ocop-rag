"""Opt-in Qwen3.5-2B structured candidate proposer.

The LLM is NEVER a fact authority: every named item and every relation must
match exact text in a particular EvidenceUnit. Invalid model output is skipped.
No model is downloaded or called unless explicitly enabled by the operator.
"""
from __future__ import annotations
import json
from typing import Protocol
from ai_core.domain.ocop_ids import stable_id
from .contracts import (
    BusinessEntity, BusinessRelation, BusinessRule, EvidenceRef,
    EntityType, RELATION_TYPES, validate_business_graph,
)

class StructuredLLM(Protocol):
    model: str
    def chat(self, system: str, user: str, *, format_json: bool = False, max_tokens: int = 1024) -> str: ...

SYSTEM = '''You extract OCOP facts ONLY from the quoted source. Do not use external knowledge.
Return ONE JSON object with these arrays: entities, relations, rules.
Entity: {"kind":"Criterion|ScoreOption|EvidenceType|ProductGroup|ProductSubgroup|Condition|Product|Organization", "anchor":"VERBATIM substring of input"}.
Relation: {"type":"HAS_OPTION|HAS_CONDITION|REQUIRES_EVIDENCE|HAS_SUBGROUP", "source_anchor":"exact anchor", "target_anchor":"exact anchor", "proof":"VERBATIM passage directly expressing relationship"}.
Rule: {"kind":"obligation|prohibition|permission|exemption|scoring|temporal", "anchor":"VERBATIM rule sentence"}.
Only source-level claims. Never infer missing point scores, star requirements, legal dates, producers or evidence types. No cross-document entity links. Output only JSON.''' 


def propose(units: list[dict], client: StructuredLLM, *, max_units: int = 50) -> dict[str, list[dict]]:
    if not (0 <= max_units <= 500):
        raise ValueError('max_units must be 0..500')
    ent: dict[str, BusinessEntity] = {}
    rel: dict[str, BusinessRelation] = {}
    rules: dict[str, BusinessRule] = {}
    failures = []
    accepted = 0
    allowed_kinds = {e.value:e for e in EntityType}
    permitted = {'Criterion','ScoreOption','EvidenceType','ProductGroup','ProductSubgroup',
                 'Condition','Product','Organization'}
    target_units = [u for u in units if u.get('unit_kind') in ('article','paragraph','section','table','criterion_table_candidate') and u.get('text','').strip()]
    for u in target_units[:max_units]:
        body = u['text'][:2500]
        sid, uid = u['source_id'],u['unit_id']
        span = u['spans'][0]
        def evidence(anchor: str) -> EvidenceRef | None:
            if not isinstance(anchor,str) or len(anchor.strip()) < 3 or anchor not in body:
                return None
            return EvidenceRef(source_id=sid,evidence_unit_id=uid,
                               pdf_page=span['pdf_page'],bbox=span.get('bbox'),quote=anchor)
        try:
            response = json.loads(client.chat(SYSTEM,body,format_json=True,max_tokens=1600))
            if not isinstance(response,dict):
                raise ValueError('not an object')
            locals_by_anchor = {}
            for obj in response.get('entities', [])[:30]:
                kind,anchor = obj.get('kind'), obj.get('anchor')
                if kind not in permitted:
                    continue
                ev = evidence(anchor)
                if ev is None:
                    continue
                entity_id=stable_id('llm_entity',sid,[uid,kind,anchor],revision='business')
                ent[entity_id]=BusinessEntity(entity_id=entity_id,kind=allowed_kinds[kind],
                       label=anchor,source_id=sid,evidence=[ev],
                       extraction_method=f'llm_candidate:{client.model}')
                locals_by_anchor[(kind,anchor)] = entity_id
            for obj in response.get('relations', [])[:30]:
                relation_type = obj.get('type')
                endpoints=RELATION_TYPES.get(relation_type)
                if endpoints is None:
                    continue
                def resolve_endpoint(expected,anchor):
                    kinds=expected if isinstance(expected,frozenset) else {expected}
                    matches={locals_by_anchor[(kind.value,anchor)] for kind in kinds
                             if (kind.value,anchor) in locals_by_anchor}
                    return next(iter(matches)) if len(matches)==1 else None
                src=resolve_endpoint(endpoints[0],obj.get('source_anchor'))
                dst=resolve_endpoint(endpoints[1],obj.get('target_anchor'))
                ev=evidence(obj.get('proof'))
                if src is None or dst is None or ev is None:
                    continue
                rid=stable_id('llm_relation',sid,[uid,relation_type,src,dst,ev.quote],revision='business')
                rel[rid]=BusinessRelation(relation_id=rid,relation_type=relation_type,
                  source_entity_id=src,target_entity_id=dst,evidence=[ev],
                  extraction_method=f'llm_candidate:{client.model}')
            for obj in response.get('rules', [])[:15]:
                kind, anchor = obj.get('kind'),obj.get('anchor')
                ev=evidence(anchor)
                if ev is None or kind not in ('obligation','prohibition','permission','exemption','scoring','temporal'):
                    continue
                rid=stable_id('llm_rule',sid,[uid,kind,anchor],revision='business')
                rules[rid]=BusinessRule(rule_id=rid,source_id=sid,kind=kind,
                     statement=anchor,evidence=[ev])
            accepted += 1
        except (RuntimeError,ValueError,TypeError,KeyError,IndexError) as exc:
            failures.append({'evidence_unit_id':uid,'error_type':type(exc).__name__})
            continue
    validate_business_graph(list(ent.values()),list(rel.values()))
    return {
      'entities':[e.model_dump(mode='json') for e in ent.values()],
      'relations':[r.model_dump(mode='json') for r in rel.values()],
      'rules':[r.model_dump(mode='json') for r in rules.values()],
      'errors':failures,
      'processed_unit_count':accepted,
    }
