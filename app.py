from __future__ import annotations

import copy
import time

import streamlit as st

from src.ai import ai_ready
from src.agent import compose_from_materials
from src.details_ui import render_details
from src.errors import DocumentError
from src.guest_work import storage_ready
from src.materials import EXTENSIONS, prepare_materials
from src.models import PLAN_FIELDS, empty_data, fingerprint
from src.password_documents import create_document, load_document, save_document
from src.service import generate_documents
from src.web_materials import prepare_links

st.set_page_config(page_title='K-브랜드 문서', page_icon='📄', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1120px;padding:2rem 2rem 4rem;}
[data-testid="stHeader"], [data-testid="stToolbar"], footer {display:none;}
[data-testid="stAppViewContainer"] {background:#f7f8f4;}
h1 {font-size:1.9rem!important;letter-spacing:-.05em;}
h2,h3 {letter-spacing:-.03em;}
div.stButton>button,div.stDownloadButton>button {border-radius:12px;min-height:44px;}
[data-testid="stFileUploader"] section {background:#f1f5ef;border:1px dashed #a9bcaa;border-radius:12px;}
.st-key-home_choices {max-width:860px;margin:clamp(60px,12vh,120px) auto 0;}
.st-key-home_intro {text-align:center;margin-bottom:1.2rem;}
.st-key-home_intro h1 {font-size:clamp(1.8rem,4vw,2.5rem)!important;}
.st-key-home_intro p {color:#65796e;line-height:1.7;}
.st-key-home_choices button {height:210px;flex-direction:column;gap:18px;border-radius:22px;box-shadow:0 5px 24px #20362e08;}
.st-key-home_choices button [data-has-shortcut] {display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;}
.st-key-home_choices button p {font-size:21px;font-weight:600;letter-spacing:-.035em;white-space:normal!important;}
.st-key-home_choices button span[data-testid="stIconMaterial"] {font-size:38px;}
.st-key-open_panel {max-width:440px;margin:12vh auto 0;}
.empty-preview {padding:65px 20px;text-align:center;color:#81907e;}
.paper {width:65px;height:84px;border:1px solid #dce3d7;border-radius:6px;background:white;box-shadow:7px 7px 0 #e6ebdf;margin:0 auto 24px;padding:14px;}
.paper hr {height:2px;border:0;background:#dce5d9;margin:9px 0;}
@media(max-width:640px){.block-container{padding:1.3rem 1rem 3rem;}.st-key-home_choices{margin:10vh auto 0;}.st-key-home_choices button{height:160px;}.st-key-home_choices button p{font-size:19px;}.st-key-open_panel{margin:7vh auto 0;}}
</style>''', unsafe_allow_html=True)

PAYLOAD_KEYS = ('data', 'messages', 'source_notes', 'questions', 'source_names')


def initialize():
    if st.session_state.pop('clear_password', False):
        st.session_state.pop('new_password', None)
    defaults = {'page': 'home', 'data': empty_data(), 'messages': [], 'source_notes': '',
                'questions': [], 'source_names': [], 'revision': 0, 'uploader_revision': 0,
                'ai_consent': False, 'writing_request': '', 'material_links': ''}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_document(page):
    epoch = st.session_state.get('uploader_revision', 0) + 1
    for key in list(st.session_state):
        del st.session_state[key]
    st.session_state.page = page
    st.session_state.uploader_revision = epoch
    initialize()


def payload():
    return {key: copy.deepcopy(st.session_state[key]) for key in PAYLOAD_KEYS}


def persist():
    try:
        save_document(payload(), st.session_state.work_access)
        st.session_state.saved_fingerprint = fingerprint(payload())
        st.session_state.pop('save_error', None)
        return True
    except DocumentError as exc:
        st.session_state.save_error = str(exc)
        return False


def ensure_document(password):
    if not st.session_state.get('work_access'):
        st.session_state.work_access = create_document(password, payload())
        st.session_state.saved_fingerprint = fingerprint(payload())
        st.session_state.clear_password = True


def change_data(data):
    st.session_state.data = copy.deepcopy(data)
    st.session_state.revision += 1
    st.session_state.pop('result', None)
    st.session_state.pop('active_dialog', None)


def apply_manual(data):
    change_data(data)
    if st.session_state.get('work_access'):
        persist()


def run_agent(materials, request, links=''):
    if time.monotonic() - st.session_state.get('last_ai_at', -1000) < 5:
        raise DocumentError('잠시 후 다시 요청해 주세요.')
    st.session_state.last_ai_at = time.monotonic()
    with st.spinner('문서를 작성하고 있습니다…'):
        materials = list(materials) + prepare_links(links)
        result = compose_from_materials(st.session_state.data, materials, request,
                                        st.session_state.source_notes, st.session_state.messages)
    change_data(result['data'])
    st.session_state.source_notes = result['source_notes']
    st.session_state.questions = result['questions']
    st.session_state.messages.extend([
        {'role': 'user', 'content': request or '제공한 자료로 문서를 작성해 주세요.'},
        {'role': 'assistant', 'content': result['summary']}])
    st.session_state.messages = st.session_state.messages[-20:]
    st.session_state.source_names = list(dict.fromkeys(
        st.session_state.source_names + [material.name for material in materials]))[-30:]
    persist()


def go_home():
    if st.session_state.get('work_access') and st.session_state.get('saved_fingerprint') != fingerprint(payload()):
        if not persist():
            return
    reset_document('home')
    st.rerun()


def close_dialog():
    st.session_state.pop('active_dialog', None)


@st.dialog('내용 수정', width='large', on_dismiss=close_dialog)
def edit_details():
    render_details(st.session_state.data, apply_manual)


def render_home():
    with st.container(key='home_choices'):
        with st.container(key='home_intro'):
            st.title('K-브랜드 신청서 작성', anchor=False)
            st.write('회사·제품 링크나 자료를 올리면 AI가 신청서 초안을 작성해 드립니다.')
        new, existing = st.columns(2, gap='large')
        if new.button('새 문서 생성', icon=':material/add:', type='primary', width='stretch'):
            reset_document('editor')
            st.rerun()
        if existing.button('작성한 문서 불러오기', icon=':material/folder_open:', width='stretch'):
            reset_document('open')
            st.rerun()


def render_open():
    with st.container(key='open_panel'):
        if st.button('처음으로', icon=':material/arrow_back:'):
            go_home()
        st.header('작성한 문서 불러오기')
        with st.form('open_document', clear_on_submit=True, border=False):
            password = st.text_input('비밀번호', type='password', max_chars=128,
                                     placeholder='문서를 만들 때 정한 비밀번호')
            submitted = st.form_submit_button('불러오기', type='primary', width='stretch', disabled=not storage_ready())
        if not storage_ready():
            st.error('문서 보관 연결을 확인해 주세요.')
        if submitted:
            try:
                client_id = st.context.ip_address or 'unknown'
                access, loaded = load_document(password, client_id)
                reset_document('editor')
                change_data(loaded['data'])
                for key, default in (('messages', []), ('questions', []), ('source_notes', ''), ('source_names', [])):
                    st.session_state[key] = loaded.get(key, default)
                st.session_state.work_access = access
                st.session_state.saved_fingerprint = fingerprint(payload())
                st.rerun()
            except DocumentError as exc:
                st.error(str(exc))


def render_editor():
    existing = bool(st.session_state.get('work_access'))
    back, title, saved = st.columns([1, 3.6, 1.1], vertical_alignment='center')
    if back.button('처음으로', icon=':material/arrow_back:'):
        go_home()
    title.subheader('문서 수정' if existing else '새 문서 생성')
    if existing:
        dirty = st.session_state.get('saved_fingerprint') != fingerprint(payload())
        if dirty:
            if saved.button('저장', type='primary', width='stretch'):
                persist()
                st.rerun()
        else:
            saved.caption('저장됨')
    if st.session_state.get('action_error'):
        st.error(st.session_state.action_error)
    if st.session_state.get('save_error'):
        st.error('저장되지 않았습니다. 화면의 내용은 유지됩니다. 위의 저장 버튼을 눌러 주세요.')
    left, right = st.columns([1, 1.1], gap='large')
    with left:
        with st.container(border=True):
            st.subheader('자료 입력')
            links = st.text_area('회사·제품 링크', key='material_links', max_chars=6002, height=80,
                                 placeholder='https://', help='한 줄에 하나씩, 최대 3개')
            uploaded = st.file_uploader('파일 첨부', type=EXTENSIONS, accept_multiple_files=True,
                                       max_upload_size=10, key=f'materials_{st.session_state.uploader_revision}',
                                       help='회사소개서·제품자료 등 최대 5개 / 파일당 10MB, 합계 25MB. HWP는 PDF 또는 HWPX로 저장해 주세요.')
            request = st.text_area('요청사항 (선택)', key='writing_request', max_chars=4000,
                                   height=80, placeholder='예: 이 제품의 일본 진출 계획을 작성해 주세요.')
            password = ''
            if not existing:
                password = st.text_input('문서 비밀번호', type='password', key='new_password', max_chars=128,
                                         placeholder='문자·숫자 조합, 10자 이상',
                                         help='이 비밀번호로 문서를 다시 엽니다. 분실하면 복구할 수 없습니다.')
            sources = bool(links.strip() or uploaded or request.strip())
            consent = st.checkbox('AI 자료 분석에 동의합니다.', key='ai_consent',
                                   help='링크 본문·첨부 자료·요청사항을 OpenAI API에 전달합니다.')
            ready = ai_ready()
            manual = bool(st.session_state.data['company']['nameKo'].strip())
            can_create = (existing or bool(password)) and storage_ready() and (
                (sources and ready and consent) or (not sources and manual))
            if st.button('초안 다시 작성' if existing else '문서 생성', type='primary', width='stretch', disabled=not can_create):
                st.session_state.pop('action_error', None)
                try:
                    materials = prepare_materials([(item.name, item.getvalue()) for item in uploaded])
                    ensure_document(password)
                    if sources:
                        run_agent(materials, request, links)
                    else:
                        persist()
                except DocumentError as exc:
                    st.session_state.action_error = str(exc)
                st.rerun()
            if not storage_ready():
                st.error('문서 보관 연결을 확인해 주세요.')
            elif not ready:
                st.caption('AI 연결 준비 중입니다. 내용을 직접 입력할 수 있습니다.')
        if existing and st.session_state.messages:
            st.subheader('수정 요청')
            with st.container(height=260, border=True):
                for message in st.session_state.messages[-8:]:
                    with st.chat_message(message['role']):
                        st.text(message['content'])
            prompt = st.chat_input('수정할 내용을 말씀해 주세요.', max_chars=4000, disabled=not (ready and consent))
            if prompt:
                st.session_state.pop('action_error', None)
                try:
                    run_agent([], prompt)
                except DocumentError as exc:
                    st.session_state.action_error = str(exc)
                st.rerun()
    with right:
        with st.container(border=True):
            st.subheader('문서 미리보기')
            data = st.session_state.data
            if not data['company']['nameKo'] and not any(data['plan'][key] for key in PLAN_FIELDS):
                st.markdown('<div class="empty-preview"><div class="paper"><hr><hr><hr></div>작성된 문서가 여기에 표시됩니다.</div>', unsafe_allow_html=True)
            else:
                st.text(data['company']['nameKo'] or '회사명 확인 필요')
                st.caption(data['products'][0]['nameKo'] or '제품명 확인 필요')
                application, plan = st.tabs(['사용신청서', '활용계획서'])
                with application:
                    rows = [('대표자', data['company']['representative']), ('사업자등록번호', data['company']['registrationNumber']),
                            ('주소', data['company']['address']), ('담당자', data['contact']['name']), ('연락처', data['contact']['phone']),
                            ('브랜드', data['products'][0]['brandKo']), ('신청국가', ', '.join(row['country'] for row in data['products'][0]['countries']))]
                    for label, value in rows:
                        label_col, value_col = st.columns([1, 2])
                        label_col.caption(label)
                        value_col.text(value or '확인 필요')
                with plan:
                    for key, label in PLAN_FIELDS.items():
                        with st.expander(label, expanded=key == 'counterfeitRisk'):
                            st.text(data['plan'][key] or '확인 필요')
            if st.button('내용 수정' if existing else '직접 입력', width='stretch'):
                st.session_state.active_dialog = 'details'
            if st.session_state.questions:
                with st.expander(f'확인할 항목 {len(st.session_state.questions)}개'):
                    for question in st.session_state.questions:
                        st.text('• ' + question)
            if st.session_state.source_names:
                with st.expander('참고 자료'):
                    for source in st.session_state.source_names:
                        st.text(source)
            if existing:
                if st.button('한글파일 만들기', type='primary', width='stretch', disabled=not data['company']['nameKo'].strip()):
                    try:
                        with st.spinner('파일을 만들고 있습니다…'):
                            st.session_state.result = generate_documents(data, temporary=True)
                    except (DocumentError, OSError) as exc:
                        st.error(str(exc) if isinstance(exc, DocumentError) else '파일을 만들지 못했습니다. 다시 시도해 주세요.')
                result = st.session_state.get('result')
                if result and result['fingerprint'] == fingerprint(data):
                    for label, item in zip(('사용신청서.hwpx', '활용계획서.hwpx'), result['files']):
                        st.download_button(label, item['bytes'], item['name'], 'application/octet-stream', width='stretch', on_click='ignore')
                    st.download_button('두 파일 ZIP 다운로드', result['zip'], 'K-브랜드_신청서_2종.zip', 'application/zip', width='stretch', on_click='ignore')
                    with st.expander('제출 전 확인'):
                        st.caption('사진·서명과 문서 배치를 확인해 주세요.')
                        for warning in dict.fromkeys(w for item in result['report']['files'] for w in item['warnings']):
                            st.text('• ' + warning)
    if st.session_state.get('active_dialog') == 'details':
        edit_details()


initialize()
if st.session_state.page == 'home':
    render_home()
elif st.session_state.page == 'open':
    render_open()
else:
    render_editor()
