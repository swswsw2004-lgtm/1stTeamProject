import itertools

import pytest

from core import workflow as wf
from core.workflow import (
    ADMIN, REGISTRAR, REVIEWER,
    RECEIVED, ASSIGNED, IN_REVIEW, COMPLETED, RE_REVIEW,
)


class FakeStore:
    def __init__(self):
        self.cases = {}
        self.image_counts = {}
        self.reports = set()
        self.user_roles = {}
        self.logs = []
        self.race = False

    def get_case(self, case_id):
        case = self.cases.get(case_id)
        return dict(case) if case else None

    def count_images(self, case_id):
        return self.image_counts.get(case_id, 0)

    def has_report(self, case_id):
        return case_id in self.reports

    def get_user_role(self, uid):
        return self.user_roles.get(uid)

    def apply_transition(self, case_id, expected_from, to_status, assignee_uid, log):
        case = self.cases[case_id]
        if self.race:
            case["status"] = COMPLETED
        if case["status"] != expected_from:
            return False
        case["status"] = to_status
        if assignee_uid:
            case["assignee"] = assignee_uid
        self.logs.append(log)
        return True


ADMIN_USER = {"uid": "admin1", "role": ADMIN}
REGISTRAR_USER = {"uid": "reg1", "role": REGISTRAR}
REVIEWER_USER = {"uid": "rev1", "role": REVIEWER}
OTHER_REVIEWER = {"uid": "rev2", "role": REVIEWER}


@pytest.fixture
def store():
    s = FakeStore()
    s.user_roles = {"admin1": ADMIN, "reg1": REGISTRAR, "rev1": REVIEWER, "rev2": REVIEWER}
    s.cases["C1"] = {"case_id": "C1", "status": RECEIVED, "assignee": None}
    s.image_counts["C1"] = 2
    return s


def set_status(store, status, assignee="rev1"):
    store.cases["C1"]["status"] = status
    store.cases["C1"]["assignee"] = assignee


def assert_rejected(result, keyword):
    ok, message = result
    assert not ok
    assert keyword in message


def test_full_flow(store):
    assert wf.assign_reviewer(store, "C1", "rev1", ADMIN_USER)[0]
    assert store.cases["C1"]["status"] == ASSIGNED
    assert store.cases["C1"]["assignee"] == "rev1"

    assert wf.change_status(store, "C1", IN_REVIEW, REVIEWER_USER, expected_from=ASSIGNED)[0]

    store.reports.add("C1")
    assert wf.change_status(store, "C1", COMPLETED, REVIEWER_USER, expected_from=IN_REVIEW)[0]

    assert wf.change_status(store, "C1", RE_REVIEW, ADMIN_USER,
                            expected_from=COMPLETED, reason="수치 재확인")[0]
    assert wf.change_status(store, "C1", IN_REVIEW, REVIEWER_USER, expected_from=RE_REVIEW)[0]
    assert wf.change_status(store, "C1", COMPLETED, REVIEWER_USER, expected_from=IN_REVIEW)[0]

    moves = [(log["from_status"], log["to_status"]) for log in store.logs]
    assert moves == [
        (RECEIVED, ASSIGNED), (ASSIGNED, IN_REVIEW), (IN_REVIEW, COMPLETED),
        (COMPLETED, RE_REVIEW), (RE_REVIEW, IN_REVIEW), (IN_REVIEW, COMPLETED),
    ]
    assert store.logs[3]["reason"] == "수치 재확인"
    assert store.logs[0]["actor"] == "admin1"


def test_transition_table_has_five_rules():
    assert set(wf.TRANSITIONS) == {
        (RECEIVED, ASSIGNED), (ASSIGNED, IN_REVIEW), (IN_REVIEW, COMPLETED),
        (COMPLETED, RE_REVIEW), (RE_REVIEW, IN_REVIEW),
    }


NOT_ALLOWED = [pair for pair in itertools.product(wf.STATUS_NAMES, repeat=2)
               if pair not in wf.TRANSITIONS]


@pytest.mark.parametrize("current,to_status", NOT_ALLOWED)
def test_transition_not_in_table_is_rejected(current, to_status):
    case = {"case_id": "C1", "status": current, "assignee": "rev1"}
    for actor in (ADMIN_USER, REVIEWER_USER, REGISTRAR_USER):
        result = wf.check_transition(case, to_status, actor, image_count=3, has_report=True,
                                     reason="사유", assignee_uid="rev1", assignee_role=REVIEWER)
        assert_rejected(result, "바꿀 수 없습니다")


@pytest.mark.parametrize("actor", [None, {}, {"uid": "x"}, {"role": ADMIN}, {"uid": "", "role": ADMIN}])
def test_not_logged_in(store, actor):
    result = wf.change_status(store, "C1", ASSIGNED, actor,
                              expected_from=RECEIVED, assignee_uid="rev1")
    assert_rejected(result, "로그인")
    assert store.cases["C1"]["status"] == RECEIVED
    assert store.logs == []


def test_registrar_cannot_assign(store):
    assert_rejected(wf.assign_reviewer(store, "C1", "rev1", REGISTRAR_USER), "이 작업은")
    assert store.cases["C1"]["status"] == RECEIVED


def test_reviewer_cannot_assign(store):
    assert_rejected(wf.assign_reviewer(store, "C1", "rev1", REVIEWER_USER), "이 작업은")


def test_admin_cannot_start_review(store):
    set_status(store, ASSIGNED)
    result = wf.change_status(store, "C1", IN_REVIEW, ADMIN_USER, expected_from=ASSIGNED)
    assert_rejected(result, "이 작업은")


