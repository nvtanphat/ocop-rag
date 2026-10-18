"""graph: materialize evidence extraction JSONL candidates as a source-grounded graph.

Candidate edges remain candidates: nothing here promotes OCR output to legal truth.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator
from ai_core.domain.ocop_ids import stable_id, content_sha256
from ai_core.graph.ocop.ontology import NODE_TYPES, validate_edge
from ai_core.retrieval.ocop.index_pipeline import _write_json, _write_jsonl

ALLOWED_STATUSES = frozenset({"verified", "needs_review", "machine_extracted", "candidate", "rejected"})

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

def build_graph(knowledge: Path, output: Path, *, include_candidates: bool = True) -> dict:
    src = json.loads((knowledge / "manifest.json").read_text(encoding="utf-8"))
    if not src.get("complete"):
        raise ValueError("evidence extraction knowledge manifest incomplete")
    version = src["corpus_version"]
    nodes: dict[str, dict] = {}; edges: dict[str, dict] = {}; rejected: list[dict] = []
    evidence_by_id: dict[str, dict] = {}
    def add_node(node_id: str, kind: str, *, source_id: str, evidence_ids: list[str], status: str,
                 label: str, properties: dict | None = None):
        if not node_id or kind not in NODE_TYPES:
            raise ValueError(f"Invalid node id or type: {node_id} / {kind}")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid node review status: {status}")
        row = {"node_id": node_id, "node_type": kind, "source_id": source_id,
               "evidence_unit_ids": sorted(set(evidence_ids)), "review_status": status,
               "label": label[:250], "properties": properties or {}, "corpus_version": version}
        old = nodes.get(node_id)
        if old:
            # Multiple rows may refer to the same *identical* entity, but
            # a conflicting label/status/attributes is never last-write-wins.
            identity_fields = ("node_type", "source_id", "review_status", "label", "properties")
            if any(old[field] != row[field] for field in identity_fields):
                raise ValueError(f"Conflicting duplicate node collision: {node_id}")
            old["evidence_unit_ids"] = sorted(set(old["evidence_unit_ids"] + row["evidence_unit_ids"]))
            return
        nodes[node_id] = row
    def add_edge(relation: str, start: str, end: str, evidence_id: str, source_id: str, status: str,
                 *, evidence_ref: dict | None = None):
        def reject(reason: str):
            rejected.append({"relation": relation, "source_entity_id": start,
                             "target_entity_id": end, "evidence_unit_id": evidence_id,
                             "reason": reason})
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
        if evidence_ref is not None:
            pages = [span.get("pdf_page") for span in unit.get("spans", [])]
            if (evidence_ref.get("source_id") != source_id or
                not str(evidence_ref.get("quote") or "").strip() or
                (pages and evidence_ref.get("pdf_page") not in pages)):
                reject("invalid_edge_evidence_reference"); return
        if (unit.get("source_id") != source_id or
            nodes[start]["source_id"] != source_id or nodes[end]["source_id"] != source_id):
            reject("edge_source_mismatch"); return
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
        edge_id = stable_id("kg_edge", source_id, [start, relation, end, evidence_id], revision=version)
        row = {"edge_id": edge_id, "relation_type": relation, "source_entity_id": start,
               "target_entity_id": end, "evidence_unit_id": evidence_id, "source_id": source_id,
               "review_status": status, "corpus_version": version}
        old = edges.get(edge_id)
        if old and old != row:
            raise ValueError(f"Conflicting duplicate edge collision: {edge_id}")
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
    for row in all_evidence:
        evid = row["unit_id"]; source = row["source_id"]
        eid = evidence_node_ids.setdefault((source, evid), stable_id("evidence_node",source,[evid],revision=version))
        if eid not in nodes:
            add_node(eid,"EvidenceUnit",source_id=source,evidence_ids=[evid],status=_status(row),label=row.get("unit_kind","evidence"))
        # Evidence nodes carry page spans for source round trips.
        nodes[eid]["properties"].update({"source_spans": row.get("spans", []), "unit_kind": row.get("unit_kind")})
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
                add_node(cid,kind,source_id=source,evidence_ids=[evid],status=_status(row),
                    label=str(row.get("title") or row.get("label_candidate") or row.get("heading") or row.get("row_text") or stem),
                    properties={"record_kind":stem,"pdf_page":row.get("pdf_page")})
                evidence_node = evidence_node_ids[(source, evid)]
                add_edge("SUPPORTED_BY",cid,evidence_node,evid,source,_status(row))
    # Domain entity candidates can be inferred only from clearly structured
    # recognition tables. Keep them unverified, never impute merged cells or
    # missing producer names from neighboring rows.
    for row in (records(knowledge / "recognition_candidates.jsonl") if include_candidates and not has_business_layer else ()):
        parts=[part.strip() for part in str(row.get("row_text", "")).split("|")]
        source=row.get("source_id", ""); evid=row.get("evidence_unit_id", "")
        if evid not in evidence_by_id or evidence_by_id[evid]["source_id"] != source or not parts or not parts[0].isdigit():
            continue
        if source.startswith("VN.HUE.") and len(parts)>=5:
            product, producer=parts[1],parts[2]
        elif source.startswith("VN.HAIPHONG.") and len(parts)>=7:
            producer,product=parts[1],parts[2]
        else:
            continue
        if not producer or not product or len(product)<3:
            continue
        rid=stable_id("recognition_decision_candidate",source,[source],revision=version)
        pid=stable_id("product_candidate",source,[row["candidate_id"]],revision=version)
        oid=stable_id("organization_candidate",source,[producer.casefold()],revision=version)
        add_node(rid,"RecognitionDecision",source_id=source,evidence_ids=[evid],
                 status="needs_review",label=source,properties={"record_kind":"recognition_candidates"})
        add_node(pid,"Product",source_id=source,evidence_ids=[evid],
                 status="needs_review",label=product,properties={"record_kind":"recognition_candidates"})
        add_node(oid,"Organization",source_id=source,evidence_ids=[evid],
                 status="needs_review",label=producer,properties={"record_kind":"recognition_candidates"})
        add_edge("RECOGNIZES",rid,pid,evid,source,"needs_review")
        add_edge("OWNED_BY",pid,oid,evid,source,"needs_review")
        for node_id in (rid, pid, oid):
            add_edge("SUPPORTED_BY",node_id,evidence_node_ids[(source,evid)],evid,source,"needs_review")
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
                     status="needs_review",label=value,properties={"field_position":position})
            add_edge("HAS_FIELD",form_id,fid,evid,source,"needs_review")
    # Business-grounded, strictly typed layer. This REPLACES legacy domain
    # candidate materialization when available, avoiding duplicate products,
    # decisions and form fields. All OCR candidates remain unverified.
    if has_business_layer and include_candidates:
        for row in records(knowledge / "business_entities.jsonl"):
            refs = row.get("evidence", [])
            valid_refs = [ref for ref in refs if isinstance(ref, dict) and
                          ref.get("evidence_unit_id") in evidence_by_id and
                          ref.get("source_id") == row["source_id"] and
                          evidence_by_id[ref["evidence_unit_id"]]["source_id"] == row["source_id"] and
                          (not evidence_by_id[ref["evidence_unit_id"]].get("spans") or
                           ref.get("pdf_page") in [span.get("pdf_page") for span in
                                                    evidence_by_id[ref["evidence_unit_id"]]["spans"]]) and
                          bool(str(ref.get("quote") or "").strip())]
            if (len(valid_refs) != len(refs) or not refs or
                (row.get("status") == "verified" and any(
                    evidence_by_id[r["evidence_unit_id"]].get("review_status") != "verified"
                    for r in valid_refs))):
                rejected.append({"reason":"business_entity_missing_evidence", "entity_id":row.get("entity_id")})
                continue
            add_node(row["entity_id"], row["kind"],source_id=row["source_id"],
                     evidence_ids=[r["evidence_unit_id"] for r in refs],
                     status="needs_review" if row.get("status") == "candidate" else row["status"],
                     label=row["label"],properties=row.get("attributes", {}))
            for ref in refs:
                add_edge("SUPPORTED_BY",row["entity_id"],
                         evidence_node_ids[(row["source_id"],ref["evidence_unit_id"])],
                         ref["evidence_unit_id"],row["source_id"],
                         "verified" if row.get("status")=="verified" else "needs_review")
        for row in records(knowledge / "business_relations.jsonl"):
            for ref in row.get("evidence", []):
                add_edge(row["relation_type"],row["source_entity_id"],row["target_entity_id"],
                         ref["evidence_unit_id"],ref["source_id"],
                         "needs_review" if row.get("status") == "candidate" else row["status"],
                         evidence_ref=ref)
        for row in records(knowledge / "business_rules.jsonl"):
            refs=row.get("evidence", [])
            if not refs or any(r.get("evidence_unit_id") not in evidence_by_id or
                                   r.get("source_id") != row.get("source_id") or
                                   evidence_by_id[r["evidence_unit_id"]].get("source_id") != row.get("source_id")
                                   for r in refs):
                rejected.append({"reason":"business_rule_missing_evidence","rule_id":row.get("rule_id")})
                continue
            source=row["source_id"]
            add_node(row["rule_id"],"RuleCandidate",source_id=source,
                     evidence_ids=[r["evidence_unit_id"] for r in refs],
                     status="needs_review" if row.get("status") == "candidate" else row["status"],
                     label=row["statement"],properties={"modality":row["kind"],"executable":False})
            for ref in refs:
                add_edge("SUPPORTED_BY",row["rule_id"],
                         evidence_node_ids[(source,ref["evidence_unit_id"])],
                         ref["evidence_unit_id"],source,"needs_review")
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
    out_nodes = [nodes[k] for k in sorted(nodes)]; out_edges = [edges[k] for k in sorted(edges)]
    # A fingerprint of the *source bytes* also detects edits to evidence text,
    # even if node IDs, spans and labels themselves happen not to change.
    knowledge_files = sorted(knowledge.glob("*.jsonl")) + [knowledge / "manifest.json"]
    source_fingerprint = content_sha256(b"".join(
        f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0" for f in knowledge_files))
    payload = json.dumps({"nodes":out_nodes,"edges":out_edges,"rejected":rejected,
                          "source_knowledge_sha256":source_fingerprint,
                          "corpus_version":version,"candidate_mode":include_candidates,
                          "schema_revision":"ocop-graph-g1-v6"},ensure_ascii=False,sort_keys=True,
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
        _write_jsonl(stage/"rejected.jsonl",rejected)
        file_hashes={f:content_sha256((stage/f).read_bytes()) for f in
                     ("nodes.jsonl","edges.jsonl","rejected.jsonl")}
        manifest={"graph_version":graph_version,"source_knowledge_version":version,
            "source_knowledge_sha256":source_fingerprint, "schema_revision":"ocop-graph-g1-v6",
            "status":"local_ready", "counts":{"nodes":len(out_nodes),"edges":len(out_edges),"rejected":len(rejected)},
            "node_ids_sha256":content_sha256("\n".join(n["node_id"] for n in out_nodes)),
            "edge_ids_sha256":content_sha256("\n".join(e["edge_id"] for e in out_edges)),
            "file_sha256":file_hashes, "candidate_mode":include_candidates, "neo4j":{"enabled":False}}
        _write_json(stage/"manifest.json",manifest)
        snapshots = output / "snapshots"
        snapshots.mkdir(exist_ok=True)
        snapshot_dir = snapshots/graph_version
        if snapshot_dir.exists():
            from ai_core.graph.ocop.integrity import validate_graph_snapshot
            validate_graph_snapshot(snapshot_dir)
            if (snapshot_dir/"manifest.json").read_bytes() != (stage/"manifest.json").read_bytes():
                raise ValueError("Snapshot version collision")
        else:
            # Atomic creation of an immutable directory on the same filesystem.
            pending = Path(tempfile.mkdtemp(prefix=".snapshot-pending-", dir=snapshots))
            try:
                for filename in ("nodes.jsonl","edges.jsonl","rejected.jsonl","manifest.json"):
                    shutil.copyfile(stage/filename,pending/filename)
                os.replace(pending,snapshot_dir)
            finally:
                if pending.exists():
                    shutil.rmtree(pending,ignore_errors=True)
        for filename in ("nodes.jsonl","edges.jsonl","rejected.jsonl"):
            temp_file=output/("."+filename+".next")
            shutil.copyfile(stage/filename,temp_file)
            os.replace(temp_file,output/filename)
        os.replace(stage/"manifest.json",output/"manifest.json")
        return manifest
    finally:
        shutil.rmtree(stage,ignore_errors=True)
