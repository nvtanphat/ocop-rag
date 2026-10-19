"""evidence extraction temporal *candidates* with evidence, never asserted legal validity.

The effective period of a statute cannot be safely inferred from a date mention
in its body. This module records spans for a later human/rule-review stage.
In particular, this is NOT a current-law resolver or a repeal classifier.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from ai_core.domain.ocop_ids import stable_id

_DMY = re.compile(r"(?<!\d)(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>20\d{2})(?!\d)")
_VI_DATE = re.compile(
    r"ngày\s+(?P<d>\d{1,2})\s+tháng\s+(?P<m>\d{1,2})\s+năm\s+(?P<y>20\d{2})",
    flags=re.IGNORECASE,
)
_REFS = re.compile(
    r"\b\d{1,4}/20\d{2}/(?:QĐ-TTg|QĐ-UBND|NĐ-CP|NQ-CP|QH\d+|TT-[A-ZĐ]+)\b",
    flags=re.IGNORECASE,
)
_TRIGGERS = (
    ("effective_date_candidate", ("có hiệu lực", "hiệu lực thi hành")),
    ("expiry_date_candidate", ("hết hiệu lực", "chấm dứt hiệu lực")),
    ("transition_candidate", ("chuyển tiếp", "tiếp tục áp dụng", "sau 60 ngày")),
    ("suspension_candidate", ("tạm ngưng", "tạm đình chỉ")),
    ("amendment_candidate", ("sửa đổi", "bổ sung", "thay thế", "bãi bỏ")),
    ("recognition_date_candidate", ("công nhận",)),
)
_INDEPENDENT_LINE = re.compile(
    r"^\s*(?:\d{1,2}[.)]\s|[a-zđ][.)]\s|\(\d+\)\s|"
    r"căn cứ\b|điều\s+\d|chương\s+|mục\s+|phụ\s+lục\b|"
    r"luật\b|nghị định\b|quyết định\b|ủy ban\b|uỷ ban\b|chủ tịch\b)",
    re.IGNORECASE,
)


def _independent_line(value: str) -> bool:
    line=value.strip()
    if not line:
        return True
    letters=[char for char in line if char.isalpha()]
    return bool(_INDEPENDENT_LINE.match(line) or
                (len(letters)>=4 and line.isupper()))


def _local_context(text: str, start: int, end: int) -> str:
    """Keep a date/transition with its clause, not nearby headings or clauses."""
    lines=text.splitlines(keepends=True)
    if not lines:
        return text[max(0,start-180):min(len(text),end+180)].strip()
    bounds=[];offset=0
    for line in lines:
        bounds.append((offset,offset+len(line),line.rstrip("\r\n")))
        offset+=len(line)
    first=next((i for i,(a,b,_) in enumerate(bounds) if a<=start<b),len(bounds)-1)
    last=next((i for i,(a,b,_) in enumerate(bounds) if a<end<=b),first)
    left=first
    while left>0:
        current=bounds[left][2]
        previous=bounds[left-1][2].rstrip()
        if _independent_line(current) or re.search(r"[.!?;:]\s*$",previous):
            break
        left-=1
    right=last
    while right+1<len(bounds):
        current=bounds[right][2].rstrip()
        following=bounds[right+1][2]
        if re.search(r"[.!?;:]\s*$",current) or _independent_line(following):
            break
        right+=1
    context_start=bounds[left][0]
    context_end=bounds[right][1]
    local=text[context_start:context_end]
    local_start=start-context_start
    local_end=end-context_start
    left_delimiters=[m.end() for m in re.finditer(r"[.!?;]",local[:local_start])]
    right_delimiter=re.search(r"[.!?;]",local[local_end:])
    cut_left=max(left_delimiters,default=0)
    cut_right=local_end+right_delimiter.start() if right_delimiter else len(local)
    return local[cut_left:cut_right].strip()


def _iso(match: re.Match[str]) -> str | None:
    try:
        return date(int(match.group("y")), int(match.group("m")), int(match.group("d"))).isoformat()
    except ValueError:
        return None


def temporal_candidates(units: Iterable[dict]) -> list[dict]:
    """Locate possible temporal relations; every item points to an EvidenceUnit.

    Context windows keep the actual phrase but do not conclude that its date
    is the source document's effective date. A single clause may have several
    dates with different legal functions, so these remain independent.
    """
    found: list[dict] = []
    for unit in units:
        if unit.get("unit_kind") in ("page", "page_fallback"):
            continue
        text = unit.get("text") or ""
        lowered = text.casefold()
        dates = sorted(
            [(m.start(), m.end(), _iso(m)) for pat in (_DMY, _VI_DATE) for m in pat.finditer(text)],
            key=lambda x: (x[0], x[1]),
        )
        if not dates and not any(w in lowered for _, triggers in _TRIGGERS for w in triggers):
            continue
        for start, end, iso_date in dates:
            if iso_date is None:
                continue
            evidence = _local_context(text,start,end)
            low_context = evidence.casefold()
            classes = [name for name, triggers in _TRIGGERS if any(t in low_context for t in triggers)]
            # An isolated date is still a searchable date mention, not a legal effect.
            if not classes:
                classes = ["date_mention"]
            for kind in classes:
                found.append({
                    "candidate_id": stable_id(
                        "temporal_candidate", unit["source_id"],
                        [unit["unit_id"], start, end, kind],
                    ),
                    "source_id": unit["source_id"],
                    "evidence_unit_id": unit["unit_id"],
                    "pdf_page": (unit.get("spans") or [{}])[0].get("pdf_page"),
                    "candidate_type": kind,
                    "date_candidate": iso_date,
                    "referenced_documents": list(dict.fromkeys(_REFS.findall(evidence))),
                    "evidence_text": evidence,
                    "source_spans": unit.get("spans", []),
                    "review_status": "needs_review",
                    "is_authoritative": False,
                })
        # Explicit transitions without a date remain separate evidence even if
        # another date appears elsewhere in this EvidenceUnit.
        for match in re.finditer(r"chuyển\s+tiếp",text,re.IGNORECASE):
            evidence=_local_context(text,match.start(),match.end())
            if _DMY.search(evidence) or _VI_DATE.search(evidence):
                continue
            found.append({
                "candidate_id": stable_id(
                    "temporal_candidate", unit["source_id"], [unit["unit_id"], match.start(), "transition_no_date"]
                ),
                "source_id": unit["source_id"],
                "evidence_unit_id": unit["unit_id"],
                "pdf_page": (unit.get("spans") or [{}])[0].get("pdf_page"),
                "candidate_type": "transition_candidate",
                "date_candidate": None,
                "referenced_documents": list(dict.fromkeys(_REFS.findall(evidence))),
                "evidence_text": evidence,
                "source_spans": unit.get("spans", []),
                "review_status": "needs_review",
                "is_authoritative": False,
            })
    return found
