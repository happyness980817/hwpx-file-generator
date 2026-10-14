from __future__ import annotations

import copy
import time
import uuid
import streamlit as st

from src.ai import ai_ready
from src.agent import compose_from_materials
from src.errors import DocumentError
from src.form_ui import render_fields
from src.google_sheets import sheets_ready, submit_application
from src.materials import EXTENSIONS, prepare_materials
from src.models import apply_form_defaults, empty_data, fingerprint
from src.service import generate_documents
from src.submission import validate_submission

st.set_page_config(page_title='K-브랜드 신청서', page_icon='📄', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width:1080px;padding:2.5rem 2rem 5rem;}
[data-testid="stHeader"], [data-testid="stToolbar"], footer {display:none;}
[data-testid="stAppViewContainer"] {background:#f5f5f7;color:#1d1d1f;}
h1 {font-size:2.2rem!important;letter-spacing:-.05em;}
h2,h3 {letter-spacing:-.035em;}
.st-key-materials_card,.st-key-company_card,[class*="st-key-product_card_"] {border-radius:20px!important;background:#fff;}
div.stButton>button,div.stDownloadButton>button {border-radius:12px;min-height:46px;}
[data-testid="stFileUploader"] section {background:#fff;border:1px dashed #c7c7cc;border-radius:16px;}
input::placeholder,textarea::placeholder {color:#a1a1a6!important;opacity:1!important;}
input:focus::placeholder,textarea:focus::placeholder {color:transparent!important;}
.st-key-home_intro {max-width:660px;text-align:center;margin:16vh auto 2rem;}
.st-key-home_intro h1 {font-size:clamp(2rem,5vw,3rem)!important;}
.st-key-home_intro p {color:#6e6e73;line-height:1.7;}
.st-key-home_action {max-width:360px;margin:0 auto;}
.st-key-home_action button {min-height:58px;font-size:18px;}
@media(max-width:640px){.block-container{padding:1.5rem 1rem 3rem;}.st-key-home_intro{margin:10vh auto 2rem;}}
</style>''', unsafe_allow_html=True)


def initialize():
    defaults = {'page': 'home', 'data': empty_data(), 'messages': [], 'source_notes': '',
                'questions': [], 'source_names': [], 'revision': 0, 'uploader_revision': 0,
                'submission_id': str(uuid.uuid4())}
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


def change_data(data):
    st.session_state.data = apply_form_defaults(data)
    st.session_state.revision += 1
    st.session_state.pop('result', None)


def run_agent(materials):
    if time.monotonic() - st.session_state.get('last_ai_at', -1000) < 5:
        raise DocumentError('잠시 후 다시 요청해 주세요.')
    st.session_state.last_ai_at = time.monotonic()
    request = '입력한 값은 유지하고 첨부 자료로 빈칸을 보완해 주세요. 선택한 상품·국가·활용채널에 맞게 활용계획 초안을 작성해 주세요.'
    with st.spinner('자료를 확인하고 초안을 작성하고 있습니다…'):
        result = compose_from_materials(st.session_state.data, materials, request,
                                        st.session_state.source_notes, st.session_state.messages)
    change_data(result['data'])
    st.session_state.source_notes = result['source_notes']
    st.session_state.questions = result['questions']
    st.session_state.messages = (st.session_state.messages + [
        {'role': 'user', 'content': request},
        {'role': 'assistant', 'content': result['summary']}])[-20:]
    st.session_state.source_names = list(dict.fromkeys(
        st.session_state.source_names + [material.name for material in materials] + result.get('search_sources', [])))[-30:]


def render_home():
    with st.container(key='home_intro'):
        st.title('K-브랜드 신청서 작성', anchor=False)
        st.write('회사와 상품 정보를 입력하고, 신청에 필요한 문서를 받아 보세요.')
    with st.container(key='home_action'):
        if st.button('새 문서 생성', icon=':material/add:', type='primary', width='stretch'):
            reset_document('editor')
            st.rerun()
        if st.session_state.data['company']['nameKo'].strip():
            if st.button('작성 중인 내용으로 돌아가기', width='stretch'):
                st.session_state.page = 'editor'
                st.rerun()


def render_editor():
    back, title = st.columns([1, 4], vertical_alignment='center')
    if back.button('처음으로', icon=':material/arrow_back:'):
        st.session_state.page = 'home'
        st.rerun()
    title.subheader('K-브랜드 신청서')
    st.caption('필수항목은 *로 표시되어 있습니다. 자료 첨부는 선택사항입니다.')
    if st.session_state.get('action_error'):
        st.error(st.session_state.action_error)
    with st.container(border=True, key='materials_card'):
        uploaded = st.file_uploader('상품관련 자료 및 회사 소개자료', type=EXTENSIONS, accept_multiple_files=True,
                                   max_upload_size=10, key=f'materials_{st.session_state.uploader_revision}',
                                   help='회사소개서·제품자료·인증서 등 최대 5개, 합계 25MB')
        analyze_slot = st.empty()

    working, structure_changed = render_fields(st.session_state.data, st.session_state.revision)
    if working != st.session_state.data:
        if structure_changed:
            change_data(working)
        else:
            st.session_state.data = copy.deepcopy(working)
            st.session_state.pop('result', None)
    if structure_changed:
        st.rerun()
    has_input = bool(uploaded or st.session_state.data['company']['nameKo'].strip()
                     or any(p['brandKo'].strip() for p in st.session_state.data['products']))
    analyze_clicked = analyze_slot.button('AI로 초안 채우기', disabled=not (ai_ready() and has_input), width='stretch')
    if analyze_clicked:
        st.session_state.pop('action_error', None)
        try:
            run_agent(prepare_materials([(u.name, u.getvalue()) for u in uploaded]))
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
    submitted_sources = list(dict.fromkeys(st.session_state.source_names + [u.name for u in uploaded]))
    current_fingerprint = fingerprint({'data': st.session_state.data, 'sources': submitted_sources})
    submitted = st.session_state.get('submitted_fingerprint') == current_fingerprint
    if submitted:
        st.success('접수되었습니다. 아래에서 신청 서류를 내려받으세요.')
    elif st.session_state.get('receipt'):
        st.caption('수정한 내용은 다시 제출하면 반영됩니다.')
    preview, submit = st.columns([1, 2])
    preview_clicked = preview.button('미리보기 파일 만들기', width='stretch',
                                     disabled=not bool(st.session_state.data['company']['nameKo'].strip()))
    submit_clicked = submit.button('수정 내용 제출하기' if st.session_state.get('receipt') else '제출하기',
                                   type='primary', width='stretch', disabled=submitted or not sheets_ready())
    if not sheets_ready():
        st.caption('현재 제출 연결을 확인 중입니다. 미리보기 파일은 만들 수 있습니다.')
    if preview_clicked or submit_clicked:
        st.session_state.pop('action_error', None)
        try:
            if not st.session_state.data.get('applicationDate'):
                raise DocumentError('신청일을 선택해 주세요.')
            data = apply_form_defaults(st.session_state.data)
            if submit_clicked:
                validate_submission(data)
            result = st.session_state.get('result')
            if not result or result['fingerprint'] != fingerprint(data):
                with st.spinner('신청 서류를 만들고 있습니다…'):
                    st.session_state.result = generate_documents(data, temporary=True)
            if submit_clicked:
                with st.spinner('제출 내용을 저장하고 있습니다…'):
                    receipt = submit_application(data, st.session_state.submission_id,
                                                 source_names=submitted_sources)
                st.session_state.receipt = receipt
                st.session_state.submitted_fingerprint = fingerprint({'data': data, 'sources': submitted_sources})
        except (DocumentError, OSError) as exc:
            st.session_state.action_error = str(exc) if isinstance(exc, DocumentError) else '파일을 만들지 못했습니다. 다시 시도해 주세요.'
        st.rerun()
    result = st.session_state.get('result')
    if result and result['fingerprint'] == fingerprint(st.session_state.data):
        st.download_button('신청 서류 전체 다운로드', result['zip'], 'K-브랜드_필작성_5종.zip',
                           'application/zip', type='primary', width='stretch', on_click='ignore')
        with st.expander('개별 파일 다운로드'):
            for item in result['files']:
                st.download_button(item['name'], item['bytes'], item['name'],
                                   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if item['name'].endswith('.xlsx') else 'application/octet-stream',
                                   width='stretch', on_click='ignore')
        st.caption('미입력 칸은 노란색입니다. 서명·직인·동의 표시는 직접 확인해 주세요.')


initialize()
if st.session_state.page == 'home':
    render_home()
else:
    render_editor()
