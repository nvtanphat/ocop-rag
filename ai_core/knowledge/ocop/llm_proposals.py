"""Opt-in LLM proposer for candidate entities, attributes, relations and rules.

Design follows schema-constrained, source-grounded extractors (Google LangExtract,
LlamaIndex SchemaLLMPathExtractor strict mode, Microsoft GraphRAG entity merging):

- the LLM is NEVER a fact authority: every entity, attribute value, relation proof
  and rule must be a verbatim substring of one EvidenceUnit, located by character
  offset and mapped to its own PDF page/bbox/SHA; anything else is dropped and counted;
- only whitelisted entity kinds, attribute keys and ontology-checked relation
  triples are accepted; score/star values are never taken from the LLM;
- long units are chunked with overlap instead of truncated; calls may run in
  parallel but results merge in unit order, and responses are cached by
  (model, prompt version, chunk text) so reruns are reproducible.
"""

from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
import logging
import sys
from threading import BoundedSemaphore, Lock
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol
from ai_core.domain.ocop_citations import quote_bbox
from ocop_contracts.ids import stable_id, code_fingerprint
from .contracts import (
    AttributeClaim,
    BusinessEntity,
    BusinessRelation,
    BusinessRule,
    EvidenceRef,
    EntityType,
    ENTITY_ATTRIBUTE_KEYS,
    RELATION_TYPES,
    validate_business_graph,
)

PROMPT_VERSION = code_fingerprint("semantic", [Path(__file__), Path(__file__).with_name("contracts.py")])
LOG = logging.getLogger(__name__)
_GLOBAL_CALLS = BoundedSemaphore(4)
CHUNK_CHARS = 2500
CHUNK_OVERLAP = 200


class StructuredLLM(Protocol):
    model: str

    def chat(self, system: str, user: str, *, format_json: bool = False, max_tokens: int = 1024) -> str: ...


PERMITTED_KINDS = (
    "Criterion",
    "EvidenceType",
    "ProductGroup",
    "ProductSubgroup",
    "Condition",
    "Product",
    "Organization",
)
# Descriptive features only. Points, stars and ranks stay with deterministic/human review.
ATTRIBUTE_KEYS = ENTITY_ATTRIBUTE_KEYS
FORBIDDEN_ATTRIBUTE_HINTS = ("point", "score", "star", "rank", "diem", "sao", "hang")
# Entity-type definitions in the prompt (GraphRAG/LangExtract style) plus a context gate
# (LlamaIndex strict schema): scoring-sheet kinds only come from table units.
KIND_DEFINITIONS = {
    "Criterion": "a numbered/lettered criterion row of an OCOP scoring sheet (phiếu đánh giá) table, listed ONLY "
    "as the source of a HAS_CONDITION or REQUIRES_EVIDENCE relation (the sheet tree itself is "
    "already extracted); "
    "NOT a procedure heading, dossier name or legal article title",
    "Condition": "a NOTE printed under a scoring-sheet criterion (Ghi chú / Yêu cầu / Chú ý / Chỉ áp dụng / "
    "an explanatory parenthesis); NOT an answer option (rows starting with □), NOT eligibility "
    "of applicants",
    "EvidenceType": "a named document/paper that must be submitted or kept as proof",
    "ProductGroup": "an explicitly listed OCOP product group (ngành/nhóm sản phẩm), copied whole: "
    '"dịch vụ du lịch cộng đồng, du lịch sinh thái và điểm du lịch" is ONE group; '
    'NOT a "Bộ sản phẩm" (criterion sheet) name and NOT a fragment of a group name',
    "ProductSubgroup": 'a product subgroup printed after "Nhóm:" in a sheet heading; '
    'NOT a "Bộ sản phẩm" (criterion sheet) name',
    "Product": 'a specific named product, not generic words such as "sản phẩm OCOP"',
    "Organization": "a specific producing/business entity (HTX, công ty, hộ kinh doanh, tổ hợp tác); "
    "NOT a state agency (UBND, Sở, Bộ, Phòng, Cục), NOT a person, NOT a generic group",
}
TABLE_ONLY_KINDS = {"Criterion", "Condition"}
TABLE_UNIT_KINDS = {"table", "criterion_table_candidate"}
_STATE_AGENCY = re.compile(
    r"^\s*(?:(?:ủy|uỷ)\s+ban|ubnd|sở|bộ|phòng|cục|chi\s+cục|hội\s+đồng|chủ\s+tịch|"
    r"trung\s+tâm|văn\s+phòng)(?:\s|$)",
    re.I,
)
_GENERIC_LABEL = re.compile(r"^\s*(?:các|những|mọi)\s", re.I)
RULE_KINDS = ("obligation", "prohibition", "permission", "exemption", "scoring", "temporal")
# Norm frame of a rule: each value is a verbatim span of the rule sentence, empty when the sentence does not say it.
FRAME_FIELDS = ("actor", "action", "object", "condition", "exception", "time")


# Group/subgroup hierarchy comes from sheet headings (deterministic); prose lists mislead the LLM.
# Scoring-sheet tree (options, sub-criteria) is extracted deterministically and arithmetic-checked;
# asking the LLM to restate it only multiplies output tokens.
LLM_EXCLUDED_RELATIONS = {"HAS_SUBGROUP", "HAS_OPTION", "HAS_SUBCRITERION"}


