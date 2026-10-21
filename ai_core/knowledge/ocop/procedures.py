"""Candidate procedures, explicit authorities, documents and local scope."""
from __future__ import annotations
import json
import re
from ai_core.processing.ocop.temporal_candidates import _DMY,_iso
from .contracts import EntityType
from .authorities import find_authorities, resolve

ACTION=re.compile(r'\s*(?:sẽ\s+)?(?:chủ\s+trì|tổ[\s.]+chức|tiếp\s+nhận|đánh\s+giá|kiểm\s+tra|giao|thành\s+lập|quyết\s+định|ban\s+hành|công\s+nhận|thu\s+hồi|chuẩn\s+bị|rà\s+soát|tăng\s+cường|chỉ\s+đạo|thông\s+tin|tổng\s+hợp|phối\s+hợp|hướng\s+dẫn|thông\s+báo|xem\s+xét|đề\s+nghị|gửi|có\s+trách\s+nhiệm|có\s+văn\s+bản|chịu\s+trách\s+nhiệm)',re.I)
TRIGGER=re.compile(r'hồ\s+sơ|công\s+bố|đăng\s+ký|nộp|tiếp\s+nhận|công\s+nhận|đánh\s+giá|thu\s+hồi|rà\s+soát|thương\s+mại\s+điện\s+tử|giám\s+sát|liên\s+hệ|hướng\s+dẫn',re.I)
DURATION=re.compile(r'(?<!\d)(\d{1,3})\s*(ngày\s+làm\s+việc|ngày(?!\s+l[àảa]m))\b',re.I)
CALENDAR=re.compile(r'(?:trước\s+ngày|chậm\s+nhất(?:\s+ngày)?)\s*(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{4})?|\d{1,2}\s+tháng\s+\d{1,2}(?:\s+năm\s+\d{4})?)',re.I)
DOCUMENT=re.compile(
    r'\b(?:phiếu\s+(?:đăng\s+ký|(?:kết\s+quả\s+)?kiểm\s+nghiệm)'
    r'|báo\s+cáo(?:\s+(?:tự\s+đánh\s+giá|(?:kết\s+quả\s+)?đánh\s+giá))?'
    r'|bản\s+tự\s+công\s+bố(?:\s+sản\s+phẩm)?'
    r'|giấy\s+chứng\s+nhận(?:\s+(?:đủ\s+điều\s+kiện\s+an\s+toàn\s+thực\s+phẩm|đăng\s+ký\s+nhãn\s+hiệu|chất\s+lượng))?'
    r'|giấy\s+tờ\s+pháp\s+lý'
    r'|văn\s+bản(?:\s+(?:ghi\s+nhận\s+quyền\s+sử\s+dụng|đề\s+nghị))?'
    r'|hồ\s+sơ\s+(?:minh\s+chứng|môi\s+trường)|tài\s+liệu\s+minh\s+chứng'
    r'|đơn\s+đăng\s+ký\s+nhãn\s+hiệu|bằng\s+(?:độc\s+quyền|sáng\s+chế)'
    r'|hợp\s+đồng(?:\s+(?:liên\s+kết|xuất\s+khẩu))?|mẫu\s+số\s*\d{1,2})\b',re.I)
INPUT_CUE=re.compile(r'hồ\s+sơ|đăng\s+ký|tự\s+đánh\s+giá|chuẩn\s+bị|nộp|kèm|bổ\s+sung|cập\s+nhật|minh\s+chứng|yêu\s+cầu|phải\s+có',re.I)
FORM=re.compile(r'Mẫu\s*(?:số\s*)?(0?\d{1,2})(?!\d)(?:\s*,?\s*Phụ\s+lục\s+([IVX]+)(?![A-Za-z0-9]))?',re.I)


def _norm(text):
    return ' '.join(text.split()).casefold()


