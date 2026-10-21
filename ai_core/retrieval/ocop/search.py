"""indexing runnable OCOP lookup: BM25 today, genuine RRF hybrid when dense built."""
from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from ai_core.system.telemetry import traced
from pathlib import Path
from ocop_contracts.ids import content_sha256
from ai_core.retrieval.ocop.models_config import (
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    get_pair_token_budget,
    resolve_local_model_path,
)
from ai_core.retrieval.ocop.index_pipeline import (
    ROOT, BM25Search, _load_embedding, _encode, _records_hash, terms,
    _fold_vietnamese,
)


def _dense_hits(query:str,manifest:dict,limit:int,*,source_id:str|None=None,
                include_needs_review:bool=True,evidence_unit_ids:set[str]|None=None)->list[tuple[str,float]]:
    dense=manifest.get("dense") or {}
    if not dense.get("enabled"):
        raise RuntimeError("Dense index not built. Run index-ocop -- --with-dense first")
    try:from qdrant_client import QdrantClient
    except ImportError as exc:raise RuntimeError("qdrant-client is required for dense/hybrid query") from exc
    model=_load_embedding(dense["model_id"],dense.get("revision"))
    vector=_encode(model,[query],True)[0]
    if len(vector)!=dense["dimension"]:raise RuntimeError("Embedding dimension mismatch")
    client=QdrantClient(host=dense["host"],port=dense["port"])
    from qdrant_client import models
    conditions=[]
    if source_id:
        conditions.append(models.FieldCondition(key="source_id",match=models.MatchValue(value=source_id)))
    if evidence_unit_ids is not None:
        conditions.append(models.FieldCondition(key='evidence_unit_id',
                          match=models.MatchAny(any=sorted(evidence_unit_ids))))
    if not include_needs_review:
        conditions.append(models.FieldCondition(key="review_status",match=models.MatchValue(value="verified")))
    if manifest.get('corpus_version'):
        conditions.append(models.FieldCondition(key="corpus_version",
                                               match=models.MatchValue(value=manifest['corpus_version'])))
    query_filter=models.Filter(must=conditions) if conditions else None
    if hasattr(client,"query_points"):
        response=client.query_points(collection_name=dense["collection"],query=vector.tolist(),limit=limit,with_payload=True,query_filter=query_filter)
        points=response.points
    else:
        points=client.search(collection_name=dense["collection"],query_vector=vector.tolist(),limit=limit,with_payload=True,query_filter=query_filter)
    return [(p.payload["chunk_id"],float(p.score)) for p in points]


def rrf(ranks:list[list[str]],k:int=60)->dict[str,float]:
    merged={}
    for lst in ranks:
        for i,uid in enumerate(lst):merged[uid]=merged.get(uid,0.)+1/(k+i+1)
    return merged


@lru_cache(maxsize=1)
def _load_reranker(model_id:str,revision:str|None=None):
    os.environ.setdefault("TRANSFORMERS_NO_TF","1")
    os.environ.setdefault("USE_TF","0")
    try:from sentence_transformers import CrossEncoder
    except ImportError as exc:raise RuntimeError("sentence-transformers required for --rerank") from exc
    resolved, is_local = resolve_local_model_path(model_id)
    # Avoid executing arbitrary Python from a remote repository. A revision
    # alone is not an approval to execute reviewed custom code.
    kwargs={"device":"cpu","trust_remote_code":False,"local_files_only":True}
    if revision and not is_local:
        kwargs["revision"]=revision
    return CrossEncoder(resolved,**kwargs)


def _check_index(index_dir:Path,manifest:dict,rows:list[dict],bm25:BM25Search)->None:
    """Reject stale postings, altered content and mismatched release manifests."""
    data=bm25.data
    ids=[r.get('chunk_id') for r in rows]
    if not all(isinstance(cid,str) and cid for cid in ids) or len(ids)!=len(set(ids)):
        raise RuntimeError('Index mismatch: duplicate or invalid chunk IDs')
    if data.get('n')!=len(rows) or data.get('corpus_hash')!=content_sha256('\n'.join(ids)):
        raise RuntimeError('Corpus/index mismatch: BM25 postings do not match chunk order')
    recorded=data.get('records_hash')
    if recorded is not None and recorded!=_records_hash(rows):
        raise RuntimeError('Corpus/index mismatch: indexed chunk content or metadata modified')
    declared=manifest.get('bm25') or {}
    if declared.get('corpus_hash') not in (None,data['corpus_hash']):
        raise RuntimeError('Corpus/index mismatch: manifest chunk hash')
    if declared.get('records_hash') not in (None,recorded):
        raise RuntimeError('Corpus/index mismatch: manifest records hash')
    if manifest.get('counts',{}).get('chunks',len(rows))!=len(rows):
        raise RuntimeError('Corpus/index mismatch: manifest row count')
    for row in rows:
        if row.get('corpus_version')!=manifest.get('corpus_version'):
            raise RuntimeError('Corpus/index mismatch: chunk version does not match manifest')


