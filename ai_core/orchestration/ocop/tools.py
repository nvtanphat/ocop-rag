"""Allowlisted domain tools mapped directly to indexing and graph adapters."""
from __future__ import annotations
from pathlib import Path
import json
from datetime import date
import re
from ai_core.retrieval.ocop.search import search
from ai_core.retrieval.ocop.lookup import exact_lookup
from ai_core.graph.ocop.retriever import traverse
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.temporal import applicable,resolve_event_applicability
from ai_core.assessment.ocop.rules import checklist,estimate_score
from ai_core.assessment.ocop.dossiers import DossierStore
from ai_core.orchestration.ocop.contracts import AuthContext
from ai_core.system.telemetry import traced
from ai_core.orchestration.ocop.semantic import normalize


def _jurisdiction_key(value: str) -> str:
    """Compare explicit locality labels, never infer locality from an arbitrary phrase."""
    return re.sub(r'[^a-z0-9]', '', normalize(value))


def _verified_recognition_scope(row: dict, *, region: str | None, stars: int | None) -> bool:
    """OCR guesses cannot satisfy restrictive, user-specified award filters."""
    if row.get('review_status') != 'verified':
        return False
    if region:
        asked=_jurisdiction_key(region)
        labels=[row.get(k) for k in ('jurisdiction','province','region','locality') if row.get(k)]
        # Source identifiers often contain a *full* provincial token: VN.GIALAI.QD.
        tokens=re.split(r'[^A-Za-z0-9]+',normalize(str(row.get('source_id') or '')))
        # Explicit metadata wins over filename tokens. Contradictory verified
        # locality labels are not resolved by guessing which label is correct.
        if labels:
            if not all(_jurisdiction_key(str(label))==asked for label in labels):
                return False
        elif asked not in {_jurisdiction_key(token) for token in tokens}:
            return False
    if stars is not None:
        values=[row.get(k) for k in ('star_rating','rating_stars','stars') if row.get(k) is not None]
        body=normalize(str(row.get('row_text') or row.get('label_candidate') or ''))
        stated={int(m.group(1)) for m in re.finditer(r'(?<!\d)([3-5])\s*sao\b',body)}
        if values:
            if any(str(v).strip()!=str(stars) for v in values):return False
            if stated and stated!={stars}:return False
        else:
            # Allowed only for an individually human-verified row, with explicit
            # "N sao" on that row itself (not a PDF/source title or document date).
            if stated!={stars}:return False
    return True