def _allowed_triples() -> dict[str, tuple[set[str], set[str]]]:
    def kinds(value):
        return {k.value for k in (value if isinstance(value, frozenset) else {value})}

    out = {}
    for name, (src, dst) in RELATION_TYPES.items():
        s, d = kinds(src) & set(PERMITTED_KINDS), kinds(dst) & set(PERMITTED_KINDS)
        if s and d and name not in LLM_EXCLUDED_RELATIONS:
            out[name] = (s, d)
    return out


ALLOWED_TRIPLES = _allowed_triples()


def response_schema() -> dict:
    """Provider-constrained output; application validation still distrusts every value."""

    def obj(properties):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    attribute_names = sorted({key for keys in ATTRIBUTE_KEYS.values() for key in keys})
    entity = obj(
        {
            "kind": {"type": "string", "enum": list(PERMITTED_KINDS)},
            "anchor": {"type": "string"},
            "attributes": {
                "type": "array",
                "items": obj(
                    {"key": {"type": "string", "enum": attribute_names}, "value": {"type": "string"}}
                ),
            },
        }
    )
    return obj(
        {
            "entities": {"type": "array", "items": entity},
            "relations": {
                "type": "array",
                "items": obj(
                    {
                        "type": {"type": "string", "enum": sorted(ALLOWED_TRIPLES)},
                        "source": {"type": "integer"},
                        "target": {"type": "integer"},
                    }
                ),
            },
            "rules": {
                "type": "array",
                "items": obj(
                    {
                        "kind": {"type": "string", "enum": list(RULE_KINDS)},
                        "anchor": {"type": "string"},
                        **{name: {"type": "string"} for name in FRAME_FIELDS},
                    }
                ),
            },
        }
    )


_EXAMPLE_INPUT = (
    "2.1. Bao bì sản phẩm\n- Bao bì đẹp, có nhãn đúng quy định\n"
    "Hồ sơ gồm: Phiếu kiểm nghiệm do đơn vị được công nhận cấp\n"
    "Sản phẩm: Mật ong hoa nhãn, đóng chai thủy tinh, chủ thể: HTX Ong Mật Bình Minh\n"
    "Chủ thể phải nộp hồ sơ cho Ủy ban nhân dân cấp xã trong thời hạn 15 ngày, trừ trường hợp được miễn."
)
_EXAMPLE_OUTPUT = {
    "entities": [
        {"kind": "Criterion", "anchor": "Bao bì sản phẩm", "attributes": {"code": "2.1"}},
        {
            "kind": "EvidenceType",
            "anchor": "Phiếu kiểm nghiệm",
            "attributes": {"issuer": "đơn vị được công nhận"},
        },
        {"kind": "Product", "anchor": "Mật ong hoa nhãn", "attributes": {"packaging": "chai thủy tinh"}},
        {
            "kind": "Organization",
            "anchor": "HTX Ong Mật Bình Minh",
            "attributes": {"organization_form": "HTX"},
        },
    ],
    "relations": [
        {"type": "REQUIRES_EVIDENCE", "source": 0, "target": 1},
        {"type": "OWNED_BY", "source": 2, "target": 3},
    ],
    "rules": [
        {
            "kind": "obligation",
            "anchor": "Chủ thể phải nộp hồ sơ cho Ủy ban nhân dân cấp xã trong thời hạn 15 ngày, trừ trường hợp được miễn.",
            "actor": "Chủ thể",
            "action": "nộp hồ sơ",
            "object": "Ủy ban nhân dân cấp xã",
            "condition": "",
            "exception": "trừ trường hợp được miễn",
            "time": "trong thời hạn 15 ngày",
        }
    ],
}
for _entity in _EXAMPLE_OUTPUT["entities"]:
    _entity["attributes"] = [{"key": k, "value": v} for k, v in _entity.get("attributes", {}).items()]


