from datetime import datetime, timedelta, timezone

from core.workflow import STATUS_NAMES, check_can_edit_memo, is_logged_in

MEMO = "memo"
REPORT = "report"
KIND_NAMES = {MEMO: "메모", REPORT: "요약 리포트"}
MAX_LENGTH = 2000
KST = timezone(timedelta(hours=9))


def now_text():
    return datetime.now(timezone.utc).isoformat()


def check_content(content):
    text = (content or "").strip()
    if not text:
        return False, "내용을 입력해 주세요."
    if len(text) > MAX_LENGTH:
        return False, f"내용은 {MAX_LENGTH}자 이하로 써 주세요. (현재 {len(text)}자)"
    return True, text


def has_report(memos):
    return any(m.get("kind") == REPORT and (m.get("content") or "").strip() for m in memos)


def write_memo(store, memo_id, case_id, user, content, kind=MEMO,
               image_id=None, history_id=None):
    if kind not in KIND_NAMES:
        return False, f"알 수 없는 종류입니다: {kind}"
    if not memo_id:
        return False, "요청 번호가 없습니다. 새로고침 후 다시 시도해 주세요."

    case = store.get_case(case_id)
    ok, message = check_can_edit_memo(case, user)
    if not ok:
        return False, message

    ok, text = check_content(content)
    if not ok:
        return False, text

    if kind == REPORT and has_report(store.list_memos(case_id)):
        return False, "요약 리포트는 케이스마다 하나만 쓸 수 있습니다. 기존 리포트를 수정해 주세요."

    now = now_text()
    memo = {
        "case_id": case_id,
        "kind": kind,
        "content": text,
        "image_id": image_id,
        "history_id": history_id,
        "author_uid": user["uid"],
        "created_at": now,
        "updated_at": now,
        "edit_log": [],
    }
    if not store.add_memo(memo_id, memo):
        return False, "이미 저장된 요청입니다. 같은 내용이 두 번 저장되지 않았습니다."
    return True, f"{KIND_NAMES[kind]}를 저장했습니다."


def edit_memo(store, memo_id, user, new_content):
    memo = store.get_memo(memo_id)
    if memo is None:
        return False, "메모를 찾을 수 없습니다."

    case = store.get_case(memo["case_id"])
    ok, message = check_can_edit_memo(case, user)
    if not ok:
        return False, message

    ok, text = check_content(new_content)
    if not ok:
        return False, text
    if text == memo["content"]:
        return False, "바뀐 내용이 없습니다."

    now = now_text()
    edit = {"prev": memo["content"], "by_uid": user["uid"], "at": now}
    changes = {
        "content": text,
        "updated_at": now,
        "edit_log": memo.get("edit_log", []) + [edit],
    }
    if not store.update_memo(memo_id, memo["content"], changes):
        return False, "다른 수정이 먼저 저장되었습니다. 새로고침 후 다시 시도해 주세요."
    return True, "수정했습니다."


def list_case_memos(store, case_id, user):
    if not is_logged_in(user):
        return False, "로그인이 필요합니다."
    if store.get_case(case_id) is None:
        return False, "케이스를 찾을 수 없습니다."
    memos = sorted(store.list_memos(case_id), key=lambda m: m["created_at"])
    return True, memos


def to_kst(value):
    if not value:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def time_text(value):
    time = to_kst(value)
    return time.strftime("%Y-%m-%d %H:%M") if time else "-"


def sort_key(value):
    return to_kst(value) or datetime.min.replace(tzinfo=KST)


def build_report_draft(case, histories, status_logs):
    lines = [
        f"케이스: {case['case_id']} (환자 {case.get('patient_id') or '-'})",
        f"검사: {case.get('exam_type') or '-'} / {case.get('exam_date') or '-'}",
        f"현재 상태: {STATUS_NAMES.get(case.get('status'), case.get('status'))}",
        "",
        "[처리 이력]",
    ]
    if not histories:
        lines.append("- 없음")
    for h in sorted(histories, key=lambda h: sort_key(h.get("executed_at"))):
        line = f"- {time_text(h.get('executed_at'))} {h.get('algorithm', '-')} {h.get('params') or {}}"
        features = h.get("features")
        if features:
            line += " / ROI " + ", ".join(f"{k} {v}" for k, v in features.items())
        lines.append(line)

    lines += ["", "[상태 변경]"]
    if not status_logs:
        lines.append("- 없음")
    for log in sorted(status_logs, key=lambda log: sort_key(log.get("at"))):
        line = (f"- {time_text(log.get('at'))} {STATUS_NAMES[log['from_status']]} → "
                f"{STATUS_NAMES[log['to_status']]}")
        if log.get("reason"):
            line += f" (사유: {log['reason']})"
        lines.append(line)

    lines += ["", "[소견]", ""]
    return "\n".join(lines)
