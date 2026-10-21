"""Deterministic OCOP evidence checklist and provisional scoring.

No interpretation of OCR score candidates as verified rules; no official star awards.
"""
from __future__ import annotations
from decimal import Decimal


def checklist(requirements:list[dict],submitted:list[dict])->list[dict]:
    # Only caller-authorized dossier evidence is compared with verified rules.
    by_type={str(item.get("evidence_type")):item for item in submitted}
    output=[]
    for r in requirements:
        ident=str(r["requirement_id"]);kind=str(r["evidence_type"])
        if r.get("review_status")!="verified":
            status="needs_human_review"; reason="requirement_unverified"
        elif r.get("applicable") is False:
            status="not_applicable";reason="condition_not_met"
        elif r.get("applicable") is None:
            status="needs_human_review";reason="applicability_unknown"
        elif kind not in by_type:
            status="missing";reason="no_document"
        elif by_type[kind].get("verified") is True:
            status="satisfied";reason="verified_dossier_evidence"
        else:
            status="insufficient_evidence";reason="uploaded_but_unverified"
        output.append({"requirement_id":ident,"evidence_type":kind,"status":status,
                       "reason":reason,"evidence_unit_id":r.get("evidence_unit_id")})
    return output

def estimate_score(criteria:list[dict],answers:dict[str,str])->dict:
    """Calculate exact subtotal only for verified, mutually-exclusive option tables.

    Unresolved criteria contribute a possible interval if their max is verified;
    otherwise the upper bound is unknown. A score is NEVER a star classification.
    """
    minimum=Decimal(0); maximum=Decimal(0); unknown_upper=False; rows=[]
    for c in criteria:
        cid=str(c["criterion_id"]); maxval=c.get("max_points")
        if c.get("review_status")!="verified" or c.get("scoring_mode")!="choose_one":
            unknown_upper=unknown_upper or maxval is None
            if maxval is not None:
                maximum+=Decimal(str(maxval))
            rows.append({"criterion_id":cid,"status":"unknown","reason":"criterion_unverified_or_scoring_mode_unknown"});continue
        options=c.get("score_options") or []
        if not options or any(o.get("review_status")!="verified" for o in options):
            unknown_upper=unknown_upper or maxval is None
            if maxval is not None:maximum+=Decimal(str(maxval))
            rows.append({"criterion_id":cid,"status":"unknown","reason":"options_unverified"});continue
        selected=answers.get(cid)
        matches=[o for o in options if o.get("option_id")==selected]
        if selected and len(matches)==1:
            points=Decimal(str(matches[0]["points"]))
            if points<0 or maxval is not None and points>Decimal(str(maxval)):
                raise ValueError("option score exceeds verified criterion bounds")
            minimum+=points;maximum+=points
            rows.append({"criterion_id":cid,"status":"estimated","points":str(points)})
        else:
            unknown_upper=unknown_upper or maxval is None
            if maxval is not None:maximum+=Decimal(str(maxval))
            rows.append({"criterion_id":cid,"status":"unknown","reason":"no_unique_verified_selection"})
    return {"status":"provisional_not_official","minimum_points":str(minimum),
            "maximum_points":None if unknown_upper else str(maximum),
            "criteria":rows,"official_star_rating":None}
