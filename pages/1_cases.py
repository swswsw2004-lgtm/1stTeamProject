"""
케이스 등록·목록 화면
담당: 역할2
위치: pages/1_케이스.py
필요: 역할1의 core/auth.py, core/firebase.py (feature/auth-login 브랜치 → dev merge 후 실행 가능)
"""
from datetime import date

import pandas as pd
import streamlit as st

from core.auth import require_login
from core.cases import (
    CAN_CREATE_ROLES,
    EXAM_TYPES,
    FirestoreCaseStore,
    create_case,
    list_cases,
    suggest_next_case_id,
)
from core.firebase import get_db

st.set_page_config(page_title="케이스", page_icon="🗂️", layout="wide")
user = require_login()

STATUS_LABELS = {"received": "접수", "assigned": "배정", "in_review": "검토 중",
                 "completed": "완료", "re_review": "재검토"}


@st.cache_data(ttl=60, show_spinner=False)
def load_cases() -> list[dict]:
    """화면이 다시 그려질 때마다 DB를 읽지 않도록 60초 캐시 (무료 사용량 절약)."""
    return list_cases(FirestoreCaseStore(get_db()))


st.title("🗂️ 케이스")
st.caption("교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma (CC BY 3.0)")

cases = load_cases()

# ── 등록 폼: 등록 권한이 있는 역할에게만 보여준다 (저장 직전에도 create_case가 다시 검사함) ──
if user.get("role") in CAN_CREATE_ROLES:
    with st.expander("➕ 새 케이스 등록", expanded=not cases):
        with st.form("case_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            case_id = c1.text_input(
                "케이스 ID", value=suggest_next_case_id([c["case_id"] for c in cases]),
                help="영문 대문자·숫자·-·_ 3~30자 (예: CASE-001)")
            patient_id = c2.text_input("환자 ID (공개 데이터)", placeholder="STS_001")
            c3, c4 = st.columns(2)
            exam_type = c3.selectbox("검사 구분", EXAM_TYPES)
            exam_date = c4.date_input("검사일", value=date.today(), max_value=date.today())
            description = st.text_area("설명 (선택)", max_chars=500)
            submitted = st.form_submit_button("등록", type="primary")

        if submitted:
            ok, msg = create_case(FirestoreCaseStore(get_db()), user, case_id, patient_id,
                                  exam_type, exam_date, description)
            if ok:
                load_cases.clear()      # 목록을 새로 읽도록 캐시 비우기
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
else:
    st.info("케이스 등록은 등록 담당자·관리자만 할 수 있습니다. 아래에서 목록을 볼 수 있습니다.")

# ── 목록 ──
st.subheader(f"케이스 목록 ({len(cases)}건)")
if not cases:
    st.write("등록된 케이스가 없습니다.")
else:
    table = pd.DataFrame([{
        "케이스 ID": c.get("case_id"),
        "환자 ID": c.get("patient_id"),
        "검사 구분": c.get("exam_type"),
        "검사일": c.get("exam_date"),
        "상태": STATUS_LABELS.get(c.get("status"), c.get("status")),
        "등록일": (c.get("registered_at") or "")[:10],
        "설명": c.get("description"),
    } for c in cases])
    st.dataframe(table, hide_index=True, use_container_width=True)

if st.button("🔄 새로고침"):
    load_cases.clear()
    st.rerun()