def _recipient(text,match):
    # OCR often misreads the tone of "đề" ("để", "đê"); the cue still marks a recipient.
    return bool(re.search(r'(?:đ[ềểếêe]\s+nghị|đ[ềểếêe]\s+xuất|gửi|đến|cho|về|trình(?:\s+Chủ\s+tịch)?|tới|của|lên|từ|họp|tổ\s+chức)\s*$',text[:match.start()],re.I))


def _subjects(text):
    mentions=list(find_authorities(text));subjects=[]
    recipients=set()
    for i,mention in enumerate(mentions):
        # A shared preposition governs the whole coordinated list ("của Bộ A,
        # Bộ B và Bộ C"), including the document authors in legal citations.
        coordinated_recipient=(i-1 in recipients and bool(re.fullmatch(
            r'\s*(?:,\s*(?:và\s*)?|và\s+)\s*',
            text[mentions[i-1].end():mention.start()], re.I)))
        if _recipient(text,mention) or coordinated_recipient:
            recipients.add(i)
            continue
        last=mention
        for following in mentions[i+1:]:
            if not re.fullmatch(r'\s*(?:,\s*(?:và\s*)?|và\s+)\s*',text[last.end():following.start()]):
                break
            last=following
        tail=text[last.end():].lstrip(' ,:')
        if ACTION.match(tail) or text[last.end():].strip()==':':
            subjects.append(mention)
    return subjects


def _procedure_sentences(text, sentences):
    """Respect observed actor/heading boundaries even when OCR loses punctuation.

    Slices remain literal substrings: no punctuation or OCR text is inserted.
    Wrapped lines without a fresh actor or heading stay in their paragraph.
    """
    chunks=[];start=0;offset=0
    actor_starts={m.start() for m in _subjects(text)}
    for raw in text.splitlines(keepends=True):
        line=raw.strip()
        line_start=offset+len(raw)-len(raw.lstrip())
        intro=re.match(r'Trong\s+đó,\s*',line,re.I)
        fresh_actor=(line_start in actor_starts or
                     bool(intro and line_start+intro.end() in actor_starts))
        heading=((len(line)>=8 and line.isupper()) or
                 bool(re.match(r'(?:Thành\s+phần\b|Nơi\s+tiếp\s+nhận\s*:|[-%]\s+)',line,re.I)))
        if offset>start and (fresh_actor or heading):
            chunks.append(text[start:offset].strip());start=offset
        offset+=len(raw)
    chunks.append(text[start:].strip())
    return [part for chunk in chunks for statement in sentences(chunk)
            for part in _split_mid_line_actors(statement)]


# A clause ends at punctuation or at a closing legal self-reference ("... Quyết định này"),
# which OCR often leaves without its period.
_CLAUSE_END=re.compile(r'(?:[.;,]|\b(?:Quyết\s+định|Nghị\s+định|Thông\s+tư|Nghị\s+quyết|Điều|khoản)\s+này)\s*$',re.I)
_LIST_MARKER=re.compile(r'(?:\d{1,2}(?:\.\d{1,2})*|[a-zđ]|\(\d+\))[.)]?',re.I)


def _split_mid_line_actors(statement):
    """Start a new step where a fresh acting subject follows a clause end; slices stay literal."""
    cuts=[m.start() for m in _subjects(statement)
          if m.start()>0 and _CLAUSE_END.search(statement[:m.start()])
          and ACTION.search(statement[:m.start()])
          and not re.search(r'\b(?:nếu|trường\s+hợp|trừ\s+khi)\b',statement[:m.start()],re.I)
          and not _LIST_MARKER.fullmatch(statement[:m.start()].strip())]
    bounds=[0,*cuts,len(statement)]
    return [part for a,b in zip(bounds,bounds[1:]) if (part:=statement[a:b].strip())]


def _scope_header(text):
    """Only the declaration before the first lettered point can supply an actor."""
    return re.split(r'(?m)^\s*[a-zđ][.)]\s+',text,maxsplit=1,flags=re.I)[0]


