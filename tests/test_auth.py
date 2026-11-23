"""로그인 모듈 테스트 (역할1)

실제 Firebase에 접속하지 않도록 requests.post 를 가짜(monkeypatch)로 바꿔서 시험한다.
"""
import pytest
import requests

from core import auth
from core.auth import AuthError, User, error_message, sign_in


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    # secrets.toml 없이도 테스트가 돌도록 st.secrets 대신 일반 dict 사용
    monkeypatch.setattr(auth.st, "secrets", {"firebase_web_api_key": "test-key"})


def test_error_message_known_and_unknown():
    assert "올바르지 않습니다" in error_message("INVALID_LOGIN_CREDENTIALS")
    assert "잠시 후" in error_message("TOO_MANY_ATTEMPTS_TRY_LATER : Access disabled")
    assert "SOMETHING_NEW" in error_message("SOMETHING_NEW")


def test_empty_input_rejected_without_network(monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("빈 입력이면 서버에 요청하면 안 됨")
    monkeypatch.setattr(auth.requests, "post", must_not_call)
    with pytest.raises(AuthError, match="모두 입력"):
        sign_in("", "pw")


def test_wrong_password(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: FakeResponse(
        400, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}))
    with pytest.raises(AuthError, match="올바르지 않습니다"):
        sign_in("a@test.com", "wrong")


def test_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(auth.requests, "post", boom)
    with pytest.raises(AuthError, match="연결할 수 없습니다"):
        sign_in("a@test.com", "pw")


def test_success_returns_token(monkeypatch):
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: FakeResponse(
        200, {"idToken": "tok", "localId": "uid1", "email": "a@test.com"}))
    assert sign_in("a@test.com", "pw")["idToken"] == "tok"


def test_role_label():
    assert User("u", "a@test.com", "관리자1", "admin").role_label == "관리자"
