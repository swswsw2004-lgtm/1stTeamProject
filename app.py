"""PET/CT 융합 기반 교육용 웹 PACS — 진입점 (로그인 + 공통 메뉴)

실행: streamlit run app.py
담당: 역할1

이 파일이 하는 일
  1) 로그인 전: 로그인 화면만 보여 준다 (다른 화면 메뉴 자체가 없음)
  2) 로그인 후: 역할에 맞는 메뉴만 보여 주고, 모든 화면 사이드바에 이름·역할·로그아웃을 표시
  3) 메뉴 이름을 한글로 (파일 이름 1_cases.py 대신 '케이스')

주의: 메뉴에서 숨기는 것은 '편의'일 뿐 보안이 아니다.
      실제 권한 검사는 각 화면(require_login + 역할 검사)과 core 모듈의 저장 함수에서 한다.
"""
import streamlit as st

from core.auth import AuthError, current_user, login, logout
from core.menu import menu_for

st.set_page_config(page_title="교육용 웹 PACS", page_icon="🩻", layout="wide")

DATA_NOTICE = (
    "교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma "
    "(DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0) · 분석 수치는 진단 결과가 아닙니다."
)


def login_page():
    st.title("🩻 PET/CT 융합 기반 교육용 웹 PACS")
    with st.form("login_form"):
        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", type="primary")
    if submitted:
        try:
            login(email, password)
            st.rerun()  # 로그인 성공 → 메뉴가 있는 화면으로 다시 그림
        except AuthError as e:
            st.error(str(e))
    st.caption(DATA_NOTICE)


def home_page():
    user = current_user()
    st.title("🩻 PET/CT 융합 기반 교육용 웹 PACS")
    st.success(f"{user.name or user.email}님, 환영합니다. ({user.role_label})")
    guide = {
        "registrar": "**케이스**에서 모의 케이스를 등록하고 CT·PET·RTSTRUCT 영상을 올리세요.",
        "reviewer": "**검토 업무**에서 배정된 케이스를 열고, **뷰어**와 **영상처리**로 검토한 뒤 메모·리포트를 남기세요.",
        "admin": "**검토 업무**에서 담당자를 배정하고, **진행 현황**에서 전체 상황을 확인하세요.",
    }
    st.write(guide.get(user.role, "왼쪽 메뉴에서 작업을 선택하세요."))
    st.caption(DATA_NOTICE)


user = current_user()

if user is None:
    # 로그인 전: 로그인 화면 하나만 (메뉴 없음)
    st.navigation([st.Page(login_page, title="로그인", icon="🔐")], position="hidden").run()
    st.stop()

# 로그인 후: 모든 화면 공통 사이드바 (이 파일은 어떤 화면을 열어도 먼저 실행된다)
with st.sidebar:
    st.markdown(f"**{user.name or user.email}**  \n{user.role_label}")
    if st.button("로그아웃", key="logout"):
        logout()
        st.rerun()
    st.divider()

pages = {"": [st.Page(home_page, title="홈", icon="🏠", default=True)]}
for group, items in menu_for(user.role).items():
    pages[group] = [st.Page(path, title=title, icon=icon) for path, title, icon in items]

st.navigation(pages).run()
