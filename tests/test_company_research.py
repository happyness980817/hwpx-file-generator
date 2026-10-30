import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agent import compose_from_materials, merge_draft
from src.company_research import ResearchResult, apply_research, research_company
from src.draft_schema import AgentDraft
from src.errors import DocumentError
from src.models import PLAN_FIELDS, empty_country, empty_data, sample_data


SOURCE = 'https://official.example/company'


def research_result(**overrides):
    values = {
        'identity_status': 'confirmed', 'company_name': '테스트기업', 'company_source_url': SOURCE,
        'facts': [
            {'path': 'company.nameKo', 'value': '테스트기업', 'source_url': SOURCE, 'evidence': '상호: 테스트기업'},
            {'path': 'products.0.brandKo', 'value': '테스트브랜드', 'source_url': SOURCE, 'evidence': '테스트기업의 테스트브랜드'},
        ],
        'plan': {key: '' for key in PLAN_FIELDS}, 'questions': [],
    }
    values.update(overrides)
    return ResearchResult.model_validate(values)


def web_response(parsed, *, searched=True, status='completed'):
    return SimpleNamespace(status=status, output_parsed=parsed, output=[
        SimpleNamespace(type='web_search_call', status='completed' if searched else 'failed',
                        action=SimpleNamespace(sources=[SimpleNamespace(url=SOURCE)]))])


def test_research_fills_brand_and_company_but_preserves_user_choices_and_existing_values():
    data = empty_data()
    data['company']['address'] = '사용자 주소'
    data['contact'].update(name='사용자', phone='010-1111-2222', email='private@example.com')
    data['products'][0]['countries'] = [empty_country('인도')]
    data['plan'].update(marketing='직접 쓴 문구', channels=['포장'])
    before = copy.deepcopy(data)
    result = research_result()
    result.plan.marketing = '이 문구로 덮어쓰면 안 됩니다.'
    result.plan.expectedEffects = '제품의 신뢰도 향상을 기대합니다.'
    result.plan.countries = '미국'
    result.facts += [
        type(result.facts[0])(path='company.address', value='검색 주소', source_url=SOURCE, evidence='주소'),
        type(result.facts[0])(path='contact.phone', value='02-111-2222', source_url=SOURCE, evidence='고객센터'),
        type(result.facts[0])(path='products.0.trademarks', value='등록완료', source_url=SOURCE, evidence='주장'),
    ]
    merged = apply_research(data, result, [SOURCE])
    assert merged['data']['company']['nameKo'] == '테스트기업'
    assert merged['data']['products'][0]['brandKo'] == '테스트브랜드'
    assert merged['data']['company']['address'] == '사용자 주소'
    assert merged['data']['contact'] == data['contact']
    assert merged['data']['products'][0]['trademarks'] == ''
    assert merged['data']['products'][0]['countries'] == data['products'][0]['countries']
    assert merged['data']['plan']['marketing'] == '직접 쓴 문구'
    assert merged['data']['plan']['countries'] == '인도'
    assert merged['data']['plan']['channels'] == ['포장']
    assert merged['data']['plan']['expectedEffects']
    assert data == before


@pytest.mark.parametrize('status', ['ambiguous', 'not_found'])
def test_ambiguous_company_keeps_entire_form_unchanged(status):
    data = empty_data()
    result = research_result(identity_status=status)
    result.plan.marketing = '추측 초안'
    merged = apply_research(data, result, [SOURCE])
    assert merged['data'] == data and merged['questions']


def test_unobserved_company_source_cannot_authorize_facts_or_plans():
    data = empty_data()
    result = research_result(company_source_url='https://invented.example')
    result.plan.marketing = '추측 초안'
    assert apply_research(data, result, [SOURCE])['data'] == data


def test_fact_requires_exact_observed_url_and_business_number_shape():
    result = research_result()
    fact_type = type(result.facts[0])
    result.facts += [
        fact_type(path='company.representative', value='이름', source_url=SOURCE + '/invented', evidence='대표'),
        fact_type(path='company.registrationNumber', value='123', source_url=SOURCE, evidence='번호'),
        fact_type(path='company.category', value='큰 회사', source_url=SOURCE, evidence='규모'),
    ]
    merged = apply_research(empty_data(), result, [SOURCE])['data']
    assert merged['company']['nameKo'] == '테스트기업'
    assert merged['company']['representative'] == ''
    assert merged['company']['registrationNumber'] == ''
    assert merged['company']['category'] == ''


@pytest.mark.parametrize('field,value', [('company', '다른회사'), ('brand', '다른브랜드')])
def test_conflicting_company_or_product_identity_does_not_mix_company_information(field, value):
    data = empty_data()
    if field == 'company':
        data['company']['nameKo'] = value
    else:
        data['products'][0]['brandKo'] = value
    result = research_result()
    result.plan.marketing = '다른 회사 초안'
    actual = apply_research(data, result, [SOURCE])
    assert actual['data'] == data and actual['questions']


