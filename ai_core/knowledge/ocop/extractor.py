"""High-fidelity *candidate* OCOP business extraction from existing PageArtifacts.

Uses structural hints for recognition rows and form fields. Legal/scoring logic
remains inert until a separately audited, approved rule is supplied. Nothing in
this module performs entity resolution across legal jurisdictions or OCR guesses.
"""

from __future__ import annotations

import re
from ocop_contracts.ratings import asterisk_quantifier, level_class
from collections import Counter

from ai_core.domain.ocop_citations import quote_bbox
from ai_core.processing.ocop.business_candidates import unbold
from ocop_contracts.ids import stable_id
from .contracts import (
    BusinessEntity,
    BusinessRelation,
    BusinessRule,
    EvidenceRef,
    EntityType,
    validate_business_graph,
    ambiguous_numbered_heading,
)


KEYWORDS = (
    ("exemption", re.compile(r"(?:được\s+miễn|không\s+phải|không\s+thuộc\s+diện)", re.I)),
    ("prohibition", re.compile(r"(?:nghiêm\s+cấm|không\s+được)", re.I)),
    ("obligation", re.compile(r"(?:\bphải\b|bắt\s+buộc|(?:có|chịu)\s+trách\s+nhiệm)", re.I)),
    (
        "temporal",
        re.compile(
            r"(?:có\s+hiệu\s+lực|có\s+giá\s+trị\s+(?:trong\s+)?(?:thời\s+hạn\s+)?\d+|kể\s+từ\s+ngày|chuyển\s+tiếp|tạm\s+ngưng\s+hiệu\s+lực)",
            re.I,
        ),
    ),
)


def _ref(candidate: dict, evidence_index: dict[str, dict], text: str | None = None) -> EvidenceRef:
    src, uid = candidate["source_id"], candidate["evidence_unit_id"]
    unit = evidence_index.get(uid)
    if unit is None or unit["source_id"] != src:
        raise ValueError("missing or mismatched source evidence")
    spans = unit.get("spans") or []
    page = int(candidate.get("pdf_page") or spans[0]["pdf_page"])
    if page not in [int(s["pdf_page"]) for s in spans]:
        raise ValueError("candidate page not present in source spans")
    original = unit.get("text") or ""
    if not original.strip():
        raise ValueError("empty evidence body")
    quote = (text or candidate.get("row_text") or candidate.get("label_candidate") or "").strip()
    row_no = candidate.get("row")
    bbox = None
    if row_no is not None:
        cells = [
            c for c in unit.get("structured", {}).get("cells", []) if int(c.get("row", -1)) == int(row_no)
        ]
        if not cells:
            raise ValueError("table row missing from evidence source")
        # Reconstruct from ORIGINAL cells, including a metadata caller that
        # supplies a row number without a proposed quote.
        reconstructed = " | ".join(
            str(c.get("text") or "").strip()
            for c in sorted(cells, key=lambda x: int(x.get("col", 0)))
            if str(c.get("text") or "").strip()
        )
        if quote:
            if quote != reconstructed and quote not in original and not reconstructed.startswith(quote):
                raise ValueError("candidate row text not traceable to table cells")
        quote = reconstructed[:1200]
        rectangles = [c.get("bbox") for c in cells if c.get("bbox")]
        if rectangles:
            bbox = (
                min(v[0] for v in rectangles),
                min(v[1] for v in rectangles),
                max(v[2] for v in rectangles),
                max(v[3] for v in rectangles),
            )
    else:
        if quote and quote not in original:
            raise ValueError("quote not literally present in evidence source")
        if not quote:
            quote = original[: min(200, len(original))].strip()
        bbox = quote_bbox(unit, page, quote)
    span = next(s for s in spans if int(s["pdf_page"]) == page)
    return EvidenceRef(
        source_id=src,
        evidence_unit_id=uid,
        pdf_page=page,
        source_sha256=span.get("source_sha256"),
        table_id=candidate.get("table_id") or span.get("table_id"),
        row=row_no,
        bbox=bbox or span.get("bbox"),
        quote=quote,
    )


