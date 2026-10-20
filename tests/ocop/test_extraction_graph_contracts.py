"""Regression cases at extraction/graph boundaries; synthetic, offline evidence only."""
import json

import pytest

from ai_core.knowledge.ocop.llm_proposals import propose, reconcile
from ai_core.graph.ocop.retriever import traverse


def unit(text, uid='unit:test'):
    return {'source_id': 'SOURCE.TEST', 'unit_id': uid, 'unit_kind': 'paragraph',
            'text': text, 'structured': {}, 'spans': [
                {'pdf_page': 1, 'bbox': [0, 0, 200, 100], 'source_sha256': 'a' * 64}]}


class Client:
    model = 'offline'

    def __init__(self, response):
        self.response = response

    def chat(self, system, user, **kwargs):
        return json.dumps(self.response(user) if callable(self.response) else self.response)


def test_chunk_cannot_ground_a_name_only_present_outside_its_input(monkeypatch):
    from ai_core.knowledge.ocop import llm_proposals as mod
    monkeypatch.setattr(mod, 'CHUNK_CHARS', 80)
    monkeypatch.setattr(mod, 'CHUNK_OVERLAP', 10)
    text = 'START ' + 'x ' * 100 + 'HTX Cuối Nguồn'
    client = Client(lambda prompt: {'entities': [
        {'kind': 'Organization', 'anchor': 'HTX Cuối Nguồn'}]} if prompt.startswith('START') else {})
    result = propose([unit(text)], client)
    assert result['entities'] == []
    assert result['grounding']['dropped_entities'] == 1


@pytest.mark.parametrize('response', [{'entities': {}}, {'relations': 'bad'}, {'rules': 7}])
def test_invalid_response_collection_is_a_recorded_failure(response):
    result = propose([unit('HTX Hoa Sen')], Client(response))
    assert result['processed_unit_count'] == 0
    assert result['errors'][0]['error_type'] == 'ValueError'


def test_attribute_has_its_own_value_and_context_provenance():
    result = propose([unit('Sản phẩm: Mật ong, đóng chai thủy tinh')], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong', 'attributes': {'packaging': 'chai thủy tinh'}}]}))
    entity = result['entities'][0]
    claim = entity['attribute_claims'][0]
    assert claim['attribute'] == 'packaging_candidate'
    assert claim['value'] == 'chai thủy tinh'
    assert claim['status'] == 'candidate'
    assert 'Mật ong' in claim['evidence'][0]['quote']
    assert 'chai thủy tinh' in claim['evidence'][0]['quote']
    assert claim['evidence'][0]['source_sha256'] == 'a' * 64


def test_conflicting_attribute_values_remain_inspectable():
    result = propose([unit('Phiếu kiểm nghiệm do Sở cấp', 'unit:a'),
                      unit('Phiếu kiểm nghiệm do Bộ cấp', 'unit:b')],
                     Client(lambda prompt: {'entities': [{'kind': 'EvidenceType',
                         'anchor': 'Phiếu kiểm nghiệm',
                         'attributes': {'issuer': 'Sở' if 'Sở' in prompt else 'Bộ'}}]}))
    entity = result['entities'][0]
    assert entity['attributes']['issuer_candidate'] is None
    assert {c['value'] for c in entity['attribute_claims']} == {'Sở', 'Bộ'}


def test_llm_enrichment_does_not_inherit_verified_entity_status():
    result = propose([unit('Mật ong đóng chai thủy tinh')], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong', 'attributes': {'packaging': 'chai thủy tinh'}}]}))
    target = {**result['entities'][0], 'entity_id': 'det:product', 'attributes': {},
              'attribute_claims': [], 'status': 'verified'}
    reconcile(result, [target], [])
    assert target['status'] == 'candidate'
    assert target['attribute_claims'][0]['value'] == 'chai thủy tinh'


def test_reconcile_rekeys_and_deduplicates_relations_after_endpoint_linking():
    text = 'Mật ong do HTX Hoa Sen sản xuất'
    result = propose([unit(text)], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong'}, {'kind': 'Organization', 'anchor': 'HTX Hoa Sen'}],
        'relations': [{'type': 'OWNED_BY', 'source': 0, 'target': 1}]}))
    result['relations'].append({**result['relations'][0], 'relation_id': 'another:id'})
    deterministic = [{**e, 'entity_id': 'det:' + e['kind']} for e in result['entities']]
    old_id = result['relations'][0]['relation_id']
    out = reconcile(result, deterministic, [])
    assert len(out['relations']) == 1
    assert out['relations'][0]['relation_id'] != old_id
    assert out['relations'][0]['source_entity_id'] == 'det:Product'