def test_research_api_requires_search_and_never_sends_contacts_or_attached_content():
    data = empty_data()
    data['contact'].update(name='비공개담당자', phone='010-1234-5678', email='private@example.com')
    data['company']['registrationNumber'] = '123-45-67890'
    data['plan']['marketing'] = '사내 비공개 목표'
    with patch('src.company_research.settings', return_value={'OPENAI_API_KEY': 'test-secret', 'OPENAI_MODEL': 'configured-model'}), \
         patch('src.company_research.ai_ready', return_value=True), patch('src.company_research.OpenAI') as client:
        api = client.return_value.__enter__.return_value.responses.parse
        api.return_value = web_response(research_result())
        result = research_company('테스트기업', data, materials=[object()])
        assert result['data']['products'][0]['brandKo'] == '테스트브랜드'
        sent = api.call_args.kwargs
        assert sent['tool_choice'] == 'required' and sent['max_tool_calls'] == 4
        assert sent['include'] == ['web_search_call.action.sources']
        assert sent['store'] is False
        for secret in ('test-secret', '비공개담당자', '010-1234-5678', 'private@example.com', '123-45-67890', '사내 비공개 목표'):
            assert secret not in sent['input']
        api.return_value = web_response(research_result(), searched=False)
        with pytest.raises(DocumentError, match='웹검색'):
            research_company('테스트기업', data)


@pytest.mark.parametrize('query', ['', 'name@example.com', '010-1234-5678', 'https://example.com', 'a\nb', '가' * 121])
def test_non_name_search_input_rejected_before_api(query):
    with patch('src.company_research.OpenAI') as client, pytest.raises(DocumentError):
        research_company(query, empty_data())
    client.assert_not_called()


def test_general_draft_merges_only_requested_existing_fields_and_does_not_change_destinations():
    current = sample_data()
    current['plan']['marketing'] = '기존 마케팅'
    proposed = copy.deepcopy(current)
    proposed['company']['nameKo'] = '다른 회사'
    proposed['contact']['name'] = '다른 사람'
    proposed['plan'].update(marketing='간결한 수정', expectedEffects='정성적 기대효과')
    proposed['products'][0]['countries'] = [empty_country('미국')]
    merged = merge_draft(current, proposed, ['plan.marketing'])
    assert merged['company'] == current['company']
    assert merged['contact'] == current['contact']
    assert merged['plan']['marketing'] == '간결한 수정'
    assert merged['plan']['expectedEffects'] == '정성적 기대효과'
    assert merged['products'][0]['countries'][0]['country'] == '일본'


def test_requested_product_rename_allowed_without_clobbering_other_product_fields():
    current = sample_data()
    proposed = copy.deepcopy(current)
    proposed['products'][0]['nameKo'] = '변경된 상품명'
    proposed['products'][0]['brandKo'] = '무관한 브랜드'
    result = merge_draft(current, proposed, ['products.0.nameKo'])
    # A conflicting brand identity prevents a different product being inserted.
    assert result['products'][0]['brandKo'] == current['products'][0]['brandKo']
    proposed['products'][0]['brandKo'] = current['products'][0]['brandKo']
    result = merge_draft(current, proposed, ['products.0.nameKo'])
    assert result['products'][0]['nameKo'] == '변경된 상품명'


def test_reordered_products_do_not_move_facts_to_other_products():
    data = sample_data()
    second = copy.deepcopy(data['products'][0])
    second.update(nameKo='다른 상품', category='다른 분류')
    data['products'].append(second)
    proposed = copy.deepcopy(data)
    proposed['products'].reverse()
    result = merge_draft(data, proposed)
    assert [p['nameKo'] for p in result['products']] == [p['nameKo'] for p in data['products']]


def test_compose_uses_edited_fields_only_when_explicit_edit_mode_enabled():
    current = sample_data()
    current['plan']['marketing'] = '기존 문장'
    output = copy.deepcopy(current)
    output['plan']['marketing'] = '수정한 문장'
    draft = AgentDraft(data=output, summary='수정', source_notes='', questions=[], edited_fields=['plan.marketing'])
    with patch('src.agent.settings', return_value={'OPENAI_API_KEY': 'test', 'OPENAI_MODEL': 'configured-model'}), \
         patch('src.agent.ai_ready', return_value=True), patch('src.agent.OpenAI') as client:
        api = client.return_value.__enter__.return_value.responses.parse
        api.return_value = SimpleNamespace(status='completed', output_parsed=draft)
        protected = compose_from_materials(current, [], '문장을 수정해 주세요')
        assert protected['data']['plan']['marketing'] == '기존 문장'
        edited = compose_from_materials(current, [], '문장을 수정해 주세요', allow_edits=True)
        assert edited['data']['plan']['marketing'] == '수정한 문장'
        assert json.loads(api.call_args.kwargs['input'][0]['content'][0]['text'])['allow_requested_edits'] is True