def test_other_reviewer_cannot_start_review(store):
    set_status(store, ASSIGNED, assignee="rev1")
    result = wf.change_status(store, "C1", IN_REVIEW, OTHER_REVIEWER, expected_from=ASSIGNED)
    assert_rejected(result, "배정된 담당자")
    assert store.cases["C1"]["status"] == ASSIGNED


def test_only_admin_can_send_to_re_review(store):
    set_status(store, COMPLETED)
    result = wf.change_status(store, "C1", RE_REVIEW, REVIEWER_USER,
                              expected_from=COMPLETED, reason="사유")
    assert_rejected(result, "이 작업은")


def test_assign_needs_image(store):
    store.image_counts["C1"] = 0
    assert_rejected(wf.assign_reviewer(store, "C1", "rev1", ADMIN_USER), "영상")
    assert store.cases["C1"]["status"] == RECEIVED


def test_assign_needs_assignee(store):
    result = wf.change_status(store, "C1", ASSIGNED, ADMIN_USER,
                              expected_from=RECEIVED, assignee_uid=None)
    assert_rejected(result, "담당자를 지정")


def test_assign_only_to_reviewer(store):
    assert_rejected(wf.assign_reviewer(store, "C1", "reg1", ADMIN_USER), "검토 담당자에게만")
    assert_rejected(wf.assign_reviewer(store, "C1", "nobody", ADMIN_USER), "검토 담당자에게만")
    assert store.cases["C1"]["status"] == RECEIVED


def test_complete_needs_report(store):
    set_status(store, IN_REVIEW)
    result = wf.change_status(store, "C1", COMPLETED, REVIEWER_USER, expected_from=IN_REVIEW)
    assert_rejected(result, "리포트")
    assert store.cases["C1"]["status"] == IN_REVIEW


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_re_review_needs_reason(store, reason):
    set_status(store, COMPLETED)
    result = wf.change_status(store, "C1", RE_REVIEW, ADMIN_USER,
                              expected_from=COMPLETED, reason=reason)
    assert_rejected(result, "사유")
    assert store.cases["C1"]["status"] == COMPLETED


def test_double_click_logs_once(store):
    set_status(store, ASSIGNED)
    first = wf.change_status(store, "C1", IN_REVIEW, REVIEWER_USER, expected_from=ASSIGNED)
    second = wf.change_status(store, "C1", IN_REVIEW, REVIEWER_USER, expected_from=ASSIGNED)
    assert first[0]
    assert_rejected(second, "새로고침")
    assert len(store.logs) == 1


def test_double_assign_logs_once(store):
    first = wf.assign_reviewer(store, "C1", "rev1", ADMIN_USER)
    second = wf.assign_reviewer(store, "C1", "rev1", ADMIN_USER)
    assert first[0]
    assert_rejected(second, "새로고침")
    assert len(store.logs) == 1


def test_race_between_check_and_save(store):
    set_status(store, ASSIGNED)
    store.race = True
    result = wf.change_status(store, "C1", IN_REVIEW, REVIEWER_USER, expected_from=ASSIGNED)
    assert_rejected(result, "다른 요청")
    assert store.logs == []


def test_case_not_found(store):
    result = wf.change_status(store, "NOPE", IN_REVIEW, REVIEWER_USER, expected_from=ASSIGNED)
    assert_rejected(result, "찾을 수 없습니다")


@pytest.mark.parametrize("status", [IN_REVIEW, RE_REVIEW])
def test_assignee_can_edit_memo(status):
    case = {"case_id": "C1", "status": status, "assignee": "rev1"}
    assert wf.check_can_edit_memo(case, REVIEWER_USER)[0]


def test_completed_case_memo_is_locked():
    case = {"case_id": "C1", "status": COMPLETED, "assignee": "rev1"}
    assert_rejected(wf.check_can_edit_memo(case, REVIEWER_USER), "완료된 케이스")


@pytest.mark.parametrize("status", [RECEIVED, ASSIGNED])
def test_memo_not_allowed_before_review(status):
    case = {"case_id": "C1", "status": status, "assignee": "rev1"}
    assert_rejected(wf.check_can_edit_memo(case, REVIEWER_USER), "이 상태에서는")


def test_memo_by_wrong_user():
    case = {"case_id": "C1", "status": IN_REVIEW, "assignee": "rev1"}
    assert_rejected(wf.check_can_edit_memo(case, OTHER_REVIEWER), "배정된 담당자")
    assert_rejected(wf.check_can_edit_memo(case, ADMIN_USER), "검토 담당자만")
    assert_rejected(wf.check_can_edit_memo(case, None), "로그인")


def test_next_statuses():
    def case(status):
        return {"case_id": "C1", "status": status, "assignee": "rev1"}

    assert wf.next_statuses(case(RECEIVED), ADMIN_USER) == [ASSIGNED]
    assert wf.next_statuses(case(RECEIVED), REVIEWER_USER) == []
    assert wf.next_statuses(case(ASSIGNED), REVIEWER_USER) == [IN_REVIEW]
    assert wf.next_statuses(case(ASSIGNED), OTHER_REVIEWER) == []
    assert wf.next_statuses(case(COMPLETED), ADMIN_USER) == [RE_REVIEW]
    assert wf.next_statuses(case(RE_REVIEW), REVIEWER_USER) == [IN_REVIEW]
    assert wf.next_statuses(case(IN_REVIEW), None) == []


def test_unknown_status():
    bad_case = {"case_id": "C1", "status": "weird", "assignee": "rev1"}
    assert_rejected(wf.check_transition(bad_case, IN_REVIEW, REVIEWER_USER), "알 수 없는 상태")
    good_case = {"case_id": "C1", "status": ASSIGNED, "assignee": "rev1"}
    assert_rejected(wf.check_transition(good_case, "weird", REVIEWER_USER), "알 수 없는 상태")
