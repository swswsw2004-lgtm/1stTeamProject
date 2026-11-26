import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core import memos as mm
from core import workflow as wf
from core.auth import require_login
from core.firebase import get_db
from core.review_store import FirestoreReviewStore, group_cases

KST = timezone(timedelta(hours=9))

st.set_page_config(page_title="검토 업무", layout="wide")
user = require_login()

if user["role"] not in (wf.REVIEWER, wf.ADMIN):
    st.info("검토 업무는 검토 담당자와 관리자만 사용할 수 있습니다.")
    st.stop()

store = FirestoreReviewStore(get_db())


def to_kst(text):
    if not text:
        return "-"
    return datetime.fromisoformat(text).astimezone(KST).strftime("%Y-%m-%d %H:%M")


def finish(result):
    st.session_state["review_flash"] = result
    st.rerun()


def request_id():
    if "memo_request_id" not in st.session_state:
        st.session_state["memo_request_id"] = uuid.uuid4().hex
    return st.session_state["memo_request_id"]


def save_new(case_id, content, kind):
    result = mm.write_memo(store, request_id(), case_id, user, content, kind=kind)
    st.session_state.pop("memo_request_id", None)
    finish(result)


st.title("검토 업무")

flash = st.session_state.pop("review_flash", None)
if flash:
    ok, message = flash
    (st.success if ok else st.error)(message)

users = store.list_users()
names = {u["id"]: u.get("name") or u.get("email") or u["id"] for u in users}
reviewers = [u["id"] for u in users if u.get("role") == wf.REVIEWER]
groups = group_cases(store.list_cases(), user)

group = st.radio("목록", list(groups), horizontal=True,
                 format_func=lambda g: f"{g} ({len(groups[g])})")
cases = groups[group]
if not cases:
    st.write("해당하는 케이스가 없습니다.")
    st.stop()

st.dataframe(pd.DataFrame([{
    "케이스 ID": c["case_id"],
    "환자 ID": c.get("patient_id") or "-",
    "검사": c.get("exam_type") or "-",
    "검사일": c.get("exam_date") or "-",
    "상태": wf.STATUS_NAMES.get(c.get("status"), c.get("status")),
    "담당자": names.get(c.get("assignee"), "-"),
} for c in cases]), hide_index=True, width="stretch")

case_id = st.selectbox("케이스 선택", [c["case_id"] for c in cases])
case = store.get_case(case_id)
if case is None:
    st.error("케이스를 찾을 수 없습니다. 새로고침해 주세요.")
    st.stop()

st.subheader(f"{case_id} · {wf.STATUS_NAMES[case['status']]}")
st.write(f"환자 {case.get('patient_id') or '-'} · {case.get('exam_type') or '-'} · "
         f"검사일 {case.get('exam_date') or '-'} · "
         f"담당자 {names.get(case.get('assignee'), '-')}")
if case.get("description"):
    st.caption(case["description"])

for to_status in wf.next_statuses(case, user):
    if to_status == wf.ASSIGNED:
        if not reviewers:
            st.warning("배정할 검토 담당자 계정이 없습니다.")
            continue
        picked = st.selectbox("검토 담당자", reviewers, format_func=names.get)
        if st.button("배정하기", type="primary"):
            finish(wf.assign_reviewer(store, case_id, picked, user))
    elif to_status == wf.RE_REVIEW:
        reason = st.text_input("재검토 사유")
        if st.button("재검토로 보내기"):
            finish(wf.change_status(store, case_id, wf.RE_REVIEW, user,
                                    expected_from=case["status"], reason=reason))
    elif to_status == wf.IN_REVIEW:
        label = "다시 검토 시작" if case["status"] == wf.RE_REVIEW else "검토 시작"
        if st.button(label, type="primary"):
            finish(wf.change_status(store, case_id, wf.IN_REVIEW, user,
                                    expected_from=case["status"]))
    elif to_status == wf.COMPLETED:
        if st.button("검토 완료", type="primary"):
            finish(wf.change_status(store, case_id, wf.COMPLETED, user,
                                    expected_from=case["status"]))

st.divider()
can_edit, why = wf.check_can_edit_memo(case, user)
_, memo_list = mm.list_case_memos(store, case_id, user)
report = next((m for m in memo_list if m["kind"] == mm.REPORT), None)
notes = [m for m in memo_list if m["kind"] == mm.MEMO]


def show_edits(memo):
    if memo.get("edit_log"):
        with st.expander(f"수정 이력 {len(memo['edit_log'])}건"):
            for edit in reversed(memo["edit_log"]):
                st.caption(f"{to_kst(edit['at'])} · {names.get(edit['by_uid'], edit['by_uid'])}")
                st.text(edit["prev"])


def edit_form(memo):
    with st.form(f"edit_{memo['id']}"):
        text = st.text_area("수정", value=memo["content"], height=200, max_chars=mm.MAX_LENGTH,
                            key=f"text_{memo['id']}")
        if st.form_submit_button("수정 저장"):
            finish(mm.edit_memo(store, memo["id"], user, text))


st.subheader("요약 리포트")
if report:
    st.caption(f"{names.get(report['author_uid'], report['author_uid'])} · "
               f"마지막 수정 {to_kst(report['updated_at'])}")
    st.text(report["content"])
    if can_edit:
        edit_form(report)
    show_edits(report)
elif can_edit:
    draft = mm.build_report_draft(case, store.list_histories(case_id), store.list_status_logs(case_id))
    with st.form("new_report", clear_on_submit=True):
        text = st.text_area("리포트 작성", value=draft, height=300, max_chars=mm.MAX_LENGTH)
        if st.form_submit_button("리포트 저장", type="primary"):
            save_new(case_id, text, mm.REPORT)
else:
    st.write("작성된 리포트가 없습니다.")

st.subheader(f"검토 메모 ({len(notes)})")
for memo in notes:
    with st.container(border=True):
        st.caption(f"{names.get(memo['author_uid'], memo['author_uid'])} · {to_kst(memo['created_at'])}")
        st.text(memo["content"])
        if can_edit:
            edit_form(memo)
        show_edits(memo)

if can_edit:
    with st.form("new_memo", clear_on_submit=True):
        text = st.text_area("새 메모", max_chars=mm.MAX_LENGTH)
        if st.form_submit_button("메모 저장"):
            save_new(case_id, text, mm.MEMO)
else:
    st.caption(why)

st.divider()
st.subheader("상태 변경 기록")
logs = store.list_status_logs(case_id)
if not logs:
    st.write("기록이 없습니다.")
for log in logs:
    line = (f"{to_kst(log['at'])} · {wf.STATUS_NAMES[log['from_status']]} → "
            f"{wf.STATUS_NAMES[log['to_status']]} · {names.get(log['actor'], log['actor'])}")
    if log.get("reason"):
        line += f" · 사유: {log['reason']}"
    st.write(line)
