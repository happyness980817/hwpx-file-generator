"""Authentication gate before rendering any document UI."""
import streamlit as st

from .auth import (
    AuthError, MIN_PASSWORD_LENGTH, change_initial_password, configuration_error, current_profile,
    sign_in, sign_out,
)


def _clear_state():
    # Clear form widgets as well as canonical data, preventing account-switch
    # leakage through old widget values or prepared download bytes.
    for key in list(st.session_state):
        del st.session_state[key]


def _logout():
    login = st.session_state.get('auth_session')
    message = '로그아웃했습니다.'
    try:
        if login:
            sign_out(login)
    except AuthError as exc:
        message = str(exc)
    finally:
        _clear_state()
        st.session_state.auth_notice = message


def _login_form():
    st.title('K-브랜드 문서 작업실')
    st.caption('발급받은 아이디와 비밀번호로 로그인해 주세요.')
    if notice := st.session_state.pop('auth_notice', None):
        st.info(notice)
    problem = configuration_error()
    if problem:
        st.error(problem)
    with st.form('login_form', clear_on_submit=True):
        username = st.text_input('아이디', placeholder='sales01', max_chars=32, key='login_username')
        password = st.text_input('비밀번호', type='password', max_chars=256, key='login_password')
        submitted = st.form_submit_button('로그인', type='primary', disabled=bool(problem), width='stretch')
    if submitted:
        st.session_state.pop('login_password', None)
        try:
            with st.spinner('로그인 확인 중…'):
                login = sign_in(username, password)
            _clear_state()
            st.session_state.auth_session = login
            st.rerun()
        except AuthError as exc:
            st.error(str(exc))
    st.caption('계정 발급이나 비밀번호 초기화는 관리자에게 요청해 주세요.')


def require_login():
    login = st.session_state.get('auth_session')
    if login is None:
        _login_form()
        st.stop()
    try:
        profile = current_profile(login)
    except AuthError as exc:
        login.close()
        _clear_state()
        st.session_state.auth_notice = str(exc)
        st.rerun()
    with st.sidebar:
        st.caption(f"{profile['display_name']} · {profile['username']}")
        st.button('로그아웃', on_click=_logout, width='stretch')
        st.divider()
    if profile['must_change_password']:
        st.title('처음 사용하시는 계정입니다')
        st.write('문서 작성을 시작하기 전에 비밀번호를 변경해 주세요.')
        with st.form('initial_password', clear_on_submit=True):
            password = st.text_input(f'새 비밀번호 ({MIN_PASSWORD_LENGTH}자 이상)', type='password', max_chars=256, key='new_password')
            confirmation = st.text_input('새 비밀번호 확인', type='password', max_chars=256, key='confirm_password')
            submitted = st.form_submit_button('비밀번호 변경', type='primary')
        if submitted:
            st.session_state.pop('new_password', None)
            st.session_state.pop('confirm_password', None)
            try:
                change_initial_password(login, password, confirmation)
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        st.stop()
    return profile
