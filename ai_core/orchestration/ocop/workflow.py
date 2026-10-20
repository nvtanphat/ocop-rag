"""A single OCOP workflow: route -> bounded tools -> evidence -> answer.

LangGraph uses conditional branches, rather than running an agent loop for
simple lookups. The dependency-free runner shares exactly the same nodes.
External model and graph services are optional, never simulated.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from time import monotonic
from typing import TypedDict
from ai_core.orchestration.ocop.contracts import AgentResponse,Route,Intent,AuthContext
from ai_core.orchestration.ocop.router import route_query,extract_slots,_merge_followup
from ai_core.orchestration.ocop.planner import ToolPlan,build_plan,evidence_ids,recovery_safe
from ai_core.orchestration.ocop.tools import ToolRegistry
from ai_core.orchestration.ocop.answer import assemble, BAD_RESULT_STATUSES
from ai_core.system.telemetry import traced
from ai_core.system.checkpoints import SQLiteCheckpoint,thread_key,should_checkpoint
from ai_core.orchestration.ocop.evidence_grader import grade_evidence,bounded_rewrite
from ai_core.orchestration.ocop.llm import OllamaClient
from ai_core.retrieval.ocop.search import query_content_bigram_coverage


class OcopState(TypedDict,total=False):
    query:str
    effective_query:str
    context:dict
    session:dict
    route:dict
    plan:ToolPlan
    results:list[dict]
    answer:dict
    auth:AuthContext|None
    debug_candidates:bool
    trace:list[dict]
    evidence_coverage:dict
    evidence_grade:dict


class OcopAgent:
    def __init__(self,root:Path,*,llm:OllamaClient|None=None,retrieval_mode:str='sparse',rerank:bool=False,
                 allow_partial_debug:bool=False):
        self.root=Path(root)
        self.tools=ToolRegistry(self.root)
        self.llm=llm
        self.retrieval_mode=retrieval_mode
        self.rerank=rerank
        self.allow_partial_debug=allow_partial_debug is True
        self._checkpoint=None

    def route(self,state:OcopState)->dict:
        query=state['query'];session=state.get('session') or {}
        # Identity originates only from a trusted AuthContext, never a session.
        safe_session={key:session[key] for key in ('last_query','slots','intent','capabilities','dossier_id') if key in session}
        auth=state.get('auth')
        if isinstance(auth,AuthContext):safe_session['tenant_id']=auth.tenant_id
        choice=route_query(query,session=safe_session,llm_route=(self.llm.route if self.llm else None),
            indexed_content_bigram_coverage=lambda text:query_content_bigram_coverage(
                self.tools.index_dir,text))
        if (choice.intent in (Intent.DOSSIER_REVIEW,Intent.SCORE_ESTIMATE) or
            set(choice.required_tools)&{'review_dossier','estimate_score'}) and not isinstance(auth,AuthContext):
            choice=Route(intent=Intent.CLARIFY,strategy='clarify',needs_clarification=True,
                         missing_slots=['authentication'],reason_codes=['untrusted_session_cannot_authorize'])
        effective=query
        if choice.intent==Intent.FOLLOWUP:
            previous=str(session.get('last_query') or '')
            updates=extract_slots(query)
            if 'years' in updates:
                previous=re.sub(r'\b20\d{2}\b',updates['years'][-1],previous)
            # Text query is only for ranking. Structured tools use effective
            # merged slots, so stale values in prose cannot change their scope.
            effective=previous+' (cập nhật yêu cầu: '+query+')'
        return {'route':choice.model_dump(mode='json'),'effective_query':effective,
                'trace':[{'step':'route','intent':choice.intent.value,'tools':list(choice.required_tools),
                          'reasons':choice.reason_codes,'retrieval_path':choice.retrieval_path.value}]}

    def plan(self,state:OcopState)->dict:
        route=Route.model_validate(state['route'])
        # Backend capability is checked at execution planning time, not guessed
        # from the user's question or an LLM-supplied tool list.
        graph_dir=getattr(self.tools,'graph_dir',None)
        graph_ready=bool(graph_dir is not None and (graph_dir/'manifest.json').is_file()
                         and (graph_dir/'nodes.jsonl').is_file()
                         and (graph_dir/'edges.jsonl').is_file())
        plan=build_plan(route,graph_available=graph_ready)
        route.retrieval_path=plan.retrieval_path
        route.required_tools=list(plan.names)
        trace=list(state.get('trace') or [])
        trace.append({'step':'retrieval_strategy','retrieval_path':plan.retrieval_path.value,
                      'tools':list(plan.names),'reason':plan.decision_reason,
                      'graph_available':graph_ready})
        return {'plan':plan,'route':route.model_dump(mode='json'),'trace':trace}

    def _trusted_context(self,state:OcopState)->dict:
        provided=state.get('context') or {}
        slots=Route.model_validate(state['route']).slots
        # Never import authenticated, tenant, verified_criteria, verified_answers,
        # graph_seed_ids, temporal_rule or server permissions from a user dict.
        context={'retrieval_mode':self.retrieval_mode,'rerank':self.rerank,
                 'allow_partial_debug':self.allow_partial_debug,
                 'business_intent':Route.model_validate(state['route']).intent.value,
                 'debug_candidates':bool(state.get('debug_candidates',False)),
                 'dossier_id':(state.get('session') or {}).get('dossier_id')}
        if slots.get('as_of_date'):context['as_of_date']=slots['as_of_date']
        elif isinstance(provided.get('as_of_date'),str) and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',provided['as_of_date']):
            context['as_of_date']=provided['as_of_date']
        return context

    @staticmethod
    def _verified_slots(results:list[dict])->dict:
        # The only additional slots propagated between tasks must come from
        # *verified source-backed* unique values, not LLM/candidate OCR.
        candidates:dict[str,set[str]]={}
        for entry in results:
            for row in (entry.get('output') or {}).get('results',[]):
                if not isinstance(row,dict) or row.get('review_status')!='verified':continue
                if not row.get('source_id') or not any(
                    isinstance(span,dict) and isinstance(span.get('pdf_page'),int) and span['pdf_page']>0
                    for span in (row.get('source_spans') or row.get('spans') or [])):continue
                for name in ('product_group','product_subgroup','criterion_id','sheet_id'):
                    if isinstance(row.get(name),str) and row[name].strip():
                        candidates.setdefault(name,set()).add(row[name].strip())
        return {k:next(iter(values)) for k,values in candidates.items() if len(values)==1}

    @staticmethod
    def _validate_output(output:object)->dict:
        """Tool adapters are an untrusted failure boundary, even if allowlisted."""
        if not isinstance(output,dict) or not isinstance(output.get('results',[]),list) or not all(
            isinstance(row,dict) for row in output.get('results',[])
        ):
            return {'results':[],'status':'invalid_tool_output'}
        if 'status' in output and not isinstance(output['status'],str):
            return {'results':[],'status':'invalid_tool_output'}
        return output

    @staticmethod
    def _dependency_ready(output:dict)->bool:
        """Only verified, source-backed observations may feed dependent tools."""
        if output.get('status') in (
            'tool_unavailable','dependency_unavailable','invalid_tool_output',
            'not_found','not_ready','unknown','recognition_scope_unverified',
            'assessment_year_scope_unverified','recognition_year_scope_unverified',
            'text_evidence_fallback','document_not_found_or_ambiguous',
        ) or output.get('fallback'):
            return False
        return any(
            isinstance(row,dict) and row.get('review_status')=='verified' and
            bool(row.get('source_id')) and
            any(isinstance(span,dict) and isinstance(span.get('pdf_page'),int)
                and span['pdf_page']>0 for span in (row.get('source_spans') or row.get('spans') or []))
            for row in output.get('results',[])
        )

    @staticmethod
    def _graph_seed_rows(output:dict)->list[dict]:
        """Source locations may seed a checked graph without becoming business facts."""
        if output.get('status') in BAD_RESULT_STATUSES or output.get('fallback'):
            return []
        return [row for row in output.get('results', []) if isinstance(row, dict) and
                row.get('review_status') != 'rejected' and row.get('source_id') and
                (row.get('evidence_unit_id') or row.get('unit_id')) and any(
                    isinstance(span, dict) and isinstance(span.get('pdf_page'), int) and
                    span['pdf_page'] > 0 and isinstance(span.get('bbox'), (list, tuple)) and
                    len(span['bbox']) == 4 and re.fullmatch(r'[0-9a-f]{64}', str(span.get('source_sha256') or ''))
                    for span in (row.get('source_spans') or row.get('spans') or []))]

    def execute(self,state:OcopState)->dict:
        route=Route.model_validate(state['route']);plan=state.get('plan') or build_plan(route)
        results=[];trace=list(state.get('trace') or [])
        if route.needs_clarification or route.intent==Intent.OUT_OF_SCOPE:return {'results':[], 'trace':trace}
        context=self._trusted_context(state)
        ordered=plan.tasks or tuple()
        task_map={task.name:task for task in ordered}
        finished={}

        def predecessor_names(name:str)->set[str]:
            seen=set();pending=list(task_map[name].depends_on)
            while pending:
                parent=pending.pop()
                if parent in seen:continue
                seen.add(parent)
                if parent in task_map:pending.extend(task_map[parent].depends_on)
            return seen
        for task in ordered:
            name=task.name
            if len(results)>=plan.max_calls:break
            failed=[dep for dep in task.depends_on if not self._dependency_ready(finished.get(dep,{})) and
                    not (name == 'search_graph' and self._graph_seed_rows(finished.get(dep, {})))]
            if failed:
                output={'results':[],'status':'dependency_unavailable'}
                results.append({'tool':name,'output':output})
                finished[name]=output
                trace.append({'step':'tool','name':name,'dependencies':list(task.depends_on),
                              'status':output['status'],'hits':0,'latency_ms':0.0})
                continue
            # Only propagate verified source evidence from completed prerequisites.
            # An explicit user slot overrides enrichment from those prerequisites.
            ancestors=predecessor_names(name)
            predecessors=[entry for entry in results if entry['tool'] in ancestors]
            tool_slots={**self._verified_slots(predecessors),**route.slots}
            context['retrieved_evidence_ids']=evidence_ids(results,verified_only=True)
            if name == 'search_graph':
                context['retrieved_evidence_ids'] = evidence_ids([
                    {'output': {'results': self._graph_seed_rows(entry.get('output') or {})}}
                    for entry in results])
            started=monotonic()
            try:
                output=self.tools.dispatch(name,query=state.get('effective_query',state['query']),
                                           slots=tool_slots,context=context,auth=state.get('auth'))
            except (RuntimeError,FileNotFoundError,TimeoutError,OSError) as exc:
                if isinstance(exc,RuntimeError) and ('Dense index not built' in str(exc) or
                    'qdrant-client is required' in str(exc) or 'sentence-transformers required' in str(exc)):
                    raise
                output={'results':[],'status':'tool_unavailable','error_type':type(exc).__name__}
            output=self._validate_output(output)
            results.append({'tool':name,'output':output})
            finished[name]=output
            trace.append({'step':'tool','name':name,'dependencies':list(task.depends_on),
                          'status':output.get('status','ok'),
                          'hits':len(output.get('results',[])),'latency_ms':round((monotonic()-started)*1000,2)})
        return {'results':results,'trace':trace}

    def recover(self,state:OcopState)->dict:
        route=Route.model_validate(state['route']);plan=state.get('plan') or build_plan(route)
        results=list(state.get('results') or []);trace=list(state.get('trace') or [])
        grade=state.get('evidence_grade') or grade_evidence(state.get('effective_query',state['query']),results,
                                        slots=route.slots,expected_tools=list(plan.names))
        if not self._should_recover(state,grade):return {'results':results,'trace':trace}
        context=self._trusted_context(state)
        started=monotonic()
        rewritten=bounded_rewrite(state.get('effective_query',state['query']),grade.get('missing_tools',[]),route.slots)
        try:
            payload=self.tools.dispatch('search_regulations',query=rewritten,
                                        slots=route.slots,context=context,auth=state.get('auth'))
        except (RuntimeError,FileNotFoundError,TimeoutError,OSError) as exc:
            if isinstance(exc,RuntimeError) and ('Dense index not built' in str(exc) or
                'qdrant-client is required' in str(exc) or 'sentence-transformers required' in str(exc)):
                raise
            payload={'results':[],'status':'tool_unavailable','error_type':type(exc).__name__}
        payload=self._validate_output(payload)
        results.append({'tool':'search_regulations','output':payload,'recovery':True})
        trace.append({'step':'recovery','name':'search_regulations','reason':'insufficient_or_irrelevant_evidence',
                      'status':payload.get('status','ok'),
                      'hits':len(payload.get('results',[])),'latency_ms':round((monotonic()-started)*1000,2)})
        return {'results':results,'trace':trace}

    def grade(self,state:OcopState)->dict:
        route=Route.model_validate(state['route'])
        plan=state.get('plan') or build_plan(route)
        result=grade_evidence(state.get('effective_query',state['query']),
                              state.get('results') or [],slots=route.slots,
                              expected_tools=list(plan.names))
        trace=list(state.get('trace') or [])
        trace.append({'step':'evidence_grade','status':result['status'],
                      'relevant_evidence':result['relevant_evidence_count'],
                      'missing_tools':result['missing_tools']})
        return {'evidence_grade':result,'trace':trace}

    def _should_recover(self,state:OcopState,grade:dict|None=None)->bool:
        route=Route.model_validate(state['route'])
        plan=state.get('plan') or build_plan(route)
        outputs=state.get('results') or []
        if not recovery_safe(route, outputs, plan):return False
        result=grade or state.get('evidence_grade') or grade_evidence(
            state.get('effective_query',state['query']),outputs,slots=route.slots,
            expected_tools=list(plan.names))
        return result['status'] in ('none','partial')

    def verify(self,state:OcopState)->dict:
        """Report tool/evidence coverage; never mistake citation presence for entailment.

        An empty structured result or an unknown temporal verdict remains
        visibly incomplete even if another tool found related text.
        """
        route=Route.model_validate(state['route'])
        outputs=state.get('results') or []
        if route.needs_clarification or route.intent==Intent.OUT_OF_SCOPE:
            return {'evidence_coverage':{'status':'not_applicable','tools':[]}}
        checks=[]
        for entry in outputs:
            output=entry.get('output') or {}
            rows=output.get('results',[])
            usable=bool(rows) and any(isinstance(row,dict) and row.get('source_id') and (
                row.get('source_spans') or row.get('spans')) for row in rows)
            # Temporal rules with 'unknown' are not considered verified source.
            if entry.get('tool')=='resolve_temporal_applicability':
                usable=output.get('status')=='checked_verified_rules' and bool(rows) and all(
                    isinstance(r,dict) and r.get('verdict',{}).get('status') in ('applicable','not_applicable') for r in rows)
            structured_names={'lookup_product_subgroup','lookup_criterion',
                              'lookup_evidence_requirements','lookup_form',
                              'lookup_recognition','resolve_temporal_applicability'}
            # This metric refers to *verified structured business outcomes*,
            # not successful text retrieval (or valid citation markers).
            business_resolved=usable and entry.get('tool') in structured_names and (
                not output.get('fallback') and
                ((output.get('status')=='checked_verified_rules' and usable) or
                 bool(rows) and all(isinstance(r,dict) and
                     r.get('review_status')=='verified' for r in rows)))
            checks.append({'name':entry.get('tool'),'has_source_evidence':usable,
                           'business_resolved':business_resolved,
                           'status':output.get('status','ok')})
        ok=sum(int(x['has_source_evidence']) for x in checks)
        if ok==0:status='none'
        elif ok==len(checks):status='complete'
        else:status='partial'
        grade=state.get('evidence_grade') or {}
        if grade.get('status') in ('none','partial') and status=='complete':status='partial'
        return {'evidence_coverage':{'status':status,'tools':checks,
                                    'source_coverage_ratio':round(ok/len(checks),3) if checks else 0,
                                    'grader_status':grade.get('status','not_run'),
                                    'missing_tools':grade.get('missing_tools',[]),
                                    'verified_business_resolution_ratio':round(
                                         sum(int(x['business_resolved']) for x in checks)/len(checks),3
                                    ) if checks else 0}}

    def answer(self,state:OcopState)->dict:
        route=Route.model_validate(state['route'])
        if route.needs_clarification:
            if 'tool_budget_exceeded' in route.reason_codes:
                return {'answer':{'answer':'Câu hỏi gồm nhiều phần tra cứu độc lập. '
                    'Vui lòng gửi từng câu riêng, chẳng hạn phân nhóm sản phẩm, tiêu chí '
                    'hoặc hồ sơ/minh chứng, để không bỏ sót nguồn cần đối chiếu.',
                    'status':'clarify','citations':[]}}
            return {'answer':{'answer':'Cần bổ sung thông tin để xử lý: '+', '.join(route.missing_slots),
                              'status':'clarify','citations':[]}}
        if route.intent==Intent.OUT_OF_SCOPE:
            return {'answer':{'answer':'Mình chỉ hỗ trợ tra cứu và rà soát kiến thức OCOP từ nguồn đã lập chỉ mục.',
                              'status':'out_of_scope','citations':[]}}
        outputs=state.get('results') or []
        if any((item.get('output') or {}).get('status')=='requested_pdf_page_not_indexed' for item in outputs):
            return {'answer':{'answer':'Trang PDF được yêu cầu chưa có trong corpus đã lập chỉ mục; '
                              'không dùng trang khác để suy ra nội dung trang này.',
                              'status':'insufficient_page_scope','citations':[]}}
        if any((item.get('output') or {}).get('status')=='sheet_scope_unavailable' for item in outputs):
            return {'answer':{'answer':'Tầng tra cứu chưa có cây phiếu đã kiểm tra khớp số phiếu và nguồn '
                              'được hỏi; không dùng phương án của phiếu khác.',
                              'status':'insufficient_sheet_scope','citations':[]}}
        if any(x.get('tool') in ('review_dossier','estimate_score') for x in outputs):
            outcome=outputs[0].get('output',{}) if outputs else {'status':'not_found'}
            # Never make empty candidate data into a passing dossier or score.
            private_status={
                'provisional_not_official':'provisional',
                'rules_not_verified':'insufficient_verified_rules',
                'not_ready':'insufficient_verified_rules',
                'not_found':'dossier_not_found',
                'tool_unavailable':'backend_unavailable',
            }.get(outcome.get('status'),'private_assessment_unavailable')
            return {'answer':{'answer':('Đánh giá sơ bộ (không phải phân hạng chính thức): '
                       if private_status=='provisional' else 'Không thể hoàn tất đánh giá hồ sơ: ')+
                       json.dumps(outcome,ensure_ascii=False),
                       'status':private_status,'citations':[]}}
        # A dated law/criteria comparison requires verified temporal rules,
        # not just PDFs with publication years in filenames. Text retrieval
        # may provide background, but never silently certify applicability.
        if 'resolve_temporal_applicability' in route.required_tools and not any(
            item.get('tool')=='resolve_temporal_applicability' and
            (item.get('output') or {}).get('status')=='checked_verified_rules' and
            (item.get('output') or {}).get('applicability_status')=='applicable'
            for item in outputs):
            return {'answer':{'answer':'Chưa đủ quy tắc hiệu lực/chuyển tiếp đã xác minh để '
                'đối chiếu chính xác các thời điểm hoặc năm được hỏi. '
                'Cần nguồn quy định và phạm vi thời gian được xác minh; '
                'không suy diễn từ năm ban hành văn bản.',
                'status':'insufficient_temporal_verification','citations':[]}}
        if any((item.get('output') or {}).get('status') in
               ('local_guidance_not_in_corpus','local_guidance_document_scope_mismatch')
               for item in outputs):
            return {'answer':{'answer':'Chưa có nguồn hướng dẫn hạn nộp hợp lệ '
                'cho địa phương và văn bản được hỏi. Không sử dụng văn bản quốc gia '
                'hoặc nguồn của địa phương khác để suy ra hạn nộp.',
                'status':'insufficient_local_guidance_scope','citations':[]}}
        if any((item.get('output') or {}).get('status') in
               ('incomplete_form_ids','form_source_scope_unverified','form_version_ambiguous')
               for item in outputs):
            missing=sorted({str(form) for item in outputs for form in
                ((item.get('output') or {}).get('missing_form_ids') or [])},key=int)
            return {'answer':{'answer':'Chưa có đầy đủ biểu mẫu đã xác minh để đối chiếu. '
                'Các mẫu còn thiếu hoặc chưa xác minh: '+(', '.join(missing) if missing
                else 'chưa xác định được phiên bản văn bản chung cho các mẫu'),
                'status':'insufficient_form_scope','citations':[]}}
        if any((item.get('output') or {}).get('status')=='recognition_scope_unverified'
               for item in outputs):
            return {'answer':{'answer':'Chưa có bản ghi công nhận đã xác minh khớp đầy đủ '
                'địa phương và mức sao được yêu cầu; không suy đoán từ văn bản hoặc OCR.',
                'status':'insufficient_recognition_scope','citations':[]}}
        if any((item.get('output') or {}).get('status') in
               ('recognition_year_scope_unverified','assessment_year_scope_unverified')
               for item in outputs):
            return {'answer':{'answer':'Chưa có bản ghi đã xác minh đúng năm sự kiện/đánh giá '
                'hoặc đúng phiên bản tài liệu để trả lời an toàn. '
                'Năm ban hành quyết định không thể tự coi là năm công nhận hay năm đánh giá.',
                'status':'insufficient_year_scope','citations':[]}}
        response=assemble(state.get('effective_query',state['query']),outputs,llm=self.llm)
        coverage=state.get('evidence_coverage') or {}
        if coverage.get('status')=='partial':
            missing=list(dict.fromkeys([x['name'] for x in coverage.get('tools',[]) if not x['has_source_evidence']]+coverage.get('missing_tools',[])))
            response['answer']='[CHƯA ĐỦ CHỨNG CỨ CHO TOÀN BỘ YÊU CẦU: '+', '.join(missing)+']\n'+response['answer']
            if response['status'] in ('generated_claims_verified','generated_unverified_claims'):
                response['status']='partial_evidence'
        return {'answer':response}

    def graph(self,*,checkpointer=None):
        try:from langgraph.graph import StateGraph,START,END
        except ImportError as exc:raise RuntimeError('langgraph not installed; install project dependencies or use fallback mode') from exc
        graph=StateGraph(OcopState)
        graph.add_node('route',self.route)
        graph.add_node('plan',self.plan)
        graph.add_node('execute',self.execute)
        graph.add_node('recover',self.recover)
        graph.add_node('grade',self.grade)
        graph.add_node('grade_after_recovery',self.grade)
        graph.add_node('verify',self.verify)
        graph.add_node('answer',self.answer)
        graph.add_edge(START,'route')
        graph.add_conditional_edges('route',lambda s:'answer' if s['route'].get('needs_clarification') or
            s['route']['intent']==Intent.OUT_OF_SCOPE.value else 'plan',{'answer':'answer','plan':'plan'})
        graph.add_edge('plan','execute')
        graph.add_edge('execute','grade')
        graph.add_conditional_edges('grade',lambda s:'recover' if self._should_recover(s) else 'verify',
                                    {'recover':'recover','verify':'verify'})
        graph.add_edge('recover','grade_after_recovery')
        graph.add_edge('grade_after_recovery','verify')
        graph.add_edge('verify','answer')
        graph.add_edge('answer',END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _checkpoint_public_input(initial:OcopState)->OcopState:
        """Minimize plaintext checkpoint state; no credentials/auth payloads.

        Query text itself is still saved by opt-in LangGraph checkpointing.
        Deployment owners must choose a private protected checkpoint volume.
        """
        original=initial.get('session') or {}
        safe_session={k:original[k] for k in ('session_id','last_query','intent','capabilities')
                      if k in original and isinstance(original[k],str) and len(original[k])<=4096}
        if isinstance(original.get('slots'),dict):
            safe_session['slots']=_merge_followup({'slots':original['slots']},{})
        if isinstance(original.get('capabilities'),list):
            from ai_core.orchestration.ocop.capabilities import Capability
            allowed={item.value for item in Capability}
            safe_session['capabilities']=[item for item in original['capabilities'][:24]
                  if isinstance(item,str) and item in allowed]
        provided=initial.get('context') or {}
        safe_context={}
        if isinstance(provided.get('as_of_date'),str) and re.fullmatch(
            r'20\d{2}-\d{2}-\d{2}',provided['as_of_date']):
            safe_context['as_of_date']=provided['as_of_date']
        return {**initial,'session':safe_session,'context':safe_context,'auth':None,
                'debug_candidates':False}

    @traced("ocop.agent.ask")
    def ask(self,query:str,*,session:dict|None=None,context:dict|None=None,
            auth_context:AuthContext|None=None,debug_candidates:bool=False,
            require_langgraph:bool=False)->AgentResponse:
        for folder in (self.tools.index_dir, getattr(self.tools,'graph_dir',self.root/'data/processed/ocop/graph')):
            manifest_file=folder/'manifest.json'
            if manifest_file.is_file():
                manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
                partial=(manifest.get('source_complete') is False or
                         str(manifest.get('status', '')).startswith('partial_'))
                if partial and not self.allow_partial_debug:
                    raise RuntimeError('partial corpus requires explicit allow_partial_debug=True')
        initial:OcopState={'query':query,'session':session or {},'context':context or {},
                           'auth':auth_context,'debug_candidates':debug_candidates}
        engine='langgraph'
        checkpointer=None;invoke_config=None
        # Private dossier state must not be recorded in plaintext LangGraph
        # snapshots. Public workflow checkpointing is explicit opt-in.
        private_requested=bool({'review_dossier','estimate_score'} & set(
            route_query(query,session=session or {}).required_tools))
        if should_checkpoint(env=os.environ,auth=auth_context,session=session or {},
                             private_tools={'private'} if private_requested else set()):
            if self._checkpoint is None:
                location=os.environ.get('OCOP_LANGGRAPH_CHECKPOINT_PATH')
                if not location:raise RuntimeError('Set OCOP_LANGGRAPH_CHECKPOINT_PATH to a private writable location')
                self._checkpoint=SQLiteCheckpoint(Path(location))
            key=thread_key(auth_context.tenant_id,auth_context.principal_id,session['session_id'])
            checkpointer=self._checkpoint.saver
            invoke_config={'configurable':{'thread_id':key}}
            initial=self._checkpoint_public_input(initial)
        try:
            compiled=self.graph(checkpointer=checkpointer)
            final=compiled.invoke(initial,config=invoke_config) if invoke_config else compiled.invoke(initial)
        except RuntimeError as exc:
            if require_langgraph or 'langgraph not installed' not in str(exc):raise
            engine='deterministic_fallback'
            final=dict(initial);final.update(self.route(final))
            if not final['route'].get('needs_clarification') and final['route']['intent']!=Intent.OUT_OF_SCOPE.value:
                final.update(self.plan(final));final.update(self.execute(final));final.update(self.grade(final))
                if self._should_recover(final):
                    final.update(self.recover(final));final.update(self.grade(final))
            final.update(self.verify(final))
            final.update(self.answer(final))
        route=Route.model_validate(final['route']);payload=final['answer']
        if self.allow_partial_debug:
            payload={**payload, 'answer':'[partial_debug_corpus]\n'+payload['answer'],
                     'status':'partial_debug_corpus',
                     'claim_verification':{**payload.get('claim_verification',{}),
                         'answer_status':payload['status'], 'corpus_status':'partial_debug_corpus'}}
        return AgentResponse(answer=payload['answer'],intent=route.intent,status=payload['status'],
            citations=payload['citations'],tools_used=[r['tool'] for r in final.get('results',[])],
            workflow_engine=engine,route=route,corpus_version=self._corpus_version(),
            tool_trace=final.get('trace',[]),evidence_coverage=final.get('evidence_coverage',{}),
            evidence_grade=final.get('evidence_grade',{}),
            claim_verification=payload.get('claim_verification',{}))

    def _corpus_version(self):
        path=self.tools.index_dir/'manifest.json'
        if not path.exists():return None
        return json.loads(path.read_text(encoding='utf-8')).get('corpus_version')
