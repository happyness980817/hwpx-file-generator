from __future__ import annotations

import copy
import time
import uuid

import streamlit as st

from src.ai import ai_ready
from src.agent import compose_from_materials
from src.application_store import save_application
from src.company_research import research_company
from src.download_ui import render_file_download
from src.errors import DocumentError
from src.form_ui import render_fields
from src.materials import EXTENSIONS, prepare_materials
from src.models import apply_form_defaults, empty_data, fingerprint
from src.service import generate_documents
from src.submission import validate_submission


st.set_page_config(page_title='K-브랜드 신청서', page_icon='📄', layout='wide',
                   initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1120px;padding:2.5rem 2rem 4rem;}
[data-testid="stHeader"], [data-testid="stToolbar"], footer {display:none;}
[data-testid="stAppViewContainer"] {background:#f5f5f7;color:#1d1d1f;}
h1 {font-size:2.2rem!important;letter-spacing:-.05em;padding-bottom:.25rem!important;}
h2,h3 {letter-spacing:-.035em;}
[data-testid="stCaptionContainer"] {color:#86868b;font-size:.82rem;}
.st-key-materials_card,.st-key-company_card,.st-key-plan_card,
[class*="st-key-product_card_"] {border-radius:14px!important;background:#fff;border-color:#e2e2e7!important;}
.st-key-materials_card,.st-key-company_card,.st-key-plan_card,
[class*="st-key-product_card_"] {padding:1.25rem!important;}
.ai-heading {font-size:1.3rem;font-weight:700;letter-spacing:-.035em;margin:0 0 .8rem;}
.optional {font-size:.88rem;font-weight:400;color:#929299;margin-left:.4rem;}
div.stButton>button,div.stDownloadButton>button {border-radius:8px;min-height:42px;}
.st-key-download_application button {min-height:50px;font-size:1.02rem;}
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea {background:#fff;}
[data-testid="stFileUploader"] section {background:#fafafa;border:1px dashed #d2d2d7;border-radius:8px;padding:.7rem 1rem;}
[data-testid="stFileUploaderDropzoneInstructions"]>div>span {font-size:0;}
[data-testid="stFileUploaderDropzoneInstructions"]>div>span::after {content:"회사·상품 소개자료 (선택)";font-size:.85rem;color:#929299;}
[data-testid="stFileUploaderDropzone"] button {font-size:0;}
[data-testid="stFileUploaderDropzone"] button [data-testid="stMarkdownContainer"] {display:none;}
[data-testid="stFileUploaderDropzone"] button::after {content:"파일 첨부";font-size:.88rem;}
input::placeholder,textarea::placeholder {color:#a1a1a6!important;opacity:1!important;}
input:focus::placeholder,textarea:focus::placeholder {color:transparent!important;}
@media(max-width:640px){.block-container{padding:1.5rem .85rem 2.5rem;}
 .st-key-materials_card,.st-key-company_card,.st-key-plan_card,[class*="st-key-product_card_"]{padding:1rem!important;}}
</style>''', unsafe_allow_html=True)


def initialize():
    defaults = {'data': empty_data(), 'messages': [], 'source_notes': '',
                'questions': [], 'source_names': [], 'revision': 0,
                'submission_session': str(uuid.uuid4())}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def change_data(data):
    st.session_state.data = apply_form_defaults(data)
    st.session_state.revision += 1
    st.session_state.pop('result', None)


def run_ai(uploaded, *, query=None, request=''):
    """Called only by explicit AI actions, after current form values commit."""
    if query is not None and not query.strip():
        raise DocumentError('회사명을 입력해 주세요.')
    if query is None and not request.strip() and not uploaded:
        raise DocumentError('요청사항을 입력하거나 자료를 첨부해 주세요.')
    if time.monotonic() - st.session_state.get('last_ai_at', -1000) < 5:
        raise DocumentError('잠시 후 다시 요청해 주세요.')
    materials = [] if query is not None else prepare_materials(
        [(item.name, item.getvalue()) for item in uploaded])
    st.session_state.last_ai_at = time.monotonic()
    if query is not None:
        with st.spinner('웹에서 회사 정보를 찾아 신청 내용을 채우고 있습니다…'):
            result = research_company(query, st.session_state.data)
        history_request = f'회사 정보 검색: {query}'
    else:
        history_request = request.strip() or (
            '입력한 값은 유지하고 첨부 자료로 빈칸을 보완해 주세요. '
            '선택한 상품·국가·활용채널에 맞게 활용계획 초안을 작성해 주세요.')
        with st.spinner('자료와 요청사항을 확인하고 내용을 작성하고 있습니다…'):
            result = compose_from_materials(
                st.session_state.data, materials, history_request,
                st.session_state.source_notes, st.session_state.messages,
                allow_edits=bool(request.strip()))
    if result['data'] != st.session_state.data:
        change_data(result['data'])
    st.session_state.source_notes = result.get('source_notes', '')
    st.session_state.questions = result.get('questions', [])
    st.session_state.messages = (st.session_state.messages + [
        {'role': 'user', 'content': history_request},
        {'role': 'assistant', 'content': result.get('summary', '')}])[-20:]
    # Provenance stays internal; the form has no source list or research dashboard.
    st.session_state.source_names = list(dict.fromkeys(
        st.session_state.source_names + [material.name for material in materials]
        + result.get('search_sources', [])))[-30:]
    questions = result.get('questions', [])
    st.session_state.ai_notice = questions[0] if questions else '신청 내용을 반영했습니다. 아래에서 확인해 주세요.'


def download_application(source_names=()):
    """Generate the current validated document; downloading never runs AI."""
    if not st.session_state.data.get('applicationDate'):
        raise DocumentError('신청일을 선택해 주세요.')
    data = apply_form_defaults(st.session_state.data)
    validate_submission(data)
    result = st.session_state.get('result')
    if not result or result['fingerprint'] != fingerprint(data):
        with st.spinner('신청 서류를 만들고 있습니다…'):
            result = generate_documents(data, temporary=True)
        st.session_state.result = result
    # Same company in this session updates one row; another company gets its own ID.
    company_number = ''.join(c for c in data['company']['registrationNumber'] if c.isdigit())
    submission_id = str(uuid.uuid5(uuid.UUID(st.session_state.submission_session), company_number))
    saved_fingerprint = fingerprint({'data': data, 'sources': list(source_names)})
    st.session_state.pop('storage_error', None)
    if st.session_state.get('saved_fingerprint') != saved_fingerprint:
        try:
            with st.spinner('신청 정보를 저장하고 있습니다…'):
                st.session_state.receipt = save_application(data, submission_id, source_names=source_names)
            st.session_state.saved_fingerprint = saved_fingerprint
        except DocumentError:
            st.session_state.storage_error = (
                '파일은 내려받을 수 있지만 신청 정보 저장에 실패했습니다. '
                '다시 내려받기를 누르면 저장을 재시도합니다.')
    render_file_download(result['zip'], 'K-브랜드_필작성_5종.zip', request_id=uuid.uuid4().hex)


def render_editor():
    st.title('K-브랜드 신청서 작성 (URCODE 컨설팅 사이트)', anchor=False)
    st.caption('회사 정보를 입력하고 신청서를 내려받으세요.')
    with st.container(border=True, key='materials_card'):
        st.markdown('<div class="ai-heading">AI로 작성하기 <span class="optional">(선택)</span></div>',
                    unsafe_allow_html=True)
        search, action = st.columns([3, 1.7], vertical_alignment='bottom')
        with search:
            query = st.text_input('회사명:', placeholder='회사명 또는 브랜드명을 입력하세요',
                                  max_chars=120, key='company_query')
        with action:
            search_clicked = st.button('신청 내용 자동으로 채우기', key='research_company',
                                       width='stretch', disabled=not ai_ready())
        st.caption('버튼을 누르면 AI가 웹에서 회사 정보를 찾아 신청서에 필요한 내용을 자동으로 채워드립니다.')
        uploaded = st.file_uploader('회사·상품 소개자료 (선택)', type=EXTENSIONS,
                                   accept_multiple_files=True, max_upload_size=10,
                                   label_visibility='collapsed', key='materials')
        request = st.text_area('AI에게 요청하기 (선택)', key='writing_request', height=110,
                              max_chars=4000,
                              placeholder='예) 인도 수출을 중심으로 활용계획을 작성해 주세요.')
        _, request_action = st.columns([3, 1])
        with request_action:
            request_clicked = st.button('요청 반영하기', key='apply_request', width='stretch',
                                        disabled=not ai_ready())
        if not ai_ready():
            st.caption('AI 연결 준비 중입니다. 아래 내용을 직접 입력해 내려받을 수 있습니다.')
        notice = st.empty()
        if st.session_state.get('ai_error'):
            notice.error(st.session_state.ai_error)
        elif st.session_state.get('ai_notice'):
            notice.info(st.session_state.ai_notice)

    working, structure_changed = render_fields(st.session_state.data, st.session_state.revision)
    if working != st.session_state.data:
        if structure_changed:
            change_data(working)
        else:
            st.session_state.data = copy.deepcopy(working)
            st.session_state.pop('result', None)
        st.session_state.pop('download_error', None)
    if structure_changed:
        st.rerun()

    # Read fields before acting so edits made immediately before clicking are included.
    if search_clicked or request_clicked:
        st.session_state.pop('ai_error', None)
        st.session_state.pop('ai_notice', None)
        try:
            run_ai(uploaded, query=query.strip() if search_clicked else None, request=request)
        except DocumentError as exc:
            st.session_state.ai_error = str(exc)
        st.rerun()

    if st.button('신청서 내려받기', icon=':material/download:', type='primary',
                 width='stretch', key='download_application'):
        st.session_state.pop('download_error', None)
        try:
            download_application(list(dict.fromkeys(
                st.session_state.source_names + [item.name for item in uploaded])))
        except (DocumentError, OSError) as exc:
            st.session_state.download_error = (str(exc) if isinstance(exc, DocumentError)
                else '파일을 만들지 못했습니다. 다시 시도해 주세요.')
    if st.session_state.get('download_error'):
        st.error(st.session_state.download_error)
    if st.session_state.get('storage_error'):
        st.warning(st.session_state.storage_error)


initialize()
render_editor()
