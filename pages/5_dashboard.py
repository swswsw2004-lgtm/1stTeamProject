from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core import workflow as wf
from core.auth import require_login
from core.dashboard import needs_attention, reviewer_summary, status_counts
from core.firebase import get_db
from core.review_store import FirestoreReviewStore

KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="진행 현황", layout="wide")
user = require_login()

if user["role"] != wf.ADMIN:
    st.info("진행 현황 대시보드는 관리자만 볼 수 있습니다.")
    st.stop()

store = FirestoreReviewStore(get_db())
cases = store.list_cases()
users = store.list_users()
names = {u["id"]: u.get("name") or u.get("email") or u["id"] for u in users}

st.title("진행 현황")
if st.button("새로고침"):
    st.rerun()

st.subheader(f"상태별 케이스 (전체 {len(cases)}건)")
counts = status_counts(cases)
for col, (status, count) in zip(st.columns(len(counts)), counts.items()):
    col.metric(wf.STATUS_NAMES[status], count)

st.subheader("검토 담당자별 현황")
rows = reviewer_summary(cases, users)
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    st.write("검토 담당자 계정이 없습니다.")

problems = needs_attention(cases, users)
if problems:
    st.subheader(f"확인이 필요한 케이스 ({len(problems)})")
    for case_id, reason in problems:
        st.warning(f"{case_id}: {reason}")

st.subheader("최근 상태 변경")
logs = store.list_recent_logs(10)
if not logs:
    st.write("기록이 없습니다.")
else:
    st.dataframe(pd.DataFrame([{
        "시간": datetime.fromisoformat(log["at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "케이스 ID": log["case_id"],
        "변경": f"{wf.STATUS_NAMES[log['from_status']]} → {wf.STATUS_NAMES[log['to_status']]}",
        "실행자": names.get(log["actor"], log["actor"]),
        "사유": log.get("reason") or "-",
    } for log in logs]), hide_index=True, width="stretch")