def _system_prompt() -> str:
    attrs = "; ".join(f"{k}: {', '.join(v) or '(none)'}" for k, v in ATTRIBUTE_KEYS.items())
    triples = "; ".join(
        f"{name}: {'|'.join(sorted(s))} -> {'|'.join(sorted(d))}"
        for name, (s, d) in sorted(ALLOWED_TRIPLES.items())
    )
    return (
        "You extract OCOP facts ONLY from the quoted Vietnamese source (OCR text, may contain errors). "
        "Do not use external knowledge and never correct OCR spelling.\n"
        "Return ONE JSON object with arrays: entities, relations, rules.\n"
        "Copy anchors character-for-character, including OCR errors. A name may continue across a line "
        "break: copy the WHOLE name. Extract EVERY qualifying entity and EVERY relation the passage states "
        "(for example each product with its producer), not only the first ones.\n"
        "Entity kinds: " + "; ".join(f"{k} = {v}" for k, v in KIND_DEFINITIONS.items()) + ".\n"
        f'Entity: {{"kind": one of {"|".join(PERMITTED_KINDS)}, "anchor": VERBATIM substring, '
        '"attributes": [{"key": attribute name, "value": VERBATIM substring}]}.\n'
        f"Allowed attribute keys per kind: {attrs}. Use an empty attributes array for unstated features.\n"
        'Relation: {"type", "source": index of the source entity in your entities array, '
        '"target": index of the target entity}; only when the source text directly states it. '
        "Do not copy text into relations.\n"
        f"Allowed relation types (source kind -> target kind): {triples}.\n"
        f'Rule: {{"kind": one of {"|".join(RULE_KINDS)}, "anchor": VERBATIM rule sentence, '
        '"actor": who must/may/must not act, "action": what they do, "object": what or whom it is about, '
        '"condition": when or if it applies, "exception": what is excluded, "time": deadline or period}. '
        "Each frame value is a VERBATIM span of the anchor, or an empty string when the sentence does not "
        "state it.\n"
        "Never output point scores, star levels, legal dates, producers or evidence types that are not "
        "written in the source. List items in order of appearance. Output only JSON.\n"
        f"Example input:\n{_EXAMPLE_INPUT}\nExample output:\n{json.dumps(_EXAMPLE_OUTPUT, ensure_ascii=False)}"
    )


SYSTEM = _system_prompt()


GLEANING_PROMPT = (
    "MANY entities and relations were missed in the previous extraction (shown below). "
    "Return ONE JSON object with the same arrays containing ONLY additional items that "
    "satisfy all rules above; return empty arrays if nothing was missed. Relation indices "
    "refer to the PREVIOUS entities followed by your new entities."
)


def client_identity(client) -> dict:
    """Provider, endpoint, model, revision and sampling parameters of a client (never credentials)."""
    declared = getattr(client, "identity", None)
    base = dict(declared()) if callable(declared) else {}
    return {
        "provider": base.get("provider", "unknown"),
        "endpoint": base.get("endpoint", ""),
        "model": str(getattr(client, "model", base.get("model", ""))),
        "revision": base.get("revision", ""),
        "params": base.get("params", {}),
    }


def _fingerprint_payload(identity: dict) -> dict:
    schema = hashlib.sha256(json.dumps(response_schema(), sort_keys=True).encode()).hexdigest()[:16]
    return {"identity": identity, "prompt": PROMPT_VERSION, "schema": schema}


def semantic_profile(identity: dict | str, max_units: int | None, gleanings: int = 1) -> str:
    """Fingerprint of an LLM extraction run; any change invalidates reused knowledge.

    Covers provider, endpoint, model, model revision, sampling parameters, prompt/code version, response schema,
    gleaning passes and the unit limit. Workers and API keys do not change results and are excluded.
    """
    if isinstance(identity, str):  # a bare model name (tests, old manifests)
        identity = {"provider": "unknown", "endpoint": "", "model": identity, "revision": "", "params": {}}
    digest = hashlib.sha256(
        json.dumps(
            {**_fingerprint_payload(identity), "gleanings": gleanings, "max_units": max_units}, sort_keys=True
        ).encode()
    ).hexdigest()[:20]
    return f"{identity['model']}:{digest}"


def norm_label(text: str) -> str:
    """Merge key only (case and whitespace); stored quotes stay verbatim."""
    return " ".join(str(text).split()).casefold()


def _align(text: str, anchor, min_len: int = 3) -> list[tuple[int, int]]:
    """Exact matches, else matches that differ only in whitespace (LangExtract-style alignment).
    Characters are never fuzzed, so OCR text is not corrected."""
    if not isinstance(anchor, str) or len(anchor.strip()) < min_len:
        return []
    hits, pos = [], text.find(anchor)
    while pos >= 0:
        hits.append((pos, pos + len(anchor)))
        pos = text.find(anchor, pos + 1)
    if hits:
        return hits
    pattern = r"\s+".join(re.escape(tok) for tok in anchor.split())
    return [m.span() for m in re.finditer(pattern, text)]


def _chunks(text: str) -> list[tuple[int, str]]:
    if len(text) <= CHUNK_CHARS:
        return [(0, text)]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            cut = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append((start, text[start:end]))
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return out


class _Cache:
    def __init__(self, directory: Path | None):
        self.dir = directory
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)

    def key(self, identity: dict, text: str) -> str:
        """Response cache key: the full client identity, prompt version and schema, then the request text."""
        payload = json.dumps(_fingerprint_payload(identity), sort_keys=True)
        return hashlib.sha256(f"{payload}|{text}".encode()).hexdigest()

    def get(self, key: str) -> str | None:
        if self.dir is None:
            return None
        path = self.dir / f"{key}.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("response") if isinstance(payload, dict) else None
            decoded = json.loads(raw) if isinstance(raw, str) else None
            if not isinstance(decoded, dict) or any(
                not isinstance(decoded.get(k, []), list) for k in ("entities", "relations", "rules")
            ):
                return None
            return raw
        except (ValueError, UnicodeError):
            return None  # An interrupted/corrupt cache write must not poison every resume.

    def put(self, key: str, response: str) -> None:
        if self.dir is None:
            return
        descriptor, name = tempfile.mkstemp(prefix=f"{key}.", suffix=".tmp", dir=self.dir)
        tmp = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"response": response}, stream, ensure_ascii=False)
            os.replace(tmp, self.dir / f"{key}.json")
        finally:
            tmp.unlink(missing_ok=True)


