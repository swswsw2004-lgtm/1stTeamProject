"""Firebase 연결 공통 모듈 (역할1)

- Firebase Admin SDK를 앱 전체에서 '한 번만' 초기화한다.
- 다른 팀원은 DB가 필요할 때 get_db() 만 호출하면 된다.
    from core.firebase import get_db
    get_db().collection("cases").document("STS_001").get()
- 비밀키는 코드에 넣지 않고 .streamlit/secrets.toml 의 [firebase_service_account] 에서 읽는다.
"""
import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore


@st.cache_resource  # Streamlit은 화면을 조작할 때마다 코드를 다시 실행하므로, 연결은 캐시해서 1번만 만든다
def get_app() -> firebase_admin.App:
    if firebase_admin._apps:  # 이미 초기화됐으면 그대로 사용 (중복 초기화 시 ValueError 발생)
        return firebase_admin.get_app()
    if "firebase_service_account" not in st.secrets:
        raise RuntimeError("secrets.toml 에 [firebase_service_account] 설정이 없습니다. README 2번을 확인하세요.")
    cred = credentials.Certificate(dict(st.secrets["firebase_service_account"]))
    return firebase_admin.initialize_app(cred)


def get_db():
    """Firestore 클라이언트를 돌려준다."""
    get_app()
    return firestore.client()
