"""로그인·로그아웃·세션 (역할1)

로그인 흐름
  1) Firebase Auth REST API 로 이메일/비밀번호 확인 → ID 토큰 발급
  2) firebase-admin 으로 ID 토큰이 진짜인지 서버에서 검증
  3) Firestore users/{uid} 문서에서 역할(role) 조회
  4) 로그인한 사용자 정보를 st.session_state["user"] 에 저장

다른 팀원 사용법 (페이지 맨 위에서)
    from core.auth import require_login
    user = require_login()      # 로그인 안 했으면 여기서 화면이 멈춤
    user.uid, user.email, user.name, user.role
"""
from __future__ import annotations  # Python 3.9에서도 'User | None' 같은 타입 표기가 동작하게 함

from dataclasses import dataclass

import requests
import streamlit as st
from firebase_admin import auth as admin_auth

from core.firebase import get_app, get_db

CLOCK_SKEW_SECONDS = 10  # 토큰 시간 검증 허용 오차(초)
SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"

ROLES = {"registrar": "등록 담당자", "reviewer": "검토 담당자", "admin": "관리자"}

# Firebase가 돌려주는 오류 코드 → 사용자에게 보여줄 한국어 안내
ERROR_MESSAGES = {
    "INVALID_LOGIN_CREDENTIALS": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "EMAIL_NOT_FOUND": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_PASSWORD": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_EMAIL": "이메일 형식이 올바르지 않습니다.",
    "MISSING_PASSWORD": "비밀번호를 입력하세요.",
    "USER_DISABLED": "사용이 중지된 계정입니다.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
}


class AuthError(Exception):
    """로그인 실패. 메시지를 그대로 화면에 보여줘도 되는 오류."""


@dataclass(frozen=True)
class User:
    uid: str
    email: str
    name: str
    role: str  # "registrar" | "reviewer" | "admin"

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)

    # 역할4 workflow.py 등 dict 형태(user["uid"], user.get("role"))로 쓰는 코드와 호환
    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None


def error_message(code: str) -> str:
    """'TOO_MANY_ATTEMPTS_TRY_LATER : ...' 처럼 뒤에 설명이 붙어 오는 경우도 처리."""
    key = code.split(":")[0].strip()
    return ERROR_MESSAGES.get(key, f"로그인에 실패했습니다. ({key})")


def sign_in(email: str, password: str) -> dict:
    """1단계: 이메일/비밀번호를 Firebase에 보내 ID 토큰을 받는다."""
    if not email or not password:
        raise AuthError("이메일과 비밀번호를 모두 입력하세요.")
    try:
        r = requests.post(
            SIGN_IN_URL,
            params={"key": st.secrets["firebase_web_api_key"]},
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
    except requests.RequestException as e:
        raise AuthError("인증 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요.") from e
    if r.status_code != 200:
        code = r.json().get("error", {}).get("message", "")
        raise AuthError(error_message(code))
    return r.json()  # idToken, localId(uid), email 등이 들어 있음


def load_user(id_token: str) -> User:
    """2~3단계: 토큰을 서버에서 검증하고, Firestore에서 역할을 읽어 User를 만든다."""
    get_app()
    try:
        # 컴퓨터·서버 시계가 Firebase보다 몇 초 느리면 "Token used too early" 오류가 나므로 10초 허용 (최대 60)
        decoded = admin_auth.verify_id_token(id_token, clock_skew_seconds=CLOCK_SKEW_SECONDS)
    except Exception as e:
        raise AuthError("로그인 정보를 확인할 수 없습니다. 다시 로그인하세요.") from e

    uid = decoded["uid"]
    doc = get_db().collection("users").document(uid).get()
    if not doc.exists:
        raise AuthError("역할이 등록되지 않은 계정입니다. 관리자에게 문의하세요.")
    data = doc.to_dict()
    role = data.get("role")
    if role not in ROLES:
        raise AuthError(f"알 수 없는 역할입니다: {role}")
    return User(uid=uid, email=decoded.get("email", ""),
                name=data.get("name") or data.get("display_name", ""), role=role)


def login(email: str, password: str) -> User:
    """로그인 화면에서 호출. 성공하면 세션에 저장하고 User를 돌려준다."""
    token = sign_in(email.strip(), password)
    user = load_user(token["idToken"])
    st.session_state["user"] = user
    return user


def logout() -> None:
    st.session_state.pop("user", None)


def current_user() -> User | None:
    return st.session_state.get("user")


def require_login() -> User:
    """페이지 맨 위에서 호출. 로그인하지 않았으면 안내를 띄우고 화면 실행을 멈춘다."""
    user = current_user()
    if user is None:
        st.warning("로그인이 필요합니다. 첫 화면에서 로그인하세요.")
        st.stop()
    return user