def _cell_ref_at(candidate: dict, evidence_index: dict[str, dict], row: int, col: int) -> EvidenceRef | None:
    """Return one literal source cell, including an explicit merged origin cell.

    Do not replace an OCR cell with alternative crop text or a guessed value.
    A missing cell yields None and remains unresolved.
    """
    unit = evidence_index.get(candidate.get("evidence_unit_id"))
    if not unit or unit.get("source_id") != candidate.get("source_id"):
        return None
    row = int(row)
    cells = [
        c
        for c in unit.get("structured", {}).get("cells", [])
        if int(c.get("row", -2)) == row and int(c.get("col", -2)) == col
    ]
    if len(cells) != 1 or not str(cells[0].get("text") or "").strip():
        return None
    cell = cells[0]
    raw = str(cell["text"]).strip()
    span = unit.get("spans") or []
    if not span:
        return None
    page = int(candidate.get("pdf_page") or span[0]["pdf_page"])
    if page not in [int(s["pdf_page"]) for s in span]:
        return None
    table_id = candidate.get("table_id") or unit.get("structured", {}).get("table_id")
    return EvidenceRef(
        source_id=candidate["source_id"],
        evidence_unit_id=candidate["evidence_unit_id"],
        pdf_page=page,
        source_sha256=next(s for s in span if int(s["pdf_page"]) == page).get("source_sha256"),
        table_id=table_id,
        row=row,
        cell_id=f"{table_id}:r{row}:c{col}" if table_id else None,
        # A cell with no box (a reviewed table row typed without geometry) is cited by its page span, as a row is.
        bbox=cell.get("bbox") or next(s for s in span if int(s["pdf_page"]) == page).get("bbox"),
        quote=raw,
    )


def _cell_ref(candidate: dict, evidence_index: dict[str, dict], col: int) -> EvidenceRef | None:
    """Return a literal source cell on the candidate's own row."""
    return _cell_ref_at(candidate, evidence_index, int(candidate.get("row", -1)), col)


def _evidence_key(evidence: EvidenceRef) -> tuple:
    return (
        evidence.source_id,
        evidence.evidence_unit_id,
        evidence.pdf_page,
        evidence.row,
        evidence.cell_id,
        evidence.quote,
    )


def _short_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:350]


def _rule_sentences(text: str) -> list[str]:
    """Join physical line wraps until sentence punctuation or a new list item."""
    result = []
    buffer = []

    def flush():
        if buffer:
            statement = "\n".join(buffer).strip()
            if statement:
                result.append(statement)
            buffer.clear()

    item_start = re.compile(r"^(?:\d{1,2}[.)]|[a-zđ][.)]|\(\d+\))\s+", re.I)
    heading = re.compile(r"^(?:Điều\s+\d+|Chương\s+|Mục\s+|Phụ\s+lục\b|Mẫu\s+)", re.I)
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if heading.match(line):
            flush()
            # "Điều 3. Bộ trưởng, ..." starts the article's first sentence on the heading line; keep it with
            # the lines that finish that sentence instead of cutting the subject off.
            if re.search(r"[.!?;:]\s*$", line) or len(line) < 40:
                result.append(line)
            else:
                buffer.append(line)
            continue
        if buffer and item_start.match(line):
            flush()
        buffer.append(line)
        if re.search(r"[.!?;:]\s*$", line):
            flush()
    flush()
    return result


