from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.auth import AuthError

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def login_ui(monkeypatch):
    session = SimpleNamespace(user_id='test-user', close=Mock())
    profile = dict(user_id='test-user', username='sales01', display_name='시험 담당자', role='sales', active=True, must_change_password=False)
    signin = Mock(return_value=session)
    verify = Mock(side_effect=lambda login: profile.copy())
    signout = Mock()
    monkeypatch.setattr('src.auth_ui.configuration_error', lambda: None)
    monkeypatch.setattr('src.auth_ui.sign_in', signin)
    monkeypatch.setattr('src.auth_ui.current_profile', verify)
    monkeypatch.setattr('src.auth_ui.sign_out', signout)
    monkeypatch.setattr('src.ai.ai_ready', lambda: False)
    return SimpleNamespace(session=session, profile=profile, signin=signin, verify=verify, signout=signout)


def click(app, label):
    return next(b for b in app.button if b.label == label).click().run(timeout=30)


def submit_login(app):
    app.text_input(key='login_username').set_value('sales01')
    app.text_input(key='login_password').set_value('test-password')
    return click(app, '로그인')


def test_anonymous_user_has_no_document_ui(login_ui):
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    assert not app.exception
    assert [b.label for b in app.button] == ['로그인']
    assert not app.get('download_button')
    assert 'data' not in app.session_state


def test_login_logout_and_account_switch_clear_all_data(login_ui):
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    submit_login(app)
    assert not app.exception
    assert 'auth_session' in app.session_state
    assert 'login_password' not in app.session_state
    click(app, '가상 고객 자료로 시작')
    app.session_state['result'] = {'zip': b'previous-user-file'}
    app.session_state['note_input'] = 'previous-user-note'
    click(app, '로그아웃')
    assert not app.exception
    for key in ('auth_session', 'data', 'result', 'notes', 'field_company_nameKo', 'note_input'):
        assert key not in app.session_state
    login_ui.signout.assert_called_once_with(login_ui.session)
    login_ui.profile.update(username='sales02', display_name='다른 담당자')
    submit_login(app)
    assert app.text_input(key='field_company_nameKo').value == ''
    assert 'result' not in app.session_state


def test_failed_login_never_opens_document_ui(login_ui):
    login_ui.signin.side_effect = AuthError('아이디 또는 비밀번호를 확인해 주세요.')
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    submit_login(app)
    assert not app.exception
    assert app.error
    assert 'auth_session' not in app.session_state
    assert 'login_password' not in app.session_state
    assert not any(b.label == '가상 고객 자료로 시작' for b in app.button)


def test_session_failure_clears_old_downloads(login_ui):
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    submit_login(app)
    app.session_state['result'] = {'zip': b'old-file'}
    login_ui.verify.side_effect = AuthError('로그인이 만료되었습니다.')
    app.run()
    assert not app.exception
    assert 'result' not in app.session_state
    assert 'data' not in app.session_state
    assert [b.label for b in app.button] == ['로그인']
    login_ui.session.close.assert_called_once()


def test_password_change_gate(login_ui, monkeypatch):
    login_ui.profile['must_change_password'] = True
    def change(login, password, confirmation):
        assert password == confirmation == 'Abcdef12!?'
        login_ui.profile['must_change_password'] = False
    monkeypatch.setattr('src.auth_ui.change_initial_password', change)
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    submit_login(app)
    assert not any(b.label == '가상 고객 자료로 시작' for b in app.button)
    assert 'data' not in app.session_state
    assert app.text_input(key='new_password').label == '새 비밀번호 (10자 이상)'
    app.text_input(key='new_password').set_value('Abcdef12!?')
    app.text_input(key='confirm_password').set_value('Abcdef12!?')
    click(app, '비밀번호 변경')
    assert not app.exception
    assert any(b.label == '가상 고객 자료로 시작' for b in app.button)
    assert 'new_password' not in app.session_state


def test_unconfigured_login_disabled(login_ui, monkeypatch):
    monkeypatch.setattr('src.auth_ui.configuration_error', lambda: '설정이 필요합니다.')
    app = AppTest.from_file(str(ROOT / 'app.py')).run()
    assert app.error
    assert next(b for b in app.button if b.label == '로그인').disabled
