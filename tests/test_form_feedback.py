"""Form regressions: examples stay out of output, and dynamic edits retain identity."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from streamlit.testing.v1 import AppTest

from src.form_examples import CERTIFICATIONS, PLAN_PLACEHOLDERS
from src.form_ui import join_phone, split_phone
from src.models import COUNTRIES, TRADEMARK_STATUSES, apply_form_defaults, empty_data


HARNESS = '''
import streamlit as st
from src.form_ui import render_fields
from src.models import empty_data
if 'data' not in st.session_state:
    st.session_state.data = empty_data()
    st.session_state.revision = 0
edited, structural_change = render_fields(st.session_state.data, st.session_state.revision)
st.session_state.data = edited
if structural_change:
    st.session_state.revision += 1
    st.rerun()
'''


def new_form(data=None):
    app = AppTest.from_string(HARNESS, default_timeout=30)
    if data is not None:
        app.session_state['data'] = data
        app.session_state['revision'] = 0
    return app.run()


def test_form_examples_never_become_customer_values():
    app = new_form()
    assert not app.exception
    data = app.session_state['data']
    assert all(not value for value in data['company'].values())
    assert all(not value for value in data['contact'].values())
    assert not data['products'][0]['brandKo']
    assert not data['products'][0]['countries']
    assert data['plan']['channels'] == [] and data['plan']['ipHistory'] == ''
    assert all(data['plan'][key] == '' for key in PLAN_PLACEHOLDERS)
    assert '(예시)' not in json.dumps(data, ensure_ascii=False)
    assert '10%' not in json.dumps(data, ensure_ascii=False)
    for item in app.text_area:
        assert item.value == '' and item.placeholder.startswith('(예시)')
    assert app.text_input(key='edit_0_product0_brandKo').placeholder == '(예시) 삼성 갤럭시 S24'
    assert app.selectbox(key='edit_0_application_projectType').options == ['라벨 (권장)', '맞춤제작']
    assert not any('희망' in item.label or '수행업체' in item.label for item in app.text_input)
    assert data['provider'] == {'name': '이노프렌즈', 'contact': '', 'phone': ''}


def test_defaults_preserve_input_and_use_korea_date_without_inventing_contacts():
    data = empty_data()
    data['applicationDate'] = ''
    data['projectType'] = '맞춤제작'
    data['provider'].update(name='예전 업체', contact='확인된 담당자')
    data['products'][0]['countries'] = [
        {'country': '인도', 'quantity': '', 'method': '', 'trademarkStatus': '등록중'},
        {'country': '미국', 'quantity': '확정 12만장', 'method': '맞춤제작'},
    ]
    original = copy.deepcopy(data)
    result = apply_form_defaults(data)
    assert data == original
    assert result['applicationDate'] == datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    assert result['projectType'] == '맞춤제작'
    assert result['provider'] == {'name': '이노프렌즈', 'contact': '확인된 담당자', 'phone': ''}
    assert result['products'][0]['countries'][0]['quantity'] == '100만장'
    assert result['products'][0]['countries'][0]['trademarkStatus'] == '등록중'
    assert result['products'][0]['countries'][1]['quantity'] == '확정 12만장'
    assert result['products'][0]['countries'][1]['method'] == '맞춤제작'
    result['company']['nameKo'] = '독립 사본'
    assert data['company']['nameKo'] == ''


@pytest.mark.parametrize('value,expected', [
    ('', ('010', '', '')),
    ('01012345678', ('010', '1234', '5678')),
    ('010-1234-5678', ('010', '1234', '5678')),
    ('0212345678', ('02', '1234', '5678')),
    ('02-123-4567', ('02', '123', '4567')),
    ('050512345678', ('0505', '1234', '5678')),
])
def test_phone_parts_preserve_digits(value, expected):
    assert split_phone(value) == expected
    assert join_phone(*expected).replace('-', '') == value.replace('-', '')


def test_phone_edits_survive_reruns_and_do_not_submit_default_prefix_alone():
    app = new_form()
    assert app.session_state['data']['contact']['phone'] == ''
    app.text_input(key='edit_0_contact_phone_middle').set_value('2468')
    app.text_input(key='edit_0_contact_phone_last').set_value('1357').run()
    assert app.session_state['data']['contact']['phone'] == '010-2468-1357'
    app.selectbox(key='edit_0_contact_phone_prefix').set_value('02').run()
    app.text_input(key='edit_0_company_nameKo').set_value('입력한 회사').run()
    assert app.session_state['data']['contact']['phone'] == '02-2468-1357'


def test_country_status_and_custom_certifications_survive_product_removal():
    data = empty_data()
    data['products'][0]['certifications'] = '사용자가 받은 별도 인증'
    data['products'][0]['countries'] = [
        {'country': '일본', 'quantity': '100만장', 'method': '라벨', 'trademarkStatus': '출원예정'},
        {'country': '미국', 'quantity': '10만장', 'method': '맞춤제작', 'trademarkStatus': '등록중'},
    ]
    app = new_form(data)
    assert not app.exception
    countries = app.multiselect(key='edit_0_product0_countries')
    assert countries.options == sorted(COUNTRIES)
    assert app.multiselect(key='edit_0_product0_certifications').options == CERTIFICATIONS + ['사용자가 받은 별도 인증']
    for select in [item for item in app.selectbox if item.label in ('상표 현황', '브랜드 상표 현황')]:
        assert select.options == ['선택'] + TRADEMARK_STATUSES
    countries.set_value(['미국']).run()
    row = app.session_state['data']['products'][0]['countries'][0]
    assert row['country'] == '미국' and row['quantity'] == '10만장' and row['trademarkStatus'] == '등록중'
    next(item for item in app.button if item.label == '상품 추가').click().run()
    revision = app.session_state['revision']
    app.text_input(key=f'edit_{revision}_product1_brandKo').set_value('두 번째 브랜드').run()
    app.button(key='remove_product_0').click().run()
    assert not app.exception
    assert len(app.session_state['data']['products']) == 1
    assert app.session_state['data']['products'][0]['brandKo'] == '두 번째 브랜드'


def test_new_country_defaults_and_multi_channels_are_independent():
    app = new_form()
    app.multiselect(key='edit_0_product0_countries').set_value(['인도', '미국']).run()
    assert not app.exception
    rows = app.session_state['data']['products'][0]['countries']
    assert all(row['quantity'] == '100만장' and row['method'] == '라벨' for row in rows)
    app.multiselect(key='edit_0_plan_channels').set_value(['제품', '포장', '홈페이지/SNS']).run()
    assert app.session_state['data']['plan']['channels'] == ['제품', '포장', '홈페이지/SNS']


def test_cleared_date_stays_empty_until_validation_on_regular_reruns():
    app = new_form()
    app.date_input(key='edit_0_application_date').set_value(None).run()
    assert not app.exception
    assert app.session_state['data']['applicationDate'] == ''
    app.text_input(key='edit_0_company_nameKo').set_value('날짜 확인 회사').run()
    assert not app.exception
    assert app.date_input(key='edit_0_application_date').value is None
    assert app.session_state['data']['applicationDate'] == ''