class ToolRegistry:
    def __init__(self,root:Path):
        self.root=Path(root)
        self.index_dir=self.root/"data/processed/ocop/index"
        self.graph_dir=self.root/"data/processed/ocop/graph"
        self.dossiers=DossierStore(self.root/"data/private/ocop/dossiers")

    def _resolve_source_id(self, code:str|None) -> str|None:
        """Resolve document code to a unique corpus source; ambiguous -> unfiltered.

        The evidence filter runs before BM25/Qdrant ranking, never after top-K.
        """
        if not code:return None
        tokens=re.findall(r"\d+",str(code))
        if not tokens:return None
        path=self.index_dir/"chunks.jsonl"
        if not path.is_file():return None
        matches=set()
        for row in records(path):
            sid=str(row["source_id"])
            if all(re.search(r"(?<!\d)"+re.escape(token)+r"(?!\d)",sid) for token in tokens):
                matches.add(sid)
        return next(iter(matches)) if len(matches)==1 else None

    @traced("ocop.agent.tool_dispatch")
    def dispatch(self,name:str,*,query:str,slots:dict,context:dict|None=None,auth:AuthContext|None=None)->dict:
        context=context or {}
        from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY
        if name not in TOOL_REGISTRY:raise ValueError('Unknown or unauthorized OCOP tool: '+name)
        if TOOL_REGISTRY[name].requires_auth and not isinstance(auth,AuthContext):
            raise PermissionError('This private OCOP tool requires trusted server authentication')
        if name=="search_regulations":
            mode=context.get("retrieval_mode","sparse")
            doc=slots.get("document_code")
            source_filter=self._resolve_source_id(doc) if doc else None
            region=slots.get('region')
            q=normalize(query)
            # Local deadlines are jurisdiction-specific: never answer with a
            # national document or an unrelated province when multiple guidance
            # files happen to exist. Enforce the source allowlist before ranking.
            local_deadline=bool(region and any(term in q for term in (
                'han nop','truoc ngay','han cuoi','thoi han nop','han dang ky',
                'thoi han dang ky')))
            if local_deadline:
                sources_path=self.root/'configs/ocop_sources.json'
                sources=[]
                if sources_path.is_file():
                    sources=json.loads(sources_path.read_text(encoding='utf-8')).get('sources',[])
                local=list(dict.fromkeys(str(src['source_id']) for src in sources
                    if src.get('source_kind')=='local_guidance' and
                    _jurisdiction_key(str(src.get('jurisdiction') or ''))==_jurisdiction_key(str(region))
                    and src.get('source_id')))
                if not local:
                    return {'results':[], 'status':'local_guidance_not_in_corpus',
                            'reason':'no_local_submission_window_source'}
                if doc and source_filter not in local:
                    return {'results':[], 'status':'local_guidance_document_scope_mismatch',
                            'reason':'requested_document_not_a_local_guidance_source'}
                selected=[source_filter] if doc else local
                hits=[];seen=set()
                for allowed_source in selected:
                    for hit in search(self.index_dir,query,mode=mode,top_k=8,
                                      source_id=allowed_source,
                                      rerank=bool(context.get('rerank',False))):
                        # Defend even if a search adapter violates its filter.
                        if hit.get('source_id')!=allowed_source:continue
                        key=hit.get('chunk_id') or hit.get('evidence_unit_id') or (
                            allowed_source,str(hit.get('pdf_page')),str(hit.get('text')))
                        if key in seen:continue
                        seen.add(key);hits.append(hit)
                return {'results':hits[:12], 'status':'local_guidance_scoped'}
            # A question explicitly about *a local document* is not answered
            # from another province simply because BM25 ranks its wording high.
            # This is intentionally narrower than "rules applicable in Huế":
            # national legislation may legitimately apply there.
            local_document_query=bool(region and not doc and any(phrase in q for phrase in (
                'van ban o ', 'van ban cua ', 'tai lieu o ', 'tai lieu cua ',
                'quyet dinh cua ', 'quyet dinh o ', 'van ban dia phuong',
            )))
            if local_document_query:
                registry=self.root/'configs/ocop_sources.json'
                entries=json.loads(registry.read_text(encoding='utf-8')).get('sources',[]) if registry.is_file() else []
                region_key=_jurisdiction_key(str(region))
                local_ids=[str(src['source_id']) for src in entries
                    if _jurisdiction_key(str(src.get('jurisdiction') or '')) in
                      (region_key,'tinh'+region_key,'thanhpho'+region_key)]
                if not local_ids:
                    return {'results':[], 'status':'local_document_not_in_corpus'}
                hits=[];seen=set()
                for allowed_source in local_ids:
                    for hit in search(self.index_dir,query,mode=mode,top_k=8,
                                      source_id=allowed_source,
                                      rerank=bool(context.get('rerank',False))):
                        if hit.get('source_id')!=allowed_source:continue
                        key=hit.get('chunk_id')
                        if key in seen:continue
                        seen.add(key);hits.append(hit)
                hits.sort(key=lambda row:-float(row.get('score') or 0))
                return {'results':hits[:8],'status':'local_document_scoped'}
            if not doc and not slots.get('region') and not slots.get('years') and context.get('business_intent') in (
                'CRITERIA_LOOKUP','PROCEDURE_FORM','OCOP_OVERVIEW'):
                # General OCOP criteria/forms belong to the national framework.
                # Do not present local deadline guidance as a nationwide rule.
                # Explicit historical years, document IDs or locality suppress this hint.
                preferred=self._resolve_source_id('26/2026')
                if preferred:source_filter=preferred
            if doc and not source_filter:
                return {"results":[],"status":"document_not_found_or_ambiguous"}
            return {"results":search(self.index_dir,query,mode=mode,top_k=8,source_id=source_filter,
                                      rerank=bool(context.get("rerank",False)))}
        if name=="lookup_legal_unit":
            code=str(slots.get("document_code") or "")
            article=slots.get("article_id")
            if code and not self._resolve_source_id(code):
                return {"results":[],"status":"document_not_found_or_ambiguous"}
            if article:
                candidates=exact_lookup(self.index_dir,contains="Điều "+article,limit=10000)
            else:
                candidates=exact_lookup(self.index_dir,contains=code or query,limit=10000)
            if article:
                # Only exact article units; never return article 10 or a mention of article 1.
                rx=re.compile(r"^Điều\s*"+re.escape(str(article))+r"(?=\b|[.])",re.I)
                candidates=[x for x in candidates if x.get("unit_kind")=="article" and
                     rx.search(str(x.get("structured",{}).get("heading") or x.get("text") or "").lstrip())]
            if code:
                # QĐ26/2026 and source id VN.OCOP.QD26.2026 share digits, not punctuation.
                required=re.findall(r"\d+",code)
                candidates=[x for x in candidates if all(
                    re.search(r"(?<!\d)"+re.escape(number)+r"(?!\d)",
                        str(x.get("source_id", ""))) for number in required)]
            return {"results":candidates[:12]}
        if name=="lookup_evidence_requirements":
            if slots.get('years') and not slots.get('document_code'):
                return {'results':[], 'status':'assessment_year_scope_unverified',
                        'reason':'historical_evidence_requirements_need_verified_version'}
            # Structured records are authoritative only when individually
            # verified. OCR candidates remain clearly flagged. Linking a
            # product name alone is insufficient to assert mandatory paperwork.
            doc=slots.get('document_code')
            source_filter=self._resolve_source_id(doc) if doc else None
            if doc and not source_filter:
                return {'results':[], 'status':'document_not_found_or_ambiguous'}
            if not source_filter and [str(y) for y in slots.get('years',[])]==['2026'] and \
                not context.get('sector_compliance',False):
                source_filter=self._resolve_source_id('26/2026')
            linked_criterion=slots.get('criterion_id')
            try:rows=exact_lookup(self.index_dir,kind='evidence_requirement_candidates',limit=10000)
            except FileNotFoundError:rows=[]
            if source_filter:rows=[x for x in rows if x.get('source_id')==source_filter]
            if linked_criterion:
                rows=[x for x in rows if str(x.get('criterion_id') or '')==str(linked_criterion)]
            if rows:
                return {'results':rows[:12], 'status':'structured_requirements_candidates',
                        'verified':all(x.get('review_status')=='verified' for x in rows[:12])}
            # Source-backed text retrieval is an explicit fallback, never a
            # fabricated structured requirement and never a verified rule.
            keyword='minh chứng giấy tờ tiêu chí '+query
            return {'results':search(self.index_dir,keyword,source_id=source_filter,
                mode=context.get('retrieval_mode','sparse'),top_k=8,
                rerank=bool(context.get('rerank',False))),
                'status':'text_evidence_fallback','verified':False}
        if name=='lookup_form' and slots.get('years') and not slots.get('document_code'):
            return {'results':[], 'status':'assessment_year_scope_unverified',
                    'reason':'historical_form_template_requires_document_version'}
        if name=='lookup_form' and not (slots.get('form_id') or slots.get('form_ids')):
            return {'results':[], 'status':'form_identifier_not_specified',
                    'reason':'use_regulation_search_for_unspecified_form'}
        if name in ("lookup_form","lookup_criterion","lookup_product_subgroup","lookup_recognition"):
            mapping={"lookup_form":"form_candidates","lookup_criterion":"criterion_candidates",
                     "lookup_product_subgroup":"taxonomy_candidates","lookup_recognition":"recognition_candidates"}
            rows=exact_lookup(self.index_dir,kind=mapping[name],limit=10000)
            # Candidate type lookup returns all matching candidates, marked needs_review.
            needle=(slots.get("form_id") or (slots.get('form_ids') or [None])[0]) if name=="lookup_form" else slots.get("product_name")
            requested_criterion=slots.get("criterion_id") if name=="lookup_criterion" else None
            document_code=slots.get("document_code")
            if document_code:
                numbers=re.findall(r"\d+",str(document_code))
                rows=[r for r in rows if all(re.search(r"(?<!\d)"+re.escape(n)+r"(?!\d)",
                     str(r.get("source_id", ""))) for n in numbers)]
            if name=='lookup_recognition' and (slots.get('region') or slots.get('star_rating')):
                rows=[r for r in rows if _verified_recognition_scope(
                    r,region=slots.get('region'),stars=slots.get('star_rating'))]
                if not rows:
                    return {'results':[], 'status':'recognition_scope_unverified',
                            'reason':'no_verified_rows_match_region_and_star_constraints'}
            if needle:
                if name == "lookup_form":
                    requested_numbers=slots.get('form_ids') or [needle]
                    if not all(re.fullmatch(r'[1-9]\d?',str(n)) for n in requested_numbers):
                        return {'results':[], 'status':'invalid_form_id'}
                    requested_forms={str(int(n)) for n in requested_numbers}
                    rows=[r for r in rows if str(r.get('form_number') or '').strip().isdigit()
                          and str(int(str(r['form_number']).strip())) in requested_forms]
                    if len(requested_forms)>1:
                        # Do not silently answer a two-form comparison from one
                        # row, nor treat OCR-only form candidates as confirmed.
                        verified_forms={str(int(str(row['form_number']).strip())) for row in rows
                            if row.get('review_status')=='verified' and
                            row.get('source_id') and (row.get('source_spans') or row.get('spans'))}
                        missing=sorted(requested_forms-verified_forms,key=int)
                        if missing:
                            return {'results':rows[:15], 'status':'incomplete_form_ids',
                                    'missing_form_ids':missing,'verified':False}
                        by_source:dict[str,dict[str,dict]]={}
                        for row in rows:
                            if row.get('review_status')!='verified' or not row.get('source_id') or not (
                                row.get('source_spans') or row.get('spans')):
                                continue
                            form=str(int(str(row['form_number']).strip()))
                            by_source.setdefault(str(row['source_id']),{}).setdefault(form,row)
                        complete=[sid for sid,forms in by_source.items()
                                  if requested_forms.issubset(forms)]
                        if not complete:
                            return {'results':[], 'status':'form_source_scope_unverified',
                                    'reason':'form_ids_only_verified_across_different_documents'}
                        if len(complete)>1:
                            return {'results':[], 'status':'form_version_ambiguous',
                                    'reason':'multiple_document_versions_contain_requested_forms'}
                        # Include at least one verified unit per requested form,
                        # regardless of OCR duplicates ordering or output limit.
                        selected=by_source[complete[0]]
                        rows=[selected[form] for form in sorted(requested_forms,key=int)]
                else:
                    rows=[r for r in rows if str(needle).casefold() in (
                          str(r.get("title", ""))+" "+str(r.get("label_candidate", ""))+
                          " "+str(r.get("heading", ""))+" "+str(r.get("row_text", ""))).casefold()]
            if requested_criterion:
                import re as _re
                # Only match an explicit criterion code at the beginning of a
                # labeled criterion. Never infer IDs from arbitrary score digits.
                pattern=_re.compile(r"^(?:tiêu chí\s*)?"+_re.escape(str(requested_criterion))+r"(?=\s|[.):-]|$)",_re.I)
                rows=[r for r in rows if str(r.get("criterion_id") or r.get("criterion_code") or "")==str(requested_criterion) or
                      pattern.search(str(r.get("label_candidate","")).strip())]
            if not rows and name in ("lookup_criterion","lookup_product_subgroup"):
                # Missing historical-year structured matches cannot silently
                # fall back to a later framework's text and imply applicability.
                if slots.get('years') and not document_code:
                    return {'results':[], 'status':'assessment_year_scope_unverified',
                            'reason':'versioned_taxonomy_or_criteria_not_verified_for_requested_year'}
                # OCR table labels often do not repeat the product-group name.
                # Search grounded source spans rather than fabricating a
                # structured criterion match. Caller sees the fallback mode.
                source_filter=self._resolve_source_id(document_code) if document_code else None
                if document_code and not source_filter:
                    return {"results":[],"status":"document_not_found_or_ambiguous"}
                # For OCOP taxonomy, a broad unfiltered lexical match can
                # accidentally select a food-safety table instead of the OCOP
                # taxonomy annex. Prefer the specific QD26 corpus only for an
                # unpinned current/2026 taxonomy query; older-year requests
                # remain unpinned rather than silently applying new criteria.
                years=[str(y) for y in slots.get('years',[])]
                if name=='lookup_product_subgroup' and not source_filter and (
                    not years or years==['2026']):
                    source_filter=self._resolve_source_id('26/2026')
                return {"results":search(self.index_dir,query,source_id=source_filter,
                                          mode=context.get("retrieval_mode","sparse"),top_k=8),
                        "verified":False,"status":"text_evidence_fallback",
                        "fallback":"source_filtered_text_search"}
            # A decision's issuance year is NOT its recognition-event year.
            # A criterion sheet's document year is NOT its assessment year.
            # No filename-based inference is permitted for these scopes.
            years=slots.get('years') or []
            scoped_year=None
            if name=='lookup_recognition':
                scoped_year=slots.get('recognition_year')
                if len(years)>1 and not document_code:
                    return {'results':[], 'status':'recognition_year_scope_unverified',
                            'reason':'multiple_event_years_need_verified_recognition_records'}
                if scoped_year is None and len(years)==1 and not document_code:
                    scoped_year=years[0]
                year_fields=('recognition_event_year','recognition_year')
            elif name=='lookup_criterion':
                scoped_year=slots.get('assessment_year')
                if not document_code and years:
                    if len(years)>1:
                        return {'results':[], 'status':'assessment_year_scope_unverified',
                                'reason':'comparison_requires_verified_version_rules'}
                    scoped_year=scoped_year or years[0]
                year_fields=('assessment_year',)
            else:
                year_fields=()
            if scoped_year is not None:
                # An explicit event year constrains even a pinned decision.
                # OCR candidates lacking a verified event-year cannot satisfy
                # this explicit request. A bounded text recovery may still
                # provide *background evidence*, never a verified award/score.
                rows=[r for r in rows if r.get('review_status')=='verified' and
                      any(str(r.get(field) or '')==str(scoped_year) for field in year_fields)]
                if not rows:
                    return {'results':[],
                            'status':('recognition_year_scope_unverified' if name=='lookup_recognition'
                                      else 'assessment_year_scope_unverified'),
                            'reason':'no_verified_records_with_requested_event_year'}
            if name=="lookup_criterion" and not document_code and not scoped_year:
                rows.sort(key=lambda r:("QD26.2026" not in str(r.get("source_id","")),
                                        str(r.get("source_id","")), int(r.get("pdf_page") or 0)))
            return {"results":rows[:15],"verified":False}
        if name=="search_graph":
            # Check *all* files before linking evidence IDs or traversing edges.
            # A partly generated graph must behave like an unavailable index.
            if not all((self.graph_dir/f).is_file() for f in
                       ('manifest.json','nodes.jsonl','edges.jsonl')):
                return {'results':[], 'note':'graph_not_built', 'status':'graph_not_built'}
            from ai_core.graph.ocop.integrity import validate_graph_snapshot
            try:
                graph_manifest=validate_graph_snapshot(self.graph_dir)
                index_manifest_file=self.index_dir/"manifest.json"
                if index_manifest_file.is_file():
                    index_manifest=json.loads(index_manifest_file.read_text(encoding="utf-8"))
                    # Chunk/index version is a derived hash of chunk settings,
                    # deliberately distinct from the knowledge source version.
                    # Compare the shared upstream knowledge version instead.
                    index_source_version=(index_manifest.get('source_knowledge_version')
                                          or index_manifest.get('corpus_version'))
                    if (index_source_version and
                            index_source_version!=graph_manifest.get("source_knowledge_version")):
                        return {"results":[],"status":"graph_index_version_mismatch"}
            except (ValueError, OSError, KeyError, json.JSONDecodeError):
                return {"results":[],"status":"graph_integrity_failed"}
            seed=slots.get("graph_seed_ids") or context.get("graph_seed_ids") or []
            if not seed and context.get("retrieved_evidence_ids"):
                source_ids=set(context["retrieved_evidence_ids"])
                # Link BM25 evidence hits to graph node identities; no LLM alias guesses.
                seed=[n["node_id"] for n in records(self.graph_dir/"nodes.jsonl")
                      if n.get("node_type")=="EvidenceUnit" and
                      source_ids.intersection(n.get("evidence_unit_ids",[]))][:6]
            if not self.graph_dir.joinpath("manifest.json").exists():
                return {"results":[],"note":"graph_not_built"}
            debug=bool(context.get("debug_candidates",False))
            semantic=("HAS_CRITERION_CANDIDATE","HAS_CRITERION","HAS_OPTION","HAS_CONDITION",
                "REQUIRES_EVIDENCE","RECOGNIZES","OWNED_BY","BASED_ON","AMENDS","REPLACES",
                "SUSPENDS","HAS_FIELD","USES_SHEET","HAS_SUBGROUP","SUPPORTED_BY")
            graph=traverse(self.graph_dir,list(seed),hops=2,relations=list(semantic),
                           verified_only=not debug,limit=75,direction="both")
            # Return the source evidence for traversed edges, not arbitrary
            # document-neighbor nodes. This is the Graph -> Evidence contract.
            if graph["edges"]:
                # Offer node source facts via the same evidence reference contract as retrieval.
                found=set();facts=[]
                for edge in graph["edges"]:
                    evid=edge.get("evidence_unit_id")
                    if not evid or evid in found:continue
                    found.add(evid)
                    facts.extend(exact_lookup(self.index_dir,identity=evid,limit=1,include_candidates=False))
                    if len(facts)>=8:break
                graph["results"]=facts
            return graph
        if name=="resolve_temporal_applicability":
            when=context.get("as_of_date")
            if not when:return {"status":"unknown","reason":"exact_as_of_date_required","results":[]}
            try: on=date.fromisoformat(str(when))
            except (TypeError,ValueError):return {"status":"unknown","reason":"invalid_as_of_date","results":[]}
            # A parser-extracted date is never enough to determine legal
            # applicability: only hand-verified, version-matching rules count.
            verified=self.root/"data/processed/ocop/knowledge/verified_temporal_rules.jsonl"
            if not verified.is_file():
                return {"status":"unknown","reason":"no_verified_temporal_rules","results":[]}
            manifest=self.index_dir/"manifest.json"
            version=json.loads(manifest.read_text(encoding="utf-8")).get("corpus_version") if manifest.is_file() else None
            if not version:
                return {'status':'unknown','reason':'active_corpus_version_missing','results':[]}
            source_id=self._resolve_source_id(slots.get("document_code")) if slots.get("document_code") else None
            found=[]
            with verified.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():continue
                    rule=json.loads(line)
                    if rule.get("review_status")!="verified" or not rule.get("evidence_unit_id") or rule.get("corpus_version")!=version:
                        continue
                    if source_id and rule.get("source_id")!=source_id:continue
                    if not source_id and slots.get("document_code"):continue
                    event_year=slots.get('assessment_year')
                    try:event_year=int(event_year) if event_year is not None else None
                    except (TypeError,ValueError):event_year=None
                    verdict=resolve_event_applicability(rule,as_of_date=on,
                        event_year=event_year,region=slots.get('region'),corpus_version=version)
                    backing=exact_lookup(self.index_dir,identity=rule['evidence_unit_id'],
                                         limit=1,include_candidates=False)
                    # 'verified' without its matching corpus source is not a
                    # trustworthy, citable legal conclusion.
                    if not backing or not any(
                        row.get('source_id')==rule.get('source_id') and
                        (row.get('source_spans') or row.get('spans')) for row in backing):
                        verdict={'status':'unknown','reason':'verified_rule_missing_matching_source_evidence'}
                    found.append({"rule_id":rule.get("rule_id"),"source_id":rule.get("source_id"),
                                  "evidence_unit_id":rule["evidence_unit_id"],"verdict":verdict,
                                  "review_status":"verified","corpus_version":version,
                                  "source_spans":backing[0].get('source_spans') or backing[0].get('spans')
                                                 if backing else [],
                                  "text":backing[0].get('text') if backing else ''})
            # Approval of the record is distinct from a resolved applicability
            # verdict. One unknown rule makes the scoped legal answer unresolved.
            verdicts=[r['verdict'].get('status') for r in found]
            resolved=bool(found) and all(v in ('applicable','not_applicable') for v in verdicts)
            return {'status':'checked_verified_rules' if resolved else 'unknown',
                    'applicability_status':('applicable' if 'applicable' in verdicts else
                        'not_applicable' if resolved else 'unknown'),
                    'reason':None if resolved else ('unresolved_applicability_verdict' if found
                        else 'no_applicable_verified_rules'), 'results':found}
        if name in ("review_dossier","estimate_score"):
            if not isinstance(auth,AuthContext):
                raise PermissionError("Dossier tool requires trusted server AuthContext")
            tenant,did=auth.tenant_id,context.get("dossier_id")
            if not did:raise PermissionError("Dossier scope required")
            dossier=self.dossiers.get(tenant,did,authorization_checked=True)
            if dossier is None:return {"status":"not_found"}
            # Rules are loaded only from the verified reference store, never
            # from caller-controlled context or an LLM tool argument.
            rules_path=self.root/"data/processed/ocop/knowledge"/(
                "verified_requirements.jsonl" if name=="review_dossier" else "verified_criteria.jsonl")
            if not rules_path.is_file():
                return {"status":"rules_not_verified","reason":"verified_rules_store_missing","results":[]}
            index_manifest=self.index_dir/"manifest.json"
            if not index_manifest.is_file():return {"status":"rules_not_verified","reason":"missing_active_corpus","results":[]}
            active_version=json.loads(index_manifest.read_text(encoding="utf-8")).get("corpus_version")
            rules=[]
            with rules_path.open(encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        record=json.loads(line)
                        if (record.get("review_status")=="verified" and record.get("evidence_unit_id") and
                            record.get("corpus_version")==active_version):
                            rules.append(record)
            if not rules:return {"status":"rules_not_verified","reason":"no_verified_rules","results":[]}
            if name=="review_dossier":
                return {"status":"provisional_not_official","results":checklist(rules,dossier["documents"])}
            answer_map=dossier.get("verified_answers") or {}
            return estimate_score(rules,answer_map)
        if name=="open_source_span":
            identity=slots.get("evidence_unit_id")
            if not identity:return {"results":[]}
            return {"results":exact_lookup(self.index_dir,identity=identity,limit=1)}
        raise ValueError("Unknown or unauthorized OCOP tool: "+name)
