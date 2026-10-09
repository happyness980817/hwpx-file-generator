from __future__ import annotations

import copy
import time

import streamlit as st

from src.ai import ai_ready
from src.agent import compose_from_materials
from src.details_ui import render_details
from src.errors import DocumentError
from src.guest_work import load_work, save_work, storage_ready
from src.materials import EXTENSIONS, prepare_materials
from src.models import PLAN_FIELDS, empty_data, example_plan, fingerprint, sample_data
from src.service import generate_documents

st.set_page_config(page_title='K-브랜드 신청서 도우미', page_icon='📄',
                   layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1180px; padding:2.5rem 2rem 4rem;}
h1 {font-size:2.3rem!important;letter-spacing:-.06em;line-height:1.2!important;margin:0!important;padding:.2rem 0!important;}
h2,h3 {letter-spacing:-.035em;}
[data-testid="stAppViewContainer"] {background:#f7f8f4;}
[data-testid="stHeader"] {background:rgba(247,248,244,.92);}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius:18px!important;}
[data-testid="stFileUploader"] section {background:#f0f4ed;border:1.5px dashed #a5b8a5;border-radius:12px;}
div.stButton>button,div.stDownloadButton>button {border-radius:10px;min-height:42px;}
.eyebrow {font-size:12px;letter-spacing:.18em;color:#46705a;font-weight:700;margin-bottom:0;}
.lead {font-size:15px;color:#637263;line-height:1.6;margin:0;}
.flow {display:flex;gap:24px;color:#69786c;font-size:13px;margin:8px 0;flex-wrap:wrap;}
.flow b {display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:#e4ebdf;color:#315342;margin-right:7px;}
.empty-preview {padding:32px 18px;text-align:center;background:#f4f5f0;border-radius:14px;color:#73806e;line-height:1.8;}
.paper {width:72px;height:90px;background:white;border:1px solid #dce3d7;border-radius:6px;box-shadow:8px 8px 0 #e4e9df;margin:0 auto 22px;padding:18px 12px;}
.paper hr {border:0;height:2px;background:#dce5d9;margin:9px 0;}
@media(max-width:640px){.block-container{padding:3.5rem 1rem;}h1{font-size:2rem!important;}.flow{gap:12px;}}
</style>''', unsafe_allow_html=True)


def initialize():
    if st.session_state.pop('reset_composer', False):
        st.session_state.ai_consent = False
        st.session_state.writing_request = ''
    defaults = {'data': empty_data(), 'messages': [], 'source_notes': '', 'questions': [], 'source_names': [
    ], 'revision': 0, 'uploader_revision': 0, 'ai_consent': False, 'writing_request': ''}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def change_data(data):
    st.session_state.data = copy.deepcopy(data)
    st.session_state.revision += 1
    st.session_state.pop('result', None)
    st.session_state.pop('active_dialog', None)


def payload():
    return {key: copy.deepcopy(st.session_state[key]) for key in ('data', 'messages', 'source_notes', 'questions', 'source_names')}


def remember_work():
    access = save_work(payload(), st.session_state.get('work_access'))
    st.session_state.work_access = access
    st.session_state.saved_fingerprint = fingerprint(payload())
    st.session_state.show_receipt = True


def apply_draft(result, prompt):
    change_data(result['data'])
    st.session_state.source_notes = result['source_notes']
    st.session_state.questions = result['questions']
    st.session_state.messages.extend([{'role': 'user', 'content': prompt}, {
                                     'role': 'assistant', 'content': result['summary']}])
    st.session_state.messages = st.session_state.messages[-20:]


def run_agent(materials, request):
    if time.monotonic() - st.session_state.get('last_ai_at', -1000) < 5:
        raise DocumentError('방금 요청한 작업을 확인한 뒤 다시 요청해 주세요.')
    st.session_state.last_ai_at = time.monotonic()
    with st.spinner('자료를 읽고 신청서 초안을 작성하고 있습니다…'):
        result = compose_from_materials(
            st.session_state.data, materials, request, st.session_state.source_notes, st.session_state.messages)
    apply_draft(result, request or '올린 자료로 신청서 초안을 작성해 주세요.')


def close_dialog():
    st.session_state.pop('active_dialog', None)


@st.dialog('세부 정보 수정', width='large', on_dismiss=close_dialog)
def edit_details():
    render_details(st.session_state.data, change_data)


@st.dialog('저장한 작업 불러오기', on_dismiss=close_dialog)
def restore_dialog():
    st.caption('저장할 때 받은 작업번호와 확인 비밀번호를 입력해 주세요.')
    with st.form('restore_form', clear_on_submit=True):
        number = st.text_input('작업번호', max_chars=32)
        password = st.text_input('확인 비밀번호', type='password', max_chars=128)
        submitted = st.form_submit_button('작업 불러오기', type='primary')
    if submitted:
        try:
            access, loaded = load_work(number, password)
            change_data(loaded['data'])
            for key, default in (('messages', []), ('questions', []), ('source_notes', ''), ('source_names', [])):
                st.session_state[key] = loaded.get(key, default)
            st.session_state.work_access = access
            st.session_state.saved_fingerprint = fingerprint(payload())
            st.session_state.uploader_revision += 1
            st.session_state.pop('show_receipt', None)
            st.session_state.reset_composer = True
            st.rerun()
        except DocumentError as exc:
            st.error(str(exc))


@st.dialog('새 신청서 작성', on_dismiss=close_dialog)
def new_dialog():
    st.write('현재 화면의 내용이 초기화됩니다. 이어서 작성하려면 먼저 작업을 저장해 주세요.')
    if st.button('새로 시작', type='primary'):
        epoch = st.session_state.uploader_revision + 1
        for key in list(st.session_state):
            del st.session_state[key]
        st.session_state.uploader_revision = epoch
        st.rerun()


initialize()
header, actions = st.columns([1.8, 1])
with header:
    st.markdown('<div class="eyebrow">K-BRAND · APPLICATION ASSISTANT</div>',
                unsafe_allow_html=True)
with actions:
    a, b = st.columns(2)
    if a.button('작업 열기', width='stretch', disabled=not storage_ready()):
        st.session_state.active_dialog = 'restore'
    if b.button('새 신청서', width='stretch'):
        st.session_state.active_dialog = 'new'

st.markdown('<h1>K-브랜드 정부인증 신청서 작성 도우미 - <br>AI 에이전트 기반 웹사이트</h1>',
            unsafe_allow_html=True)
st.markdown('<div class="lead">회사소개서와 제품 자료를 올려 주세요.<br>AI가 자동으로 필요한 정보를 찾아 K-브랜드 신청 서류 두 종을 작성해 드립니다.</div>',
            unsafe_allow_html=True)
st.markdown('<div class="flow"><span><b>1</b>자료 올리기</span><span><b>2</b>초안 확인·수정</span><span><b>3</b>한글파일 다운로드</span></div>', unsafe_allow_html=True)

left, right = st.columns([1.18, 1], gap='large')
with left:
    with st.container(border=True):
        st.subheader('자료와 요청사항')
        uploaded = st.file_uploader('예시) 회사소개서 · 제품 카탈로그 · 사업자등록증', type=EXTENSIONS, accept_multiple_files=True,
                                    max_upload_size=10, key=f'materials_{st.session_state.uploader_revision}')
        st.caption(
            'PDF·사진·Word·Excel·PowerPoint·HWPX·텍스트 / 최대 5개, 합계 25MB. HWP는 PDF나 HWPX로 저장해 주세요.')
        request = st.text_area('어떤 내용으로 작성할까요?', key='writing_request', max_chars=4000, height=110,
                               placeholder='예: "첨부한 현미과자 제품으로 K-브랜드 신청용 문서 초안을 작성해 주세요."\n자료가 없으시면 회사와 제품에 관한 내용을 여기에 설명해 주셔도 됩니다.')
        consent = st.checkbox(
            '자료와 작성 내용을 AI에 전달하여 신청서를 작성하는 데 동의합니다.', key='ai_consent')
        ready = ai_ready()
        if not ready:
            st.caption('AI 연결 준비 중입니다. 세부 정보에서 직접 작성하실 수 있습니다.')
        if st.button('자료에서 초안 만들기', type='primary', width='stretch', disabled=not (ready and consent and (uploaded or request.strip()))):
            try:
                materials = prepare_materials(
                    [(item.name, item.getvalue()) for item in uploaded])
                run_agent(materials, request)
                st.session_state.source_names = list(dict.fromkeys(
                    st.session_state.source_names + [item.name for item in materials]))[-30:]
                st.success('초안을 작성했습니다. 오른쪽에서 확인해 주세요.')
            except DocumentError as exc:
                st.error(str(exc))
        st.caption('회원가입 없이 사용할 수 있습니다. 수정할 내용은 아래 대화나 세부 정보에서 알려 주세요.')

    if st.session_state.messages:
        st.subheader('작성 도우미에게 수정 요청')
        with st.container(height=300, border=True):
            for message in st.session_state.messages[-8:]:
                with st.chat_message(message['role']):
                    st.text(message['content'])
        prompt = st.chat_input('예: 수출 실적은 없고 계획만 있습니다. 그에 맞게 고쳐 주세요.',
                               max_chars=4000, disabled=not (ready and consent))
        if prompt:
            try:
                run_agent([], prompt)
                st.rerun()
            except DocumentError as exc:
                st.error(str(exc))

with right:
    with st.container(border=True):
        st.subheader('신청서 초안')
        data = st.session_state.data
        if not data['company']['nameKo'] and not any(data['plan'][key] for key in PLAN_FIELDS):
            st.markdown('<div class="empty-preview"><div class="paper"><hr><hr><hr><hr></div>이곳에 AI가 작성한 신청서 초안이 나타납니다.<br><small>사용신청서 · 도입 필요성 및 활용계획서</small></div>', unsafe_allow_html=True)
        else:
            st.text(data['company']['nameKo'] or '회사명 확인 필요')
            st.caption(data['products'][0]['nameKo'] or '신청 제품 확인 필요')
            tabs = st.tabs(['사용신청서', '활용계획서'])
            with tabs[0]:
                for label, value in [('대표자', data['company']['representative']), ('사업자등록번호', data['company']['registrationNumber']), ('주소', data['company']['address']), ('담당자', data['contact']['name']), ('연락처', data['contact']['phone']), ('브랜드', data['products'][0]['brandKo']), ('신청국가', ', '.join(row['country'] for row in data['products'][0]['countries']))]:
                    st.caption(label)
                    st.text(value or '확인 필요')
            with tabs[1]:
                for key, label in PLAN_FIELDS.items():
                    with st.expander(label, expanded=key == 'counterfeitRisk'):
                        st.text(data['plan'][key] or '확인 필요')
        if st.button('세부 정보 수정', width='stretch'):
            st.session_state.active_dialog = 'details'
        if st.session_state.questions:
            with st.expander(f'고객 확인이 필요한 항목 {len(st.session_state.questions)}개', expanded=True):
                for question in st.session_state.questions:
                    st.text('• ' + question)
        if st.button('한글파일 두 개 만들기', type='primary', width='stretch', disabled=not data['company']['nameKo'].strip()):
            try:
                with st.spinner('원본 양식에 내용을 채우고 있습니다…'):
                    st.session_state.result = generate_documents(
                        data, temporary=True)
            except (DocumentError, OSError) as exc:
                st.error(str(exc) if isinstance(exc, DocumentError)
                         else '파일을 만들지 못했습니다. 다시 시도해 주세요.')
        result = st.session_state.get('result')
        if result and result['fingerprint'] == fingerprint(data):
            st.download_button('두 문서 ZIP 다운로드', result['zip'], 'K-브랜드_신청서_2종.zip',
                               'application/zip', type='primary', width='stretch', on_click='ignore')
            for item in result['files']:
                st.download_button(item['name'], item['bytes'], item['name'],
                                   'application/octet-stream', width='stretch', on_click='ignore')
            warnings = list(dict.fromkeys(
                w for item in result['report']['files'] for w in item['warnings']))
            with st.expander('제출 전 확인사항'):
                for warning in warnings:
                    st.text('• ' + warning)
        st.caption('검토용 문서입니다. 사진·서명은 한글에서 추가하고, 제출 전 사실과 표·쪽 배치를 확인해 주세요.')

st.divider()
save_col, note_col = st.columns([1, 2])
with save_col:
    if st.button('작업 저장 · 확인 비밀번호 발급' if not st.session_state.get('work_access') else '수정한 작업 저장', width='stretch', disabled=not storage_ready()):
        try:
            remember_work()
            st.success('현재 작성 내용을 저장했습니다.')
        except DocumentError as exc:
            st.error(str(exc))
with note_col:
    if storage_ready():
        st.caption(
            '나중에 이어서 작성하려면 작업을 저장해 주세요. 작업번호와 확인 비밀번호로 다시 열 수 있습니다. 업로드 원본은 보관하지 않습니다.')
    else:
        st.caption('현재는 이 화면에서 작성·다운로드할 수 있습니다. 작업 보관 기능은 운영자가 준비 중입니다.')
access = st.session_state.get('work_access')
if access:
    dirty = st.session_state.get('saved_fingerprint') != fingerprint(payload())
    if dirty:
        st.warning('저장 이후 수정한 내용이 있습니다. 이어서 작성하려면 다시 저장해 주세요.')
    with st.expander('내 작업번호와 확인 비밀번호', expanded=st.session_state.get('show_receipt', False)):
        st.code(
            f'작업번호: {access.number}\n확인 비밀번호: {access.password}', language=None)
        st.caption('이 두 정보를 가진 분이 작업을 열 수 있습니다. 비밀번호를 잃으면 복구할 수 없으니 보관해 주세요.')
        st.download_button(
            '작업 확인정보 보관하기', f'K-브랜드 신청서\n작업번호: {access.number}\n확인 비밀번호: {access.password}\n', 'K-브랜드_작업확인정보.txt', 'text/plain', on_click='ignore')

with st.expander('자료 없이 화면 살펴보기'):
    st.caption('가상 회사와 예시 문안을 불러옵니다. 현재 작성 내용을 바꾸며 실제 AI를 호출하지 않습니다.')
    if st.button('가상 자료로 체험하기'):
        sample = sample_data()
        sample['plan'].update(example_plan(sample))
        change_data(sample)
        for key in ('work_access', 'saved_fingerprint', 'show_receipt'):
            st.session_state.pop(key, None)
        st.session_state.messages = []
        st.session_state.source_notes = ''
        st.session_state.questions = []
        st.session_state.source_names = []
        st.session_state.uploader_revision += 1
        st.session_state.reset_composer = True
        st.rerun()

if st.session_state.get('active_dialog') == 'details':
    edit_details()
elif st.session_state.get('active_dialog') == 'restore':
    restore_dialog()
elif st.session_state.get('active_dialog') == 'new':
    new_dialog()