def extract_semantics(
    units: list[dict],
    source_kinds: dict[str, str],
    candidate_sets: dict[str, list[dict]],
    *,
    source_registry: dict[str, dict] | None = None,
) -> dict[str, list[dict]]:
    """Create typed graph facts from only source-observable information.

    The outputs are read-only candidates. No candidate is automatically verified,
    and a missing score/owner/date is represented as unknown, NEVER imputed.
    """
    evidence_by_id = {u["unit_id"]: u for u in units}
    entities: dict[str, BusinessEntity] = {}
    relations: dict[str, BusinessRelation] = {}
    rules: dict[str, BusinessRule] = {}
    omitted = Counter()

    def add(
        kind: EntityType,
        label: str,
        record: dict,
        evidence: EvidenceRef,
        *,
        key: str,
        attributes: dict | None = None,
    ) -> str:
        src = record["source_id"]
        entity_id = stable_id("biz_entity", src, [kind.value, key], revision="business")
        new = BusinessEntity(
            entity_id=entity_id,
            kind=kind,
            label=label,
            source_id=src,
            evidence=[evidence],
            attributes=attributes or {},
        )
        if entity_id in entities:
            existing = entities[entity_id]
            if existing.kind != kind or existing.source_id != src:
                raise ValueError("entity identity collision")
            if _evidence_key(evidence) not in {_evidence_key(e) for e in existing.evidence}:
                existing.evidence.append(evidence)
        else:
            entities[entity_id] = new
        return entity_id

    def link(
        relation: str,
        src: str,
        dst: str,
        ev: EvidenceRef,
        *,
        extra_evidence: list[EvidenceRef] | None = None,
        attributes: dict | None = None,
    ) -> None:
        rid = stable_id(
            "biz_relation",
            ev.source_id,
            [relation, src, dst, ev.evidence_unit_id, ev.row],
            revision="business",
        )
        relations[rid] = BusinessRelation(
            relation_id=rid,
            relation_type=relation,
            source_entity_id=src,
            target_entity_id=dst,
            evidence=[ev, *(extra_evidence or [])],
            attributes=attributes or {},
        )

    # Table row candidates MUST NOT be promoted to Criterion/ScoreOption.
    # A row may be a heading, subtotal, merged cell or score option.
    for row in candidate_sets.get("criterion_candidates", []):
        try:
            ev = _ref(row, evidence_by_id)
            add(
                EntityType.CRITERION_ROW,
                _short_label(row.get("label_candidate", "")) or "Dòng bảng",
                row,
                ev,
                key=row["candidate_id"],
                attributes={
                    "score_candidate": row.get("score_candidate"),
                    "table_id": row.get("table_id"),
                    "row": row.get("row"),
                },
            )
        except (KeyError, ValueError):
            omitted["criterion_row_missing_evidence"] += 1

    # Structure-aware scoring candidate graph, not a point-awarding engine.
    # Only a NUMBERED row may introduce a parent criterion. The following rows
    # are linked as options only within the SAME original table. All statuses
    # remain candidate and score values are observational, not approved rules.
    from collections import defaultdict

    score_tables = defaultdict(list)
    for row in candidate_sets.get("criterion_candidates", []):
        score_tables[(row.get("source_id"), row.get("evidence_unit_id"), row.get("table_id"))].append(row)
    heading_re = re.compile(r"^\s*(?:\d+(?:\.\d+){1,3}[.,)]?\s*(?=[^\W\d_])|[A-C][.]\s*\S)", re.I)
    # A single-number heading such as "2. PHÁT TRIỂN SẢN PHẨM" is a criterion group, not a score option.
    # Requiring capitals keeps an ordinary numbered option ("1. Có ...") out.
    section_re = re.compile(r"^\s*(\d{1,2})[.,)]\s*\S")
    numbering_re = re.compile(r"^\s*(\d+(?:\.\d+){0,3})")
    note_re = re.compile(
        r"^\s*(?:gh[iị]\s+ch[úủ]|chú\s+ý|lưu\s+ý|yêu\s+cầu|ch[iỉ]\s+áp\s+dụng|tổng\s+cộng|các\s+tiêu\s+chí|thang\s+điểm)\b|^\s*\(",
        re.I,
    )
    part_re = re.compile(r"^\s*Phần\s+([ABC])\b", re.I)
    markers_re = re.compile(r"(?<!\*)\*" + asterisk_quantifier() + r"(?!\*)")

    def part_title(text: str) -> str:
        return re.sub(r"\s+", " ", re.split(r"[(|]", text, maxsplit=1)[0]).strip(" :.").casefold()

    # Part titles as the same document writes them in full ("Phần B: KHẢ NĂNG TIẾP THỊ (25 điểm)"). An unnumbered row
    # ending in one of them is that part's heading even when OCR lost the "Phần B:" lead ("Ph KHẢ NĂNG TIẾP THỊ").
    part_titles = defaultdict(dict)
    for row in candidate_sets.get("criterion_candidates", []):
        label = str(row.get("label_candidate") or "").split("|")[0]
        if match := part_re.match(label):
            part_titles[row["source_id"]][part_title(label[match.end():])] = match[1].upper()

    def part_letter(label: str, source_id: str) -> str | None:
        if match := part_re.match(label):
            return match[1].upper()
        letters = [c for c in re.split(r"[(|]", label, maxsplit=1)[0] if c.isalpha()]
        if numbering_re.match(label) or sum(c.isupper() for c in letters) < 0.8 * max(len(letters), 1):
            return None
        title = part_title(label)
        # Only a short OCR remnant ("Ph") may precede the title.
        return next(
            (v for t, v in part_titles[source_id].items() if t and title.endswith(t) and len(title) - len(t) <= 4),
            None,
        )

    def is_section(label: str) -> bool:
        # A heading cell may include a lower-case explanatory paragraph, or an OCR-mixed tail ("11. TÍNH ĐỘC ĐÁO Chất
        # lượng (...)"): the first two words after the number in capitals name the heading, an option ("1. Có ...") never
        # starts that way.
        match = section_re.match(label)
        if not match:
            return False
        title = re.split(r"[\n(]", label, maxsplit=1)[0]
        letters = [c for c in title if c.isalpha()]
        if len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.8 * len(letters):
            return True
        words = re.findall(r"[^\W\d_]+", label[match.end(1):])[:2]
        return len(words) == 2 and all(w.isupper() for w in words) and sum(map(len, words)) >= 4

    def heads_its_options(ordered: list[dict], at: int) -> bool:
        # "14. Chất lượng phục vụ | 4" in sentence case: a numbered row whose score is the top score of the unnumbered
        # rows under it (up to the next numbered row) is the criterion over those options. A numbered option
        # ("1. Có ...") is followed by its numbered siblings, not by options of its own.
        # A group closing its page table ("7. Kiến trúc …" with one option, the rest on the next page) only needs
        # its options so far to stay under its score.
        own = ordered[at].get("score_candidate")
        below, closed = [], False
        for row in ordered[at + 1 :]:
            text = unbold(str(row.get("label_candidate") or ""))
            if numbering_re.match(text) or note_re.match(text):
                closed = True
                break
            below.append(row.get("score_candidate"))
        scores = [s for s in below if isinstance(s, int) and not isinstance(s, bool)]
        if not isinstance(own, int) or not scores:
            return False
        return max(scores) == own or (not closed and max(scores) < own)

    for _, rows in sorted(score_tables.items(), key=lambda item: str(item[0])):
        parent_id = None
        group_number = None
        criteria_by_number: dict[str, str] = {}
        ordered = sorted(rows, key=lambda rec: int(rec.get("row", 0)))
        for at, row in enumerate(ordered):
            raw = str(row.get("label_candidate") or "")
            parts = [unbold(part).strip() for part in raw.split("|")]
            label = parts[0] if parts else ""
            try:
                ev = _ref(row, evidence_by_id)
            except (KeyError, ValueError):
                omitted["score_row_missing_evidence"] += 1
                continue
            score = row.get("score_candidate")
            if score is not None and (not isinstance(score, int) or not 0 <= score <= 100):
                score = None
            if ambiguous_numbered_heading(label):
                parent_id = None
                omitted["criterion_numbering_prefix_unresolved"] += 1
                continue
            part = part_letter(label, row["source_id"])
            letter = (
                re.match(r"^\s*([a-zđ])\)\s+\S", label, re.I)
                if source_kinds.get(row["source_id"]) == "ocop_historical"
                else None
            )
            section = is_section(label) or (bool(section_re.match(label)) and heads_its_options(ordered, at))
            if part or heading_re.match(label) or section or letter:
                number = numbering_re.match(label).group(1) if numbering_re.match(label) else None
                if part:
                    group_number = None
                elif number and "." not in number:
                    group_number = number
                criterion_id = add(
                    EntityType.CRITERION,
                    _short_label(label),
                    row,
                    ev,
                    key=f"numbered:{row['candidate_id']}",
                    attributes={
                        "max_points_candidate": score,
                        "level": 0 if part else 3 if letter else number.count(".") + 1 if number else None,
                        "part_letter": part,
                        "criterion_letter": letter[1].casefold() if letter else None,
                        "table_id": row.get("table_id"),
                        "row": row.get("row"),
                    },
                )
                # The parent is found by numbering ("2.1" under "2"), only within this same table.
                parent_number = (
                    group_number if letter else number.rsplit(".", 1)[0] if number and "." in number else None
                )
                if parent_number and parent_number in criteria_by_number:
                    link("HAS_SUBCRITERION", criteria_by_number[parent_number], criterion_id, ev)
                if number:
                    criteria_by_number[number] = criterion_id
                parent_id = criterion_id
            elif (
                len(label.strip()) >= 2
                and any(c.isalpha() for c in label)
                and not note_re.match(label)
                and (score is not None or parent_id)
            ):
                # A row under a criterion whose score is not in its cell text stays an option with an unknown
                # score; a crop re-read of the score cell is kept apart as an unverified alternative.
                crop = row.get("crop_score_candidate") or {}
                option_id = add(
                    EntityType.SCORE_OPTION,
                    _short_label(label),
                    row,
                    ev,
                    key=f"score-option:{row['candidate_id']}",
                    attributes={
                        "points_candidate": score,
                        "parent_identified": bool(parent_id),
                        "crop_points_candidate": crop.get("text") if score is None else None,
                        "table_id": row.get("table_id"),
                        "row": row.get("row"),
                    },
                )
                score_cols = [
                    int(c.get("col", -1))
                    for c in evidence_by_id[row["evidence_unit_id"]].get("structured", {}).get("cells", [])
                    if int(c.get("row", -1)) == int(row.get("row", -2))
                ]
                score_ev = _cell_ref(row, evidence_by_id, max(score_cols)) if score_cols else None
                if score_ev and score_ev.quote.replace(" ", "") == str(score):
                    entities[option_id].evidence.append(score_ev)
                if parent_id:
                    link(
                        "HAS_OPTION",
                        parent_id,
                        option_id,
                        ev,
                        extra_evidence=[score_ev]
                        if score_ev and score_ev.quote.replace(" ", "") == str(score)
                        else None,
                    )
                rule_id = stable_id(
                    "biz_scoring_rule", row["source_id"], [row["candidate_id"]], revision="business_row"
                )
                rules[rule_id] = BusinessRule(
                    rule_id=rule_id,
                    source_id=row["source_id"],
                    kind="scoring",
                    statement=raw,
                    evidence=[ev, score_ev]
                    if score_ev and score_ev.quote.replace(" ", "") == str(score)
                    else [ev],
                )
            # OCR keeps star markers out of the text; the image detector records them on the row's cells.
            marks = {mark: "ocr_text" for mark in markers_re.findall(label)}
            for cell in evidence_by_id[row["evidence_unit_id"]].get("structured", {}).get("cells", []):
                if int(cell.get("row", -1)) != int(row.get("row", -2)):
                    continue
                for marker in cell.get("image_marker_candidates") or []:
                    if markers_re.fullmatch(str(marker.get("text") or "")):
                        marks.setdefault(marker["text"], "image_marker_candidate")
            for mark, observed_in in sorted(marks.items()):
                if not parent_id:
                    continue
                condition_id = add(
                    EntityType.CONDITION,
                    f"Dấu {mark} (cần xác minh)",
                    row,
                    ev,
                    key=f"mandatory-marker:{row['candidate_id']}:{mark}",
                    attributes={
                        "marker_observed": mark,
                        "marker_observed_in": observed_in,
                        "interpretation_verified": False,
                    },
                )
                link("HAS_CONDITION", parent_id, condition_id, ev)

    for row in candidate_sets.get("form_candidates", []):
        try:
            ev = _ref(row, evidence_by_id)
            form_id = add(
                EntityType.FORM_TEMPLATE,
                _short_label(row.get("title", "")) or "Biểu mẫu",
                row,
                ev,
                key=row["candidate_id"],
                attributes={"form_number": row.get("form_number")},
            )
            for i, label in enumerate(row.get("fields_candidate", [])):
                label = _short_label(label)
                if len(label) < 3:
                    continue
                field_ev = _ref(row, evidence_by_id, text=label)
                field_id = add(
                    EntityType.FORM_FIELD,
                    label,
                    row,
                    field_ev,
                    key=f"{row['candidate_id']}:field:{i}",
                    attributes={"required": None, "field_position": i},
                )
                link("HAS_FIELD", form_id, field_id, field_ev)
        except (KeyError, ValueError):
            omitted["form_missing_evidence"] += 1

    # Recognition tables may have true merged cells. Layout comes from the
    # table header, while inherited values require an explicit source rowspan.
    for row in candidate_sets.get("recognition_candidates", []):
        src = row.get("source_id", "")
        cols = row.get("resolved_columns") or {}
        layout = row.get("layout_columns") or {}
        if not {"sequence", "product", "producer"}.issubset(layout):
            omitted["recognition_unknown_layout"] += 1
            continue

        def column_record(role: str) -> dict:
            col = layout.get(role)
            return cols.get(str(col)) or {} if col is not None else {}

        def value(role: str) -> str:
            return " ".join(str(column_record(role).get("text") or "").split())

        def cell_evidence(role: str) -> EvidenceRef | None:
            col = layout.get(role)
            record = column_record(role)
            if col is None or not record.get("text"):
                return None
            origin = record.get("row")
            if origin is None:
                return None
            origin = int(origin)
            current = int(row.get("row", -1))
            if (record.get("inherited") and origin >= current) or (
                not record.get("inherited") and origin != current
            ):
                return None
            ref = _cell_ref_at(row, evidence_by_id, origin, int(col))
            if not ref or " ".join(ref.quote.split()) != " ".join(str(record.get("text") or "").split()):
                return None
            return ref

        sequence = value("sequence")
        if not re.fullmatch(r"\d+", sequence):
            omitted["recognition_header_or_incomplete_row"] += 1
            continue
        product, producer = value("product"), value("producer")
        if len(_short_label(product)) < 3:
            omitted["recognition_missing_owner_or_product"] += 1
            continue
        # A row may print no owner (QĐ525 row 4: the owner cells are blank on the page): the record and its product
        # stand on the cells that are printed, and no owner is guessed from a neighbouring row.
        has_owner = len(_short_label(producer)) >= 3
        owner_cell = column_record("producer")
        inherited = bool(owner_cell.get("inherited")) if has_owner else False
        owner_ref = cell_evidence("producer") if has_owner else None
        product_ref = cell_evidence("product")
        if product_ref is None or (has_owner and owner_ref is None):
            omitted["recognition_missing_cell_evidence"] += 1
            continue
        address = value("address") or None
        representative = value("representative") or None
        address_ref = cell_evidence("address") if address else None
        representative_ref = cell_evidence("representative") if representative else None
        if (address and address_ref is None) or (representative and representative_ref is None):
            omitted["recognition_missing_cell_evidence"] += 1
            continue
        # A merged score/star value is visible, but it is not known to belong
        # to every product row. Keep those candidates only when directly printed
        # on this row; the source cell remains the citation for accepted values.
        score = value("score") or None
        score_ref = cell_evidence("score") if score and not column_record("score").get("inherited") else None
        if score and score_ref is None:
            score = None
        star_text = value("star") or None
        star_ref = cell_evidence("star") if star_text and not column_record("star").get("inherited") else None
        if star_text and star_ref is None:
            star_text = None
        star_match = re.search(r"(?<!\d)(" + level_class() + r")\s*sao\b", star_text or "", re.I)
        star_candidate = int(star_match.group(1)) if star_match else None
        try:
            ev = _ref(row, evidence_by_id)
            decision = add(
                EntityType.RECOGNITION_DECISION, src, row, ev, key=src, attributes={"decision_source_id": src}
            )
            rec = add(
                EntityType.RECOGNITION_RECORD,
                _short_label(row["row_text"]),
                row,
                ev,
                key=row["candidate_id"],
                attributes={
                    "star_rating_candidate": star_candidate,
                    "score_candidate": score,
                    "producer_address_candidate": address,
                    "representative_candidate": representative,
                    "row_number": sequence,
                    "owner_inherited_from_merge": inherited,
                },
            )
            record_refs = [product_ref, owner_ref, address_ref, representative_ref, score_ref, star_ref]
            for ref in record_refs:
                if ref and _evidence_key(ref) not in {_evidence_key(e) for e in entities[rec].evidence}:
                    entities[rec].evidence.append(ref)
            product_id = add(
                EntityType.PRODUCT,
                _short_label(product),
                row,
                product_ref,
                key=f"{row['candidate_id']}:product",
            )
            link("HAS_RECORD", decision, rec, ev)
            link("RECOGNIZES", rec, product_id, ev, extra_evidence=[product_ref])
            if has_owner:
                owner_id = add(
                    EntityType.ORGANIZATION,
                    _short_label(producer),
                    row,
                    owner_ref,
                    key=f"organization:{_short_label(producer).casefold()}:"
                    f"{_short_label(address).casefold() if address else owner_ref.evidence_unit_id + ':' + str(owner_ref.row)}",
                )
                link("DECLARED_BY", rec, owner_id, ev, extra_evidence=[owner_ref])
                link("OWNED_BY", product_id, owner_id, ev, extra_evidence=[product_ref, owner_ref])
        except (KeyError, ValueError):
            omitted["recognition_missing_evidence"] += 1

    # Deontic extraction is ONLY a textual claim candidate. We deliberately do
    # not compile OCR prose into executable IF/THEN or effective-date rules.
    permitted = {
        "food_safety_law",
        "food_safety_decree",
        "food_safety_resolution",
        "labeling_decree",
        "labeling_amendment",
        "cooperative_law",
        "ocop_framework",
        "ocop_historical",
        "ocop_amendment",
        "local_guidance",
    }
    from .procedures import _procedure_sentences

    for u in units:
        if source_kinds.get(u["source_id"]) not in permitted or u["unit_kind"] not in (
            "article",
            "paragraph",
            "section",
        ):
            continue
        for sentence_no, statement in enumerate(_procedure_sentences(u.get("text") or "", _rule_sentences)):
            if len(statement) < 25:
                continue
            if re.fullmatch(r"\s*Điều\s+\d+[.]?\s*Điều\s+khoản\s+chuyển\s+tiếp\s*[.:]?\s*", statement, re.I):
                omitted["transition_heading_not_rule"] += 1
                continue
            for kind, pattern in KEYWORDS:
                if not pattern.search(statement):
                    continue
                # Keep wrapped source text together; these are still claims,
                # never executable or verified rules.
                try:
                    ev = _ref(
                        {
                            "source_id": u["source_id"],
                            "evidence_unit_id": u["unit_id"],
                            "pdf_page": u["spans"][0]["pdf_page"],
                        },
                        evidence_by_id,
                        text=statement,
                    )
                    rid = stable_id(
                        "biz_rule", u["source_id"], [u["unit_id"], sentence_no, kind], revision="business_row"
                    )
                    rules[rid] = BusinessRule(
                        rule_id=rid, source_id=u["source_id"], kind=kind, statement=statement, evidence=[ev]
                    )
                except (KeyError, ValueError):
                    omitted["rule_missing_evidence"] += 1
                break  # one dominant modality per source sentence; ambiguous remains candidate

    from .legal_structure import extract_documents

    # Local article structure needs no registry resolution. Cross-document
    # identities remain disabled unless the caller supplies the real registry.
    legal_registry = (
        source_registry
        if source_registry is not None
        else {sid: {"document_number": None} for sid in source_kinds}
    )
    extract_documents(
        units,
        source_kinds,
        legal_registry,
        evidence_by_id,
        entities,
        relations,
        rules,
        omitted,
        add,
        link,
        _ref,
    )

    from .criterion_sheets import extract_criterion_sheets

    extract_criterion_sheets(
        units, source_kinds, candidate_sets, evidence_by_id, entities, relations, omitted, add, link, _ref
    )
    from .star_requirements import extract_star_requirements

    extract_star_requirements(
        units,
        source_kinds,
        candidate_sets,
        evidence_by_id,
        entities,
        omitted,
        add,
        link,
        _ref,
        _cell_ref_at,
        _rule_sentences,
    )
    from .procedures import extract_procedures

    extract_procedures(
        units,
        source_kinds,
        candidate_sets,
        evidence_by_id,
        entities,
        omitted,
        add,
        link,
        _ref,
        _rule_sentences,
    )

    replaced_by = {}
    for relation in relations.values():
        if relation.relation_type in {"REPLACES", "AMENDS"}:
            old = entities[relation.target_entity_id].source_id
            new = entities[relation.source_entity_id].source_id
            replaced_by.setdefault(old, set()).add(new)
    for entity in entities.values():
        if source_kinds.get(entity.source_id) == "ocop_historical":
            entity.attributes["historical"] = True
            if entity.source_id in replaced_by:
                entity.attributes["superseded_by"] = ",".join(sorted(replaced_by[entity.source_id]))
                entity.attributes["supersession_interpretation_verified"] = False
    typed_entities = sorted(entities.values(), key=lambda x: x.entity_id)
    typed_relations = sorted(relations.values(), key=lambda x: x.relation_id)
    validate_business_graph(typed_entities, typed_relations, source_registry=source_registry)
    return {
        "business_entities": [e.model_dump(mode="json") for e in typed_entities],
        "business_relations": [r.model_dump(mode="json") for r in typed_relations],
        "business_rules": [
            r.model_dump(mode="json") for r in sorted(rules.values(), key=lambda x: x.rule_id)
        ],
        "business_omissions": [{"reason": key, "count": val} for key, val in sorted(omitted.items())],
    }
