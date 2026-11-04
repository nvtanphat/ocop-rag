"""Prompt SOURCE excerpts: question-aware windows over the raw passage, never the head of an enriched chunk.

Design notes (see docs/adr/006-context-window-and-parent-chain.md):
* The excerpt comes from ``raw_text`` (the extracted passage). Graph/parent context is a short separate line.
* A window of whole lines/sentences is chosen around the question's content terms; cuts are marked with "…".
* Table rows carry their column labels so roles (organisation / owner / representative) are not confused.
* The text handed to the claim checker is exactly the window the model saw (labels included, markers excluded).
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass

from ai_core.orchestration.ocop.language import fold, get_language
from ai_core.retrieval.ocop.settings import ContextSettings
from ai_core.retrieval.ocop.graph_context import CONTEXT_PREFIX
from ai_core.retrieval.ocop.structure_chunker import estimated_tokens

COLUMN_PREFIX = "Cột: "  # the column-header line shown above a table excerpt

ELLIPSIS = "…"
MIN_EXCERPT_CHARS = 300
_SENTENCE = re.compile(r'(?<=[.;:!?])\s+(?=[\wÀ-ỹ(\[“"-])')


def graph_hops(row):
    values = row.get("graph_hops", [row.get("graph_hop")])
    return {value for value in values if type(value) is int and value >= 0} if isinstance(values, list) else set()


@dataclass(frozen=True)
class Excerpt:
    display: str
    evidence: str
    cut_left: bool
    cut_right: bool
    source_chars: int


def question_terms(question: str) -> list[str]:
    """Distinct content words (folded) of the question, ignoring vocabulary stopwords."""
    # Document codes (qd148, 26/2026/QĐ-TTg) and bare numbers are scope slots handled by the tools, not words to find
    # in a passage: a run of non-space characters holding a digit is an identifier, whole, including its letters.
    identifiers = re.sub(r"\S*\d\S*", " ", question)
    words = [w for w in get_language().content_words(identifiers) if not re.fullmatch(r"[a-z]{0,3}\d+", w)]
    # "phiếu 1", "mẫu 02", "điều 5": a noun directly followed by its number is a reference the slots resolve; the
    # passage that answers it need not repeat the noun (a criterion sheet's text rarely says "phiếu").
    referenced = set(re.findall(r"([a-z]+)\s+\d{1,4}\b", fold(question)))
    # The kind of document a question points at ("Quyết định", "Luật") locates it like its number does; it is not content.
    kinds = {fold(w) for names in get_language().document_types.values() for n in names for w in n.split()}
    return list(dict.fromkeys(w for w in words if w not in referenced and w not in kinds))


def _segments(text: str, limit: int = 420) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if len(line) <= limit:
            parts.append(line)
            continue
        parts.extend(s for s in _SENTENCE.split(line) if s.strip())
    return parts


def _hard_cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def _word_window(text: str, wanted: set[str], max_chars: int) -> tuple[str, bool, bool]:
    """A bounded original-text slice, balancing context on both sides of matched words."""
    words = list(re.finditer(r"\S+", text))
    hits = [set(re.findall(r"[a-z0-9]+", fold(word.group()))) & wanted for word in words]
    counts: Counter = Counter()
    positions: deque = deque()
    right = 0
    best_score = (-1, -1, -1, 0)
    best = None
    for left, word in enumerate(words):
        start = word.start()
        while right < len(words) and words[right].end() - start <= max_chars:
            counts.update(hits[right])
            if hits[right]:
                positions.append(right)
            right += 1
        if right == left:  # A single token cannot fit intact.
            right += 1
            continue
        end = words[right - 1].end()
        balance = min(words[positions[0]].start() - start, end - words[positions[-1]].end()) if positions else 0
        score = (len(counts), balance, end - start, -start)
        if score > best_score:
            best_score, best = score, (start, end)
        for term in hits[left]:
            counts[term] -= 1
            if not counts[term]:
                del counts[term]
        if positions and positions[0] == left:
            positions.popleft()
    if best is None:
        return _hard_cut(text, max_chars), False, True
    start, end = best
    return text[start:end], start > 0, end < len(text)


def select_window(text: str, terms: list[str], max_chars: int) -> tuple[str, bool, bool]:
    """Best contiguous run of whole segments (≤ max_chars) by distinct question-term hits."""
    if len(text) <= max_chars:
        return text.strip(), False, False
    if not terms:
        return _hard_cut(text, max_chars), False, True
    segments = _segments(text)
    if not segments:
        return _hard_cut(text, max_chars), False, True
    wanted = set(terms)
    long = {i: _word_window(segment, wanted, max_chars) for i, segment in enumerate(segments)
            if len(segment) > max_chars}
    rendered = [long[i][0] if i in long else segment for i, segment in enumerate(segments)]
    sets = [set(re.findall(r"[a-z0-9]+", fold(segment))) for segment in rendered]
    sizes = [len(segment) + 1 for segment in rendered]
    best = (-1, 0, 0, 0)  # (score, -length, i, j)
    for i in range(len(segments)):
        covered: set[str] = set()
        total = 0
        for j in range(i, len(segments)):
            if j > i and (i in long or j in long):
                break  # A slice inside a long segment cannot skip text to join a neighbour.
            total += sizes[j]
            if total > max_chars and j > i:
                break
            covered |= sets[j] & wanted
            score = len(covered)
            cand = (score, -total, -i, j)
            if cand > (best[0], best[1], -best[2], best[3]):
                best = (score, -total, i, j)
    _, _, i, j = best
    if i in long:
        window, left, right = long[i]
        return window, i > 0 or left, i < len(segments) - 1 or right
    window = "\n".join(segments[i : j + 1])
    if len(window) > max_chars:  # one segment longer than the budget
        window = _hard_cut(window, max_chars)
        return window, i > 0, True
    return window, i > 0, j < len(segments) - 1


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _labelled_row(row: dict) -> str | None:
    """ "Column: value" pairs for a graph table row whose header cells are known."""
    cells = (row.get("structured") or {}).get("cells") or []
    spans = row.get("source_spans") or row.get("spans") or []
    row_no = next(
        (s.get("row") for s in spans if isinstance(s, dict) and isinstance(s.get("row"), int)), None
    )
    if not cells or row_no is None:
        return None
    header_row = min((c.get("row", 0) for c in cells), default=None)
    if header_row is None or header_row == row_no:
        return None
    names = {c.get("col"): _clean(c.get("text")) for c in cells if c.get("row") == header_row}
    own = [c for c in cells if c.get("row") == row_no]
    taken = {c.get("col") for c in own}
    # A merged (rowspan) cell that starts above this row still covers it: "Tổ chức/cá nhân" is often one cell for
    # several product rows. Geometry decides, nothing is guessed.
    covering = [
        c
        for c in cells
        if isinstance(c.get("row"), int)
        and c["row"] < row_no < c["row"] + int(c.get("rowspan") or 1)
        and c.get("col") not in taken
        and c["row"] != header_row
    ]
    values = sorted(own + covering, key=lambda c: c.get("col", 0))
    pairs = [
        (names.get(c.get("col")) or "Cột " + str(c.get("col"))) + ": " + _clean(c.get("text"))
        for c in values
        if _clean(c.get("text"))
    ]
    return "; ".join(pairs) if pairs else None


def _context_line(row: dict) -> str:
    context = row.get("context") if isinstance(row.get("context"), dict) else {}
    chain = context.get("parent_chain") or []
    return " > ".join(chain) if chain else ""


def render_row(
    row: dict, terms: list[str], cfg: ContextSettings, *, table_backed: bool, max_chars: int | None = None
) -> Excerpt:
    raw = str(row.get("raw_text") or "").strip()
    if not raw:
        raw = str(
            row.get("text")
            or row.get("evidence_text")
            or row.get("row_text")
            or row.get("label_candidate")
            or row.get("title")
            or ""
        ).strip()
    # OCR field candidates are shown as candidates but never become support for a claim.
    extra = ""
    if row.get("fields_candidate") and isinstance(row["fields_candidate"], list):
        extra = "Các trường OCR dự kiến: " + "; ".join(str(x) for x in row["fields_candidate"][:12])
    limit = max_chars or (cfg.table_excerpt_max_chars if table_backed else cfg.excerpt_max_chars)
    labelled = _labelled_row(row) if table_backed else None
    if labelled:
        window, left, right = select_window(labelled, terms, limit)
        header = ""
    else:
        window, left, right = select_window(raw, terms, limit)
        headers = row.get("table_headers") or []
        header = (COLUMN_PREFIX + " | ".join(str(h) for h in headers[:1])) if (table_backed and headers) else ""
    parent = _context_line(row)
    lines = [x for x in ((CONTEXT_PREFIX + parent) if parent else "", header) if x]
    display = "\n".join(
        [
            *lines,
            (ELLIPSIS + " " if left else "") + window + (" " + ELLIPSIS if right else ""),
            *([extra] if extra else []),
        ]
    )
    evidence = "\n".join([x for x in (header, window) if x])
    return Excerpt(display=display, evidence=evidence, cut_left=left, cut_right=right, source_chars=len(raw))


def fit_budget(
    rows: list[dict],
    flags: list[bool],
    terms: list[str],
    cfg: ContextSettings,
    token_budget: int,
    label_tokens: list[int],
) -> list[Excerpt | None]:
    """Render every row, shrinking the longest windows (never below MIN_EXCERPT_CHARS) until the SOURCE fits.

    Only the row whose cap changed is re-rendered; rows are dropped from the tail (lowest rank) last.
    """
    caps = [cfg.table_excerpt_max_chars if f else cfg.excerpt_max_chars for f in flags]
    keep = list(range(len(rows)))
    rendered = {i: render_row(rows[i], terms, cfg, table_backed=flags[i], max_chars=caps[i]) for i in keep}
    cost = {i: estimated_tokens(rendered[i].display) + label_tokens[i] for i in keep}
    while keep and sum(cost[i] for i in keep) > token_budget:
        longest = max(keep, key=lambda i: cost[i])
        if caps[longest] > MIN_EXCERPT_CHARS * 2:
            caps[longest] = max(MIN_EXCERPT_CHARS, int(caps[longest] * 0.7))
        elif len(keep) > 1:
            counts = Counter(hop for i in keep for hop in graph_hops(rows[i]))
            removable = [i for i in keep if all(counts[hop] > 1 for hop in graph_hops(rows[i]))]
            if removable:
                keep.remove(removable[-1])
            elif any(caps[i] > 120 for i in keep):
                longest = max(keep, key=lambda i: caps[i])
                caps[longest] = max(120, int(caps[longest] * 0.7))
                rendered[longest] = render_row(rows[longest], terms, cfg, table_backed=flags[longest],
                                            max_chars=caps[longest])
                cost[longest] = estimated_tokens(rendered[longest].display) + label_tokens[longest]
            else:
                # A chain that cannot fit even one minimum block per hop is
                # withheld together, rather than presenting a broken chain.
                keep = [i for i in keep if not graph_hops(rows[i])]
            continue
        elif caps[longest] > 120:
            caps[longest] = max(120, int(caps[longest] * 0.7))
        else:
            keep.pop()  # Even the minimum excerpt plus its header cannot fit.
            continue
        rendered[longest] = render_row(
            rows[longest], terms, cfg, table_backed=flags[longest], max_chars=caps[longest]
        )
        cost[longest] = estimated_tokens(rendered[longest].display) + label_tokens[longest]
    return [rendered[i] if i in keep else None for i in range(len(rows))]


def term_coverage(terms: list[str], texts: list[str]) -> float:
    if not terms:
        return 1.0
    seen = set(re.findall(r"[a-z0-9]+", fold(" ".join(texts))))
    return round(sum(t in seen for t in terms) / len(terms), 3)