def _page_of(unit: dict, start: int, end: int) -> int | None:
    """PDF page of text[start:end]; None if it spans pages or cannot be located."""
    text = unit.get("text") or ""
    spans = unit.get("spans") or []
    pages = {int(s["pdf_page"]) for s in spans}
    if len(pages) == 1:
        return next(iter(pages))
    lines = text.splitlines()
    first, last = text.count("\n", 0, start), text.count("\n", 0, max(start, end - 1))
    geometry = unit.get("structured", {}).get("quote_lines", [])
    rows = geometry if len(geometry) == len(lines) else spans if len(spans) == len(lines) else None
    if rows is None:
        return None
    found = {int(rows[i]["pdf_page"]) for i in range(first, last + 1)}
    return found.pop() if len(found) == 1 else None


class _Grounder:
    def __init__(self, unit: dict, start: int = 0, end: int | None = None):
        self.unit = unit
        self.start = start
        self.text = (unit.get("text") or "")[start:end]
        self.sha = {int(s["pdf_page"]): s.get("source_sha256") for s in unit.get("spans") or []}

    def locate(self, anchor, min_len: int = 3) -> str | None:
        """Verbatim source substring for an anchor, or None if absent."""
        hits = _align(self.text, anchor, min_len)
        return self.text[hits[0][0] : hits[0][1]] if hits else None

    def ref(self, anchor) -> EvidenceRef | None:
        hits = _align(self.text, anchor)
        if not hits:
            return None
        quote = self.text[hits[0][0] : hits[0][1]]
        pages = {_page_of(self.unit, s + self.start, e + self.start) for s, e in hits}
        if len(pages) != 1 or None in pages:
            return None
        page = pages.pop()
        return EvidenceRef(
            source_id=self.unit["source_id"],
            evidence_unit_id=self.unit["unit_id"],
            pdf_page=page,
            source_sha256=self.sha.get(page),
            bbox=quote_bbox(self.unit, page, quote),
            quote=quote,
        )


MAX_PROOF_CHARS = 700


def _covering_span(text: str, first: str, second: str) -> str | None:
    """Shortest substring of text containing both anchors, or None if longer than MAX_PROOF_CHARS."""
    best = None
    for a0, a1 in _align(text, first, 1):
        for b0, b1 in _align(text, second, 1):
            start, end = min(a0, b0), max(a1, b1)
            if best is None or end - start < best[1] - best[0]:
                best = (start, end)
    if best is None or best[1] - best[0] > MAX_PROOF_CHARS:
        return None
    return text[best[0] : best[1]]


def _kind_allowed(kind, anchor, unit: dict) -> bool:
    if kind not in PERMITTED_KINDS or not isinstance(anchor, str):
        return False
    if kind in TABLE_ONLY_KINDS and unit.get("unit_kind") not in TABLE_UNIT_KINDS:
        return False
    if _GENERIC_LABEL.match(anchor):
        return False
    return not (kind == "Organization" and _STATE_AGENCY.match(anchor))


def _attributes(
    kind: str, anchor: str, raw, grounder: "_Grounder", stats: dict, method: str
) -> tuple[dict[str, str], list[AttributeClaim]]:
    out, claims = {}, []
    if isinstance(raw, list):
        values = {}
        for item in raw:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("key"), str)
                or not isinstance(item.get("value"), str)
            ):
                stats["dropped_attributes"] += 1
                continue
            values.setdefault(item["key"], set()).add(item["value"])
        for alternatives in values.values():
            if len(alternatives) > 1:
                stats["dropped_attributes"] += len(alternatives)
        raw = {
            key: next(iter(alternatives)) for key, alternatives in values.items() if len(alternatives) == 1
        }
    if not isinstance(raw, dict):
        return out, claims
    for key, value in raw.items():
        if value is None:
            continue  # strict providers emit null for an unstated optional feature
        found = (
            grounder.locate(value, min_len=2)
            if isinstance(value, str)
            and len(value) <= 200
            and key in ATTRIBUTE_KEYS.get(kind, ())
            and not any(h in str(key).lower() for h in FORBIDDEN_ATTRIBUTE_HINTS)
            else None
        )
        context = _covering_span(grounder.text, anchor, found) if found else None
        proof = grounder.ref(context) if context else None
        if found is None or proof is None:
            stats["dropped_attributes"] += 1
            continue
        out[f"{key}_candidate"] = " ".join(found.split())
        claims.append(
            AttributeClaim(
                attribute=f"{key}_candidate",
                value=out[f"{key}_candidate"],
                evidence=[proof],
                extraction_method=method,
            )
        )
    return out, claims


