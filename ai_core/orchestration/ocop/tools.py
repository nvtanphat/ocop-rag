"""Allowlisted domain tools mapped directly to indexing and graph adapters."""

from __future__ import annotations
from pathlib import Path
import json
from datetime import date
import re
import unicodedata
from itertools import zip_longest
from ocop_contracts.ratings import level_class
from ai_core.retrieval.ocop.search import search
from ai_core.retrieval.ocop.settings import get_settings
from ai_core.retrieval.ocop.lookup import exact_lookup
from ai_core.graph.ocop.retriever import traverse
from ai_core.graph.ocop.lookup import GraphEvidence
from ai_core.graph.ocop.links import LINK_RELATIONS, SetLinker
from ai_core.graph.ocop.builder import records
from ai_core.graph.ocop.temporal import resolve_event_applicability
from ai_core.orchestration.ocop.contracts import AuthContext
from ai_core.system.telemetry import traced
from ai_core.orchestration.ocop.semantic import normalize
from ai_core.orchestration.ocop.language import fold, get_language
from ai_core.orchestration.ocop.document_scope import DocumentResolver
from ai_core.retrieval.ocop.fusion import criterion_facets, order_evidence


def _jurisdiction_key(value: str) -> str:
    """Compare explicit locality labels, never infer locality from an arbitrary phrase."""
    key = normalize(value)
    prefixes = "|".join(
        r"\s+".join(re.escape(w) for w in normalize(x).split()) for x in get_language().cues["administrative_prefix"]
    )
    key = re.sub(r"^(?:" + prefixes + r")\s+", "", key)
    return re.sub(r"[^a-z0-9]", "", key)


def _recognition_stars(row: dict):
    values = [row.get(k) for k in ("star_rating", "rating_stars", "stars") if row.get(k) is not None]
    body = normalize(str(row.get("row_text") or row.get("text") or row.get("label_candidate") or ""))
    nouns = "|".join(r"\s+".join(re.escape(word) for word in normalize(value).split())
                     for value in get_language().star_noun if value.strip())
    stated = {int(m.group(1)) for m in re.finditer(
        r"(?<!\d)(" + level_class(certified=True) + r")\s*(?:" + nouns + r")(?![a-z0-9])", body
    )} if nouns else set()
    return values, stated


def _verified_recognition_scope(row: dict, *, region: str | None, stars: int | None) -> bool:
    """OCR guesses cannot satisfy restrictive, user-specified award filters."""
    if row.get("review_status") != "verified":
        return False
    if region:
        asked = _jurisdiction_key(region)
        labels = [row.get(k) for k in ("jurisdiction", "province", "region", "locality") if row.get(k)]
        # Source identifiers often contain a *full* provincial token: VN.GIALAI.QD.
        tokens = re.split(r"[^A-Za-z0-9]+", normalize(str(row.get("source_id") or "")))
        # Explicit metadata wins over filename tokens. Contradictory verified
        # locality labels are not resolved by guessing which label is correct.
        if labels:
            if not all(_jurisdiction_key(str(label)) == asked for label in labels):
                return False
        elif asked not in {_jurisdiction_key(token) for token in tokens}:
            return False
    if stars is not None:
        values, stated = _recognition_stars(row)
        if values:
            if any(str(v).strip() != str(stars) for v in values):
                return False
            if stated and stated != {stars}:
                return False
        else:
            # Allowed only for an individually human-verified row, with explicit
            # "N sao" on that row itself (not a PDF/source title or document date).
            if stated != {stars}:
                return False
    return True


def _recognition_records_in_scope(rows: list[dict], *, region, stars):
    groups = {}
    for index, row in enumerate(rows):
        ids = row.get("graph_node_ids")
        key = (row.get("source_id"), tuple(sorted(ids))) if (
            row.get("graph_node_type") == "RecognitionRecord" and isinstance(ids, list) and ids
            and all(isinstance(value, str) for value in ids)
        ) else ("row", index)
        groups.setdefault(key, []).append(row)
    result = []
    for group in groups.values():
        verified = [row for row in group if row.get("review_status") == "verified"]
        if not verified or not all(_verified_recognition_scope(row, region=region, stars=None) for row in verified):
            continue
        if stars is not None:
            ratings = [row for row in verified if any(_recognition_stars(row))]
            if not ratings or not all(_verified_recognition_scope(row, region=None, stars=stars) for row in ratings):
                continue
        result.extend(verified)
    return result


def _matching_entity_ids(nodes: list[dict], requested: str) -> set[str]:
    def identity(value):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value)).casefold()).strip()

    exact = {node["node_id"] for node in nodes if identity(node["label"]) == identity(requested)}
    if exact:
        return exact
    from ai_core.orchestration.ocop.language import has_diacritics

    key = identity if has_diacritics(requested) else normalize
    needle = key(requested)
    pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)")
    partial = [node for node in nodes if needle and pattern.search(key(node["label"]))]
    return {node["node_id"] for node in partial} if len({identity(node["label"]) for node in partial}) == 1 else set()


def _bounded_recognition_rows(rows: list[dict], limit: int) -> list[dict]:
    """Allocate a bounded result across records before taking more cells of any one record."""
    if len(rows) <= limit:
        return rows
    groups = {}
    for index, row in enumerate(rows):
        ids = row.get("graph_node_ids") or []
        key = (row.get("source_id"), tuple(sorted(ids))) if ids else ("row", index)
        groups.setdefault(key, []).append(row)
    return [row for batch in zip_longest(*groups.values()) for row in batch if row is not None][:limit]


def graph_seeds(
    checked_nodes: list[dict], query: str, product_name: str | None, source_filter: str | None
) -> list[str]:
    """Grounded traversal seeds: a resolved document, Product/Organization labels quoted in the
    question, and Product labels containing a product name the user literally wrote.

    A product slot only counts when its text occurs in the question itself, so a model-proposed
    slot can never become an alias."""
    qnorm = " " + normalize(query).replace("?", " ").replace(".", " ") + " "
    asked = normalize(product_name or "")
    asked = asked if len(asked) >= 3 and " " + asked + " " in qnorm else ""
    seeds = []
    for n in checked_nodes:
        if source_filter and n["source_id"] != source_filter:
            continue
        label = " " + normalize(n["label"]) + " "
        if (
            (source_filter and n["node_type"] == "SourceDocument")
            or (n["node_type"] in {"Product", "Organization", "Concept", "SubjectType", "ProductSet", "Authority",
                                    "AdministrativeArea", "FormTemplate", "CriterionSheet"}
                and len(label.strip()) >= 4 and label in qnorm)
            or (asked and n["node_type"] == "Product" and " " + asked + " " in label)
        ):
            seeds.append(n["node_id"])
    return seeds


PART_SCOPE_SLOTS = frozenset({"document_code", "document_codes", "region", "article_id", "pdf_page"})
BAD_DOCUMENT_STATUSES = frozenset({"document_not_found_or_ambiguous", "no_results", "unknown"})


def _section_evidence_units(graph, section, linked_units):
    """Keep source continuations between checked section anchors, never a whole-page expansion."""
    if not linked_units:
        return linked_units
    source = section.get("source_id")

    def order(uid):
        unit = graph.units.get(uid) or {}
        value = unit.get("properties", {}).get("source_order")
        return value if unit.get("source_id") == source and type(value) is int else None

    def start(node):
        return min((value for uid in node.get("evidence_unit_ids", [])
                    if (value := order(uid)) is not None), default=None)

    first = start(section)
    if first is None:
        return linked_units
    following = [value for node in graph.nodes.values()
                 if node.get("source_id") == source and node.get("node_type") == section.get("node_type")
                 and (value := start(node)) is not None and value > first]
    # Without a following section, stop at the last linked unit rather than opening the document tail.
    last = min(following) if following else max(
        (value + 1 for uid in linked_units if (value := order(uid)) is not None), default=first,
    )
    return linked_units | {
        uid for uid, unit in graph.units.items()
        if (value := order(uid)) is not None and first <= value < last
        and unit.get("properties", {}).get("unit_kind") != "page"
    }


