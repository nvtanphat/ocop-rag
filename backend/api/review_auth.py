"""Server-side identity for human-review writes (fail-closed).

A decision can promote graph nodes to ``human_verified``, so the writer must be a known person:
* ``OCOP_REVIEWERS_FILE`` points to a JSON file kept outside the repository:
  ``{"reviewers": [{"id": "expert_01", "token_sha256": "<hex>", "can_decide": true}]}``;
* the caller sends ``Authorization: Bearer <token>``; the server hashes it, finds the reviewer and uses that
  reviewer id in the ledger. The client never states who it is.
Missing/invalid configuration, a missing or unknown token and a reviewer without ``can_decide`` all refuse the write.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

HEX64 = re.compile(r'^[0-9a-f]{64}$')
ID = re.compile(r'^[\w.@-]{1,120}$')


@dataclass(frozen=True)
class Reviewer:
    id: str
    can_decide: bool


def _unavailable(code: str) -> HTTPException:
    return HTTPException(503, {'code': code, 'layer': 'configuration',
                               'message': 'Xác thực người duyệt chưa được cấu hình; từ chối ghi quyết định.'})


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def load_reviewers() -> list[dict]:
    location = os.environ.get('OCOP_REVIEWERS_FILE', '').strip()
    if not location:
        raise _unavailable('review_auth_not_configured')
    try:
        data = json.loads(Path(location).read_text(encoding='utf-8'))
        entries = data['reviewers']
        if not isinstance(entries, list) or not entries:
            raise ValueError('no reviewers')
        seen = set()
        for item in entries:
            if not ID.match(str(item['id'])) or not HEX64.match(str(item['token_sha256'])) or item['id'] in seen:
                raise ValueError('invalid reviewer entry')
            seen.add(item['id'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _unavailable('review_auth_invalid') from exc
    return entries


def authenticate(authorization: str | None) -> Reviewer:
    entries = load_reviewers()                       # configuration problems win over credential problems
    if not authorization or not authorization.startswith('Bearer ') or not authorization[7:].strip():
        raise HTTPException(401, 'Cần mã truy cập của người duyệt')
    digest = hash_token(authorization[7:].strip())
    match = None
    for item in entries:                             # constant-time comparison over every entry
        if hmac.compare_digest(digest, item['token_sha256']):
            match = item
    if match is None:
        raise HTTPException(403, 'Mã truy cập không hợp lệ')
    if match.get('can_decide') is not True:
        raise HTTPException(403, 'Tài khoản này không có quyền ghi quyết định duyệt')
    return Reviewer(id=match['id'], can_decide=True)
