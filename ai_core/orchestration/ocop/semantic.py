"""Auditable Vietnamese OCOP capability signals (no tool/auth grants from an LLM).

Matching is accent-insensitive for natural text. Negation and *task intent* are
checked before assigning restricted dossier capabilities, and comparison alone
never implies a historical/legal applicability question.
"""
from __future__ import annotations
import re
import unicodedata
from ai_core.orchestration.ocop.capabilities import Capability


def normalize(value: str) -> str:
    value = unicodedata.normalize('NFD', value).casefold().replace('đ', 'd')
    return ''.join(c for c in value if unicodedata.category(c) != 'Mn')


def has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(normalize(p) in text for p in phrases)


def public_scoring_method(q: str) -> bool:
    return has_any(q, ('cách tính điểm', 'hướng dẫn tính điểm', 'công thức tính điểm',
        'quy trình chấm điểm', 'tính điểm như thế nào', 'tính điểm ra sao',
        'tính điểm ocop như thế nào', 'thang điểm', 'phương pháp chấm điểm',
        'điểm được tính thế nào')) or bool(re.search(r'\btinh diem\b.{0,25}\b(nhu the nao|ra sao|the nao)\b',q))


def private_scoring_action(q: str) -> bool:
    if public_scoring_method(q) or re.search(r'\b(khong|dung|chua|khong can)\s+(?:can\s+)?(?:tinh|cham|uoc tinh)\s+diem\b',q):
        return False
    if re.fullmatch(r'(?:hay\s+)?(?:tinh|cham|uoc tinh)\s+diem(?:\s+ocop)?[?.!]*',q):
        return True
    if re.search(r'\btinh diem\b.{0,30}\b(neu|gia su)\b',q):
        return True
    return has_any(q, ('chấm điểm hồ sơ của tôi', 'tính điểm hồ sơ của tôi',
        'ước tính điểm hồ sơ', 'dự tính điểm hồ sơ', 'tính điểm cho hồ sơ',
        'hồ sơ của tôi được bao nhiêu điểm', 'bao nhiêu sao nếu',
        'hãy tính điểm', 'chấm điểm giúp tôi', 'đánh giá điểm cho tôi')) or (
            has_any(q, ('tính điểm','ước tính điểm','dự tính điểm','chấm điểm'))
            and has_any(q, ('hồ sơ này', 'hồ sơ của tôi','cho sản phẩm của tôi')))


def private_dossier_action(q: str) -> bool:
    if has_any(q, ('hồ sơ riêng', 'dossier riêng', 'hồ sơ nội bộ')):
        return True
    if has_any(q, ('hồ sơ tôi cần chuẩn bị', 'hồ sơ của tôi cần chuẩn bị',
                    'hồ sơ tôi cần nộp', 'tôi cần chuẩn bị hồ sơ',
                    'hồ sơ gồm những gì', 'hồ sơ cần có gì')):
        return False
    return has_any(q, ('rà soát hồ sơ của tôi', 'kiểm tra hồ sơ của tôi',
        'hồ sơ của tôi còn thiếu', 'hồ sơ tôi còn thiếu', 'hồ sơ tôi thiếu gì',
        'hồ sơ tôi cần bổ sung minh chứng',
        'hồ sơ của tôi đạt chưa', 'hồ sơ của tôi có đạt',
        'rà soát hồ sơ', 'đánh giá hồ sơ của tôi'))


def temporal_question(q: str, slots: dict) -> bool:
    years=slots.get('years') or []
    legal=has_any(q, ('quy định','bộ tiêu chí','tiêu chí','mẫu','hồ sơ','ocop',
                     'chính sách','văn bản','luật','hiệu lực', 'công nhận','năm'))
    if len(years)>=2 and legal:return True
    if has_any(q, ('hiệu lực', 'chuyển tiếp', 'thời điểm áp dụng','năm nào áp dụng',
                    'thay đổi theo năm', 'theo thời điểm','quy định năm',
                    'trước và sau khi', 'có còn áp dụng', 'hết hiệu lực')):
        return True
    if has_any(q, ('so sánh','khác nhau', 'khác biệt', 'đối chiếu', 'thay đổi')):
        return bool(len(years)>=2 or (years and has_any(q, ('phiên bản','quy định','tiêu chí'))) or
            has_any(q, ('quy định cũ','quy định mới','văn bản cũ','văn bản mới')))
    return False