def collective_authorities(header):
    match=re.fullmatch(r'\s*\d+[.)]\s*Các\s+Bộ\s*:\s*([^\n]+)\s*',header,re.I)
    return ['Bộ '+name.strip() for name in match[1].split(',') if name.strip()] if match else []


def _deadline(text):
    durations={(int(m[1]),' '.join(m[2].casefold().split())) for m in DURATION.finditer(text)}
    dates=[m[0] for m in CALENDAR.finditer(text)]
    normalized={_iso(match) for value in dates if (match:=_DMY.search(value))}
    normalized.discard(None)
    count,unit=next(iter(durations)) if len(durations)==1 else (None,None)
    return {'deadline':count,'deadline_unit':unit,
            'deadline_date_candidate':next(iter(normalized)) if len(normalized)==1 else None,
            'deadline_calendar_text_candidate':dates[0] if len(dates)==1 else None,
            'deadline_inclusive_candidate':not dates[0].casefold().startswith('trước') if len(dates)==1 else None,
            'deadline_mentions_candidate':json.dumps(sorted(durations),ensure_ascii=False) if len(durations)>1 else None,
            'interpretation_verified':False}


def extract_procedures(units,kinds,candidates,index,entities,omitted,add,link,ref,sentences):
    allowed={'ocop_framework','ocop_historical','ocop_amendment','local_guidance',
             'food_safety_decree','food_safety_resolution','recognition_decision'}
    covered=set();seen=set();forms_seen=set()
    procedure_articles={(article.source_id, article.attributes.get('article_number')) for article in entities.values()
        if article.kind==EntityType.ARTICLE and re.search(
            r'trình\s+tự|thủ\s+tục|hồ\s+sơ|đánh\s+giá|công\s+nhận|thu\s+hồi|trách\s+nhiệm|tổ\s+chức\s+thực\s+hiện',
            str(article.attributes.get('title_candidate') or ''), re.I)}
    framework_units={e.evidence_unit_id for article in entities.values()
        if article.kind==EntityType.ARTICLE and (article.source_id, article.attributes.get('article_number')) in procedure_articles
        for e in article.evidence}

    def attach(eid,ev):
        if ev not in entities[eid].evidence:
            entities[eid].evidence.append(ev)

    def anchor_ref(evidence, literal=None):
        if literal is None:
            literal=next((s for s in sentences(evidence.quote) if DURATION.search(s)),evidence.quote)
        record={'source_id':evidence.source_id,'evidence_unit_id':evidence.evidence_unit_id,
                'pdf_page':evidence.pdf_page}
        return ref(record,index,text=literal)

    def documents(parent,statement,record,ev):
        procedure=entities[parent].kind==EntityType.PROCEDURE_STEP
        context=entities[parent].attributes.get('context_statement_candidate') or ''
        header=(sentences(context) or [''])[0]
        input_list=bool(re.search(r'hồ\s+sơ.*(?:gồm|chuẩn\s+bị)',header,re.I|re.S))
        if procedure and not INPUT_CUE.search(statement) and not input_list:
            return
        if procedure:
            action=entities[parent].attributes.get('action_candidate') or ''
            if (not re.search(r'hồ\s+sơ|tài\s+liệu\s+minh\s+chứng',statement,re.I) and not input_list
                or re.match(r'ban\s+hành|công\s+nhận|quyết\s+định|thành\s+lập|thu\s+hồi|thông\s+báo',action,re.I)):
                return  # legislation being revised and documents being issued are not dossier inputs
        if not procedure and re.match(r'\s*[□☐☑•-]*\s*Không\b',statement,re.I):
            return
        for match in DOCUMENT.finditer(statement):
            prefix=re.split(r'[;.!?]',statement[:match.start()])[-1]
            if re.search(r'\b(?:không|chưa|nếu|trường\s+hợp|trừ\s+khi|chỉ\s+áp\s+dụng)\b', prefix, re.I):
                omitted['document_requirement_negated_or_conditional']+=1
                continue
            required=bool(re.search(
                r'chuẩn\s+bị|(?:phải|cần)\s+có|nộp|cung\s+cấp|gửi\s+kèm|'
                r'hồ\s+sơ[^;.!?]*(?:bao\s+gồm|gồm)|yêu\s+cầu\s*:\s*(?:có)?',prefix,re.I))
            if not required:
                omitted['document_role_not_explicit_input']+=1
                continue
            if _norm(match[0])=='báo cáo' and re.match(
                    r'\s+(?:Bộ\b|Chủ\s+tịch\b|UBND\b|Thủ\s+tướng\b)',statement[match.end():],re.I):
                continue  # verb "report to an authority", not a document noun
            if re.match(r'\)[a-z]{2,}\b',statement[match.end():],re.I):
                omitted['evidence_type_ocr_noise']+=1
                continue
            if procedure and re.search(r'(?:cấp|thu\s+hồi|lập|xây\s+dựng|ban\s+hành|bằng)\s*(?:các\s+)?$',statement[:match.start()],re.I):
                continue  # an issued/withdrawn certificate is an output, not evidence to submit
            literal=match[0].strip()
            doc_ev=ref(record,index,text=literal)
            eid=add(EntityType.EVIDENCE_TYPE,' '.join(literal.split())[:350],record,doc_ev,
                    key=f'evidence-type:{_norm(literal)}')
            attach(parent,doc_ev)
            link('REQUIRES_EVIDENCE',parent,eid,doc_ev,attributes={
                'interpretation_verified':False,
                'conditional_candidate':not procedure and not bool(re.search(r'yêu\s+cầu|phải\s+có',statement,re.I))})

    def steps(sid,scope,base,primary=None):
        record={'source_id':sid,'evidence_unit_id':base.evidence_unit_id,'pdf_page':base.pdf_page}
        for ordinal,statement in enumerate(_procedure_sentences(base.quote,sentences)):
            key=(scope,base.evidence_unit_id,statement)
            if key in seen or len(statement)<12:
                continue
            seen.add(key)
            ev=ref(record,index,text=statement)
            if (re.match(r'\s*(?:Căn\s+cứ|Điều\s+\d|THỦ\s+TỤC|CÔNG\s+BÁO)',statement,re.I)
                or re.search(r'Email|thời\s+gian\s+ký|chinhphu\.(?:vn|yn)',statement,re.I)):
                omitted['non_procedure_source_text']+=1
                continue
            deadline=_deadline(statement)
            inherited=[]
            if primary and primary!=base and not DURATION.search(statement):
                context_deadline=_deadline(primary.quote)
                if context_deadline['deadline'] is not None:
                    deadline=context_deadline;inherited=[anchor_ref(primary)]
            subjects=_subjects(statement)
            body=re.sub(r'^\s*(?:\d{1,2}[.)]|[a-zđ][.)]|\(\d+\)|[-%])\s*','',statement,flags=re.I)
            if re.match(r'(?:Sửa\s+đổi|Bãi\s+bỏ)\b',body,re.I):
                omitted['amendment_heading_not_action_step']+=1
                continue
            nominal=bool(re.match(r'(?:Phiếu\b|Bản\s+tự\s+công\s+bố\b|Văn\s+bản\b|Báo\s+cáo\b|Sản\s+phẩm\s+mẫu\b)',body,re.I))
            nominal=nominal or bool(re.match(r'Hồ\s+sơ\b',body,re.I) and re.search(r'bao\s+gồm\s*:\s*$',body,re.I))
            if nominal:
                omitted['document_list_not_action_step']+=1
                continue
            leading_action=ACTION.match(re.sub(r'^(?:Chủ\s+động|Thường\s+xuyên)\s+','',body,flags=re.I))
            anchors=[]
            collective=re.match(r'\s*\d+[.)]\s*Các\s+Bộ\s*:\s*([^\n]+)',primary.quote,re.I) if primary else None
            if not subjects and collective and leading_action:
                # A list header explicitly supplies a shared ministry prefix.
                # A ministry named later as a recipient is not the sole actor.
                subjects=['Bộ '+name.strip() for name in collective[1].split(',') if name.strip()]
                anchors=[anchor_ref(primary,primary.quote.splitlines()[0])]
            mentions=list(find_authorities(statement))
            if not subjects and primary and leading_action and (not mentions or all(_recipient(statement,m) for m in mentions)):
                header=_scope_header(primary.quote)
                parents={_norm(m[0]):m[0] for m in _subjects(header)
                         if re.fullmatch(r'\s*:\s*',header[m.end():])}
                if len(parents)==1:
                    label=next(iter(parents.values()))
                    literal=next((s for s in sentences(header) if label in s),header)
                    anchors=[anchor_ref(primary,literal)]
                    subjects=[next(iter(parents.values()))]
            # A heading/list item, legal basis, validity statement or actorless
            # prose remains in Article/Clause/evidence. It is not an action step.
            direct_actions=[ACTION.match(statement,m.end()+len(statement[m.end():])-len(statement[m.end():].lstrip(' ,:')))
                            for m in subjects if not isinstance(m,str)]
            action=next((m for m in direct_actions if m),None) or (ACTION.search(statement) if leading_action else None)
            if not subjects or not action:
                omitted['procedure_frame_not_observed']+=1
                continue
            step=add(EntityType.PROCEDURE_STEP,' '.join(statement.split())[:350],record,ev,
                key=f'procedure:{scope}:{base.evidence_unit_id}:{ordinal}:{statement}',
                attributes={**deadline,'statement_candidate':statement,
                            'action_candidate':action[0].strip(),
                            'object_candidate':statement[action.end():].strip() or None,
                            'context_statement_candidate':primary.quote if primary else None,
                            'authority_candidate':None})
            for anchor in inherited:
                attach(step,anchor)
            labels=[]
            for subject in subjects:
                label=subject if isinstance(subject,str) else subject[0]
                canonical=resolve(label)
                if canonical is None:
                    omitted['authority_not_in_catalog']+=1
                    continue
                labels.append(canonical['label'])
                agency_ev=anchors[0] if isinstance(subject,str) and anchors else ref(record,index,text=label)
                agency=add(EntityType.AUTHORITY,canonical['label'],record,agency_ev,
                           key=f"authority:{canonical['canonical_id']}",
                           attributes={'canonical_id':canonical['canonical_id'],
                                       'interpretation_verified':False})
                if anchors:
                    attach(agency,ev)  # scoped continuation shares the action-page evidence
                for anchor in anchors:
                    attach(step,anchor)
                link('RESPONSIBLE_FOR',agency,step,ev,extra_evidence=anchors)
            if labels:
                entities[step].attributes['authority_candidate']='; '.join(sorted(set(labels)))
            else:
                omitted['procedure_without_explicit_authority']+=1
            if deadline['deadline'] is None and deadline['deadline_date_candidate'] is None and deadline['deadline_calendar_text_candidate'] is None:
                omitted['procedure_without_single_deadline']+=1
            documents(step,statement,record,ev)

    clauses=[e for e in entities.values() if e.kind==EntityType.CLAUSE and kinds.get(e.source_id) in allowed]
    for clause in clauses:
        if kinds[clause.source_id] in {'ocop_framework','ocop_historical'} and (clause.source_id, clause.attributes.get('article_number')) not in procedure_articles:
            continue
        if not any(TRIGGER.search(e.quote) for e in clause.evidence):
            continue
        primary=clause.evidence[0]
        for ev in list(clause.evidence):
            covered.add(ev.evidence_unit_id)
            steps(clause.source_id,clause.entity_id,ev,primary)

    for unit in units:
        sid=unit['source_id'];text=unit.get('text') or ''
        if kinds.get(sid) not in allowed or unit.get('unit_kind') not in {'article','paragraph','section','form'}:
            continue
        record={'source_id':sid,'evidence_unit_id':unit['unit_id'],'pdf_page':unit['spans'][0]['pdf_page']}
        ev=ref(record,index,text=text)
        if unit['unit_id'] not in covered and TRIGGER.search(text) and (kinds[sid]!='ocop_framework' or unit['unit_id'] in framework_units):
            steps(sid,unit['unit_id'],ev)
        for match in FORM.finditer(text):
            form_ev=ref(record,index,text=match[0])
            number=match[1];annex=match[2].upper() if match[2] else None
            add(EntityType.FORM_TEMPLATE,match[0],record,form_ev,key=f'form-reference:{number}:{annex}',
                attributes={'form_number':number,'annex_number_candidate':annex,'reference_only':True,
                            'fields_observed':False,'fields_candidate':None,'interpretation_verified':False})
            if (sid,number,annex) not in forms_seen:
                forms_seen.add((sid,number,annex));omitted['form_reference_without_fields']+=1
            if annex is None:
                omitted['form_reference_missing_annex']+=1
        if kinds[sid]=='local_guidance':
            area=re.search(r'(?:phường|xã|thị trấn|huyện|quận|thành phố|tỉnh)\s+[A-ZĐ][^\W\d_]*(?:\s+[A-ZĐ][^\W\d_]*){0,4}',text)
            if area:
                area_ev=ref(record,index,text=area[0])
                guidance=add(EntityType.LOCAL_GUIDANCE,sid,record,area_ev,key='local-guidance')
                region=add(EntityType.ADMINISTRATIVE_AREA,' '.join(area[0].split()),record,area_ev,key=f'area:{_norm(area[0])}')
                link('APPLIES_IN',guidance,region,area_ev)

    form_groups={}
    for entity in entities.values():
        if entity.kind==EntityType.FORM_TEMPLATE and entity.attributes.get('reference_only'):
            form_groups.setdefault((entity.source_id,entity.attributes.get('form_number')),[]).append(entity)
    for group in form_groups.values():
        annexes={e.attributes.get('annex_number_candidate') for e in group if e.attributes.get('annex_number_candidate')}
        if len(annexes)>1:
            omitted['form_reference_multiple_annex_candidates']+=1
            for entity in group:
                entity.attributes['annex_conflict_candidate']=True

    # Document requirements in a criterion heading, option, or explicit note.
    # Select a parent only from an observed row or a continuity-backed parent
    # whose evidence actually includes this table unit.
    options_by_row=set()
    criteria_by_unit={}
    for entity in entities.values():
        for proof in entity.evidence:
            if entity.kind==EntityType.SCORE_OPTION:
                options_by_row.add((entity.source_id,proof.evidence_unit_id,proof.row))
            elif entity.kind==EntityType.CRITERION:
                criteria_by_unit.setdefault((entity.source_id,proof.evidence_unit_id),[]).append(entity)
    for row in candidates.get('criterion_candidates',[]):
        if row.get('score_candidate') is not None or (row['source_id'],row['evidence_unit_id'],row['row']) in options_by_row:
            continue  # scored alternatives describe assessment, not submitted papers
        label=str(row.get('label_candidate') or '')
        if not DOCUMENT.search(label):
            continue
        uid=row['evidence_unit_id'];page=int(row['pdf_page']);sid=row['source_id']
        preceding=[e for e in criteria_by_unit.get((sid,uid),[])
            if (e.evidence[0].pdf_page<page or (e.evidence[0].pdf_page==page and
                 e.attributes.get('row',10**9)<=row['row']))]
        if not preceding:
            omitted['evidence_requirement_without_criterion_parent']+=1
            continue
        parent=max(preceding,key=lambda e:(e.evidence[0].pdf_page,e.attributes.get('row',-1)))
        ev=ref(row,index)
        # Use the literal row reconstructed from cells, not a cropped proposal.
        documents(parent.entity_id,ev.quote,row,ev)