def _read_checked_index(index_dir:Path)->tuple[dict,list[dict],dict,BM25Search]:
    manifest=json.loads((index_dir/'manifest.json').read_text(encoding='utf-8'))
    ordered=[];chunks={}
    with (index_dir/'chunks.jsonl').open(encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():continue
            row=json.loads(line)
            ordered.append(row)
            chunks[row['chunk_id']]=row
    bm25=BM25Search(index_dir/'bm25.json.gz')
    _check_index(index_dir,manifest,ordered,bm25)
    return manifest,ordered,chunks,bm25


# Function words in question syntax should not dilute coverage of the content
# phrases. These are deliberately language-level stopwords, not OCOP terms.
_SCOPE_STOPWORDS = frozenset(_fold_vietnamese(token) for token in terms(
    "ai cái các có của để gì gồm không là mà mỗi nào như những phải sao thì "
    "và về với ở tại trong ngoài cần được này đó hôm nay tuần bên thế cùng "
    "một số hãy"
))


def _scope_bigrams(text:str)->frozenset[tuple[str,str]]:
    tokens=tuple(_fold_vietnamese(token) for token in terms(text))
    return frozenset((left,right) for left,right in zip(tokens,tokens[1:])
                     if left not in _SCOPE_STOPWORDS and right not in _SCOPE_STOPWORDS)


@lru_cache(maxsize=4)
def _indexed_scope_tokens(index_dir:str,signature:tuple[tuple[int,int],...])->tuple[tuple[str,...],...]:
    # Validate the BM25 postings, manifest and chunk content before using the
    # index to reopen a query that the deterministic scope gate rejected.
    _,ordered,_,_=_read_checked_index(Path(index_dir))
    return tuple(tuple(_fold_vietnamese(token) for token in terms(row.get('text_for_bm25','')))
                 for row in ordered)


def query_content_bigram_coverage(index_dir:Path,query:str)->float|None:
    """Return max accent-folded content-bigram coverage in one checked chunk.

    A missing or invalid local index returns ``None`` so the caller keeps the
    normal fail-closed out-of-scope decision. At least two informative query
    bigrams are required to avoid reopening on a single generic phrase.
    """
    index_dir=Path(index_dir).resolve()
    files=(index_dir/'manifest.json',index_dir/'chunks.jsonl',index_dir/'bm25.json.gz')
    try:
        signature=tuple((item.stat().st_mtime_ns,item.stat().st_size) for item in files)
    except OSError:
        return None
    query_bigrams=_scope_bigrams(query)
    if len(query_bigrams)<2:
        return 0.0
    try:
        corpus_tokens=_indexed_scope_tokens(str(index_dir),signature)
    except (OSError,RuntimeError,ValueError,KeyError,json.JSONDecodeError):
        return None
    best=0.0
    for tokens in corpus_tokens:
        chunk_bigrams=_scope_bigrams_from_tokens(tokens)
        if not chunk_bigrams:
            continue
        best=max(best,len(query_bigrams & chunk_bigrams)/len(query_bigrams))
        if best>=1.0:
            break
    return best


def _scope_bigrams_from_tokens(tokens:tuple[str,...])->frozenset[tuple[str,str]]:
    return frozenset((left,right) for left,right in zip(tokens,tokens[1:])
                     if left not in _SCOPE_STOPWORDS and right not in _SCOPE_STOPWORDS)


def _rerank(query:str,candidates:list[dict],model_id:str,revision:str|None=None,
            pair_token_budget:int|None=None):
    budget = pair_token_budget or get_pair_token_budget()
    reranker=_load_reranker(model_id,revision)
    pairs=[(query,item["text"]) for item in candidates]
    tokenizer=getattr(reranker,'tokenizer',None)
    if tokenizer is not None and callable(tokenizer):
        for q,doc in pairs:
            encoded=tokenizer(q,doc,add_special_tokens=True,truncation=False)
            tokens=len(encoded['input_ids'])
            if tokens>budget:
                raise RuntimeError(f"Reranker pair input exceeds pair_token_budget ({tokens} > {budget}); silent truncation is forbidden")
    scores=reranker.predict(pairs,show_progress_bar=False)
    for row,score in zip(candidates,scores,strict=True):
        row["reranker_score"]=float(score)
        row["ranking_reason"]="local_reranker"
    candidates.sort(key=lambda r:-r["reranker_score"])
    return candidates


@traced("ocop.retrieval.search")
def search(index_dir:Path,query:str,*,mode:str="sparse",top_k:int=8,
           source_id:str|None=None,include_needs_review:bool=True,rerank:bool=False,
           reranker_model:str=DEFAULT_RERANKER_MODEL,
           reranker_revision:str|None=DEFAULT_RERANKER_REVISION,expand_parent:bool=False,
           parent_max_chars:int=2400,rerank_candidates:int=40,
           pair_token_budget:int|None=None,
           evidence_unit_ids:set[str]|None=None)->list[dict]:
    if mode not in ("sparse","hybrid","dense"):
        raise ValueError("mode must be sparse, dense or hybrid")
    if top_k<=0:raise ValueError("top_k must be positive")
    if rerank_candidates<1 or rerank_candidates>200:
        raise ValueError('rerank_candidates must be between 1 and 200')
    if expand_parent and parent_max_chars<100:raise ValueError('parent_max_chars must be >=100')
    manifest,ordered,chunks,bm25=_read_checked_index(index_dir)
    requested_mode=mode
    fallback_reason=None
    if mode!='sparse' and not manifest.get('dense',{}).get('enabled'):
        mode='sparse';fallback_reason='dense_not_built'
    allowed=lambda cid: ((source_id is None or chunks[cid]["source_id"]==source_id)
                          and (evidence_unit_ids is None or chunks[cid]['evidence_unit_id'] in evidence_unit_ids)
                          and (include_needs_review or chunks[cid]["review_status"] == "verified"))
    # Determine admissible postings before scoring/ranking; top-K oversampling
    # cannot guarantee that a rare target document survives global ranking.
    allowed_positions={i for i,ch in enumerate(ordered) if allowed(ch["chunk_id"])}
    if not allowed_positions:return []
    pool_size=max(top_k,rerank_candidates if rerank else top_k)
    sparse=[];sparse_scores={}
    if mode in ("sparse","hybrid"):
        for pos,score in bm25.search(query,top_k=max(40,pool_size*2),allowed_docs=allowed_positions):
            cid=ordered[pos]["chunk_id"]
            if allowed(cid):sparse.append(cid);sparse_scores[cid]=score
    dense=[];dense_scores={}
    if mode in ("dense","hybrid"):
        scope={'evidence_unit_ids':evidence_unit_ids} if evidence_unit_ids is not None else {}
        try:
            for cid,score in _dense_hits(query,manifest,max(40,pool_size*2),source_id=source_id,
                                          include_needs_review=include_needs_review,**scope):
                if cid in chunks and allowed(cid):dense.append(cid);dense_scores[cid]=score
        except (OSError,RuntimeError,ImportError,ConnectionError):
            mode='sparse';fallback_reason='local_dense_model_or_backend_unavailable'
            if not sparse:
                for pos,score in bm25.search(query,top_k=max(40,pool_size*2),allowed_docs=allowed_positions):
                    cid=ordered[pos]['chunk_id'];sparse.append(cid);sparse_scores[cid]=score
    fused=rrf([lst for lst in (sparse,dense) if lst]) if mode=="hybrid" else (
          {cid:score for cid,score in sparse_scores.items()} if mode=="sparse" else dense_scores)
    items=sorted(fused.items(),key=lambda x:(-x[1],x[0]))[:pool_size]
    results=[]
    for cid,score in items:
        ch=chunks[cid]
        results.append({"chunk_id":cid,"evidence_unit_id":ch["evidence_unit_id"],
          "source_id":ch["source_id"],"pdf_page":ch["spans"][0]["pdf_page"],
          "source_spans":ch["spans"],"review_status":ch["review_status"],
          "corpus_version":ch["corpus_version"],"score":round(float(score),6),
          "text":ch["text_for_bm25"],
          "raw_text":ch.get('raw_text',ch['text_for_bm25']),
          "context":ch.get('context',{}),"row_ids":ch.get('row_ids',[]),
          "table_headers":ch.get('table_headers',[]),
          "char_start":ch.get('char_start'),"char_end":ch.get('char_end'),
          "over_budget":ch.get('over_budget',False)})
        results[-1]['retrieval_mode']=mode
        results[-1]['requested_retrieval_mode']=requested_mode
        if fallback_reason:results[-1]['retrieval_fallback_reason']=fallback_reason
    if rerank and results:
        try:
            results=_rerank(query,results,reranker_model,reranker_revision,pair_token_budget=pair_token_budget)
        except TypeError:
            try:
                results=_rerank(query,results,reranker_model,reranker_revision)
            except Exception as exc:
                err_msg=f"{type(exc).__name__}: {str(exc)}" if str(exc) else type(exc).__name__
                for row in results:
                    row['rerank_unavailable']=True
                    row['ranking_reason']=f"rerank_unavailable: {err_msg}; deterministic_{mode}_order"
        except Exception as exc:
            err_msg=f"{type(exc).__name__}: {str(exc)}" if str(exc) else type(exc).__name__
            for row in results:
                row['rerank_unavailable']=True
                row['ranking_reason']=f"rerank_unavailable: {err_msg}; deterministic_{mode}_order"
    for row in results:
        row.setdefault('ranking_reason','local_reranker' if 'reranker_score' in row else
                       'deterministic_'+mode+'_order; reranker_not_requested')
    results=results[:top_k]
    if expand_parent and results:
        wanted={r['evidence_unit_id'] for r in results}
        parents={}
        path=index_dir/'evidence_units.jsonl'
        if path.is_file():
            with path.open(encoding='utf-8') as fh:
                for line in fh:
                    if not line.strip():continue
                    unit=json.loads(line)
                    if unit['unit_id'] in wanted:
                        parents[unit['unit_id']]=unit
        for row in results:
            unit=parents.get(row['evidence_unit_id'])
            if not unit or unit.get('source_id')!=row['source_id']:
                continue  # never cross sources on parent expansion
            if not include_needs_review and unit.get('review_status')!='verified':
                continue
            source=unit.get('text') or ''
            if len(source)>parent_max_chars:
                start=row.get('char_start')
                end=row.get('char_end')
                if start is not None and end is not None:
                    left=max(0,min(len(source)-parent_max_chars,(start+end)//2-parent_max_chars//2))
                else:
                    left=0
                context=source[left:left+parent_max_chars]
            else:
                context=source
            row['parent_context']=context
            row['parent_evidence_unit_id']=unit['unit_id']
            row['parent_source_spans']=unit.get('spans',[])
    return results


def main():
    ap=argparse.ArgumentParser(description="indexing: search indexed OCOP evidence")
    ap.add_argument("query")
    ap.add_argument("--root",type=Path,default=ROOT)
    ap.add_argument("--index",type=Path,default=Path("data/processed/ocop/index"))
    ap.add_argument("--mode",choices=("sparse","dense","hybrid"),default="sparse")
    ap.add_argument("--top-k",type=int,default=8)
    ap.add_argument("--expand-parent",action="store_true")
    ap.add_argument("--parent-max-chars",type=int,default=2400)
    ap.add_argument("--source-id")
    ap.add_argument("--verified-only",action="store_true")
    ap.add_argument("--rerank",action="store_true")
    ap.add_argument("--reranker-model",default=DEFAULT_RERANKER_MODEL)
    ap.add_argument("--reranker-revision",default=DEFAULT_RERANKER_REVISION)
    ap.add_argument("--rerank-candidates",type=int,default=40)
    ap.add_argument("--pair-token-budget",type=int,default=None)
    args=ap.parse_args();root=args.root.resolve()
    out=search(args.index if args.index.is_absolute() else root/args.index,args.query,
          mode=args.mode,top_k=args.top_k,source_id=args.source_id,
          include_needs_review=not args.verified_only,rerank=args.rerank,
          reranker_model=args.reranker_model,reranker_revision=args.reranker_revision,
          rerank_candidates=args.rerank_candidates,
          pair_token_budget=args.pair_token_budget,
          expand_parent=args.expand_parent,parent_max_chars=args.parent_max_chars)
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