def detect_capabilities(query: str, slots: dict) -> tuple[list[Capability], list[str]]:
    q=normalize(query)
    found: list[Capability]=[]
    reasons=[]
    def add(cap:Capability,reason:str):
        if cap not in found:found.append(cap);reasons.append(reason)
    if slots.get('document_code') and slots.get('article_id'):
        add(Capability.EXACT_ARTICLE,'document_and_article_id')
    if has_any(q,('thuộc nhóm','thuộc phân nhóm','thuộc loại','nhóm gì','nhóm nào',
                   'phân nhóm','phân loại sản phẩm')):
        add(Capability.CLASSIFY_PRODUCT,'product_classification_signal')
    if has_any(q,('tiêu chí','bộ tiêu chí','thang điểm','mức điểm','điểm tối đa',
                   'cách tính điểm','công thức tính điểm','để đạt 3 sao','để đạt 4 sao',
                   'để đạt 5 sao','điểm ocop','phương pháp chấm điểm')) or public_scoring_method(q):
        add(Capability.CRITERIA,'criterion_signal')
    if has_any(q,('minh chứng','giấy tờ cần','hồ sơ cần có','cần chứng nhận gì',
                   'yêu cầu giấy tờ','loại giấy tờ','cần giấy tờ')):
        add(Capability.EVIDENCE_REQUIREMENTS,'evidence_requirements_signal')
    if slots.get('form_id') or has_any(q,('biểu mẫu','mẫu hồ sơ','mẫu nào','điền mẫu',
                   'mẫu số','mẫu 01','mẫu 02','mẫu 03','đăng ký','thủ tục',
                   'hồ sơ ocop','hồ sơ lần đầu','cần nộp','nộp hồ sơ',
                   'hồ sơ tôi cần chuẩn bị', 'hồ sơ gồm những gì')):
        add(Capability.PROCEDURE_FORM,'procedure_form_signal')
    if temporal_question(q,slots):add(Capability.TEMPORAL,'legal_temporal_signal')
    is_authority = has_any(q, ('tham quyen', 'co quan nao', 'ai cong nhan', 'ai co tham quyen',
                               'ai quyet dinh', 'cap nao cong nhan', 'cap nao co tham quyen'))
    if is_authority:
        add(Capability.EXACT_ARTICLE, 'authority_signal')
    if not is_authority and has_any(q,('công nhận','đã đạt ocop','đạt sao ocop','sản phẩm được công nhận',
                  'sản phẩm ocop 3 sao','sản phẩm ocop 4 sao','sản phẩm ocop 5 sao',
                  'danh sách sản phẩm ocop', 'sản phẩm đạt sao')):
        add(Capability.RECOGNITION,'recognition_signal')
    if has_any(q,('an toàn thực phẩm','attp','an toàn vệ sinh','giấy chứng nhận cơ sở',
                  'nhãn hàng hóa','miễn giấy','miễn chứng nhận','điều kiện vệ sinh')):
        add(Capability.SECTOR_COMPLIANCE,'compliance_signal')
    if private_dossier_action(q):add(Capability.REVIEW_DOSSIER,'private_dossier_action')
    if private_scoring_action(q):add(Capability.ESTIMATE_SCORE,'private_scoring_action')
    if (slots.get('document_code') and has_any(q, ('thay thế', 'sửa đổi văn bản',
            'sửa đổi quyết định', 'bổ sung văn bản', 'căn cứ văn bản'))) or has_any(q,('liên quan đến','mối quan hệ','đối chiếu','liên hệ với',
                  'kết hợp các','liên hệ giữa')) or (Capability.EVIDENCE_REQUIREMENTS in found and Capability.CRITERIA in found):
        add(Capability.RELATION_REASONING,'relational_signal')
    if not found:add(Capability.OVERVIEW,'general_ocop_question')
    return found,reasons