def _ask(client: StructuredLLM, cache: _Cache, prompt: str) -> dict:
    key = cache.key(client_identity(client), prompt)
    raw = cache.get(key)
    fresh = raw is None
    if fresh:
        structured = getattr(client, "chat_structured", None)
        for token_limit in (1600, 4096):
            try:
                with _GLOBAL_CALLS:
                    raw = (
                        structured(SYSTEM, prompt, schema=response_schema(), max_tokens=token_limit)
                        if callable(structured)
                        else client.chat(SYSTEM, prompt, format_json=True, max_tokens=token_limit)
                    )
                break
            except RuntimeError as exc:
                if "response filtered" in str(exc):
                    raw = json.dumps({"_omission": "provider_content_filter"})
                    break
                if "truncated" in str(exc) and token_limit == 4096:
                    cache.put(key, json.dumps({"_split": True}))
                if "truncated" not in str(exc) or token_limit == 4096:
                    raise
    response = json.loads(raw)
    if not isinstance(response, dict):
        response = {"_omission": "response_not_object"}
        raw = json.dumps(response)
    if response.get("_split"):
        from ai_core.orchestration.ocop.llm import ModelOutputTruncated

        raise ModelOutputTruncated("cached chunk split required: response truncated")
    if any(not isinstance(response.get(key, []), list) for key in ("entities", "relations", "rules")):
        raise ValueError("extraction collections must be arrays")
    if fresh:
        cache.put(key, raw)
    return response


def _call(client: StructuredLLM, cache: _Cache, body: str, gleanings: int = 0) -> dict:
    """First pass plus GraphRAG-style gleaning passes that ask only for missed items."""
    merged = _ask(client, cache, body)
    if merged.get("_omission"):
        return merged
    for _ in range(gleanings):
        previous = {k: merged.get(k) or [] for k in ("entities", "relations", "rules")}
        extra = _ask(
            client,
            cache,
            f"{body}\n\n{GLEANING_PROMPT}\nPREVIOUS EXTRACTION:\n{json.dumps(previous, ensure_ascii=False)}",
        )
        if extra.get("_omission"):
            merged.setdefault("_gleaning_omissions", []).append(extra["_omission"])
            break
        added = 0
        for k in ("entities", "relations", "rules"):
            items = extra.get(k) if isinstance(extra.get(k), list) else []
            merged[k] = list(merged.get(k) or []) + items
            added += len(items)
        if not added:
            break
    return merged


