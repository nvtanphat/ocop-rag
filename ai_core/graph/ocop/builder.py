"""graph: materialize evidence extraction JSONL candidates as a source-grounded graph.

Candidate edges remain candidates: nothing here promotes OCR output to legal truth.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterator
from ai_core.domain.ocop_citations import bbox_matches, cell_at, quote_bbox, row_quote_bbox
from ocop_contracts.ids import code_fingerprint, stable_id, content_sha256
from ai_core.graph.ocop.ontology import NODE_TYPES, validate_edge
from ai_core.knowledge.ocop.contracts import AttributeClaim, contains_document_number
from ai_core.retrieval.ocop.index_pipeline import _write_json, _write_jsonl

ALLOWED_STATUSES = frozenset({"verified", "needs_review", "machine_extracted", "candidate", "rejected"})
_ROOT = Path(__file__).resolve().parents[2]
# Graph construction, ontology and citation checks identify the graph schema.
SCHEMA_REVISION = code_fingerprint("graph", [_ROOT / "graph" / "ocop" / "builder.py",
                                            _ROOT / "graph" / "ocop" / "ontology.py",
                                            _ROOT / "graph" / "ocop" / "review.py",
                                            _ROOT / "graph" / "ocop" / "grounding.py",
                                            *(_ROOT / 'knowledge/ocop' / name for name in
                                              ('contracts.py','shapes.py','procedures.py','authorities.py')),
                                            _ROOT / 'processing/ocop/business_candidates.py',
                                            _ROOT.parent / 'configs/ocop_authorities.json',
                                            _ROOT / "domain" / "ocop_citations.py"])

CANDIDATE_FILES = {
    "criterion_candidates": "Criterion", "form_candidates": "FormTemplate",
    "recognition_candidates": "CandidateFact", "taxonomy_candidates": "CandidateFact",
    "temporal_candidates": "CandidateFact", "domain_facts": "CandidateFact",
}

def records(file: Path) -> Iterator[dict]:
    if not file.is_file():
        return
    with file.open(encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL {file}:{number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"Expected JSON object at {file}:{number}")
                yield row

def _status(row: dict) -> str:
    return str(row.get("review_status", "needs_review"))


def _span_citations(unit: dict, evidence_id: str, source_id: str) -> list[dict] | None:
    if unit.get("source_id")!=source_id or not unit.get("spans"):
        return None
    result=[]
    for span in unit["spans"]:
        sha=str(span.get("source_sha256") or "")
        bbox=span.get("bbox")
        if (not re.fullmatch(r"[0-9a-f]{64}",sha) or not bbox or len(bbox)!=4 or
            span.get("pdf_page") is None):
            return None
        ref={"source_id":source_id,"evidence_unit_id":evidence_id,
             "pdf_page":int(span["pdf_page"]),"bbox":bbox,"source_sha256":sha}
        for key in ("table_id","cell_id","block_id","printed_page"):
            if span.get(key) is not None:
                ref[key]=span[key]
        result.append(ref)
    return result or None


def _specific_citation(ref: dict, unit: dict) -> dict | None:
    source_id=ref.get("source_id")
    evidence_id=ref.get("evidence_unit_id")
    quote=str(ref.get("quote") or "").strip()
    if (not source_id or unit.get("source_id")!=source_id or not evidence_id or
        not quote or ref.get("bbox") is None):
        return None
    try:
        page=int(ref.get("pdf_page"))
    except (TypeError,ValueError):
        return None
    spans=[s for s in unit.get("spans",[]) if int(s.get("pdf_page",-1))==page]
    shas={str(s.get("source_sha256") or "") for s in spans}
    if (not spans or len(shas)!=1 or
        not re.fullmatch(r"[0-9a-f]{64}",next(iter(shas)))):
        return None
    if ref.get('source_sha256') is not None and ref['source_sha256'] not in shas:
        return None
    table=unit.get("structured",{}).get("table_id")
    if ref.get("table_id") and table and ref["table_id"]!=table:
        return None
    cell_id=ref.get("cell_id")
    row=ref.get("row")
    if cell_id:
        match=re.search(r":r(\d+):c(\d+)$",str(cell_id))
        if not match:
            return None
        row_no,col=int(match.group(1)),int(match.group(2))
        if ref.get("table_id") and not str(cell_id).startswith(str(ref["table_id"])+":r"):
            return None
        cell=cell_at(unit,row_no,col)
        if (cell is None or quote!=str(cell.get("text") or "").strip() or
            not bbox_matches(ref.get("bbox"),cell.get("bbox"))):
            return None
        if row is not None and int(row)!=row_no:
            return None
    elif row is not None:
        row_data=row_quote_bbox(unit,int(row))
        if (row_data is None or quote!=row_data[0][:1200] or
            not bbox_matches(ref.get("bbox"),row_data[1])):
            return None
    else:
        if quote not in str(unit.get("text") or ""):
            return None
        expected=quote_bbox(unit,page,quote)
        if not bbox_matches(ref.get("bbox"),expected):
            return None
    citation={"source_id":source_id,"evidence_unit_id":evidence_id,
              "pdf_page":page,"bbox":ref["bbox"],"source_sha256":next(iter(shas)),
              "quote":quote}
    for key in ("table_id","row","cell_id"):
        if ref.get(key) is not None:
            citation[key]=ref[key]
    return citation


def _dedupe_citations(citations: list[dict]) -> list[dict]:
    seen=set();result=[]
    for citation in citations:
        key=json.dumps(citation,sort_keys=True,ensure_ascii=False,separators=(",",":"))
        if key not in seen:
            seen.add(key);result.append(citation)
    return result

def _with_provenance(row: dict) -> dict:
    """Keep LLM origin visible to reviewers; deterministic rows keep their properties unchanged."""
    properties=dict(row.get('attributes') or {})
    method=str(row.get('extraction_method') or '')
    if method.startswith('llm_candidate'):
        properties['extraction_method']=method
    return properties

def build_graph(knowledge: Path, output: Path, *, include_candidates: bool = True,
                allow_partial: bool = False, review_decisions: Path | None = None) -> dict:
    src = json.loads((knowledge / "manifest.json").read_text(encoding="utf-8"))
    source_complete=bool(src.get("complete"))
    if not source_complete and not allow_partial:
        raise ValueError("evidence extraction knowledge manifest incomplete")
    version = src["corpus_version"]
    nodes: dict[str, dict] = {}; edges: dict[str, dict] = {}; rejected: list[dict] = []
    evidence_by_id: dict[str, dict] = {}
    document_registry = src.get('document_registry') or {}

    def resolved_document(node: dict, citing_source: str) -> bool:
        number = document_registry.get(node['source_id'], {}).get('document_number')
        return bool(node['node_type'] == 'SourceDocument' and number and
                    node['properties'].get('registry_source_id') == node['source_id'] and
                    any(c.get('source_id') == citing_source and contains_document_number(c.get('quote',''),number)
                        for c in node.get('citations',[])))
    def add_node(node_id: str, kind: str, *, source_id: str, evidence_ids: list[str], status: str,
                 label: str, properties: dict | None = None, citations: list[dict] | None = None):
        if not node_id or kind not in NODE_TYPES:
            raise ValueError(f"Invalid node id or type: {node_id} / {kind}")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid node review status: {status}")
        row = {"node_id": node_id, "node_type": kind, "source_id": source_id,
               "evidence_unit_ids": sorted(set(evidence_ids)), "review_status": status,
               "label": label[:250], "properties": properties or {}, "corpus_version": version}
        if citations is not None:
            row["citations"]=_dedupe_citations(citations)
        old = nodes.get(node_id)
        if old:
            # Multiple rows may refer to the same *identical* entity, but
            # a conflicting label/status/attributes is never last-write-wins.
            identity_fields = ("node_type", "source_id", "review_status", "label", "properties")
            if any(old[field] != row[field] for field in identity_fields):
                raise ValueError(f"Conflicting duplicate node collision: {node_id}")
            old["evidence_unit_ids"] = sorted(set(old["evidence_unit_ids"] + row["evidence_unit_ids"]))
            if citations is not None:
                old["citations"]=_dedupe_citations(old.get("citations",[])+row["citations"])
            return
        nodes[node_id] = row
    def add_edge(relation: str, start: str, end: str, evidence_id: str, source_id: str, status: str,
                 *, evidence_ref: dict | None = None, attributes: dict | None = None):
        def reject(reason: str):
            rejected.append({"relation": relation, "source_entity_id": start,
                             "target_entity_id": end, "evidence_unit_id": evidence_id,
                             "reason": reason})
            identity = stable_id("kg_edge", source_id, [start, relation, end], revision=version)
            if identity not in edges:
                edges[identity] = {"edge_id": identity, "relation_type": relation,
                    "source_entity_id": start, "target_entity_id": end, "source_id": source_id,
                    "evidence_unit_id": evidence_id, "evidence_unit_ids": [evidence_id],
                    "review_status": status, "corpus_version": version,
                    "properties": attributes or {}, "citations": [evidence_ref] if evidence_ref else [],
                    "construction_error": reason}
        if status not in ALLOWED_STATUSES:
            reject("invalid_edge_status"); return
        if start not in nodes or end not in nodes:
            reject("missing_endpoint"); return
        check = validate_edge(relation, nodes[start]["node_type"], nodes[end]["node_type"])
        if not check.ok:
            reject(check.reason); return
        unit = evidence_by_id.get(evidence_id)
        if unit is None:
            reject("missing_edge_evidence"); return
        cross_relations = {'AMENDS','REPLACES','SUSPENDS','BASED_ON','SUPPORTED_BY'}
        if (unit.get("source_id") != source_id or
            any(node['source_id'] != source_id and
                (relation not in cross_relations or not resolved_document(node,source_id))
                for node in (nodes[start],nodes[end]))):
            reject("edge_source_mismatch"); return
        if evidence_ref is not None:
            if evidence_ref.get("evidence_unit_id")!=evidence_id:
                reject("invalid_edge_evidence_reference"); return
            citation=_specific_citation(evidence_ref,unit)
            if citation is None:
                reject("invalid_edge_evidence_reference"); return
            citations=[citation]
        else:
            citations=_span_citations(unit,evidence_id,source_id)
            if citations is None:
                reject("missing_source_citation"); return
        # SourceDocument denotes the entire source; other grounded endpoints
        # must be justified by exactly the same evidence unit.
        for endpoint in (nodes[start], nodes[end]):
            refs = endpoint["evidence_unit_ids"]
            if endpoint["node_type"] != "SourceDocument" and refs and evidence_id not in refs:
                reject("edge_not_shared_by_endpoint"); return
        if status == "verified" and (unit.get("review_status") != "verified" or
            nodes[start]["review_status"] != "verified" or
            nodes[end]["review_status"] != "verified"):
            reject("verified_edge_with_unverified_proof"); return
        edge_id = stable_id("kg_edge", source_id, [start, relation, end], revision=version)
        row = {"edge_id": edge_id, "relation_type": relation, "source_entity_id": start,
               "target_entity_id": end, "evidence_unit_id": evidence_id, "source_id": source_id,
               "review_status": status, "corpus_version": version,
               "citations": _dedupe_citations(citations), "evidence_unit_ids": [evidence_id]}
        if attributes:
            row['properties'] = attributes
        old = edges.get(edge_id)
        if old and not old.get('construction_error'):
            identity_fields=("relation_type", "source_entity_id", "target_entity_id", "source_id", "review_status")
            if any(old.get(key)!=row.get(key) for key in identity_fields):
                raise ValueError(f"Conflicting duplicate edge collision: {edge_id}")
            old["citations"]=_dedupe_citations(old.get("citations",[])+row["citations"])
            old['evidence_unit_ids']=sorted(set(old['evidence_unit_ids']+[evidence_id]))
            # Conflicting candidate attributes remain visible, never last-write-wins.
            if old.get('properties',{}) != row.get('properties',{}):
                variants=old.setdefault('attribute_candidates', [old.get('properties',{})])
                if row.get('properties',{}) not in variants:
                    variants.append(row.get('properties',{}))
        else:
            edges[edge_id] = row
    # Read the evidence registry FIRST so original entity nodes are held to the
    # same source-grounding contract as typed business entities.
    all_evidence = list(records(knowledge / "evidence_units.jsonl"))
    for row in all_evidence:
        evid = row["unit_id"]
        if evid in evidence_by_id and evidence_by_id[evid] != row:
            raise ValueError(f"Conflicting duplicate evidence collision: {evid}")
        evidence_by_id[evid] = row
    # Stable identity maps: an extracted document/evidence entity and a later
    # synthesized node MUST NOT represent the same real-world source twice.
    original_entities = []
    for row in records(knowledge / "entities.jsonl"):
        refs = row.get("evidence_unit_ids", [])
        if (any(uid not in evidence_by_id or
                evidence_by_id[uid].get("source_id") != row.get("source_id") for uid in refs)
            or (row.get("review_status") == "verified" and any(
                evidence_by_id[uid].get("review_status") != "verified" for uid in refs))):
            rejected.append({"reason":"original_entity_invalid_evidence", "entity_id":row.get("entity_id")})
            continue
        original_entities.append(row)
    source_node_ids: dict[str, str] = {}
    evidence_node_ids: dict[tuple[str, str], str] = {}
    aliases: dict[str, str] = {}
    for entity in sorted(original_entities, key=lambda r: r["entity_id"]):
        typ, source = entity.get("entity_type"), entity["source_id"]
        if typ == "source_document":
            canonical = source_node_ids.setdefault(source, entity["entity_id"])
            aliases[entity["entity_id"]] = canonical
        if typ == "evidence_unit" and len(entity.get("evidence_unit_ids", [])) == 1:
            unit_id = entity["evidence_unit_ids"][0]
            canonical = evidence_node_ids.setdefault((source, unit_id), entity["entity_id"])
            aliases[entity["entity_id"]] = canonical
    # Original entities, irrespective of ordering in JSONL.
    for row in original_entities:
        if aliases.get(row["entity_id"], row["entity_id"]) != row["entity_id"]:
            continue
        kind = {"source_document":"SourceDocument", "evidence_unit":"EvidenceUnit",
                "article":"Article", "clause":"Clause",
                "criterion_table_candidate":"CandidateFact"}.get(row.get("entity_type"), "Mention")
        add_node(row["entity_id"],kind,source_id=row["source_id"],
                 evidence_ids=row.get("evidence_unit_ids",[]),status=_status(row),label=str(row.get("name",kind)))
    # Guarantee every evidence is addressable, including page-root.
    for ordinal,row in enumerate(all_evidence):
        evid = row["unit_id"]; source = row["source_id"]
        eid = evidence_node_ids.setdefault((source, evid), stable_id("evidence_node",source,[evid],revision=version))
        if eid not in nodes:
            add_node(eid,"EvidenceUnit",source_id=source,evidence_ids=[evid],status=_status(row),
                     label=row.get("unit_kind","evidence"),
                     citations=_span_citations(row,evid,source) or [])
        # Evidence nodes carry page spans for source round trips.
        nodes[eid]["properties"].update({"source_spans": row.get("spans", []), "unit_kind": row.get("unit_kind")})
        # One immutable source for runtime structure and its original evidence.
        # This is a transcription, never a promotion of OCR to verified facts.
        nodes[eid]['properties'].update({'evidence_text':row.get('text',''),
            'structured':row.get('structured') or {}, 'source_order':ordinal})
        nodes[eid]['citations'] = _span_citations(row, evid, source) or []
        # The source document node is created even when the extractor didn't emit an entity.
        source_node = source_node_ids.setdefault(source, stable_id("document_node",source,[source],revision=version))
        if source_node not in nodes:
            add_node(source_node,"SourceDocument",source_id=source,evidence_ids=[],status="machine_extracted",label=source)
        add_edge("LOCATED_IN",eid,source_node,evid,source,_status(row))
    has_business_layer = (knowledge / "business_entities.jsonl").exists()
    # Domain candidates with evidence references but no fabricated structured score options.
    if include_candidates:
        for stem, kind in CANDIDATE_FILES.items():
            if has_business_layer and stem in ("criterion_candidates", "form_candidates", "recognition_candidates"):
                continue  # replaced by typed, grounded business ontology
            for row in records(knowledge / (stem+".jsonl")):
                evid = row.get("evidence_unit_id")
                if evid not in evidence_by_id:
                    rejected.append({"reason":"orphan_candidate","stem":stem,"candidate_id":row.get("candidate_id")});continue
                if evidence_by_id[evid]["source_id"] != row.get("source_id"):
                    rejected.append({"reason":"candidate_source_mismatch","stem":stem,"candidate_id":row.get("candidate_id")});continue
                cid = row.get("candidate_id") or row.get("fact_id")
                if not cid:continue
                source = row["source_id"]
                citations=_span_citations(evidence_by_id[evid],evid,source)
                if citations is None:
                    rejected.append({"reason":"candidate_missing_source_citation","stem":stem,"candidate_id":cid})
                    continue
                add_node(cid,kind,source_id=source,evidence_ids=[evid],status=_status(row),
                    label=str(row.get("title") or row.get("label_candidate") or row.get("heading") or row.get("row_text") or stem),
                    properties={"record_kind":stem,"pdf_page":row.get("pdf_page")},
                    citations=citations)
                evidence_node = evidence_node_ids[(source, evid)]
                add_edge("SUPPORTED_BY",cid,evidence_node,evid,source,_status(row))
    # Form-field candidates are derived from OCR field labels, never promoted
    # to verified required fields at this stage.
    for row in (records(knowledge / "form_candidates.jsonl") if include_candidates and not has_business_layer else ()):
        form_id=row.get("candidate_id");source=row.get("source_id");evid=row.get("evidence_unit_id")
        if not form_id or not source or evid not in evidence_by_id or evidence_by_id[evid]["source_id"] != source or form_id not in nodes:
            continue
        for position,label in enumerate(row.get("fields_candidate",[])[:35]):
            value=str(label).strip()
            if not value:continue
            fid=stable_id("form_field_candidate",source,[form_id,position,value],revision=version)
            add_node(fid,"FormField",source_id=source,evidence_ids=[evid],
                     status="needs_review",label=value,properties={"field_position":position},
                     citations=_span_citations(evidence_by_id[evid],evid,source) or [])
            add_edge("HAS_FIELD",form_id,fid,evid,source,"needs_review")
    # Business-grounded, strictly typed layer. This REPLACES legacy domain
    # candidate materialization when available, avoiding duplicate products,
    # decisions and form fields. All OCR candidates remain unverified.
    if has_business_layer and include_candidates:
        business_rows=list(records(knowledge / 'business_entities.jsonl'))
        # Debug extraction layers remain in knowledge/index. The agent graph
        # exposes typed criteria/options and MINIMUM_FOR instead of their shadows.
        debug_ids={r['entity_id'] for r in business_rows
                   if r['kind']=='CriterionRowCandidate' or
                   (r['kind']=='Condition' and 'marker_observed' in r.get('attributes',{}))}
        for row in records(knowledge / "business_entities.jsonl"):
            if row['entity_id'] in debug_ids:
                continue
            refs = row.get("evidence", [])
            if row['kind'] != 'SourceDocument' and any(
                    not isinstance(ref, dict) or ref.get('source_id') != row.get('source_id') for ref in refs):
                rejected.append({'reason': 'business_entity_source_mismatch', 'entity_id': row.get('entity_id')})
                continue
            citations=[]
            valid_refs=[]
            for ref in refs:
                unit=evidence_by_id.get(ref.get("evidence_unit_id")) if isinstance(ref,dict) else None
                citation=_specific_citation(ref,unit) if unit else None
                if citation:
                    valid_refs.append(ref);citations.append(citation)
            if (len(valid_refs) != len(refs) or not refs or
                (row.get("status") == "verified" and any(
                    evidence_by_id[r["evidence_unit_id"]].get("review_status") != "verified"
                    for r in valid_refs))):
                rejected.append({"reason":"business_entity_missing_evidence", "entity_id":row.get("entity_id")})
                continue
            # Attribute proof is validated independently of the entity's name.
            claims = row.get('attribute_claims', [])
            try:
                if not isinstance(claims, list):
                    raise ValueError('attribute claims must be a list')
                for claim in claims:
                    AttributeClaim.model_validate(claim)
            except (ValueError, TypeError):
                rejected.append({'reason': 'business_attribute_schema_invalid', 'entity_id': row.get('entity_id')})
                continue
            if any(not claim.get('attribute', '').endswith('_candidate') or
                   any(ref not in refs or _specific_citation(ref, evidence_by_id.get(ref.get('evidence_unit_id'), {})) is None
                       for ref in claim.get('evidence', [])) for claim in claims):
                rejected.append({'reason': 'business_attribute_missing_evidence', 'entity_id': row.get('entity_id')})
                continue
            node_id = row['entity_id']
            status = "needs_review" if row.get("status") == "candidate" else row["status"]
            if row['kind'] == 'SourceDocument':
                source = row['source_id']
                node_id = source_node_ids.setdefault(source,
                    stable_id('document_node',source,[source],revision=version))
                aliases[row['entity_id']] = node_id
            if row['kind'] == 'SourceDocument' and node_id in nodes:
                # Metadata candidates belong to the existing document identity,
                # including references resolved from a different source PDF.
                old = nodes[node_id]
                old['evidence_unit_ids'] = sorted(set(old['evidence_unit_ids'] +
                    [r['evidence_unit_id'] for r in refs]))
                old['citations'] = _dedupe_citations(old.get('citations',[]) + citations)
                old['properties'].update(row.get('attributes',{}))
                old['review_status'] = status
                if row.get('attributes',{}).get('document_number_candidate') is not None:
                    old['label'] = row['label'][:250]
            else:
                add_node(node_id, row["kind"],source_id=row["source_id"],
                         evidence_ids=[r["evidence_unit_id"] for r in refs],status=status,
                         label=(row.get('attributes',{}).get('document_number_candidate') or
                                document_registry.get(row['source_id'],{}).get('document_number') or row['label'])
                                if row['kind'] in {'RecognitionDecision','LocalGuidance','SourceDocument'} else row['label'],
                         properties=_with_provenance(row),citations=citations)
            if claims:
                nodes[node_id]['attribute_claims'] = claims
            for ref in refs:
                add_edge("SUPPORTED_BY",node_id,
                         evidence_node_ids[(ref["source_id"],ref["evidence_unit_id"])],
                         ref["evidence_unit_id"],ref["source_id"],
                         "verified" if row.get("status")=="verified" else "needs_review",
                         evidence_ref=ref,
                         attributes={key: value for key, value in _with_provenance(row).items()
                                     if key in {'extraction_method', 'llm_enriched_attributes'}} or None)
        for row in records(knowledge / "business_relations.jsonl"):
            if row['source_entity_id'] in debug_ids or row['target_entity_id'] in debug_ids:
                continue
            for ref in row.get("evidence", []):
                add_edge(row["relation_type"],aliases.get(row["source_entity_id"],row["source_entity_id"]),
                         aliases.get(row["target_entity_id"],row["target_entity_id"]),
                         ref["evidence_unit_id"],ref["source_id"],
                         "needs_review" if row.get("status") == "candidate" else row["status"],
                         evidence_ref=ref, attributes=_with_provenance(row) or None)
        for row in records(knowledge / "business_rules.jsonl"):
            if row.get('kind')=='scoring':
                continue  # raw scoring statements are retained in knowledge for debug/retrieval
            refs=row.get("evidence", [])
            if any(not isinstance(ref, dict) or ref.get('source_id') != row.get('source_id') for ref in refs):
                rejected.append({'reason': 'business_rule_source_mismatch', 'rule_id': row.get('rule_id')})
                continue
            citations=[]
            for ref in refs:
                unit=evidence_by_id.get(ref.get("evidence_unit_id")) if isinstance(ref,dict) else None
                citation=_specific_citation(ref,unit) if unit else None
                if citation:
                    citations.append(citation)
            if not refs or len(citations)!=len(refs):
                rejected.append({"reason":"business_rule_missing_evidence","rule_id":row.get("rule_id")})
                continue
            source=row["source_id"]
            add_node(row["rule_id"],"RuleCandidate",source_id=source,
                     evidence_ids=[r["evidence_unit_id"] for r in refs],
                     status="needs_review" if row.get("status") == "candidate" else row["status"],
                     label=row["statement"],properties={"modality":row["kind"],"executable":False},
                     citations=citations)
            for ref in refs:
                add_edge("SUPPORTED_BY",row["rule_id"],
                         evidence_node_ids[(source,ref["evidence_unit_id"])],
                         ref["evidence_unit_id"],source,"needs_review",evidence_ref=ref)
    # evidence extraction edges refer to evidence extraction entities; verify both ends AND source evidence.
    for row in records(knowledge / "relations.jsonl"):
        if row.get("evidence_unit_id") not in evidence_by_id:
            rejected.append({"reason":"missing_relation_evidence","relation_id":row.get("relation_id")})
            continue
        if evidence_by_id[row["evidence_unit_id"]]["source_id"] != row["source_id"]:
            rejected.append({"reason":"relation_evidence_source_mismatch","relation_id":row.get("relation_id")})
            continue
        add_edge(row["relation_type"],aliases.get(row["source_entity_id"],row["source_entity_id"]),
                 aliases.get(row["target_entity_id"],row["target_entity_id"]),
                 row["evidence_unit_id"],row["source_id"],_status(row))
    # Invalid input assertions remain inspectable in the same graph; their
    # construction error can never be promoted by the semantic or review gate.
    failed_entities = {r.get('entity_id'): r['reason'] for r in rejected if r.get('entity_id')}
    for filename in ('entities.jsonl', 'business_entities.jsonl'):
        for row in records(knowledge / filename):
            identity = row.get('entity_id')
            if identity not in failed_entities or identity in nodes:
                continue
            kind = row.get('kind') or {'source_document': 'SourceDocument',
                'evidence_unit': 'EvidenceUnit', 'article': 'Article', 'clause': 'Clause'}.get(row.get('entity_type'), 'Mention')
            refs = row.get('evidence', [])
            add_node(identity, kind, source_id=row['source_id'],
                evidence_ids=row.get('evidence_unit_ids') or [r['evidence_unit_id'] for r in refs if isinstance(r, dict) and r.get('evidence_unit_id')],
                status=_status(row) if filename == 'entities.jsonl' else row.get('status', 'candidate'),
                label=str(row.get('label') or row.get('name') or kind),
                properties=_with_provenance(row), citations=refs)
            nodes[identity]['construction_error'] = failed_entities[identity]
    for node in nodes.values():
        if node['node_type'] in {'SourceDocument','RecognitionDecision','LocalGuidance'}:
            number=(node['properties'].get('document_number_candidate') or
                    document_registry.get(node['source_id'],{}).get('document_number'))
            if number:
                node['label']=number
    out_nodes = [nodes[k] for k in sorted(nodes)]; out_edges = [edges[k] for k in sorted(edges)]
    review_manifest={}
    if review_decisions is not None:
        from ai_core.graph.ocop.review import apply_decisions
        review_manifest=apply_decisions(out_nodes,out_edges,evidence_by_id,review_decisions)
    from ai_core.graph.ocop.grounding import check_graph
    out_nodes, out_edges, checks = check_graph(
        out_nodes, out_edges, evidence_by_id, registry=document_registry)
    # A fingerprint of the *source bytes* also detects edits to evidence text,
    # even if node IDs, spans and labels themselves happen not to change.
    knowledge_files = sorted(knowledge.glob("*.jsonl")) + [knowledge / "manifest.json"]
    source_fingerprint = content_sha256(b"".join(
        f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0" for f in knowledge_files))
    payload = json.dumps({"nodes":out_nodes,"edges":out_edges,"rejected":rejected,
                          "source_knowledge_sha256":source_fingerprint,
                          "corpus_version":version,"candidate_mode":include_candidates,
                          "source_complete":source_complete,
                          "human_review":review_manifest,
                          'checks': checks,
                          "schema_revision":SCHEMA_REVISION},ensure_ascii=False,sort_keys=True,
                         separators=(",",":"))
    graph_version = content_sha256(payload)[:20]
    output.mkdir(parents=True, exist_ok=True)
    # A complete immutable snapshot is persisted first. The old root layout
    # remains for existing callers; its manifest is committed LAST. Readers
    # with a manifest verify all hashes, and refuse torn/mixed generations.
    stage = Path(tempfile.mkdtemp(prefix=".graph-stage-", dir=output))
    try:
        _write_jsonl(stage/"nodes.jsonl",out_nodes)
        _write_jsonl(stage/"edges.jsonl",out_edges)
        snapshot_files = ('nodes.jsonl', 'edges.jsonl')
        file_hashes={f:content_sha256((stage/f).read_bytes()) for f in
                     snapshot_files}
        manifest={"graph_version":graph_version,"source_knowledge_version":version,
            "human_review":review_manifest,
            'checks': checks,
            'construction_failures': rejected,
            "source_knowledge_sha256":source_fingerprint, "schema_revision":SCHEMA_REVISION,
            "status":"local_ready" if source_complete else "partial_debug_not_production",
            "source_complete":source_complete,
            "counts":{"nodes":len(out_nodes),"edges":len(out_edges),"rejected":len(rejected)},
            "node_ids_sha256":content_sha256("\n".join(n["node_id"] for n in out_nodes)),
            "edge_ids_sha256":content_sha256("\n".join(e["edge_id"] for e in out_edges)),
            "file_sha256":file_hashes, "candidate_mode":include_candidates, "neo4j":{"enabled":False}}
        _write_json(stage/"manifest.json",manifest)
        snapshots = output / "snapshots"
        snapshots.mkdir(exist_ok=True)
        snapshot_dir = snapshots/graph_version
        if snapshot_dir.exists():
            from ai_core.graph.ocop.integrity import validate_graph_snapshot
            validate_graph_snapshot(snapshot_dir,allow_partial=allow_partial)
            if (snapshot_dir/"manifest.json").read_bytes() != (stage/"manifest.json").read_bytes():
                raise ValueError("Snapshot version collision")
        else:
            # Atomic creation of an immutable directory on the same filesystem.
            pending = Path(tempfile.mkdtemp(prefix=".snapshot-pending-", dir=snapshots))
            try:
                for filename in (*snapshot_files, 'manifest.json'):
                    shutil.copyfile(stage/filename,pending/filename)
                os.replace(pending,snapshot_dir)
            finally:
                if pending.exists():
                    shutil.rmtree(pending,ignore_errors=True)
        for filename in snapshot_files:
            temp_file=output/("."+filename+".next")
            shutil.copyfile(stage/filename,temp_file)
            os.replace(temp_file,output/filename)
        os.replace(stage/"manifest.json",output/"manifest.json")
        # Historical snapshots remain immutable.
        (output / 'rejected.jsonl').unlink(missing_ok=True)
        return manifest
    finally:
        shutil.rmtree(stage,ignore_errors=True)
