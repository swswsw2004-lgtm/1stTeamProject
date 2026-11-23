from datetime import datetime, timezone

RECEIVED = "received"
ASSIGNED = "assigned"
IN_REVIEW = "in_review"
COMPLETED = "completed"
RE_REVIEW = "re_review"

STATUS_NAMES = {
    RECEIVED: "접수",
    ASSIGNED: "배정",
    IN_REVIEW: "검토 중",
    COMPLETED: "완료",
    RE_REVIEW: "재검토",
}

REGISTRAR = "registrar"
REVIEWER = "reviewer"
ADMIN = "admin"

ROLE_NAMES = {
    REGISTRAR: "등록 담당자",
    REVIEWER: "검토 담당자",
    ADMIN: "관리자",
}

TRANSITIONS = {
    (RECEIVED, ASSIGNED): (ADMIN, False),
    (ASSIGNED, IN_REVIEW): (REVIEWER, True),
    (IN_REVIEW, COMPLETED): (REVIEWER, True),
    (COMPLETED, RE_REVIEW): (ADMIN, False),
    (RE_REVIEW, IN_REVIEW): (REVIEWER, True),
}

EDITABLE_STATUSES = (IN_REVIEW, RE_REVIEW)


def is_logged_in(user):
    return bool(user and user.get("uid") and user.get("role"))


def check_transition(case, to_status, user, assignee_uid=None, assignee_role=None,
                     image_count=0, has_report=False, reason=""):
    if not is_logged_in(user):
        return False, "로그인이 필요합니다."
    if case is None:
        return False, "케이스를 찾을 수 없습니다."

    current = case.get("status")
    if current not in STATUS_NAMES or to_status not in STATUS_NAMES:
        return False, f"알 수 없는 상태입니다: {current} -> {to_status}"

    rule = TRANSITIONS.get((current, to_status))
    if rule is None:
        return False, f"'{STATUS_NAMES[current]}' 상태에서 '{STATUS_NAMES[to_status]}' 상태로는 바꿀 수 없습니다."

    needed_role, must_be_assignee = rule
    if user["role"] != needed_role:
        return False, f"이 작업은 {ROLE_NAMES[needed_role]}만 할 수 있습니다."
    if must_be_assignee and case.get("assignee") != user["uid"]:
        return False, "이 케이스에 배정된 담당자만 할 수 있습니다."

    if to_status == ASSIGNED:
        if image_count < 1:
            return False, "영상이 1개 이상 등록되어야 배정할 수 있습니다."
        if not assignee_uid:
            return False, "배정할 담당자를 지정해 주세요."
        if assignee_role != REVIEWER:
            return False, "검토 담당자에게만 배정할 수 있습니다."
    elif to_status == COMPLETED and not has_report:
        return False, "리포트를 작성한 뒤에 완료할 수 있습니다."
    elif to_status == RE_REVIEW and not (reason or "").strip():
        return False, "재검토 사유를 입력해 주세요."

    return True, "가능합니다."


def next_statuses(case, user):
    if case is None or not is_logged_in(user):
        return []
    result = []
    for (current, to_status), (needed_role, must_be_assignee) in TRANSITIONS.items():
        if current != case.get("status") or user["role"] != needed_role:
            continue
        if must_be_assignee and case.get("assignee") != user["uid"]:
            continue
        result.append(to_status)
    return result


def check_can_edit_memo(case, user):
    if not is_logged_in(user):
        return False, "로그인이 필요합니다."
    if case is None:
        return False, "케이스를 찾을 수 없습니다."

    status = case.get("status")
    if status == COMPLETED:
        return False, "완료된 케이스는 수정할 수 없습니다. 재검토로 바꾼 뒤 수정해 주세요."
    if status not in EDITABLE_STATUSES:
        return False, "이 상태에서는 메모·리포트를 쓸 수 없습니다."
    if user["role"] != REVIEWER:
        return False, "메모·리포트는 검토 담당자만 쓸 수 있습니다."
    if case.get("assignee") != user["uid"]:
        return False, "이 케이스에 배정된 담당자만 쓸 수 있습니다."
    return True, "가능합니다."


def change_status(store, case_id, to_status, user, expected_from,
                  assignee_uid=None, reason=""):
    if not is_logged_in(user):
        return False, "로그인이 필요합니다."

    case = store.get_case(case_id)
    if case is None:
        return False, "케이스를 찾을 수 없습니다."
    if case.get("status") != expected_from:
        return False, "이미 상태가 바뀌었습니다. 새로고침 후 다시 시도해 주세요."

    image_count = 0
    has_report = False
    assignee_role = None
    if to_status == ASSIGNED:
        image_count = store.count_images(case_id)
        if assignee_uid:
            assignee_role = store.get_user_role(assignee_uid)
    elif to_status == COMPLETED:
        has_report = store.has_report(case_id)

    ok, message = check_transition(case, to_status, user, assignee_uid, assignee_role,
                                   image_count, has_report, reason)
    if not ok:
        return False, message

    log = {
        "case_id": case_id,
        "from_status": expected_from,
        "to_status": to_status,
        "actor": user["uid"],
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": (reason or "").strip(),
    }
    if not store.apply_transition(case_id, expected_from, to_status, assignee_uid, log):
        return False, "다른 요청이 먼저 처리되었습니다. 새로고침 후 다시 시도해 주세요."
    return True, f"'{STATUS_NAMES[expected_from]}'에서 '{STATUS_NAMES[to_status]}'(으)로 바꿨습니다."


def assign_reviewer(store, case_id, reviewer_uid, user):
    return change_status(store, case_id, ASSIGNED, user,
                         expected_from=RECEIVED, assignee_uid=reviewer_uid)
