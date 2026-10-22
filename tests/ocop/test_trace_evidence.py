import importlib.util
from pathlib import Path

from ai_core.system import stage_trace

SPEC = importlib.util.spec_from_file_location('trace_evidence', Path(__file__).parents[2] / 'tools' / 'trace_evidence.py')
tracer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracer)


def test_emit_is_a_no_op_outside_tracing_and_collects_inside():
    stage_trace.emit('x', a=1)
    assert not stage_trace.active()
    with stage_trace.tracing() as events:
        stage_trace.emit('search.fused', items=[])
        assert stage_trace.active()
    assert events == [{'stage': 'search.fused', 'items': []}]
    assert not stage_trace.active()


def test_gold_needs_every_phrase_on_a_gold_page():
    gold = tracer.Gold([3], ['15/10/2026', 'Thành Sen'])
    assert gold.has([{'pdf_page': 3, 'text': 'hồ sơ trước ngày 15/10/2026 UBND phường THÀNH SEN'}])['content_hit']
    assert not gold.has([{'pdf_page': 3, 'text': 'trước ngày 15/10/2026'}])['content_hit']
    assert not gold.has([{'pdf_page': 4, 'text': '15/10/2026 Thành Sen'}])['content_hit']


def test_diagnosis_names_the_first_stage_that_lost_the_gold():
    hit, miss = {'content_hit': True}, {'content_hit': False}
    stages = {'evidence_unit': hit, 'chunk': hit, 'pool': hit, 'fused': hit, 'returned': hit, 'tool_output': hit,
              'ctx_candidates': hit, 'ctx_packed': miss, 'prompt': miss}
    assert tracer.diagnose(stages)['lost_at'] == 'ctx_packed'
    assert tracer.diagnose({**stages, 'ctx_packed': hit, 'ctx_budgeted': hit, 'prompt': hit})['lost_at'] is None
    assert tracer.diagnose({'evidence_unit': miss, 'chunk': miss})['lost_at'] == 'evidence_unit'
    assert tracer.diagnose({'evidence_unit': hit, 'chunk': miss})['lost_at'] == 'chunk'
    assert tracer.diagnose({'evidence_unit': hit, 'chunk': hit, 'pool': miss})['lost_at'] == 'pool'


def test_source_part_splits_prompt_blocks_by_page():
    prompt = 'CÂU HỎI: q\nSOURCE:\n[S1] A, PDF p.3, review=needs_review: x\ny\n[S2] A, PDF p.7, review=needs_review: z'
    assert [b['pdf_page'] for b in tracer.source_part(prompt)] == [3, 7]
