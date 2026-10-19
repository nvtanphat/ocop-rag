"""Local human review of public OCOP candidates; no dossier paths are accepted."""
from __future__ import annotations
import hmac
import os
from urllib.parse import quote
from typing import Literal
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from backend.api import ocop_routes
from ai_core.graph.ocop.review import load_queue,statistics,record_decision,render_crop,rebuild_reviewed_graph

router=APIRouter(prefix='/api/ocop/review',tags=['OCOP human review'])


class DecisionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_id:str=Field(min_length=1,max_length=300)
    content_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    decision:Literal['approve','reject','correct']
    reviewer:str=Field(min_length=1,max_length=160)
    correction:dict|None=None
    notes:str=Field(default='',max_length=8000)


def _items():
    try:
        return load_queue(ocop_routes.ROOT)
    except (ValueError,OSError) as exc:
        raise HTTPException(409,str(exc)) from exc


def _item(target_id):
    item=next((i for i in _items() if i['target_id']==target_id),None)
    if item is None: raise HTTPException(404,'Không tìm thấy mục duyệt trong corpus hiện tại')
    for i,ref in enumerate(item['citations']):
        ref['crop_url']=f'/api/ocop/review/items/{quote(target_id,safe="")}/crops/{i}'
    return item


@router.get('/stats')
def stats():
    return statistics(_items())


@router.get('/queue')
def queue(priority:Literal['P1','P2','P3']|None=None,offset:int=Query(0,ge=0),
          limit:int=Query(30,ge=1,le=100),include_decided:bool=False):
    items=[i for i in _items() if (priority is None or i['priority']==priority) and
           (include_decided or i['review_status'] not in {'verified','rejected'})]
    return {'items':items[offset:offset+limit],'total':len(items),'offset':offset}


@router.get('/items/{target_id}')
def item(target_id:str):
    return _item(target_id)


@router.get('/items/{target_id}/crops/{index}')
def crop(target_id:str,index:int):
    try:
        path=render_crop(ocop_routes.ROOT,_item(target_id),index)
        return FileResponse(path,media_type='image/png')
    except (ValueError,OSError,IndexError) as exc:
        raise HTTPException(409,str(exc)) from exc


@router.post('/decisions')
def decide(body:DecisionRequest,authorization:str|None=Header(default=None)):
    token=os.environ.get('OCOP_REVIEW_TOKEN')
    if token and not hmac.compare_digest(authorization or '',f'Bearer {token}'):
        raise HTTPException(403,'Cần mã truy cập của người duyệt')
    try:
        row=record_decision(ocop_routes.ROOT,body.target_id,body.content_hash,body.decision,
                            body.reviewer,correction=body.correction,notes=body.notes)
    except (ValueError,RuntimeError) as exc:
        raise HTTPException(409,str(exc)) from exc
    try:
        graph=rebuild_reviewed_graph(ocop_routes.ROOT)
        ocop_routes._graph_data.cache_clear()
    except (OSError,ValueError,RuntimeError) as exc:
        raise HTTPException(503,'Đã ghi quyết định; cần build lại graph: '+str(exc)) from exc
    return {'decision':row,'graph':graph['counts'],'review':graph['human_review']}