def test_traversal_excludes_rejected_assertions_and_caps_initial_seeds(tmp_path):
    nodes = [{'node_id': str(i), 'node_type': 'Product', 'review_status': status, 'check': 'failed' if status == 'rejected' else 'passed'}
             for i, status in enumerate(['needs_review', 'rejected', 'needs_review'])]
    (tmp_path / 'nodes.jsonl').write_text(''.join(json.dumps(n) + '\n' for n in nodes))
    (tmp_path / 'edges.jsonl').write_text('')
    result = traverse(tmp_path, ['1', '0', '2'], hops=0, limit=1)
    assert [n['node_id'] for n in result['nodes']] == ['0']


def test_names_alone_do_not_merge_products_or_businesses_across_units():
    result = propose([unit('Mật ong do HTX Hoa Sen sản xuất', 'unit:a'),
                      unit('Mật ong do HTX Hoa Sen sản xuất', 'unit:b')], Client({'entities': [
        {'kind': 'Product', 'anchor': 'Mật ong'}, {'kind': 'Organization', 'anchor': 'HTX Hoa Sen'}]}))
    assert len(result['entities']) == 4


def test_ollama_schema_disables_thinking_and_preserves_schema(monkeypatch):
    import io
    from ai_core.orchestration.ocop import llm
    from ai_core.knowledge.ocop.llm_proposals import response_schema
    seen = {}
    def post(request, timeout):
        seen.update(json.loads(request.data))
        return io.BytesIO(b'{"message":{"content":"{}"},"done_reason":"stop"}')
    monkeypatch.setattr(llm.urllib.request, 'urlopen', post)
    llm.OllamaClient().chat_structured('s', 'u', schema=response_schema())
    assert seen['format'] == response_schema()
    assert seen['think'] is False


def test_truncated_provider_output_is_not_treated_as_a_complete_extraction(monkeypatch):
    import io
    from ai_core.orchestration.ocop import llm
    monkeypatch.setattr(llm.urllib.request, 'urlopen', lambda *args, **kwargs:
        io.BytesIO(b'{"message":{"content":"{}"},"done_reason":"length"}'))
    with pytest.raises(RuntimeError, match='truncated'):
        llm.OllamaClient().chat_structured('s', 'u', schema={})


def test_compact_schema_attributes_and_malformed_relation_are_checked():
    output = propose([unit('Sản phẩm: Mật ong đóng chai thủy tinh')], Client({'entities': [
        {'kind':'Product','anchor':'Mật ong','attributes':[{'key':'packaging','value':'chai thủy tinh'}]}],
        'relations':[{'type':['OWNED_BY'],'source':0,'target':0}]}))
    assert output['entities'][0]['attributes']['packaging_candidate'] == 'chai thủy tinh'
    assert output['grounding']['dropped_relations'] == 1


def test_reconcile_does_not_link_a_same_name_on_another_unit_of_the_same_page():
    payload = {'entities':[{'kind':'Product','anchor':'Mật ong'}]}
    first = propose([unit('Sản phẩm: Mật ong', 'unit:a')], Client(payload))
    second = propose([unit('Sản phẩm: Mật ong', 'unit:b')], Client(payload))
    result = reconcile(second, first['entities'], [])
    assert len(result['entities']) == 1 and result['reconciled']['merged_entities'] == 0
