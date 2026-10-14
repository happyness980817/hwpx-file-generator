from __future__ import annotations

import copy
import hashlib
import time

import streamlit as st

from src.ai import ai_ready
from src.agent import compose_from_materials
from src.form_ui import render_fields
from src.errors import DocumentError
from src.guest_work import storage_ready
from src.materials import EXTENSIONS, prepare_materials
from src.models import empty_data, fingerprint
from src.password_documents import create_document, load_document, save_document
from src.service import generate_documents

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
                'ai_consent': False, 'writing_request': ''}
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


def run_agent(materials, request):
    if time.monotonic() - st.session_state.get('last_ai_at', -1000) < 5:
        raise DocumentError('잠시 후 다시 요청해 주세요.')
    st.session_state.last_ai_at = time.monotonic()
    with st.spinner('문서를 작성하고 있습니다…'):
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
        st.session_state.source_names + [material.name for material in materials] + result.get('search_sources', [])))[-30:]
    if st.session_state.get('work_access'):
        persist()


def go_home():
    if st.session_state.get('work_access') and st.session_state.get('saved_fingerprint') != fingerprint(payload()):
        if not persist():
            return
    reset_document('home')
    st.rerun()


def render_home():
    with st.container(key='home_choices'):
        with st.container(key='home_intro'):
            st.title('K-브랜드 신청서 작성', anchor=False)
            st.write('회사·제품 자료를 올리면 신청에 필요한 문서를 작성해 드립니다.')
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
    back, title, saved = st.columns([1.3, 3.6, 1.1], vertical_alignment='center')
    if back.button('처음으로', icon=':material/arrow_back:'):
        go_home()
    title.subheader('문서 수정' if existing else '새 문서 생성')
    if existing:
        if st.session_state.get('save_error'):
            if saved.button('다시 저장', width='stretch'):
                persist()
                st.rerun()
        else:
            saved.caption('자동 저장')
    if st.session_state.get('action_error'):
        st.error(st.session_state.action_error)
    if st.session_state.get('save_error'):
        st.error('저장하지 못했습니다. 화면의 내용은 유지됩니다.')
    st.caption('자료를 첨부하면 자동으로 채워집니다. 노란 칸만 확인해 주세요.')
    uploaded = st.file_uploader('파일 첨부', type=EXTENSIONS, accept_multiple_files=True,
                               max_upload_size=10, key=f'materials_{st.session_state.uploader_revision}',
                               help='회사소개서·제품자료·인증서 등 최대 5개, 합계 25MB')
    with st.expander('추가 요청'):
        request = st.text_area('작성 요청', key='writing_request', max_chars=4000, height=90,
                               placeholder='예: 첨부한 두 제품의 활용계획을 작성해 주세요.')
    consent = st.checkbox('AI 자료 분석에 동의합니다.', key='ai_consent',
                          help='첨부 자료와 입력 내용을 OpenAI API로 분석하고, 부족한 공개 회사·제품 정보는 웹검색으로 보완합니다.')
    ready = ai_ready()
    signature = fingerprint({'files': [(u.name, hashlib.sha256(u.getvalue()).hexdigest()) for u in uploaded], 'request': request})
    has_sources = bool(uploaded or request.strip())
    analyze_clicked = st.button('자료로 자동 채우기', type='primary', disabled=not (ready and consent and has_sources), width='stretch')

    working, structure_changed = render_fields(st.session_state.data, st.session_state.revision)
    if working != st.session_state.data:
        if structure_changed:
            change_data(working)
        else:
            st.session_state.data = copy.deepcopy(working)
            st.session_state.pop('result', None)
        if existing:
            persist()
    if structure_changed:
        st.rerun()

    if analyze_clicked:
        st.session_state.pop('action_error', None)
        try:
            materials = prepare_materials([(u.name, u.getvalue()) for u in uploaded])
            run_agent(materials, request)
            st.session_state.analyzed_materials = signature
        except DocumentError as exc:
            st.session_state.action_error = str(exc)
        st.rerun()


    if st.session_state.questions or st.session_state.source_names:
        with st.expander('확인 사항 및 출처'):
            for question in st.session_state.questions:
                st.text('• ' + question)
            for source in st.session_state.source_names:
                if source.startswith(('https://', 'http://')):
                    st.link_button(source, source)
                else:
                    st.text(source)

    password = ''
    if not existing:
        password = st.text_input('문서 비밀번호', type='password', key='new_password', max_chars=128,
                                 placeholder='문자·숫자 조합, 10자 이상')
    needs_analysis = has_sources and signature != st.session_state.get('analyzed_materials')
    can_generate = bool(st.session_state.data['company']['nameKo'].strip()) or (needs_analysis and ready and consent)
    label = '파일 만들기' if existing else '문서 생성'
    if st.button(label, type='primary', width='stretch', disabled=not ((existing or bool(password)) and storage_ready() and can_generate)):
        st.session_state.pop('action_error', None)
        try:
            ensure_document(password)
            if needs_analysis and ready and consent:
                run_agent(prepare_materials([(u.name, u.getvalue()) for u in uploaded]), request)
                st.session_state.analyzed_materials = signature
            persist()
            with st.spinner('문서를 만들고 있습니다…'):
                st.session_state.result = generate_documents(st.session_state.data, temporary=True)
        except (DocumentError, OSError) as exc:
            st.session_state.action_error = str(exc) if isinstance(exc, DocumentError) else '파일을 만들지 못했습니다. 다시 시도해 주세요.'
        st.rerun()
    if not storage_ready():
        st.error('문서 보관 연결을 확인해 주세요.')
    result = st.session_state.get('result')
    if result and result['fingerprint'] == fingerprint(st.session_state.data):
        st.download_button('필작성 문서 전체 다운로드', result['zip'], 'K-브랜드_필작성_5종.zip',
                           'application/zip', type='primary', width='stretch', on_click='ignore')
        with st.expander('개별 파일 다운로드'):
            for item in result['files']:
                st.download_button(item['name'], item['bytes'], item['name'],
                                   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if item['name'].endswith('.xlsx') else 'application/octet-stream',
                                   width='stretch', on_click='ignore')
        st.caption('서명·직인·동의 표시는 직접 확인해 주세요.')


initialize()
if st.session_state.page == 'home':
    render_home()
elif st.session_state.page == 'open':
    render_open()
else:
    render_editor()
