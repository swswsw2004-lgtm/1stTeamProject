"""PET/CT 융합 기반 교육용 웹 PACS — 진입점

실행: streamlit run app.py
담당: 역할1 (로그인 화면은 feature/auth-login 에서 구현 예정)
"""
import streamlit as st

st.set_page_config(page_title="교육용 웹 PACS", page_icon="🩻", layout="wide")

st.title("🩻 PET/CT 융합 기반 교육용 웹 PACS")
st.info("로그인 화면 준비 중입니다. (역할1 · feature/auth-login)")
st.caption(
    "교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma "
    "(DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0) · 분석 수치는 진단 결과가 아닙니다."
)