class ToolRegistry:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_dir = self.root / "data/processed/ocop/index"
        self.graph_dir = self.root / "data/processed/ocop/graph"

    def _corpus_words(self) -> frozenset[str]:
        """Folded words that occur anywhere in the indexed evidence (what the corpus can be asked about)."""
        if not hasattr(self, "_words"):
            from ai_core.orchestration.ocop.language import fold

            words: set[str] = set()
            path = self.index_dir / "evidence_units.jsonl"
            if path.is_file():
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        words.update(re.findall(r"[a-z0-9]+", fold(json.loads(line).get("text") or "")))
            self._words = frozenset(words)
        return self._words

    def _set_linker(self) -> SetLinker:
        if not hasattr(self, "_linker"):
            self._linker = SetLinker.from_jsonl(self.index_dir / "evidence_units.jsonl")
        return self._linker

    def _linked_product_sheets(self, graph, slots: dict, query: str) -> list[dict] | None:
        """The framework's criterion sheets whose product list names the asked product, with the subgroup and group using them.

        People name a product ("nước mắm", "gạo ST25"); the framework names product sets ("Bộ sản phẩm: Tương, nước mắm,
        gia vị dạng lỏng khác"). The link is the set whose listed words cover the asked words that the fewest sets list
        (inverse set frequency, a pair of adjacent words counting double). None when no set is clearly named, so the
        caller keeps its own lookup; empty when sets exist but none is clearly named.
        """
        years = [str(y) for y in slots.get("years") or []]
        source = (
            self._resolve_source_id(slots["document_code"])
            if slots.get("document_code")
            else self._framework_source(years[0] if len(years) == 1 else None)
        )
        sheets = [n for n in graph.nodes.values() if n["node_type"] == "CriterionSheet" and n["source_id"] == source]
        if not sheets:
            return None
        # The whole question: an extracted name can be only its generic part ("thực phẩm" of "đồ chế biến từ gạo, ngũ
        # cốc ... nhóm thực phẩm khác"); a remembered name the question no longer writes is added.
        named = str(slots.get("product_name") or "")
        asked_text = query if fold(named) in fold(query) else f"{query} {named}"
        by_id = {n["node_id"]: n for n in sheets}
        chosen = [by_id[key] for key in self._set_linker().rank(asked_text, {k: n["label"] for k, n in by_id.items()})]
        if not chosen:
            return []  # no product set is clearly named
        ids = {n["node_id"] for n in chosen}
        subgroups = {
            e["source_entity_id"] for e in graph.edges if e["relation_type"] == "USES_SHEET" and e["target_entity_id"] in ids
        }
        groups = {
            e["source_entity_id"]
            for e in graph.edges
            if e["relation_type"] == "HAS_SUBGROUP" and e["target_entity_id"] in subgroups
        }
        return chosen + [graph.nodes[i] for i in (*sorted(subgroups), *sorted(groups)) if i in graph.nodes]

    def _star_level_seeds(self, nodes: list[dict], query: str, slots: dict) -> list[str]:
        """Star-level nodes of the current framework that the question names by level or by a score inside their range."""
        framework = self._framework_source()
        levels = [
            n
            for n in nodes
            if n.get("node_type") == "StarLevel"
            and n.get("source_id") == framework
            and (n.get("properties") or {}).get("star_level") is not None
        ]
        wanted = {int(slots["star_rating"])} if slots.get("star_rating") else set()
        score = get_language().alternation("score_noun")
        for match in re.finditer(r"(?<![\d.,])(\d{1,3})(?:[.,]\d+)?\s*" + score + r"\b", unicodedata.normalize("NFC", query), re.I):
            value = float(match.group(0).split()[0].replace(",", "."))
            for node in levels:
                props = node["properties"]
                low, high = props.get("min_points"), props.get("max_points")
                above = low is None or value > low or (value == low and props.get("min_inclusive") is not False)
                below = high is None or value < high or (value == high and props.get("max_inclusive") is not False)
                if above and below and (low is not None or high is not None):
                    wanted.add(int(props["star_level"]))
        return [n["node_id"] for n in levels if int(n["properties"]["star_level"]) in wanted]

    def _graph_failure(self):
        return {
            "results": [],
            "layer": "graph",
            "reason": "checked_graph_snapshot_unavailable",
            "status": "graph_integrity_failed"
            if (self.graph_dir / "manifest.json").is_file()
            else "graph_not_built",
        }

    def _framework_source(self, year: str | None = None) -> str | None:
        """Registry source of kind `ocop_framework` for a document year, or the newest one when no year is given."""
        path = self.root / "configs/ocop_sources.json"
        if not path.is_file():
            return None
        found = []
        for src in json.loads(path.read_text(encoding="utf-8")).get("sources", []):
            if src.get("source_kind") != "ocop_framework":
                continue
            years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", str(src.get("document_number") or src["source_id"]))
            found.append(
                (max(years) if years else "", str(src.get("effective_from") or ""), src["source_id"])
            )
        if year is not None:
            found = [x for x in found if x[0] == str(year)]
        return max(found)[2] if found else None

    def document_labels(self, source_ids: list[str]) -> list[str]:
        """Human-readable document numbers (falling back to the source id) for a list of registry sources."""
        path = self.root / "configs/ocop_sources.json"
        names = {}
        if path.is_file():
            names = {
                s["source_id"]: str(s.get("document_number") or "")
                for s in json.loads(path.read_text(encoding="utf-8")).get("sources", [])
            }
        return [names.get(sid) or sid for sid in source_ids]

    def _resolve_source_id(self, code: str | None) -> str | None:
        """Resolve the whole reference to one current source; ambiguity never broadens it."""
        return DocumentResolver(self.root).resolve(code)

    def _per_document(self, name: str, query: str, slots: dict, context: dict, auth, codes: list) -> dict:
        """A comparison names several documents: look each one up on its own and keep the rows of every one.

        A document that is not in the index is reported (`unresolved_documents`), never replaced by another."""
        results, unresolved, statuses = [], [], []
        for code in codes[:5]:
            one = self.dispatch(
                name,
                query=query,
                slots={**slots, "document_code": code, "document_codes": None},
                context=context,
                auth=auth,
            )
            rows = one.get("results", []) if isinstance(one, dict) else []
            statuses.append(one.get("status") if isinstance(one, dict) else None)
            if rows:
                results.extend({**row, "document_code": code} for row in rows)
            else:
                unresolved.append(code)
        merged = {"results": results, "unresolved_documents": unresolved}
        if results:
            merged["status"] = next((x for x in statuses if x and x not in BAD_DOCUMENT_STATUSES), "ok")
        else:
            merged["status"] = next((x for x in statuses if x), "no_results")
        return merged

    def _search_with_parts(self, query: str, slots: dict, context: dict, auth) -> dict:
        """The whole question first, then each part of a compound question; part hits only add candidates."""
        from ai_core.retrieval.ocop.decompose import sub_queries

        whole = self.dispatch(
            "search_regulations", query=query, slots=slots, context={**context, "_part": True}, auth=auth
        )
        seen = {self._hit_key(row) for row in whole.get("results", [])}
        extra = []
        earlier = []  # rows of the parts already searched, in order: what a later "văn bản đó" can point back to
        # The model's self-contained sub-questions and the parts cut at joining words are both searched, as RAG-Fusion
        # searches every phrasing: the model may write fewer parts than the question has, and a part it drops loses its hits.
        parts = list(context.get("aspects") or [])
        parts += [p for p in sub_queries(query) if all(fold(p) != fold(q) for q in parts)]
        for part in parts:
            scope = (
                self._anaphoric_source(
                    part,
                    earlier,
                    (slots.get("product_name"), slots.get("organization_name")),
                    mode=context.get("retrieval_mode", "sparse"),
                )
                if not slots.get("document_code")
                else None
            )
            found = self.search_part(
                part, slots, {**context, **({"_scope_source": scope} if scope else {})}, auth
            )
            earlier.extend(found.get("results", [])[:4])
            for row in found.get("results", [])[:4]:
                if self._hit_key(row) not in seen:
                    seen.add(self._hit_key(row))
                    extra.append({**row, "query_part": part})
        if not extra:
            return whole
        merged = {**whole, "results": [*whole.get("results", []), *extra]}
        if not whole.get("results"):
            merged.pop("status", None)  # part hits are real evidence even if the whole found none
        return merged

    def chunks_by_reference(
        self, refs: list[dict], *, exclude: set | None = None, limit: int = 6
    ) -> list[dict]:
        """Index chunks for remembered evidence references (by chunk id, else by evidence unit), as search-shaped rows."""
        path = self.index_dir / "chunks.jsonl"
        if not refs or not path.is_file():
            return []
        # graph rows carry a "graph-evidence:" id that is not an index chunk: those are re-read through their evidence unit
        by_chunk = {
            r["chunk_id"]
            for r in refs
            if r.get("chunk_id") and not r["chunk_id"].startswith("graph-evidence:")
        }
        by_unit = {
            (r["source_id"], r["evidence_unit_id"])
            for r in refs
            if (not r.get("chunk_id") or r["chunk_id"].startswith("graph-evidence:"))
            and r.get("evidence_unit_id")
        }
        out = []
        for ch in records(path):
            if len(out) >= limit:
                break
            if ch["chunk_id"] in (exclude or ()):
                continue
            if ch["chunk_id"] in by_chunk or (ch["source_id"], ch["evidence_unit_id"]) in by_unit:
                out.append(
                    {
                        "chunk_id": ch["chunk_id"],
                        "evidence_unit_id": ch["evidence_unit_id"],
                        "source_id": ch["source_id"],
                        "pdf_page": ch["spans"][0]["pdf_page"],
                        "source_spans": ch["spans"],
                        "review_status": ch["review_status"],
                        "corpus_version": ch["corpus_version"],
                        "score": 0.0,
                        "text": ch["text_for_bm25"],
                        "raw_text": ch.get("raw_text", ch["text_for_bm25"]),
                        "context": ch.get("context", {}),
                        "row_ids": ch.get("row_ids", []),
                        "table_headers": ch.get("table_headers", []),
                        "char_start": ch.get("char_start"),
                        "char_end": ch.get("char_end"),
                        "ranking_reason": "memory_evidence",
                        "from_memory": True,
                    }
                )
        return out

    def _anaphoric_source(
        self, part: str, earlier: list[dict], anchors: tuple = (), *, mode: str = "sparse"
    ) -> str | None:
        """Source a part like "văn bản đó do cơ quan nào ban hành" points back to.

        "That document" is the one that holds the thing the question names (a product, an organisation): the entity is
        searched on its own and the source that dominates the rows mentioning it is used. With no named entity, the source
        that dominates the rows of the parts before it. Without a clear single source the part is searched unscoped."""
        from collections import Counter
        from ai_core.orchestration.ocop import memory
        from ai_core.orchestration.ocop.language import fold, get_language

        noun = memory._noun_pattern(get_language(), "document")
        if not re.search(r"(?:" + noun + r")\s+" + memory.DEMONSTRATIVE + r"\b", fold(part)):
            return None
        wanted = [fold(a) for a in anchors if a]
        if wanted:
            try:
                rows = search(self.index_dir, " ".join(a for a in anchors if a), mode=mode, top_k=8)
            except (RuntimeError, ValueError, OSError):
                return None
            rows = [
                r
                for r in rows
                if any(a in fold(str(r.get("raw_text") or r.get("text") or "")) for a in wanted)
            ]
        else:
            rows = [r for r in earlier if r.get("source_id")]
        top = Counter(r["source_id"] for r in rows).most_common(1)
        return top[0][0] if top and top[0][1] / len(rows) >= get_settings().agent.source_agreement_share else None

    def search_part(self, part: str, slots: dict, context: dict, auth) -> dict:
        """Search one part of a question, scoped by what that part names itself: "Thành Sen hạn nộp ..., và theo QĐ26 ..."
        must not filter the local-deadline part by the other part's document."""
        from ai_core.orchestration.ocop.router import extract_slots

        own = extract_slots(part)
        part_slots = {
            **{k: v for k, v in slots.items() if k not in PART_SCOPE_SLOTS},
            **{k: v for k, v in own.items() if k in PART_SCOPE_SLOTS},
        }
        return self.dispatch(
            "search_regulations", query=part, slots=part_slots, context={**context, "_part": True}, auth=auth
        )

    @staticmethod
    def _hit_key(row: dict):
        return row.get("chunk_id") or (
            row.get("source_id"),
            row.get("evidence_unit_id"),
            str(row.get("text"))[:80],
        )

    @traced("ocop.agent.tool_dispatch")
    def dispatch(
        self,
        name: str,
        *,
        query: str,
        slots: dict,
        context: dict | None = None,
        auth: AuthContext | None = None,
    ) -> dict:
        context = context or {}
        from ai_core.orchestration.ocop.capabilities import TOOL_REGISTRY

        if name not in TOOL_REGISTRY:
            raise ValueError("Unknown or unauthorized OCOP tool: " + name)
        if TOOL_REGISTRY[name].requires_auth and not isinstance(auth, AuthContext):
            raise PermissionError("This private OCOP tool requires trusted server authentication")
        codes = slots.get("document_codes")
        if name == "search_regulations" and not context.get("_part"):
            return self._search_with_parts(query, slots, context, auth)
        if name in ("search_regulations", "lookup_legal_unit") and isinstance(codes, list) and len(codes) > 1:
            return self._per_document(name, query, slots, context, auth, codes)
        if name == "search_regulations":
            mode = context.get("retrieval_mode", "sparse")
            doc = slots.get("document_code")
            source_filter = self._resolve_source_id(doc) if doc else None
            if slots.get("sheet_number"):
                from ai_core.graph.ocop.integrity import validate_graph_snapshot

                try:
                    gm = validate_graph_snapshot(
                        self.graph_dir, allow_partial=context.get("allow_partial_debug") is True
                    )
                    im = json.loads((self.index_dir / "manifest.json").read_text(encoding="utf8"))
                    from ai_core.graph.ocop.integrity import graph_index_mismatch

                    if graph_index_mismatch(gm, im):
                        raise ValueError("sheet graph/index version mismatch")
                    path = self.graph_dir / "snapshots" / gm["graph_version"]
                    validate_graph_snapshot(path, allow_partial=context.get("allow_partial_debug") is True)
                    nodes = {
                        n["node_id"]: n
                        for n in records(path / "nodes.jsonl")
                        if n.get("check") == "passed"
                    }
                    seeds = [
                        n
                        for n in nodes.values()
                        if n["node_type"] == "CriterionSheet"
                        and str(n.get("properties", {}).get("sheet_number")) == str(slots["sheet_number"])
                        and (not doc or source_filter and n["source_id"] == source_filter)
                    ]
                    if len(seeds) != 1:
                        raise ValueError("sheet not unique")
                    ids = {seeds[0]["node_id"]}
                    edges = [
                        e
                        for e in records(path / "edges.jsonl")
                        if e.get("check") == "passed"
                        and e["relation_type"] in {"HAS_CRITERION", "HAS_SUBCRITERION", "HAS_OPTION"}
                        and e["source_entity_id"] in nodes
                        and e["target_entity_id"] in nodes
                    ]
                    while True:
                        children = {e["target_entity_id"] for e in edges if e["source_entity_id"] in ids}
                        if children <= ids:
                            break
                        ids.update(children)
                    units = {
                        uid
                        for identity in ids - {seeds[0]["node_id"]}
                        for uid in nodes[identity].get("evidence_unit_ids", [])
                    }
                    # Apply checked sheet membership before top-K; filtering
                    # forty document-wide hits can lose the entire sheet.
                    scoped = search(
                        self.index_dir,
                        query,
                        source_id=seeds[0]["source_id"],
                        mode=mode,
                        top_k=32,
                        evidence_unit_ids=units,
                        rerank=bool(context.get("rerank", False)),
                    )
                    graph = GraphEvidence(
                        self.graph_dir,
                        self.index_dir,
                        allow_partial_debug=context.get("allow_partial_debug") is True,
                    )
                    for facet in criterion_facets(query):
                        matches = [
                            identity
                            for identity in ids
                            if re.match(r"^" + re.escape(facet) + r"(?!\d)", nodes[identity]["label"])
                        ]
                        descendants, links = graph.descendants(matches, {"HAS_OPTION", "HAS_CONDITION"})
                        for row in graph.node_rows([nodes[i] for i in sorted(descendants)]):
                            row.setdefault("context", {})["criterion_codes"] = [facet]
                            row["graph_edge_ids"] = [edge["edge_id"] for edge in links]
                            scoped.append(row)
                    return {
                        "results": order_evidence(query, scoped),
                        "status": "checked_sheet_text" if scoped else "sheet_scope_unavailable",
                        "graph_trace": {
                            "graph_version": gm["graph_version"],
                            "seed_ids": [seeds[0]["node_id"]],
                            "node_checks": {identity: nodes[identity]["check"] for identity in sorted(ids)},
                            "edge_checks": {
                                edge["edge_id"]: edge["check"]
                                for edge in edges
                                if edge["source_entity_id"] in ids and edge["target_entity_id"] in ids
                            },
                        },
                    }
                except (ValueError, KeyError, OSError):
                    return {"results": [], "status": "sheet_scope_unavailable"}
            region = slots.get("region")
            # Local deadlines are jurisdiction-specific: never answer with a
            # national document or an unrelated province when multiple guidance
            # files happen to exist. Enforce the source allowlist before ranking.
            local_deadline = bool(region and get_language().hit(query, "deadline"))
            if local_deadline:
                sources_path = self.root / "configs/ocop_sources.json"
                sources = []
                if sources_path.is_file():
                    sources = json.loads(sources_path.read_text(encoding="utf-8")).get("sources", [])
                # A jurisdiction reads "province - locality": guidance of a locality is the guidance of that place, and
                # also what the province it lies in can be told, with the narrower scope stated in the answer.
                asked = _jurisdiction_key(str(region))
                matched = [
                    src
                    for src in sources
                    if src.get("source_kind") == "local_guidance"
                    and src.get("source_id")
                    and asked
                    in {
                        _jurisdiction_key(str(src.get("jurisdiction") or "")),
                        *(_jurisdiction_key(part) for part in re.split(r"\s+-\s+", str(src.get("jurisdiction") or ""))),
                    }
                ]
                local = list(dict.fromkeys(str(src["source_id"]) for src in matched))
                narrower = sorted(
                    {
                        str(src.get("jurisdiction"))
                        for src in matched
                        if asked != _jurisdiction_key(str(src.get("jurisdiction") or ""))
                        and asked != _jurisdiction_key(re.split(r"\s+-\s+", str(src.get("jurisdiction") or ""))[-1])
                    }
                )
                if not local:
                    return {
                        "results": [],
                        "status": "local_guidance_not_in_corpus",
                        "reason": "no_local_submission_window_source",
                    }
                if doc and source_filter not in local:
                    return {
                        "results": [],
                        "status": "local_guidance_document_scope_mismatch",
                        "reason": "requested_document_not_a_local_guidance_source",
                    }
                selected = [source_filter] if doc else local
                hits = []
                seen = set()
                for allowed_source in selected:
                    for hit in search(
                        self.index_dir,
                        query,
                        mode=mode,
                        top_k=8,
                        source_id=allowed_source,
                        rerank=bool(context.get("rerank", False)),
                    ):
                        # Defend even if a search adapter violates its filter.
                        if hit.get("source_id") != allowed_source:
                            continue
                        key = (
                            hit.get("chunk_id")
                            or hit.get("evidence_unit_id")
                            or (allowed_source, str(hit.get("pdf_page")), str(hit.get("text")))
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append(hit)
                return {
                    "results": hits[:12],
                    "status": "local_guidance_scoped",
                    **({"narrower_scope": narrower} if narrower else {}),
                }
            # A question explicitly about *a local document* is not answered
            # from another province simply because BM25 ranks its wording high.
            # This is intentionally narrower than "rules applicable in Huế":
            # national legislation may legitimately apply there.
            local_document_query = bool(
                region
                and not doc
                and get_language().hit(query, "local_document")
            )
            if local_document_query:
                registry = self.root / "configs/ocop_sources.json"
                entries = (
                    json.loads(registry.read_text(encoding="utf-8")).get("sources", [])
                    if registry.is_file()
                    else []
                )
                region_key = _jurisdiction_key(str(region))
                local_ids = [
                    str(src["source_id"])
                    for src in entries
                    if _jurisdiction_key(str(src.get("jurisdiction") or ""))
                    in (region_key, "tinh" + region_key, "thanhpho" + region_key)
                ]
                if not local_ids:
                    return {"results": [], "status": "local_document_not_in_corpus"}
                hits = []
                seen = set()
                for allowed_source in local_ids:
                    for hit in search(
                        self.index_dir,
                        query,
                        mode=mode,
                        top_k=8,
                        source_id=allowed_source,
                        rerank=bool(context.get("rerank", False)),
                    ):
                        if hit.get("source_id") != allowed_source:
                            continue
                        key = hit.get("chunk_id")
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append(hit)
                hits.sort(key=lambda row: -float(row.get("score") or 0))
                return {"results": hits[:8], "status": "local_document_scoped"}
            # Business intent alone does not pin a document version or scope.
            # Broad queries rank across the checked corpus; only an explicit
            # document_code, locality policy above, or verified structured tool
            # may constrain the source set.
            if doc and not source_filter:
                return {"results": [], "status": "document_not_found_or_ambiguous"}
            return {
                "results": search(
                    self.index_dir,
                    query,
                    mode=mode,
                    top_k=8,
                    source_id=source_filter or context.get("_scope_source"),
                    rerank=bool(context.get("rerank", False)),
                    with_continuations=True,
                )
            }
        if name == "lookup_legal_unit":
            code = slots.get("document_code")
            source = self._resolve_source_id(code) if code else None
            if code and not source:
                return {"results": [], "status": "document_not_found_or_ambiguous"}
            try:
                graph = GraphEvidence(
                    self.graph_dir,
                    self.index_dir,
                    allow_partial_debug=context.get("allow_partial_debug") is True,
                )
            except (OSError, ValueError, KeyError):
                return self._graph_failure()
            if (
                not slots.get("article_id")
                and not slots.get("pdf_page")
                and get_language().hit(normalize(query), "authority")
            ):
                # "Who recognises N-star products?" is answered by the legal unit naming that
                # authority, not by text that merely contains the word "thẩm quyền".
                return {
                    "results": graph.authority(star_rating=slots.get("star_rating"), source_id=source),
                    "status": "checked_graph_authority_units",
                }
            rows = graph.legal(
                source_id=source, article=slots.get("article_id"), pdf_page=slots.get("pdf_page"), query=query
            )
            if (
                rows
                and slots.get("article_id")
                and not slots.get("pdf_page")
                and (self.index_dir / "chunks.jsonl").is_file()
            ):
                allowed = {row["evidence_unit_id"] for row in rows}
                hits = search(
                    self.index_dir,
                    query,
                    source_id=source,
                    evidence_unit_ids=allowed,
                    mode=context.get("retrieval_mode", "sparse"),
                    top_k=32,
                    rerank=bool(context.get("rerank", False)),
                )
                for hit in hits:
                    unit = graph.units[hit["evidence_unit_id"]]
                    hit.update({"graph_node_ids": [unit["node_id"]], "check": unit["check"]})
                rows = hits + rows
            if slots.get("article_id"):
                # The passages were fetched under this article: that scope, not the question's wording, says where they sit.
                rows = [{**row, "resolved_locator": {"article_id": str(slots["article_id"])}} for row in rows]
            return {
                "results": rows,
                "status": ("exact_pdf_page" if rows else "requested_pdf_page_not_indexed")
                if slots.get("pdf_page")
                else "checked_graph_legal_units",
            }
        if name == "lookup_evidence_requirements":
            if slots.get("years") and not slots.get("document_code"):
                return {
                    "results": [],
                    "status": "assessment_year_scope_unverified",
                    "reason": "historical_evidence_requirements_need_verified_version",
                }
            # Structured records are authoritative only when individually
            # verified. OCR candidates remain clearly flagged. Linking a
            # product name alone is insufficient to assert mandatory paperwork.
            doc = slots.get("document_code")
            source_filter = self._resolve_source_id(doc) if doc else None
            if doc and not source_filter:
                return {"results": [], "status": "document_not_found_or_ambiguous"}
            if (
                not source_filter
                and len(slots.get("years", [])) == 1
                and not context.get("sector_compliance", False)
            ):
                source_filter = self._framework_source(str(slots["years"][0]))
            linked_criterion = slots.get("criterion_id")
            try:
                graph = GraphEvidence(
                    self.graph_dir,
                    self.index_dir,
                    allow_partial_debug=context.get("allow_partial_debug") is True,
                )
            except (OSError, ValueError, KeyError):
                return self._graph_failure()
            requirement_nodes = [n for n in graph.nodes.values() if n["node_type"] == "EvidenceType"]
            if linked_criterion:
                parents = {
                    n["node_id"]
                    for n in graph.nodes.values()
                    if n["node_type"] == "Criterion"
                    and re.match(r"^" + re.escape(str(linked_criterion)) + r"(?!\d)", n["label"])
                }
                required = {
                    edge["target_entity_id"]
                    for edge in graph.edges
                    if edge["source_entity_id"] in parents and edge["relation_type"] == "REQUIRES_EVIDENCE"
                }
                requirement_nodes = [n for n in requirement_nodes if n["node_id"] in required]
            rows = graph.node_rows(requirement_nodes)
            if source_filter:
                rows = [x for x in rows if x.get("source_id") == source_filter]
            if rows:
                return {
                    "results": rows[:12],
                    "status": "checked_graph_requirements",
                    "verified": all(x.get("review_status") == "verified" for x in rows[:12]),
                }
            # Source-backed text retrieval is an explicit fallback, never a
            # fabricated structured requirement and never a verified rule.
            keyword = " ".join([*get_language().cues["evidence_search_terms"], query])
            return {
                "results": search(
                    self.index_dir,
                    keyword,
                    source_id=source_filter,
                    mode=context.get("retrieval_mode", "sparse"),
                    top_k=16,
                    evidence_unit_ids=set(graph.units),
                    rerank=bool(context.get("rerank", False)),
                ),
                "status": "text_evidence_fallback",
                "verified": False,
            }
        if name == "lookup_form" and slots.get("years") and not slots.get("document_code"):
            return {
                "results": [],
                "status": "assessment_year_scope_unverified",
                "reason": "historical_form_template_requires_document_version",
            }
        if name == "lookup_form" and not (slots.get("form_id") or slots.get("form_ids")):
            return {
                "results": [],
                "status": "form_identifier_not_specified",
                "reason": "use_regulation_search_for_unspecified_form",
            }
        if name in ("lookup_form", "lookup_criterion", "lookup_product_subgroup", "lookup_recognition"):
            row_limit = get_settings().agent.lookup_max_rows
            document_code = slots.get("document_code")
            resolved_source = self._resolve_source_id(document_code) if document_code else None
            if document_code and not resolved_source:
                return {"results": [], "status": "document_not_found_or_ambiguous"}
            try:
                graph = GraphEvidence(
                    self.graph_dir,
                    self.index_dir,
                    allow_partial_debug=context.get("allow_partial_debug") is True,
                )
            except (OSError, ValueError, KeyError):
                return self._graph_failure()
            mapping = {
                "lookup_form": {"FormTemplate"},
                "lookup_criterion": {"Criterion", "Subcriterion"},
                "lookup_product_subgroup": {"ProductSubgroup", "ProductGroup"},
                "lookup_recognition": {"RecognitionRecord"},
            }
            nodes = [n for n in graph.nodes.values() if n["node_type"] in mapping[name]]
            linked = self._linked_product_sheets(graph, slots, query) if name == "lookup_product_subgroup" else None
            if linked:
                nodes = linked
            elif name == "lookup_product_subgroup" and not slots.get("product_name"):
                # The question names no product set. Returning the first taxonomy nodes would answer every product
                # with the same group; an ordinary miss lets the planner's text recovery search instead.
                return {"results": [], "status": "no_results", "reason": "no_product_set_named"}
            asked_products = [
                str(x)
                for x in (slots.get("product_names") or [slots.get("product_name")])
                if x
            ]
            if name == "lookup_recognition" and asked_products:
                product_nodes = [node for node in graph.nodes.values() if node["node_type"] == "Product"]
                products = set().union(*(_matching_entity_ids(product_nodes, asked) for asked in asked_products))
                generic = False
                if not products:
                    # A name whose words all occur in the corpus is a kind of product ("mứt"), not an unknown product:
                    # list the records whose product label carries those words, or none restricted when nothing does.
                    # A name with a word the corpus never uses ("ST25" in a corpus without it) is reported as absent.
                    known = self._corpus_words()
                    lang = get_language()
                    words = [w for asked in asked_products for w in lang.content_words(asked, accent_aware=True)]
                    if all(w in known for w in words):
                        generic = True
                        products = {
                            node["node_id"]
                            for node in product_nodes
                            if words and set(words) <= set(lang.content_words(node["label"], accent_aware=True))
                        }
                    else:
                        return {
                            "results": [],
                            "status": "entity_not_found",
                            "entity": [str(x) for x in (slots.get("product_names") or [slots.get("product_name")]) if x],
                        }
                record_ids = {
                    edge["source_entity_id"]
                    for edge in graph.edges
                    if edge["relation_type"] == "RECOGNIZES" and edge["target_entity_id"] in products
                }
                if products and not generic and not record_ids and (slots.get("region") or slots.get("star_rating")):
                    # The product exists in the graph but no recognition record points at it (a list row the graph did not
                    # link): this is a gap in the structured data, not a verified "not recognised"; the text search answers.
                    return {"results": [], "status": "no_results"}
                if not (generic and not record_ids):
                    nodes = [n for n in nodes if n["node_id"] in record_ids]
            asked_orgs = [str(slots["organization_name"])] if slots.get("organization_name") else []
            if name == "lookup_recognition" and asked_orgs:
                organization_nodes = [node for node in graph.nodes.values() if node["node_type"] == "Organization"]
                orgs = set().union(*(_matching_entity_ids(organization_nodes, asked) for asked in asked_orgs))
                if not orgs:
                    return {"results": [], "status": "entity_not_found", "entity": [str(slots["organization_name"])]}
                # One owner can appear as several Organization nodes (full name and abbreviation) and one product as several
                # Product nodes, while a record's DECLARED_BY edge reaches only one of them: a record also belongs to the
                # owner of the product it recognizes, matched by label within the same document.
                owned_products = {
                    (graph.nodes[edge["source_entity_id"]]["source_id"], normalize(graph.nodes[edge["source_entity_id"]]["label"]))
                    for edge in graph.edges
                    if edge["relation_type"] == "OWNED_BY" and edge["target_entity_id"] in orgs
                }
                declared = {
                    edge["source_entity_id"]
                    for edge in graph.edges
                    if (edge["relation_type"] == "DECLARED_BY" and edge["target_entity_id"] in orgs)
                    or (
                        edge["relation_type"] == "RECOGNIZES"
                        and (
                            graph.nodes[edge["target_entity_id"]]["source_id"],
                            normalize(graph.nodes[edge["target_entity_id"]]["label"]),
                        )
                        in owned_products
                    )
                }
                nodes = [n for n in nodes if n["node_id"] in declared]
            scoped_units = None
            if name == "lookup_criterion" and slots.get("sheet_number"):
                doc = slots.get("document_code")
                source = self._resolve_source_id(doc) if doc else None
                sheets = [
                    n["node_id"]
                    for n in graph.nodes.values()
                    if n["node_type"] == "CriterionSheet"
                    and str(n.get("properties", {}).get("sheet_number")) == str(slots["sheet_number"])
                    and (not doc or source and n["source_id"] == source)
                ]
                if len(sheets) > 1 and not doc:
                    # The same sheet number exists in several documents: the user chooses, nothing is guessed.
                    holders = sorted({graph.nodes[identity]["source_id"] for identity in sheets})
                    if len(holders) > 1:
                        return {
                            "results": [],
                            "status": "sheet_document_ambiguous",
                            "candidate_documents": self.document_labels(holders),
                        }
                if len(sheets) != 1:
                    return {"results": [], "status": "sheet_scope_unavailable"}
                scope, _ = graph.descendants(sheets, {"HAS_CRITERION", "HAS_SUBCRITERION", "HAS_OPTION"})
                scoped_units = {
                    uid for identity in scope - set(sheets)
                    for uid in graph.nodes[identity].get("evidence_unit_ids", [])
                } & set(graph.units)
                scoped_units = _section_evidence_units(graph, graph.nodes[sheets[0]], scoped_units)
                nodes = [n for n in nodes if n["node_id"] in scope]
            rows = graph.node_rows(nodes)
            if name == "lookup_recognition" and asked_products:
                for row in rows:
                    links = [
                        edge
                        for edge in graph.edges
                        if edge["relation_type"] == "RECOGNIZES"
                        and edge["source_entity_id"] in row["graph_node_ids"]
                        and edge["target_entity_id"] in products
                    ]
                    row["graph_edge_ids"] = [edge["edge_id"] for edge in links]
                    row["graph_node_ids"] += list(dict.fromkeys(edge["target_entity_id"] for edge in links))
            # Candidate type lookup returns all matching candidates, marked needs_review.
            needle = (
                (slots.get("form_id") or (slots.get("form_ids") or [None])[0])
                if name == "lookup_form"
                else slots.get("product_name")
            )
            if name == "lookup_recognition" or linked:
                needle = None  # Keep all source cells of the matched record (owner included) or of the linked sheet.
            requested_criterion = slots.get("criterion_id") if name == "lookup_criterion" else None
            if document_code:
                rows = [row for row in rows if row["source_id"] == resolved_source]
            if name == "lookup_recognition" and (slots.get("region") or slots.get("star_rating")):
                rows = _recognition_records_in_scope(rows, region=slots.get("region"), stars=slots.get("star_rating"))
                if not rows:
                    return {
                        "results": [],
                        "status": "recognition_scope_unverified",
                        "reason": "no_verified_rows_match_region_and_star_constraints",
                    }
            if needle:
                if name == "lookup_form":
                    requested_numbers = slots.get("form_ids") or [needle]
                    if not all(re.fullmatch(r"[1-9]\d?", str(n)) for n in requested_numbers):
                        return {"results": [], "status": "invalid_form_id"}
                    requested_forms = {str(int(n)) for n in requested_numbers}
                    rows = [
                        r
                        for r in rows
                        if str(r.get("form_number") or "").strip().isdigit()
                        and str(int(str(r["form_number"]).strip())) in requested_forms
                    ]
                    if len(requested_forms) > 1:
                        # Do not silently answer a two-form comparison from one
                        # row, nor treat OCR-only form candidates as confirmed.
                        verified_forms = {
                            str(int(str(row["form_number"]).strip()))
                            for row in rows
                            if row.get("review_status") == "verified"
                            and row.get("source_id")
                            and (row.get("source_spans") or row.get("spans"))
                        }
                        missing = sorted(requested_forms - verified_forms, key=int)
                        if missing:
                            return {
                                "results": rows[:row_limit],
                                "status": "incomplete_form_ids",
                                "missing_form_ids": missing,
                                "verified": False,
                            }
                        by_source: dict[str, dict[str, dict]] = {}
                        for row in rows:
                            if (
                                row.get("review_status") != "verified"
                                or not row.get("source_id")
                                or not (row.get("source_spans") or row.get("spans"))
                            ):
                                continue
                            form = str(int(str(row["form_number"]).strip()))
                            by_source.setdefault(str(row["source_id"]), {}).setdefault(form, row)
                        complete = [
                            sid for sid, forms in by_source.items() if requested_forms.issubset(forms)
                        ]
                        if not complete:
                            return {
                                "results": [],
                                "status": "form_source_scope_unverified",
                                "reason": "form_ids_only_verified_across_different_documents",
                            }
                        if len(complete) > 1:
                            return {
                                "results": [],
                                "status": "form_version_ambiguous",
                                "reason": "multiple_document_versions_contain_requested_forms",
                                "candidate_documents": self.document_labels(sorted(complete)),
                            }
                        # Include at least one verified unit per requested form,
                        # regardless of OCR duplicates ordering or output limit.
                        selected = by_source[complete[0]]
                        rows = [selected[form] for form in sorted(requested_forms, key=int)]
                else:
                    rows = [
                        r
                        for r in rows
                        if str(needle).casefold()
                        in (
                            str(r.get("title", ""))
                            + " "
                            + str(r.get("label_candidate", ""))
                            + " "
                            + str(r.get("heading", ""))
                            + " "
                            + str(r.get("row_text", ""))
                            + " "
                            + str(r.get("text", ""))
                        ).casefold()
                    ]
            if requested_criterion:
                import re as _re

                # Only match an explicit criterion code at the beginning of a
                # labeled criterion. Never infer IDs from arbitrary score digits.
                noun = get_language().alternation(get_language().structure_nouns["criterion"])
                pattern = _re.compile(
                    r"^(?:" + noun + r"\s*)?" + _re.escape(str(requested_criterion)) + r"(?=\s|[.):-]|$)", _re.I
                )
                rows = [
                    r
                    for r in rows
                    if str(r.get("criterion_id") or r.get("criterion_code") or "") == str(requested_criterion)
                    or pattern.search(str(r.get("label_candidate", "")).strip())
                ]
            if not rows and name in ("lookup_criterion", "lookup_product_subgroup"):
                # Missing historical-year structured matches cannot silently
                # fall back to a later framework's text and imply applicability.
                if slots.get("years") and not document_code:
                    return {
                        "results": [],
                        "status": "assessment_year_scope_unverified",
                        "reason": "versioned_taxonomy_or_criteria_not_verified_for_requested_year",
                    }
                # OCR table labels often do not repeat the product-group name.
                # Search grounded source spans rather than fabricating a
                # structured criterion match. Caller sees the fallback mode.
                source_filter = self._resolve_source_id(document_code) if document_code else None
                if document_code and not source_filter:
                    return {"results": [], "status": "document_not_found_or_ambiguous"}
                # For OCOP taxonomy, a broad unfiltered lexical match can
                # accidentally select a food-safety table instead of the OCOP
                # taxonomy annex. Prefer the registry's framework document for
                # an unpinned query (the newest one, or the one of the asked
                # year); a year with no framework document stays unpinned
                # rather than silently applying another version's criteria.
                years = [str(y) for y in slots.get("years", [])]
                if name == "lookup_product_subgroup" and not source_filter and len(years) <= 1:
                    source_filter = self._framework_source(years[0] if years else None)
                if scoped_units is not None and not scoped_units:
                    return {"results": [], "status": "sheet_scope_unavailable"}
                return {
                    "results": search(
                        self.index_dir,
                        query,
                        source_id=source_filter,
                        mode=context.get("retrieval_mode", "sparse"),
                        top_k=16,
                        evidence_unit_ids=scoped_units if scoped_units is not None else set(graph.units),
                        rerank=bool(context.get("rerank", False)),
                    ),
                    "verified": False,
                    "status": "text_evidence_fallback",
                    "fallback": "source_filtered_text_search",
                }
            # A decision's issuance year is NOT its recognition-event year.
            # A criterion sheet's document year is NOT its assessment year.
            # No filename-based inference is permitted for these scopes.
            years = slots.get("years") or []
            scoped_year = None
            if name == "lookup_recognition":
                scoped_year = slots.get("recognition_year")
                if len(years) > 1 and not document_code:
                    return {
                        "results": [],
                        "status": "recognition_year_scope_unverified",
                        "reason": "multiple_event_years_need_verified_recognition_records",
                    }
                if scoped_year is None and len(years) == 1 and not document_code:
                    scoped_year = years[0]
                year_fields = ("recognition_event_year", "recognition_year")
            elif name == "lookup_criterion":
                scoped_year = slots.get("assessment_year")
                if not document_code and years:
                    if len(years) > 1:
                        return {
                            "results": [],
                            "status": "assessment_year_scope_unverified",
                            "reason": "comparison_requires_verified_version_rules",
                        }
                    scoped_year = scoped_year or years[0]
                year_fields = ("assessment_year",)
            else:
                year_fields = ()
            if scoped_year is not None:
                # An explicit event year constrains even a pinned decision.
                # OCR candidates lacking a verified event-year cannot satisfy
                # this explicit request. A bounded text recovery may still
                # provide *background evidence*, never a verified award/score.
                rows = [
                    r
                    for r in rows
                    if r.get("review_status") == "verified"
                    and any(str(r.get(field) or "") == str(scoped_year) for field in year_fields)
                ]
                if not rows:
                    return {
                        "results": [],
                        "status": (
                            "recognition_year_scope_unverified"
                            if name == "lookup_recognition"
                            else "assessment_year_scope_unverified"
                        ),
                        "reason": "no_verified_records_with_requested_event_year",
                    }
            if name == "lookup_criterion" and not document_code and not scoped_year:
                current = self._framework_source()
                rows.sort(
                    key=lambda r: (
                        str(r.get("source_id", "")) != current,
                        str(r.get("source_id", "")),
                        int(r.get("pdf_page") or 0),
                    )
                )
            # Completeness describes the delivered set, after every scope and output limit.
            rows = _bounded_recognition_rows(rows, row_limit) if name == "lookup_recognition" else rows[:row_limit]
            if name == "lookup_criterion":
                # The sheet and criterion the rows were fetched under: scope the tool resolved, not wording from the question.
                locator = {key: str(slots[key]) for key in ("sheet_number", "criterion_id") if slots.get(key)}
                if locator:
                    rows = [{**row, "resolved_locator": {**locator, **(row.get("resolved_locator") or {})}} for row in rows]
            missing_entities = []
            if name == "lookup_recognition" and (asked_products or asked_orgs):
                represented = {node_id for row in rows for node_id in row.get("graph_node_ids", [])}
                for requested, entity_nodes, relation in (
                    (asked_products, [n for n in graph.nodes.values() if n["node_type"] == "Product"], "RECOGNIZES"),
                    (asked_orgs, [n for n in graph.nodes.values() if n["node_type"] == "Organization"], "DECLARED_BY"),
                ):
                    for asked in requested:
                        matches = _matching_entity_ids(entity_nodes, asked)
                        if not any(edge["relation_type"] == relation and edge["source_entity_id"] in represented
                                   and edge["target_entity_id"] in matches for edge in graph.edges):
                            missing_entities.append(asked)
            return {"results": rows, "verified": False,
                    "status": "incomplete_entity_set" if rows and missing_entities else "ok" if rows else "no_results",
                    **({"missing_entities": missing_entities} if missing_entities else {})}
        if name == "search_graph":
            document_code = slots.get("document_code")
            source_filter = self._resolve_source_id(document_code) if document_code else None
            if document_code and not source_filter:
                return {"results": [], "status": "document_not_found_or_ambiguous"}
            # Check *all* files before linking evidence IDs or traversing edges.
            # A partly generated graph must behave like an unavailable index.
            if not all(
                (self.graph_dir / f).is_file() for f in ("manifest.json", "nodes.jsonl", "edges.jsonl")
            ):
                return {"results": [], "note": "graph_not_built", "status": "graph_not_built"}
            from ai_core.graph.ocop.integrity import validate_graph_snapshot

            try:
                graph_manifest = validate_graph_snapshot(
                    self.graph_dir, allow_partial=context.get("allow_partial_debug") is True
                )
                index_manifest_file = self.index_dir / "manifest.json"
                if index_manifest_file.is_file():
                    index_manifest = json.loads(index_manifest_file.read_text(encoding="utf-8"))
                    # Chunk/index version is a derived hash of chunk settings,
                    # deliberately distinct from the knowledge source version.
                    # Compare the shared upstream knowledge version instead.
                    from ai_core.graph.ocop.integrity import graph_index_mismatch

                    if graph_index_mismatch(graph_manifest, index_manifest):
                        return {"results": [], "status": "graph_index_version_mismatch"}
            except (ValueError, OSError, KeyError):
                return {"results": [], "status": "graph_integrity_failed"}
            seed = slots.get("graph_seed_ids") or context.get("graph_seed_ids") or []
            from ai_core.graph.ocop.builder import SCHEMA_REVISION

            if not graph_manifest.get("checks") or graph_manifest.get("schema_revision") != SCHEMA_REVISION:
                return {"results": [], "status": "graph_requires_grounding_rebuild"}
            graph_path = self.graph_dir / "snapshots" / graph_manifest["graph_version"]
            if not graph_path.is_dir():
                return {"results": [], "status": "graph_integrity_failed"}
            try:
                source_graph = GraphEvidence(
                    self.graph_dir,
                    self.index_dir,
                    allow_partial_debug=context.get("allow_partial_debug") is True,
                )
            except (OSError, ValueError, KeyError):
                return {"results": [], "status": "graph_integrity_failed"}
            checked_nodes = [
                n
                for n in records(graph_path / "nodes.jsonl")
                if n["node_id"] in source_graph.nodes
            ]
            if not seed:
                seed = graph_seeds(
                    checked_nodes,
                    query,
                    slots.get("product_name"),
                    source_filter,
                )
            if context.get("retrieved_evidence_ids"):
                source_ids = list(context["retrieved_evidence_ids"])
                # Link BM25 evidence hits to graph node identities; no LLM alias guesses.
                passage_seeds = list(
                    dict.fromkeys(
                        n["node_id"]
                        for uid in source_ids
                        for n in checked_nodes
                        if n.get("node_type") == "EvidenceUnit" and uid in n.get("evidence_unit_ids", [])
                    )
                )[:6]
                seed = list(dict.fromkeys([*seed, *passage_seeds]))
            # The question names a star level or a score ("nâng lên 5 sao", "chấm được 92 điểm"): the graph hops start at
            # that level too, whatever product the retrieved passages are about.
            seed = list(dict.fromkeys([*seed, *self._star_level_seeds(checked_nodes, query, slots)]))
            semantic = (
                "HAS_ARTICLE",
                "HAS_CLAUSE",
                "HAS_POINT",
                "MINIMUM_FOR",
                "HAS_CRITERION_CANDIDATE",
                "HAS_CRITERION",
                "HAS_SUBCRITERION",
                "HAS_OPTION",
                "HAS_CONDITION",
                "REQUIRES_EVIDENCE",
                "RECOGNIZES",
                "OWNED_BY",
                "BASED_ON",
                "AMENDS",
                "REPLACES",
                "SUSPENDS",
                "HAS_FIELD",
                "RESPONSIBLE_FOR",
                "APPLIES_IN",
                "DEFINES_GROUP",
                "USES_SHEET",
                "HAS_SUBGROUP",
                "HAS_RECORD",
                "DECLARED_BY",
                "SUPPORTED_BY",
                *sorted(LINK_RELATIONS),
            )
            from ai_core.graph.ocop.semantics import SEMANTIC_ENDPOINTS, MODEL_ENDPOINTS

            semantic = tuple(dict.fromkeys([*semantic, *SEMANTIC_ENDPOINTS, *MODEL_ENDPOINTS]))
            requested = []
            folded = normalize(query)
            language = get_language()
            for predicate, phrases in language.cues["relation_predicates"].items():
                if predicate in semantic and language.words("graph_relation:" + predicate, phrases).search(folded):
                    requested.append(predicate)
            if requested and slots.get("document_code"):
                semantic = tuple(requested)
            language = get_language()
            asked_words = set(language.content_words(query, accent_aware=True))

            def relevance(node: dict) -> float:
                """Question words found in a node's label and quotes: a table row is about the products it names."""
                text = " ".join([str(node.get("label") or ""), *(str(c.get("quote") or "") for c in node.get("citations", []))])
                return float(len(asked_words & set(language.content_words(text, accent_aware=True))))

            graph = traverse(
                graph_path,
                list(seed),
                hops=get_settings().agent.graph_hops,
                relations=list(semantic),
                limit=get_settings().agent.graph_node_limit,
                direction="both",
                allow_partial_debug=context.get("allow_partial_debug") is True,
                semantic_first=True,
                relevance=relevance,
                entry_limit=get_settings().agent.graph_entry_nodes,
                pagerank=get_settings().agent.graph_pagerank and not requested,
            )
            # Only checked assertions enter generation. Source text is linked as
            # provenance, never reintroduced wholesale as an accepted relation.
            by_node = {n["node_id"]: n for n in graph["nodes"]}
            facts = []
            # Links across units and documents are the point of a graph hop: they come before in-document structure.
            preferred = {
                "OWNED_BY": 0,
                "RECOGNIZES": 1,
                "DECLARED_BY": 2,
                "HAS_RECORD": 3,
                **{relation: -1 for relation in LINK_RELATIONS},
            }
            entered = {node_id for node_id in by_node if node_id in seed}
            ranked = sorted(
                [e for e in graph["edges"] if e["relation_type"] not in {"SUPPORTED_BY", "IN_VERSION"}],
                key=lambda e: (
                    e["relation_type"] == "SUPPORTED_BY",
                    e["relation_type"] not in LINK_RELATIONS,
                    -relevance(by_node[e["source_entity_id"]]) - relevance(by_node[e["target_entity_id"]]),
                    e["source_entity_id"] not in entered and e["target_entity_id"] not in entered,
                    preferred.get(e["relation_type"], 4),
                    e["edge_id"],
                ),
            )
            hop_first = {}
            for edge in ranked:
                hop = max(graph["node_hops"].get(edge["source_entity_id"], 0),
                          graph["node_hops"].get(edge["target_entity_id"], 0))
                hop_first.setdefault(hop, edge)
            reserved = [hop_first[hop] for hop in sorted(hop_first)]
            reserved_ids = {e["edge_id"] for e in reserved}
            ranked = reserved + [e for e in ranked if e["edge_id"] not in reserved_ids]
            per_relation: dict[str, int] = {}
            shown_units: set[str] = set()
            proof_by_unit: dict[str, dict] = {}
            shown_facts: set[tuple] = set()
            for edge in ranked:
                # One kind of relation must not fill the context with the same row seen from many entities.
                if per_relation.get(edge["relation_type"], 0) >= get_settings().agent.graph_facts_per_relation:
                    continue
                per_relation[edge["relation_type"]] = per_relation.get(edge["relation_type"], 0) + 1
                source, target = by_node[edge["source_entity_id"]], by_node[edge["target_entity_id"]]
                hop = max(graph["node_hops"].get(source["node_id"], 0),
                          graph["node_hops"].get(target["node_id"], 0))
                refs = edge["citations"]
                for ref in refs:
                    previous = proof_by_unit.get(ref["evidence_unit_id"])
                    if previous is not None:
                        previous["graph_hops"] = sorted(set(previous["graph_hops"]) | {hop})
                proofs = [
                    proof
                    for proof in source_graph.evidence(
                        refs,
                        node_ids=[source["node_id"], target["node_id"]],
                        edge_ids=[edge["edge_id"]],
                        check=edge["check"],
                        review_status=edge["review_status"],
                    )
                    if proof["evidence_unit_id"] not in shown_units
                ]
                statement = (edge["relation_type"], source["label"], target["label"])
                if not proofs and statement in shown_facts:
                    continue  # a fact already shown whose proof is already in the context
                shown_facts.add(statement)
                facts.append(
                    {
                        "chunk_id": "graph:" + edge["edge_id"],
                        "evidence_unit_id": edge.get("evidence_unit_id") or edge["evidence_unit_ids"][0],
                        "source_id": edge["source_id"],
                        "text": source["label"] + " [" + edge["relation_type"] + "] " + target["label"],
                        "source_spans": refs,
                        "review_status": "machine_extracted",
                        "validation": edge["validation"],
                        "graph_edge_id": edge["edge_id"],
                        "graph_hop": hop,
                        "check": edge["check"],
                        "graph_node_ids": [source["node_id"], target["node_id"]],
                        "corpus_version": graph_manifest["source_knowledge_version"],
                    }
                )
                for proof in proofs:
                    proof["graph_edge_id"] = edge["edge_id"]
                    proof["graph_relation"] = edge["relation_type"]
                    proof["graph_hop"] = hop
                    proof["graph_hops"] = [hop]
                    proof_by_unit[proof["evidence_unit_id"]] = proof
                    shown_units.add(proof["evidence_unit_id"])
                    facts.append(proof)
                if len(facts) >= get_settings().agent.graph_max_facts:
                    break
            graph["results"] = facts
            graph["status"] = "checked_source_graph"
            return graph
        if name == "resolve_temporal_applicability":
            when = context.get("as_of_date")
            if not when:
                return {"status": "unknown", "reason": "exact_as_of_date_required", "results": []}
            try:
                on = date.fromisoformat(str(when))
            except (TypeError, ValueError):
                return {"status": "unknown", "reason": "invalid_as_of_date", "results": []}
            # A parser-extracted date is never enough to determine legal
            # applicability: only hand-verified, version-matching rules count.
            verified = self.root / "data/processed/ocop/knowledge/verified_temporal_rules.jsonl"
            if not verified.is_file():
                return {"status": "unknown", "reason": "no_verified_temporal_rules", "results": []}
            manifest = self.index_dir / "manifest.json"
            version = (
                json.loads(manifest.read_text(encoding="utf-8")).get("corpus_version")
                if manifest.is_file()
                else None
            )
            if not version:
                return {"status": "unknown", "reason": "active_corpus_version_missing", "results": []}
            source_id = (
                self._resolve_source_id(slots.get("document_code")) if slots.get("document_code") else None
            )
            found = []
            with verified.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    rule = json.loads(line)
                    if (
                        rule.get("review_status") != "verified"
                        or not rule.get("evidence_unit_id")
                        or rule.get("corpus_version") != version
                    ):
                        continue
                    if source_id and rule.get("source_id") != source_id:
                        continue
                    if not source_id and slots.get("document_code"):
                        continue
                    event_year = slots.get("assessment_year")
                    try:
                        event_year = int(event_year) if event_year is not None else None
                    except (TypeError, ValueError):
                        event_year = None
                    verdict = resolve_event_applicability(
                        rule,
                        as_of_date=on,
                        event_year=event_year,
                        region=slots.get("region"),
                        corpus_version=version,
                    )
                    backing = exact_lookup(
                        self.index_dir, identity=rule["evidence_unit_id"], limit=1, include_candidates=False
                    )
                    # 'verified' without its matching corpus source is not a
                    # trustworthy, citable legal conclusion.
                    if not backing or not any(
                        row.get("source_id") == rule.get("source_id")
                        and (row.get("source_spans") or row.get("spans"))
                        for row in backing
                    ):
                        verdict = {
                            "status": "unknown",
                            "reason": "verified_rule_missing_matching_source_evidence",
                        }
                    found.append(
                        {
                            "rule_id": rule.get("rule_id"),
                            "source_id": rule.get("source_id"),
                            "evidence_unit_id": rule["evidence_unit_id"],
                            "verdict": verdict,
                            "review_status": "verified",
                            "corpus_version": version,
                            "source_spans": backing[0].get("source_spans") or backing[0].get("spans")
                            if backing
                            else [],
                            "text": backing[0].get("text") if backing else "",
                        }
                    )
            # Approval of the record is distinct from a resolved applicability
            # verdict. One unknown rule makes the scoped legal answer unresolved.
            verdicts = [r["verdict"].get("status") for r in found]
            resolved = bool(found) and all(v in ("applicable", "not_applicable") for v in verdicts)
            return {
                "status": "checked_verified_rules" if resolved else "unknown",
                "applicability_status": (
                    "applicable" if "applicable" in verdicts else "not_applicable" if resolved else "unknown"
                ),
                "reason": None
                if resolved
                else ("unresolved_applicability_verdict" if found else "no_applicable_verified_rules"),
                "results": found,
            }
        if name == "open_source_span":
            identity = slots.get("evidence_unit_id")
            if not identity:
                return {"results": [], "status": "no_results"}
            try:
                graph = GraphEvidence(
                    self.graph_dir,
                    self.index_dir,
                    allow_partial_debug=context.get("allow_partial_debug") is True,
                )
            except (OSError, ValueError, KeyError):
                return self._graph_failure()
            node = graph.units.get(identity)
            rows = graph.node_rows([node]) if node else []
            return {"results": rows, "status": "ok" if rows else "no_results"}
        raise ValueError("Unknown or unauthorized OCOP tool: " + name)
