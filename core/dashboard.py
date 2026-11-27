from core.workflow import ASSIGNED, COMPLETED, IN_REVIEW, RE_REVIEW, REVIEWER, STATUS_NAMES

ACTIVE_STATUSES = (ASSIGNED, IN_REVIEW, RE_REVIEW)


def status_counts(cases):
    counts = {status: 0 for status in STATUS_NAMES}
    for case in cases:
        if case.get("status") in counts:
            counts[case["status"]] += 1
    return counts


def reviewer_summary(cases, users):
    rows = []
    for user in users:
        if user.get("role") != REVIEWER:
            continue
        mine = [c for c in cases if c.get("assignee") == user["id"]]
        rows.append({
            "검토 담당자": user.get("name") or user.get("email") or user["id"],
            "배정": sum(c.get("status") == ASSIGNED for c in mine),
            "검토 중": sum(c.get("status") in (IN_REVIEW, RE_REVIEW) for c in mine),
            "완료": sum(c.get("status") == COMPLETED for c in mine),
        })
    return sorted(rows, key=lambda r: (-(r["배정"] + r["검토 중"]), r["검토 담당자"]))


def needs_attention(cases, users):
    reviewers = {u["id"] for u in users if u.get("role") == REVIEWER}
    problems = []
    for case in cases:
        status = case.get("status")
        if status not in STATUS_NAMES:
            problems.append((case["case_id"], f"알 수 없는 상태입니다: {status}"))
        elif status in ACTIVE_STATUSES and not case.get("assignee"):
            problems.append((case["case_id"], f"'{STATUS_NAMES[status]}' 상태인데 담당자가 없습니다."))
        elif case.get("assignee") and case["assignee"] not in reviewers:
            problems.append((case["case_id"], "담당자가 검토 담당자 계정이 아닙니다."))
    return sorted(problems)