def propose(
    units: list[dict],
    client: StructuredLLM,
    *,
    max_units: int | None = None,
    cache_dir: Path | None = None,
    max_workers: int = 1,
    gleanings: int = 0,
) -> dict:
    if max_units is not None and (
        isinstance(max_units, bool) or not isinstance(max_units, int) or max_units < 0
    ):
        raise ValueError("max_units must be a nonnegative integer or None")
    if not (1 <= max_workers <= 16):
        raise ValueError("max_workers must be 1..16")
    if isinstance(gleanings, bool) or not isinstance(gleanings, int) or not 0 <= gleanings <= 3:
        raise ValueError("gleanings must be 0..3")
    cache = _Cache(cache_dir)
    eligible_units = [
        u
        for u in units
        if u.get("unit_kind") in ("article", "paragraph", "section", "table", "criterion_table_candidate")
        and u.get("text", "").strip()
    ]
    target_units = eligible_units[:max_units]
    jobs = [(u, start, body) for u in target_units for start, body in _chunks(u["text"])]
    progress_lock = Lock()
    attempts = 0

    def run(job):
        nonlocal attempts
        try:
            return [(job, (_call(client, cache, job[2], gleanings), None))]
        except (RuntimeError, ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            if "truncated" in str(exc) and len(job[2]) > 32:
                unit, start, body = job
                half = len(body) // 2
                LOG.info(
                    "split extraction chunk unit=%s start=%d chars=%d", unit["unit_id"], start, len(body)
                )
                return run((unit, start, body[:half])) + run((unit, start + half, body[half:]))
            return [(job, (None, type(exc).__name__ + (f": {exc}" if isinstance(exc, RuntimeError) else "")))]
        finally:
            with progress_lock:
                attempts += 1
                if attempts == 1 or attempts % 10 == 0:
                    print(
                        f"OCOP extraction: chunk attempts={attempts}, selected units={len(target_units)}",
                        file=sys.stderr,
                        flush=True,
                    )

    if max_workers == 1:
        batches = [run(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            batches = list(pool.map(run, jobs))
    flattened = [item for batch in batches for item in batch]
    jobs = [job for job, _ in flattened]
    results = [result for _, result in flattened]
    LOG.info("extraction finished chunks=%d selected_units=%d", len(jobs), len(target_units))

    stats = {"dropped_entities": 0, "dropped_attributes": 0, "dropped_relations": 0, "dropped_rules": 0}
    ent: dict[str, BusinessEntity] = {}
    rel: dict[str, BusinessRelation] = {}
    rules: dict[str, BusinessRule] = {}
    failures, ok_units, failed_units = [], set(), set()
    terminal_omissions = []
    method = f"llm_candidate:{client.model}"
    for (unit, start, body), (response, error) in zip(jobs, results):
        sid, uid = unit["source_id"], unit["unit_id"]
        if response is None:
            failures.append(
                {
                    "evidence_unit_id": uid,
                    "chunk_start": start,
                    "chunk_end": start + len(body),
                    "error_type": error,
                }
            )
            failed_units.add(uid)
            continue
        ok_units.add(uid)
        for reason in response.get("_gleaning_omissions", []):
            terminal_omissions.append(
                {
                    "evidence_unit_id": uid,
                    "chunk_start": start,
                    "chunk_end": start + len(body),
                    "reason": reason,
                    "permanent": True,
                    "pass": "gleaning",
                }
            )
        if response.get("_omission"):
            terminal_omissions.append(
                {
                    "evidence_unit_id": uid,
                    "chunk_start": start,
                    "chunk_end": start + len(body),
                    "reason": response["_omission"],
                    "permanent": True,
                }
            )
            continue
        grounder = _Grounder(unit, start, start + len(body))
        by_anchor: dict[tuple[str, str], str] = {}
        by_index: dict[int, tuple[str, str, str]] = {}
        for index, obj in enumerate((response.get("entities") or [])[:80]):
            if not isinstance(obj, dict):
                stats["dropped_entities"] += 1
                continue
            kind, anchor = obj.get("kind"), obj.get("anchor")
            ev = grounder.ref(anchor) if _kind_allowed(kind, anchor, unit) else None
            if ev is None:
                stats["dropped_entities"] += 1
                continue
            # GraphRAG-style merge: one entity per (source, kind, normalized label), evidence accumulated.
            key = norm_label(ev.quote)
            # Scoring-sheet rows repeat verbatim across sheets: never merge them across units.
            scope = [uid] if kind in TABLE_ONLY_KINDS | {"Product", "Organization"} else []
            entity_id = stable_id("llm_entity", sid, [kind, key, *scope], revision="business")
            attrs, claims = _attributes(kind, ev.quote, obj.get("attributes"), grounder, stats, method)
            refs = [ev] + [ref for claim in claims for ref in claim.evidence if ref != ev]
            if entity_id in ent:
                old = ent[entity_id]
                merged = dict(old.attributes)
                for k, v in attrs.items():
                    if k in merged and merged[k] != v:
                        merged[k] = None  # conflicting OCR readings: keep none, flag for review
                        merged[k.replace("_candidate", "_conflict")] = True
                    elif k not in merged:
                        merged[k] = v
                evidence = old.evidence + [e for e in refs if e not in old.evidence]
                ent[entity_id] = old.model_copy(
                    update={
                        "evidence": evidence,
                        "attributes": merged,
                        "attribute_claims": old.attribute_claims
                        + [c for c in claims if c not in old.attribute_claims],
                    }
                )
            else:
                ent[entity_id] = BusinessEntity(
                    entity_id=entity_id,
                    kind=EntityType(kind),
                    label=" ".join(ev.quote.split()),
                    source_id=sid,
                    evidence=refs,
                    attributes=attrs,
                    attribute_claims=claims,
                    extraction_method=method,
                )
            by_anchor[(kind, key)] = entity_id
            by_index[index] = (entity_id, kind, ev.quote)
        for obj in (response.get("relations") or [])[:80]:
            if (
                not isinstance(obj, dict)
                or not isinstance(obj.get("type"), str)
                or obj["type"] not in ALLOWED_TRIPLES
            ):
                stats["dropped_relations"] += 1
                continue
            relation_type = obj["type"]
            src_kinds, dst_kinds = ALLOWED_TRIPLES[relation_type]

            def resolve(kinds, ref, anchor):
                # Index into the entities array (compact format); anchor text accepted for older responses.
                if isinstance(ref, int) and not isinstance(ref, bool) and ref in by_index:
                    entity_id, kind, quote = by_index[ref]
                    return (entity_id, quote) if kind in kinds else (None, None)
                if not isinstance(anchor, str):
                    return None, None
                matches = {
                    by_anchor[(k, norm_label(anchor))] for k in kinds if (k, norm_label(anchor)) in by_anchor
                }
                return (next(iter(matches)), anchor) if len(matches) == 1 else (None, None)

            src, src_text = resolve(src_kinds, obj.get("source"), obj.get("source_anchor"))
            dst, dst_text = resolve(dst_kinds, obj.get("target"), obj.get("target_anchor"))
            # Proof is the shortest verbatim source span holding both endpoints, computed here
            # rather than copied by the model.
            proof = _covering_span(grounder.text, src_text, dst_text) if src and dst else None
            ev = grounder.ref(proof) if proof else None
            if src is None or dst is None or ev is None:
                stats["dropped_relations"] += 1
                continue
            rid = stable_id("llm_relation", sid, [relation_type, src, dst], revision="business")
            if rid in rel:
                old = rel[rid]
                rel[rid] = old.model_copy(
                    update={"evidence": old.evidence + [e for e in [ev] if e not in old.evidence]}
                )
            else:
                rel[rid] = BusinessRelation(
                    relation_id=rid,
                    relation_type=relation_type,
                    source_entity_id=src,
                    target_entity_id=dst,
                    evidence=[ev],
                    attributes={"grounding_method": "verbatim_cooccurrence", "semantic_verified": False},
                    extraction_method=method,
                )
        for obj in (response.get("rules") or [])[:40]:
            kind, anchor = (obj.get("kind"), obj.get("anchor")) if isinstance(obj, dict) else (None, None)
            ev = grounder.ref(anchor) if kind in RULE_KINDS else None
            if ev is None:
                stats["dropped_rules"] += 1
                continue
            rid = stable_id("llm_rule", sid, [uid, kind, norm_label(ev.quote)], revision="business")
            frame = {}
            for name in FRAME_FIELDS:
                value = obj.get(name)
                hits = _align(ev.quote, value, min_len=2) if isinstance(value, str) and value.strip() else []
                if hits:
                    frame[name] = ev.quote[hits[0][0] : hits[0][1]]
            rules[rid] = BusinessRule(
                rule_id=rid, source_id=sid, kind=kind, statement=ev.quote, evidence=[ev], frame=frame
            )
    validate_business_graph(list(ent.values()), list(rel.values()))
    chunk_counts = Counter(u["unit_id"] for u, _, _ in jobs)
    failed_counts = Counter(row["evidence_unit_id"] for row in failures)
    statuses = [
        {
            "evidence_unit_id": u["unit_id"],
            "status": "failed" if u["unit_id"] in failed_units else "processed",
            "chunk_count": chunk_counts[u["unit_id"]],
            "completed_chunk_count": chunk_counts[u["unit_id"]] - failed_counts[u["unit_id"]],
        }
        for u in target_units
    ]
    omissions = [
        {"evidence_unit_id": u["unit_id"], "reason": "semantic_unit_budget_exceeded"}
        for u in eligible_units[len(target_units) :]
    ]
    omissions.extend(
        {"evidence_unit_id": u["unit_id"], "reason": "semantic_unit_failed"}
        for u in target_units
        if u["unit_id"] in failed_units
    )
    omissions.extend(terminal_omissions)
    return {
        "entities": [e.model_dump(mode="json") for e in ent.values()],
        "relations": [r.model_dump(mode="json") for r in rel.values()],
        "rules": [r.model_dump(mode="json") for r in rules.values()],
        "errors": [
            {"evidence_unit_id": r["evidence_unit_id"], "error_type": r["error_type"]} for r in failures
        ],
        "chunk_errors": failures,
        "processed_unit_count": len(ok_units - failed_units),
        "eligible_unit_count": len(eligible_units),
        "selected_unit_count": len(target_units),
        "omissions": omissions,
        "unit_statuses": statuses
        + [
            {
                "evidence_unit_id": u["unit_id"],
                "status": "not_selected",
                "chunk_count": 0,
                "completed_chunk_count": 0,
            }
            for u in eligible_units[len(target_units) :]
        ],
        "chunk_count": len(jobs),
        "grounding": stats,
    }


ENRICHABLE_KINDS = {"Product", "Organization", "EvidenceType", "ProductGroup", "ProductSubgroup"}
# The deterministic scoring-sheet tree is arithmetic-checked; the LLM may only anchor to it.
ANCHOR_ONLY_KINDS = {"Criterion"}
_LEADING_CODE = re.compile(r"^\s*(?:phần\s+)?(?:[a-z]|\d+(?:[.,]\d+)*)\s*[.,:)\-]\s*", re.I)


_SHEET_PREFIX = re.compile(r"^\s*bộ\s+sản\s+phẩm\s*:\s*", re.I)
GROUP_FAMILY = {"CriterionSheet", "ProductGroup", "ProductSubgroup"}


def _resolution_key(label: str) -> str:
    return norm_label(_SHEET_PREFIX.sub("", _LEADING_CODE.sub("", str(label), count=1), count=1))


def _match(row: dict, candidates: list[dict]) -> dict | None:
    """Same label may recur on several sheets: require a shared evidence unit, then a shared page."""
    units = {e["evidence_unit_id"] for e in row["evidence"]}
    pages = {e["pdf_page"] for e in row["evidence"]}
    tests = [lambda c: units & {e["evidence_unit_id"] for e in c.get("evidence", [])}]
    if row["kind"] not in {"Product", "Organization"}:
        tests.append(lambda c: pages & {e["pdf_page"] for e in c.get("evidence", [])})
    for test in tests:
        hits = [c for c in candidates if test(c)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return None
    # A unique name in this extraction is not a globally unique business identity.
    return (
        candidates[0]
        if len(candidates) == 1 and row["kind"] in {"EvidenceType", "ProductGroup", "ProductSubgroup"}
        else None
    )


def reconcile(proposed: dict, entities: list[dict], relations: list[dict]) -> dict:
    """Entity resolution against deterministic extraction (same source, kind, label without
    its leading code, and location).

    A matching LLM entity is folded into the existing one: its relations are re-pointed,
    duplicate relations dropped, and new descriptive features added only under keys the
    existing entity lacks. Scoring-sheet kinds are never modified, and an LLM Criterion
    without a deterministic match is dropped instead of forming a parallel tree."""
    index: dict[tuple, list[dict]] = {}

    def entity_key(row):
        return (
            norm_label(row["label"])
            if row["kind"] in {"Product", "Organization", "EvidenceType"}
            else _resolution_key(row["label"])
        )

    for e in entities:
        index.setdefault((e["source_id"], e["kind"], entity_key(e)), []).append(e)
    family = {}
    for e in entities:
        if e["kind"] in GROUP_FAMILY:
            family.setdefault((e["source_id"], _resolution_key(e["label"])), set()).add(e["kind"])
    options = {(e["source_id"], _resolution_key(e["label"])) for e in entities if e["kind"] == "ScoreOption"}
    remap, enriched, kept, unanchored, kind_conflicts = {}, 0, [], 0, 0
    for row in proposed["entities"]:
        key = (row["source_id"], entity_key(row))
        target = _match(row, index.get((row["source_id"], row["kind"], key[1]), []))
        if row["kind"] == "Condition" and key in options:
            kind_conflicts += 1  # an answer option restated as a condition
            continue
        if target is None and row["kind"] in GROUP_FAMILY and family.get(key, set()) - {row["kind"]}:
            kind_conflicts += 1  # deterministic structure already typed this name differently
            continue
        if target is None:
            if row["kind"] in ANCHOR_ONLY_KINDS:
                unanchored += 1
            else:
                kept.append(row)
            continue
        remap[row["entity_id"]] = target["entity_id"]
        if row["kind"] in ENRICHABLE_KINDS:
            # The LLM mention becomes another grounded mention of the existing entity.
            if target.get("status") == "rejected":
                continue
            before = json.dumps(target, sort_keys=True, ensure_ascii=False)
            evidence = target.setdefault("evidence", [])
            evidence.extend(e for e in row["evidence"] if e not in evidence)
            claims = target.setdefault("attribute_claims", [])
            claims.extend(c for c in row.get("attribute_claims", []) if c not in claims)
            attrs = target.setdefault("attributes", {})
            added = [k for k in row.get("attributes", {}) if k not in attrs]
            for k in added:
                attrs[k] = row["attributes"][k]
            for k, value in row.get("attributes", {}).items():
                if k.endswith("_candidate") and k in attrs and attrs[k] != value:
                    # Keep the incumbent reading and both source claims; flag the conflict.
                    attrs[k.removesuffix("_candidate") + "_conflict"] = True
            if added:
                enriched += len(added)
                previous = [k for k in str(attrs.get("llm_enriched_attributes") or "").split(",") if k]
                attrs["llm_enriched_attributes"] = ",".join(sorted(set(previous + added)))
            if target.get("status") == "verified" and before != json.dumps(
                target, sort_keys=True, ensure_ascii=False
            ):
                target["status"] = "candidate"
    units_of = {
        e["entity_id"]: {ev["evidence_unit_id"] for ev in e.get("evidence", [])}
        for e in list(entities) + kept
    }
    existing = {(r["relation_type"], r["source_entity_id"], r["target_entity_id"]): r for r in relations}
    out_rel, duplicates, ungrounded = [], 0, 0
    for row in proposed["relations"]:
        if (
            row["source_entity_id"] not in remap
            and row["source_entity_id"] not in units_of
            or row["target_entity_id"] not in remap
            and row["target_entity_id"] not in units_of
        ):
            ungrounded += 1  # endpoint dropped as unanchored
            continue
        row = dict(
            row,
            source_entity_id=remap.get(row["source_entity_id"], row["source_entity_id"]),
            target_entity_id=remap.get(row["target_entity_id"], row["target_entity_id"]),
        )
        key = (row["relation_type"], row["source_entity_id"], row["target_entity_id"])
        if key in existing:
            duplicates += 1
            old = existing[key]
            proof = old.setdefault("evidence", [])
            added_proof = [e for e in row["evidence"] if e not in proof]
            proof.extend(added_proof)
            if added_proof and old.get("status") == "verified":
                old["status"] = "candidate"
            continue
        shared = units_of.get(row["source_entity_id"], set()) & units_of.get(row["target_entity_id"], set())
        if not shared & {ev["evidence_unit_id"] for ev in row["evidence"]}:
            ungrounded += 1
            continue
        row["relation_id"] = stable_id(
            "llm_relation",
            row["evidence"][0]["source_id"],
            [row["relation_type"], row["source_entity_id"], row["target_entity_id"]],
            revision="business",
        )
        out_rel.append(row)
        existing[key] = row
    # A Condition only means something under its criterion; drop ones left without a parent.
    linked = {r["target_entity_id"] for r in out_rel if r["relation_type"] == "HAS_CONDITION"}
    orphans = [e for e in kept if e["kind"] == "Condition" and e["entity_id"] not in linked]
    kept = [e for e in kept if e not in orphans]
    unanchored += len(orphans)
    statuses = {e["entity_id"]: e.get("status") for e in entities + kept}
    for relation in relations:
        if relation.get("status") == "verified" and any(
            statuses.get(relation[endpoint]) != "verified"
            for endpoint in ("source_entity_id", "target_entity_id")
        ):
            relation["status"] = "candidate"
    return {
        **proposed,
        "entities": kept,
        "relations": out_rel,
        "reconciled": {
            "merged_entities": len(remap),
            "enriched_attributes": enriched,
            "duplicate_relations": duplicates,
            "ungrounded_after_merge": ungrounded,
            "unanchored_scoring_entities": unanchored,
            "kind_conflicts": kind_conflicts,
        },
    }
