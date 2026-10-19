"""Deterministic-first, multi-signal OCOP business intent router.

An intent is a business question, not a retrieval technology. A route may need
several *allowlisted* tools. The shared small LLM is consulted only when no
strong deterministic policy matches; its output cannot supply tools or auth.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
import re
import unicodedata
from ai_core.orchestration.ocop.contracts import Intent, Route
from ai_core.orchestration.ocop.capabilities import (
    Capability, TOOL_REGISTRY, CAPABILITY_TO_TOOLS, PRIVATE_TOOLS, MAX_TOOL_CALLS,
)
from ai_core.orchestration.ocop.retrieval_strategy import choose_retrieval_path
from ai_core.orchestration.ocop.semantic import (
    detect_capabilities, normalize, temporal_question, private_dossier_action,
    private_scoring_action, public_scoring_method, has_any)

DOC_ID = re.compile(r"(?:quyết định|nghị định|nghị quyết|qđ|nđ|nq)\s*(?:số\s*)?([0-9]{1,4}(?:[/.-][0-9]{2,4})?(?:[/.-][a-zA-ZĐđ-]+)?)",re.I)
ARTICLE = re.compile(r"\bđiều\s*(\d{1,3})\b",re.I)
FORM = re.compile(r"\bmẫu\s*(?:số\s*)?0?([1-9]\d?)\b",re.I)
YEARS = re.compile(r"\b20\d{2}\b")
DATE_ISO = re.compile(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b")
DATE_VI = re.compile(r"\b(0?[1-9]|[12]\d|3[01])[/.-](0?[1-9]|1[0-2])[/.-](20\d{2})\b")
PRODUCT = re.compile(r"(?:sản phẩm|có sản phẩm|với sản phẩm)\s+([\wÀ-ỹ][\wÀ-ỹ\s,-]{1,70}?)(?=\s+(?:thì|thuộc|là|theo|ở|được|có|cần|nên|trong|đạt|của|liên hệ)\b|[?.!,]|$)", re.I)
PRODUCTS = ("rau củ quả tươi", "rau củ quả", "hạt sen", "mật ong", "cà phê", "nước mắm", "chè", "trà", "sầu riêng", "gạo", "cam", "bưởi", "tổ yến")
REGIONS = ("Quảng Nam", "Huế", "Hải Phòng", "Hà Tĩnh", "Đà Nẵng", "Hồ Chí Minh", "Hà Nội", "Bình Định", "Gia Lai", "Cần Thơ", "Lâm Đồng", "Đồng Nai", "Nghệ An", "Khánh Hòa", "Quảng Ninh", "Thanh Hóa", "An Giang", "Đồng Tháp", "Bắc Ninh", "Ninh Bình", "Phú Thọ", "Quảng Trị", "Quảng Ngãi", "Tây Ninh", "Cao Bằng", "Sơn La", "Lạng Sơn", "Lào Cai", "Điện Biên", "Lai Châu", "Tuyên Quang", "Thái Nguyên", "Hưng Yên")
TOOLS = frozenset(TOOL_REGISTRY)
# Calibration on the temporary 893-chunk native-text corpus: 13 OCOP-relevant
# prompts included 8 keyword-gate false rejects; 7 of those scored >=0.60.
# Six out-of-scope probes scored at most 0.50, with none reaching this cutoff.
# Re-measure when the corpus/chunker or the scope probe set materially changes.
MIN_INDEXED_CONTENT_BIGRAM_COVERAGE = 0.60
ROUTES = {
 Intent.OCOP_OVERVIEW:("hybrid",["search_regulations"]),
 Intent.EXACT_LOOKUP:("exact",["lookup_legal_unit"]),
 Intent.PRODUCT_CLASSIFICATION:("structured",["lookup_product_subgroup"]),
 Intent.CRITERIA_LOOKUP:("structured",["lookup_criterion"]),
 Intent.PROCEDURE_FORM:("structured",["lookup_form"]),
 Intent.TEMPORAL_COMPARE:("graph_hybrid",["resolve_temporal_applicability","search_regulations"]),
 Intent.RECOGNITION_LOOKUP:("structured",["lookup_recognition"]),
 Intent.SECTOR_COMPLIANCE:("hybrid",["search_regulations"]),
 Intent.DOSSIER_REVIEW:("agentic",["review_dossier"]),
 Intent.SCORE_ESTIMATE:("agentic",["estimate_score"]),
 Intent.MULTIHOP_REASONING:("graph_hybrid",["search_regulations","search_graph"]),
 Intent.FOLLOWUP:("hybrid",["search_regulations"]),
 Intent.CLARIFY:("clarify",[]),
 Intent.OUT_OF_SCOPE:("clarify",[]),
}
MULTIHOP = ("liên quan đến", "mối quan hệ", "căn cứ vào những", "đối chiếu", "liên hệ với", "dựa trên những", "liên hệ giữa", "yêu cầu minh chứng", "minh chứng nào", "đòi hỏi giấy tờ")
TEMPORAL = ("so sánh", "chuyển tiếp", "trước và sau", "thay đổi theo năm", "khác nhau", "hiệu lực", "năm nào áp dụng")
COMPLIANCE = ("an toàn thực phẩm", "giấy attt", "giấy chứng nhận cơ sở", "nhãn hàng hóa", "miễn giấy", "vệ sinh thực phẩm", "đủ điều kiện attt", "miễn chứng nhận", "attp", "an toàn vệ sinh thực phẩm")
CLASSIFICATION = ("thuộc nhóm", "thuộc phân nhóm", "thuộc loại", "nhóm nào", "nhóm gì", "phân nhóm", "phân loại sản phẩm")
RECOGNITION = ("công nhận", "đã đạt ocop", "được chứng nhận ocop", "sản phẩm đạt sao")
PROCEDURE = ("mẫu", "biểu mẫu", "điền", "đăng ký", "thủ tục", "hồ sơ lần đầu", "hồ sơ ocop", "hồ sơ gồm", "cần nộp hồ sơ")
CRITERIA = ("tiêu chí", "thang điểm", "mức điểm", "điểm tối đa", "điểm chấm")


def _norm(text: str) -> str:
    return normalize(text)


def _contains(text: str, terms: tuple[str,...]) -> bool:
    return has_any(text,terms)


def extract_slots(query: str) -> dict:
    """Extract only explicit slots; never assume a date, group, or document."""
    slots:dict = {}
    ascii_query=_norm(query)
    # Accent-free user input is legitimate, without changing the original legal ID.
    for pattern,key,ascii_pattern in ((DOC_ID,"document_code",r"(?:quyet dinh|nghi dinh|nghi quyet|qd|nd|nq)\s*(?:so\s*)?([0-9]{1,4}(?:[/.-][0-9]{2,4})?(?:[/.-][a-zA-Z-]+)?)"),
        (ARTICLE,"article_id",r"\bdieu\s*(\d{1,3})\b"),
        (FORM,"form_id",r"\bmau\s*(?:so\s*)?0?([1-9]\d?)\b")):
        match=pattern.search(query)
        if not match:match=re.search(ascii_pattern,ascii_query,re.I)
        if match:slots[key]=match.group(1)
    form_ids=list(dict.fromkeys(m.group(1).lstrip("0") for m in FORM.finditer(query)))
    if not form_ids:
        form_ids=list(dict.fromkeys(m.group(1).lstrip("0") for m in re.finditer(
            r"\bmau\s*(?:so\s*)?0?([1-9]\d?)\b",ascii_query)))
    # Forms can share one "mẫu" prefix: "mẫu 02 và 03", "mẫu 02, 03, 04".
    # Restrict to an immediately coordinated numeric list to avoid capturing dates/scores.
    for match in re.finditer(r"\bmau\s*(?:so\s*)?0?([1-9]\d?)\b((?:\s*(?:,|va|&|/)\s*0?[1-9]\d?\b){1,6})", ascii_query):
        numbers=[match.group(1)]+re.findall(r"(?:,|va|&|/)\s*0?([1-9]\d?)\b",match.group(2))
        form_ids.extend(str(int(n)) for n in numbers)
    form_ids=list(dict.fromkeys(form_ids))
    if len(form_ids)>1:slots["form_ids"]=form_ids
    if form_ids:slots["form_id"]=form_ids[0]
    star=re.search(r"(?<!\d)([3-5])\s*sao\b", ascii_query)
    if star:slots["star_rating"]=int(star.group(1))
    last_date = None
    for match in DATE_ISO.finditer(query):
        try:last_date=(match.start(),date(*map(int,match.groups())).isoformat())
        except ValueError:pass
    for match in DATE_VI.finditer(query):
        try:
            day,month,year=map(int,match.groups())
            candidate=(match.start(),date(year,month,day).isoformat())
            if last_date is None or candidate[0]>last_date[0]:last_date=candidate
        except ValueError:pass
    if last_date: slots["as_of_date"]=last_date[1]
    years=list(dict.fromkeys(YEARS.findall(query)))
    if years:slots["years"]=years
    lower=_norm(query)
    for name in sorted(REGIONS,key=len,reverse=True):
        if re.search(r"(?<!\w)"+re.escape(_norm(name))+r"(?!\w)",lower):
            slots["region"]=name;break
    matched=PRODUCT.search(query)
    if matched:
        raw=matched.group(1).strip()
        # Trim the same number of words in the source spelling to preserve accents.
        folded=_norm(raw)
        head=re.split(r"\s+(?:ocop|lien he|lien quan|theo quy|dang ky|tren dia ban|tai|o)\b",
                      folded,maxsplit=1,flags=re.I)[0].strip()
        candidate=" ".join(raw.split()[:len(head.split())])
        generic=("nao", "gi", "nay", "do", "kia", "ocop", "cua toi", "cong nhan", "dat sao", "duoc cong nhan", "duoc chung nhan", "duoc danh gia")
        if candidate and not re.match(r"^(?:20\d{2}|\d+|năm\b)",candidate,re.I) and _norm(candidate) not in generic and not _norm(candidate).startswith(("duoc ", "nao ", "gi ", "cong nhan ", "da ", "dat ", "nam ", "nay ", "do ", "ocop ", "tai ", "o ", "voi ", "tren ", "cac ", "nhung ", "can ", "phai ", "co the ")):
            canonical=next((x for x in sorted(PRODUCTS,key=len,reverse=True) if _norm(candidate).startswith(_norm(x))),candidate)
            if len(canonical.split())<=9:slots["product_name"]=canonical
    if "product_name" not in slots:
        for item in sorted(PRODUCTS,key=len,reverse=True):
            for token in re.finditer(r"(?<!\w)"+re.escape(_norm(item))+r"(?!\w)",lower):
                # The imperative "tra cứu" is not a tea product called "trà".
                if _norm(item)=="tra" and re.match(r"\s+cuu\b",lower[token.end():]):
                    continue
                slots["product_name"]=item
                break
            if "product_name" in slots:break
    criterion=re.search(r"\btieu chi\s+(?:so\s+)?([A-Z]?\d+(?:\.\d+){0,3})(?!\d)",lower,re.I)
    if criterion and not re.fullmatch(r"20\d{2}",criterion.group(1)):
        slots["criterion_id"]=criterion.group(1)
    # Explicit event years can coexist with an issuance year inside a QD code.
    # Avoid using the latter as a recognition or assessment event year.
    event=re.search(r"\b(?:cong nhan|duoc cong nhan|san pham (?:ocop )?dat sao)\b.{0,90}?\bnam\s+(20\d{2})\b", lower)
    assessment=re.search(r"\b(?:danh gia|cham diem|xet hang)\b.{0,90}?\bnam\s+(20\d{2})\b", lower)
    if event:slots['recognition_year']=int(event.group(1))
    if assessment:slots['assessment_year']=int(assessment.group(1))
    # Role-qualified years are different from the issuance year embedded in a QD ID.
    if len(years)==1 and not slots.get("document_code"):
        if _contains(lower,("nam danh gia", "ky danh gia", "cham diem nam")):
            slots["assessment_year"]=int(years[0])
        if _contains(lower,("cong nhan", "san pham ocop", "san pham dat sao")):
            slots["recognition_year"]=int(years[0])
    return slots


# Conversation state is an input, not a server-authorized tool or source claim.
# Only ordinary question-extracted scope is carried across a follow-up; graph
# node IDs, evidence identities, authentication and verified flags never are.
FOLLOWUP_SCOPE_KEYS=frozenset({
    'document_code','article_id','form_id','form_ids','star_rating','as_of_date',
    'years','region','product_name','product_group','criterion_id',
    'recognition_year','assessment_year',
})


def _merge_followup(prior:dict,updates:dict)->dict:
    raw=prior.get('slots') or {}
    if not isinstance(raw,dict):raw={}
    slots={key:value for key,value in raw.items() if key in FOLLOWUP_SCOPE_KEYS and (
        isinstance(value,str) and len(value)<=128 or
        type(value) is int and 0<=value<=2100 or
        key in ('years','form_ids') and isinstance(value,list) and len(value)<=8 and
        all(isinstance(x,str) and len(x)<=12 for x in value))}
    # Overwrite only explicitly mentioned dimensions; never concatenate years.
    slots.update(updates)
    if "years" in updates:
        if "as_of_date" not in updates:slots.pop("as_of_date",None)
        for key in ("assessment_year","recognition_year"):
            if key not in updates:slots.pop(key,None)
    return slots


def route_query(query:str,*,session:dict|None=None,llm_route:Callable[[str],dict]|None=None,
                indexed_content_bigram_coverage:Callable[[str],float|None]|None=None)->Route:
    q=query.strip()
    if not q:return Route(intent=Intent.CLARIFY,strategy="clarify",needs_clarification=True,
                          missing_slots=["question"],reason_codes=["empty_query"])
    lower=_norm(q);prior=session or {}
    updates=extract_slots(q)
    followup=bool(re.match(r"^(the|vay|con|neu vay|voi nam do|20\d{2}\b|doi sang|chuyen sang|nam 20\d{2})\b",lower)) and bool(prior.get("last_query"))
    slots=_merge_followup(prior,updates) if followup else updates
    # A historical follow-up can contradict a pinned decision/version. Asking
    # whether the user wants that *document* or the *rules in that year* is
    # safer than silently applying a 2026 criteria sheet to a 2025 case.
    old_code=(prior.get('slots') or {}).get('document_code') if followup else None
    old_doc_year=YEARS.findall(str(old_code or ''))
    changed_year=updates.get('years',[])
    if old_doc_year and changed_year and changed_year[-1]!=old_doc_year[-1] and not updates.get('document_code'):
        return Route(intent=Intent.CLARIFY,strategy='clarify',slots=slots,
                     needs_clarification=True,missing_slots=['document_version_or_event_year'],
                     reason_codes=['historical_year_conflicts_with_pinned_document'])
    is_compare=temporal_question(lower,slots)
    has_multihop=_contains(lower,MULTIHOP)
    # Asking *which criteria make a product eligible* is a criteria question,
    # not a lookup in an already-approved product recognition list.
    normative_star_question = bool(slots.get('star_rating')) and _contains(lower, (
        'dieu kien', 'yeu cau', 'can dap ung', 'de duoc', 'de dat', 'tieu chi',
        'can nhung gi', 'quy dinh the nao',
    )) and not _contains(lower, ('danh sach', 'liet ke', 'da duoc cong nhan',
                                  'san pham nao duoc cong nhan', 'bao nhieu san pham'))
    is_recognition=_contains(lower,RECOGNITION+("danh sach san pham ocop", "san pham ocop 3 sao",
        "san pham ocop 4 sao", "san pham ocop 5 sao", "liet ke san pham ocop"))
    is_criteria=_contains(lower,CRITERIA) or normative_star_question or bool(slots.get('star_rating') and
        _contains(lower,('dieu kien','yeu cau','can dat','de dat','can dap ung')))
    is_form=_contains(lower,PROCEDURE)
    is_compliance=_contains(lower,COMPLIANCE)
    ocop_domain=_contains(lower,("ocop", "tieu chi", "phieu danh gia", "thang diem",
        "ho so", "thu tuc", "cong nhan", "chung nhan", "attt", "an toan thuc pham",
        "quy dinh", "nghi dinh", "quyet dinh", "qd", "bieu mau", "phan nhom",
        "minh chung", "truy xuat", "nhan hang hoa", "luat", "nong san", "nhom nao"))
    # A conversation-local continuation may omit the domain words.
    out_of_scope=not ocop_domain and not followup and not any(_norm(p) in lower for p in PRODUCTS)
    if updates.get("form_id") or updates.get("document_code") or (updates.get('star_rating') and
            _contains(lower,('san pham','ocop','dieu kien'))) or _contains(lower,("diem", "mau", "dang ky", "nop ho so", "so sanh nam")):
        out_of_scope=False
    explicit_out_of_scope=_contains(lower,("ket qua bong da", "gia bitcoin", "xem tarot", "du bao thoi tiet", "viet ma doc"))
    if explicit_out_of_scope:
        out_of_scope=True
    reopened_by_indexed_coverage=False
    # The index is consulted only after the deterministic keyword gate would
    # reject the query. Explicitly off-topic requests still remain blocked.
    if out_of_scope and not explicit_out_of_scope and indexed_content_bigram_coverage is not None:
        try:
            coverage=indexed_content_bigram_coverage(q)
        except (OSError,RuntimeError,ValueError,TypeError,KeyError):
            coverage=None
        if isinstance(coverage,(int,float)) and not isinstance(coverage,bool) and \
                MIN_INDEXED_CONTENT_BIGRAM_COVERAGE<=coverage<=1.0:
            out_of_scope=False
            reopened_by_indexed_coverage=True
    scores={}
    if out_of_scope:scores[Intent.OUT_OF_SCOPE]=100
    requests_scoring=private_scoring_action(lower)
    asks_method=public_scoring_method(lower)
    if requests_scoring and not asks_method:
        scores[Intent.SCORE_ESTIMATE]=90
    if asks_method:
        scores[Intent.CRITERIA_LOOKUP]=70
    if private_dossier_action(lower):
        scores[Intent.DOSSIER_REVIEW]=85
    if has_multihop and (is_criteria or is_form or is_compliance or is_recognition):
        scores[Intent.MULTIHOP_REASONING]=80
    if is_compare:scores[Intent.TEMPORAL_COMPARE]=75
    if updates.get("article_id") and updates.get("document_code"):scores[Intent.EXACT_LOOKUP]=70
    if _contains(lower,CLASSIFICATION):scores[Intent.PRODUCT_CLASSIFICATION]=65
    if is_compliance:scores[Intent.SECTOR_COMPLIANCE]=60
    if is_recognition and not normative_star_question:
        scores[Intent.RECOGNITION_LOOKUP]=55
    if normative_star_question:
        scores[Intent.CRITERIA_LOOKUP]=max(85, scores.get(Intent.CRITERIA_LOOKUP,0))
    if is_form:scores[Intent.PROCEDURE_FORM]=50
    if is_criteria:scores.setdefault(Intent.CRITERIA_LOOKUP,45)
    if _contains(lower,("ho so toi can chuan bi", "ho so cua toi can chuan bi")):
        scores[Intent.PROCEDURE_FORM]=72
    if has_multihop:scores.setdefault(Intent.MULTIHOP_REASONING,35)
    # A generic listing of OCOP-star products is recognition, not an overview.
    if is_recognition and _contains(lower,("danh sach", "liet ke", "cac san pham")):
        scores[Intent.RECOGNITION_LOOKUP]=80
    if followup and not scores:
        parent=prior.get("intent")
        try:parent=Intent(parent)
        except (ValueError,TypeError):parent=Intent.OCOP_OVERVIEW
        if parent==Intent.FOLLOWUP:parent=Intent.OCOP_OVERVIEW
        scores[parent]=30
    if scores:
        intent=max(scores,key=scores.get)
    else:
        intent=Intent.OCOP_OVERVIEW
        if llm_route is not None:
            try:
                result=llm_route(q)
                candidate=Intent(result["intent"])
                if candidate not in (Intent.DOSSIER_REVIEW,Intent.SCORE_ESTIMATE) or prior.get("dossier_id"):
                    intent=candidate
                safe={"product_name","product_group","region","as_of_date","document_code","form_id","criterion_id"}
                slots.update({k:v for k,v in (result.get("slots") or {}).items()
                              if k in safe and isinstance(v,(str,int)) and len(str(v))<=128})
            except (ValueError,KeyError,TypeError,AttributeError):pass
    # Keep FOLLOWUP as a public label for compatibility, while inheriting the
    # actual previous business toolset; never downgrade every follow-up to search.
    effective=intent
    if followup and not out_of_scope and Intent.SCORE_ESTIMATE not in scores and Intent.DOSSIER_REVIEW not in scores:
        if not scores or max(scores.values())<75:
            intent=Intent.FOLLOWUP
            parent=prior.get("intent")
            try:effective=Intent(parent)
            except (ValueError,TypeError):effective=Intent.OCOP_OVERVIEW
            if effective in (Intent.FOLLOWUP,Intent.CLARIFY):effective=Intent.OCOP_OVERVIEW
    strategy,base=ROUTES[effective]
    required=list(base)
    # Add supplementary tools only when they contribute *distinct* evidence.
    if is_recognition and effective==Intent.TEMPORAL_COMPARE:required.insert(0,"lookup_recognition")
    if effective==Intent.MULTIHOP_REASONING:
        if is_criteria:required.insert(0,"lookup_criterion")
        if is_form:required.insert(0,"lookup_form")
        if is_recognition:required.insert(0,"lookup_recognition")
    if effective==Intent.TEMPORAL_COMPARE and is_criteria:required.insert(0,"lookup_criterion")
    if effective==Intent.EXACT_LOOKUP and is_criteria:required.append("lookup_criterion")
    if effective==Intent.PROCEDURE_FORM and is_criteria:required.append("lookup_criterion")
    # When a question asks about procedural requirements instead of an
    # identified FormTemplate, search the procedure text. Returning the first
    # arbitrary form candidate would be misleading.
    if effective==Intent.PROCEDURE_FORM and not slots.get('form_id') and 'mẫu' not in lower:
        required=['search_regulations']
    # A generic question about criteria must not return the first unrelated
    # criterion sheet simply because OCR produced many candidates.
    if effective==Intent.CRITERIA_LOOKUP and not any(slots.get(k) for k in
        ('criterion_id','product_name','product_group','document_code')):
        required=['search_regulations']
    # Business capabilities are multi-label; primary intent is retained for old
    # API callers and regression comparability, but no longer dictates the only
    # tool. A user may ask for taxonomy + criteria + evidence + temporal scope.
    capabilities,cap_reasons=detect_capabilities(q,slots)
    if normative_star_question:
        capabilities=[c for c in capabilities if c != Capability.RECOGNITION]
        if Capability.CRITERIA not in capabilities:
            capabilities.insert(0,Capability.CRITERIA)
        cap_reasons.append('normative_star_requires_criteria_not_recognition_records')
    if followup and len(capabilities)==1 and capabilities[0]==Capability.OVERVIEW:
        previous=prior.get('capabilities') or []
        capabilities=[Capability(x) for x in previous if x in Capability._value2member_map_] or capabilities
        if capabilities==[Capability.OVERVIEW]:
            inherit={Intent.CRITERIA_LOOKUP:Capability.CRITERIA,
                Intent.PRODUCT_CLASSIFICATION:Capability.CLASSIFY_PRODUCT,
                Intent.PROCEDURE_FORM:Capability.PROCEDURE_FORM,
                Intent.RECOGNITION_LOOKUP:Capability.RECOGNITION,
                Intent.SECTOR_COMPLIANCE:Capability.SECTOR_COMPLIANCE}
            try:old_intent=Intent(prior.get('intent'))
            except (TypeError,ValueError):old_intent=Intent.OCOP_OVERVIEW
            capabilities=[inherit[old_intent]] if old_intent in inherit else capabilities
    if intent==Intent.OUT_OF_SCOPE:
        capabilities=[]
    elif capabilities==[Capability.OVERVIEW] and intent!=Intent.OCOP_OVERVIEW:
        fallback_map={Intent.PRODUCT_CLASSIFICATION:Capability.CLASSIFY_PRODUCT,
            Intent.CRITERIA_LOOKUP:Capability.CRITERIA,Intent.RECOGNITION_LOOKUP:Capability.RECOGNITION,
            Intent.PROCEDURE_FORM:Capability.PROCEDURE_FORM,Intent.SECTOR_COMPLIANCE:Capability.SECTOR_COMPLIANCE,
            Intent.TEMPORAL_COMPARE:Capability.TEMPORAL,Intent.MULTIHOP_REASONING:Capability.RELATION_REASONING}
        if intent in fallback_map:capabilities=[fallback_map[intent]]
    explicit=set(capabilities)
    # Explicit private capabilities never get public tools in the same plan.
    private_caps={Capability.REVIEW_DOSSIER,Capability.ESTIMATE_SCORE}
    if explicit & private_caps:
        capabilities=[c for c in capabilities if c in private_caps]
    else:
        composed=[]
        for capability in capabilities:
            composed.extend(CAPABILITY_TO_TOOLS[capability])
        # Historical exact lookups are primary; broad text only supplements
        # business-specific capabilities, never overrides a document ID.
        if len(capabilities)>1 and 'search_regulations' not in composed and (
            Capability.TEMPORAL in capabilities or Capability.SECTOR_COMPLIANCE in capabilities
            or Capability.RELATION_REASONING in capabilities):
            composed.append('search_regulations')
        # For a generic question without form number, *do not* return an
        # arbitrary form template; search grounded policy text instead.
        if Capability.PROCEDURE_FORM in explicit and not slots.get('form_id'):
            composed=[x for x in composed if x!='lookup_form']+['search_regulations']
        # Same rule for generic scoring-method questions.
        if Capability.CRITERIA in explicit and not any(slots.get(k) for k in (
            'criterion_id','product_name','product_group','document_code')) and not (
            explicit & {Capability.CLASSIFY_PRODUCT,Capability.EVIDENCE_REQUIREMENTS}):
            composed=[x for x in composed if x!='lookup_criterion']+['search_regulations']
        # An exact query with no extra business dimension needs only lookup.
        if explicit=={Capability.EXACT_ARTICLE}:composed=['lookup_legal_unit']
        required=list(dict.fromkeys(x for x in composed if x in TOOLS))
        if Capability.TEMPORAL in explicit and Capability.RECOGNITION in explicit:
            required=['lookup_recognition']+[x for x in required if x!='lookup_recognition']
    if explicit & private_caps:
        required=list(dict.fromkeys(x for c in capabilities for x in CAPABILITY_TO_TOOLS[c]))
    if (slots.get('years') and not slots.get('document_code') and
        effective in (Intent.PROCEDURE_FORM,Intent.CRITERIA_LOOKUP,Intent.SECTOR_COMPLIANCE,Intent.OCOP_OVERVIEW)
        and 'search_regulations' in required and not (explicit & private_caps)):
        required=list(dict.fromkeys(['resolve_temporal_applicability',*required]))
    missing=[]
    if effective in (Intent.DOSSIER_REVIEW,Intent.SCORE_ESTIMATE):
        for key in ("tenant_id","dossier_id"):
            if not prior.get(key):missing.append(key)
    if missing:
        return Route(intent=Intent.CLARIFY,strategy="clarify",slots=slots,needs_clarification=True,
                     missing_slots=missing,reason_codes=["required_dossier_context_missing"])
    if len(required)>MAX_TOOL_CALLS:
        return Route(intent=Intent.CLARIFY,strategy="clarify",slots=slots,needs_clarification=True,
                     missing_slots=["split_question"],
                     reason_codes=["tool_budget_exceeded"]+cap_reasons)
    secondary=[x for x in scores if x!=effective and scores[x]>=40]
    return Route(intent=intent,strategy=strategy,retrieval_path=choose_retrieval_path(required),
                 slots=slots,required_tools=required,
                  secondary_intents=secondary[:3],capabilities=[x.value for x in capabilities],
                  reason_codes=(["followup_slot_override" if followup else "deterministic_multi_signal"]+
                                cap_reasons+(["indexed_content_bigram_scope_recovery"] if reopened_by_indexed_coverage else [])),
                 confidence=None)
