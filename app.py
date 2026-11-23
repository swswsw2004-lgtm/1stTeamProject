"""PET/CT 융합 기반 교육용 웹 PACS — 진입점 (로그인 화면)

실행: streamlit run app.py
담당: 역할1
"""
import streamlit as st

from core.auth import AuthError, current_user, login, logout

st.set_page_config(page_title="교육용 웹 PACS", page_icon="🩻", layout="wide")

DATA_NOTICE = (
    "교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma "
    "(DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0) · 분석 수치는 진단 결과가 아닙니다."
)

st.title("🩻 PET/CT 융합 기반 교육용 웹 PACS")
user = current_user()

if user is None:
    # ── 로그인 화면 ──
    with st.form("login_form"):
        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", type="primary")
    if submitted:
        try:
            login(email, password)
            st.rerun()  # 로그인 성공 → 화면을 다시 그려서 아래 '로그인 후' 화면으로
        except AuthError as e:
            st.error(str(e))
else:
    # ── 로그인 후 화면 ──
    with st.sidebar:
        st.markdown(f"**{user.name or user.email}**  \n{user.role_label}")
        if st.button("로그아웃"):
            logout()
            st.rerun()
    st.success(f"{user.name or user.email}님, 환영합니다. ({user.role_label})")
    st.write("왼쪽 메뉴에서 작업을 선택하세요. (각 화면은 팀원별 브랜치에서 개발 중)")

st.caption(DATA_NOTICE)
