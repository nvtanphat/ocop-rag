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
    ("recognition_date_candidate", ("công nhận", "đánh giá", "phân hạng")),
)


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
            left, right = max(0, start - 180), min(len(text), end + 180)
            evidence = text[left:right]
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
                    "candidate_type": kind,
                    "date_candidate": iso_date,
                    "referenced_documents": list(dict.fromkeys(_REFS.findall(evidence))),
                    "evidence_text": evidence,
                    "source_spans": unit.get("spans", []),
                    "review_status": "needs_review",
                    "is_authoritative": False,
                })
        # Explicit transition without parsed day/month/year remains evidence.
        if "chuyển tiếp" in lowered and not dates:
            found.append({
                "candidate_id": stable_id(
                    "temporal_candidate", unit["source_id"], [unit["unit_id"], "transition_no_date"]
                ),
                "source_id": unit["source_id"],
                "evidence_unit_id": unit["unit_id"],
                "candidate_type": "transition_candidate",
                "date_candidate": None,
                "referenced_documents": list(dict.fromkeys(_REFS.findall(text))),
                "evidence_text": text[:900],
                "source_spans": unit.get("spans", []),
                "review_status": "needs_review",
                "is_authoritative": False,
            })
    return found
