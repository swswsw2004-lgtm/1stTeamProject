from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import firebase, review_store
from core.auth import User
from core.memos import has_report
from core.review_store import group_cases
from core.workflow import (
    ADMIN, REGISTRAR, REVIEWER,
    RECEIVED, ASSIGNED, IN_REVIEW, COMPLETED, RE_REVIEW,
)

PAGE = str(Path(__file__).parent.parent / "pages" / "4_review.py")

ADMIN_USER = User(uid="admin1", email="a@test.com", name="관리자", role=ADMIN)
REVIEWER_USER = User(uid="rev1", email="r1@test.com", name="검토자1", role=REVIEWER)
OTHER_REVIEWER = User(uid="rev2", email="r2@test.com", name="검토자2", role=REVIEWER)
REGISTRAR_USER = User(uid="reg1", email="g@test.com", name="등록자", role=REGISTRAR)


def make_case(case_id, status, assignee=None, registered_at="2026-11-25T00:00:00+00:00"):
    return {"case_id": case_id, "patient_id": "STS_001", "exam_type": "PET/CT",
            "exam_date": "2026-11-20", "description": "", "status": status,
            "assignee": assignee, "registered_at": registered_at}


class FakeStore:
    def __init__(self):
        self.cases = {}
        self.images = {}
        self.users = {u.uid: {"name": u.name, "email": u.email, "role": u.role}
                      for u in (ADMIN_USER, REVIEWER_USER, OTHER_REVIEWER, REGISTRAR_USER)}
        self.logs = []
        self.memos = {}
        self.histories = []

    def get_case(self, case_id):
        case = self.cases.get(case_id)
        return dict(case) if case else None

    def list_cases(self):
        return [dict(c) for c in self.cases.values()]

    def count_images(self, case_id):
        return self.images.get(case_id, 0)

    def get_user_role(self, uid):
        return self.users.get(uid, {}).get("role")

    def list_users(self):
        return [u | {"id": uid} for uid, u in self.users.items()]

    def list_status_logs(self, case_id):
        return [log for log in self.logs if log["case_id"] == case_id]

    def list_histories(self, case_id):
        return [h for h in self.histories if h["case_id"] == case_id]

    def apply_transition(self, case_id, expected_from, to_status, assignee_uid, log):
        case = self.cases[case_id]
        if case["status"] != expected_from:
            return False
        case["status"] = to_status
        if assignee_uid:
            case["assignee"] = assignee_uid
        self.logs.append(log)
        return True

    def get_memo(self, memo_id):
        memo = self.memos.get(memo_id)
        return dict(memo) if memo else None

    def list_memos(self, case_id):
        return [m | {"id": mid} for mid, m in self.memos.items() if m["case_id"] == case_id]

    def has_report(self, case_id):
        return has_report(self.list_memos(case_id))

    def add_memo(self, memo_id, memo):
        if memo_id in self.memos:
            return False
        self.memos[memo_id] = memo
        return True

    def update_memo(self, memo_id, expected_content, changes):
        memo = self.memos[memo_id]
        if memo["content"] != expected_content:
            return False
        memo.update(changes)
        return True


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(review_store, "FirestoreReviewStore", lambda db: s)
    monkeypatch.setattr(firebase, "get_db", lambda: None)
    return s


def open_page(user):
    at = AppTest.from_file(PAGE, default_timeout=10)
    if user is not None:
        at.session_state["user"] = user
    return at.run()


def click(at, label):
    buttons = [b for b in at.button if b.label == label]
    assert buttons, f"'{label}' 버튼이 없습니다"
    return buttons[0].click().run()


def texts(at):
    return " ".join(str(e.value) for e in list(at.success) + list(at.error) + list(at.markdown)
                    + list(at.caption) + list(at.info) + list(at.warning) + list(at.text))


def test_group_cases_for_reviewer():
    cases = [
        make_case("C1", ASSIGNED, "rev1"),
        make_case("C2", IN_REVIEW, "rev1"),
        make_case("C3", RE_REVIEW, "rev1"),
        make_case("C4", COMPLETED, "rev1"),
        make_case("C5", ASSIGNED, "rev2"),
        make_case("C6", RECEIVED),
    ]
    groups = group_cases(cases, REVIEWER_USER)
    assert [c["case_id"] for c in groups["내 대기 목록"]] == ["C1", "C2", "C3"]
    assert [c["case_id"] for c in groups["완료 목록"]] == ["C4"]


def test_group_cases_for_admin():
    cases = [make_case("C1", RECEIVED), make_case("C2", IN_REVIEW, "rev1"),
             make_case("C3", COMPLETED, "rev2")]
    groups = group_cases(cases, ADMIN_USER)
    assert [c["case_id"] for c in groups["배정 대기"]] == ["C1"]
    assert [c["case_id"] for c in groups["진행 중"]] == ["C2"]
    assert [c["case_id"] for c in groups["완료"]] == ["C3"]


def test_group_cases_for_registrar_is_empty():
    assert group_cases([make_case("C1", RECEIVED)], REGISTRAR_USER) == {}


def test_group_cases_newest_first():
    cases = [make_case("OLD", RECEIVED, registered_at="2026-11-20T00:00:00+00:00"),
             make_case("NEW", RECEIVED, registered_at="2026-11-24T00:00:00+00:00")]
    assert [c["case_id"] for c in group_cases(cases, ADMIN_USER)["배정 대기"]] == ["NEW", "OLD"]


def test_page_needs_login(store):
    at = open_page(None)
    assert "로그인이 필요합니다" in texts(at)


def test_registrar_cannot_use_page(store):
    at = open_page(REGISTRAR_USER)
    assert "검토 담당자와 관리자만" in texts(at)
    assert len(at.radio) == 0


def test_admin_assigns_reviewer(store):
    store.cases["C1"] = make_case("C1", RECEIVED)
    store.images["C1"] = 1
    at = open_page(ADMIN_USER)
    reviewer_box = [s for s in at.selectbox if s.label == "검토 담당자"][0]
    reviewer_box.set_value("rev2")
    at = click(at, "배정하기")
    assert store.cases["C1"]["status"] == ASSIGNED
    assert store.cases["C1"]["assignee"] == "rev2"
    assert store.logs[0]["actor"] == "admin1"
    assert "바꿨습니다" in texts(at)


def test_admin_assign_without_image_shows_reason(store):
    store.cases["C1"] = make_case("C1", RECEIVED)
    at = click(open_page(ADMIN_USER), "배정하기")
    assert store.cases["C1"]["status"] == RECEIVED
    assert "영상이 1개 이상" in texts(at)


def test_reviewer_full_flow(store):
    store.cases["C1"] = make_case("C1", ASSIGNED, "rev1")
    at = open_page(REVIEWER_USER)
    assert "검토 시작" in [b.label for b in at.button]

    at = click(at, "검토 시작")
    assert store.cases["C1"]["status"] == IN_REVIEW

    report_box = [t for t in at.text_area if t.label == "리포트 작성"][0]
    assert "케이스: C1" in report_box.value
    report_box.set_value("소견: 이상 없음")
    at = click(at, "리포트 저장")
    assert has_report(store.list_memos("C1"))

    at = click(at, "검토 완료")
    assert store.cases["C1"]["status"] == COMPLETED
    assert [(l["from_status"], l["to_status"]) for l in store.logs] == [
        (ASSIGNED, IN_REVIEW), (IN_REVIEW, COMPLETED)]


def test_reviewer_cannot_complete_without_report(store):
    store.cases["C1"] = make_case("C1", IN_REVIEW, "rev1")
    at = click(open_page(REVIEWER_USER), "검토 완료")
    assert store.cases["C1"]["status"] == IN_REVIEW
    assert "리포트를 작성한 뒤" in texts(at)


def test_reviewer_writes_and_edits_memo(store):
    store.cases["C1"] = make_case("C1", IN_REVIEW, "rev1")
    at = open_page(REVIEWER_USER)
    [t for t in at.text_area if t.label == "새 메모"][0].set_value("경계 다시 볼 것")
    at = click(at, "메모 저장")
    assert [m["content"] for m in store.memos.values()] == ["경계 다시 볼 것"]

    memo_id = next(iter(store.memos))
    at.text_area(key=f"text_{memo_id}").set_value("경계 확인 완료")
    at = click(at, "수정 저장")
    memo = store.memos[memo_id]
    assert memo["content"] == "경계 확인 완료"
    assert memo["edit_log"][0]["prev"] == "경계 다시 볼 것"


def test_empty_memo_shows_error(store):
    store.cases["C1"] = make_case("C1", IN_REVIEW, "rev1")
    at = click(open_page(REVIEWER_USER), "메모 저장")
    assert store.memos == {}
    assert "내용을 입력" in texts(at)


def test_completed_case_is_locked(store):
    store.cases["C1"] = make_case("C1", COMPLETED, "rev1")
    at = open_page(REVIEWER_USER)
    at.radio[0].set_value("완료 목록")
    at = at.run()
    labels = [b.label for b in at.button]
    assert "메모 저장" not in labels and "검토 완료" not in labels
    assert "완료된 케이스는 수정할 수 없습니다" in texts(at)


def test_admin_sends_back_to_re_review(store):
    store.cases["C1"] = make_case("C1", COMPLETED, "rev1")
    at = open_page(ADMIN_USER)
    at.radio[0].set_value("완료")
    at = at.run()
    at = click(at, "재검토로 보내기")
    assert store.cases["C1"]["status"] == COMPLETED
    assert "사유" in texts(at)

    at.radio[0].set_value("완료")
    at = at.run()
    [t for t in at.text_input if t.label == "재검토 사유"][0].set_value("수치 재확인")
    at = click(at, "재검토로 보내기")
    assert store.cases["C1"]["status"] == RE_REVIEW
    assert store.logs[-1]["reason"] == "수치 재확인"


def test_other_reviewer_sees_nothing(store):
    store.cases["C1"] = make_case("C1", ASSIGNED, "rev1")
    at = open_page(OTHER_REVIEWER)
    assert "해당하는 케이스가 없습니다" in texts(at)


def test_missing_fields_show_dash(store):
    store.cases["C1"] = {"case_id": "C1", "status": IN_REVIEW, "assignee": None}
    at = open_page(ADMIN_USER)
    at.radio[0].set_value("진행 중")
    at = at.run()
    assert "None" not in texts(at)
    assert "환자 - · - · 검사일 -" in texts(at)
    table = at.dataframe[0].value
    assert list(table.iloc[0][["환자 ID", "검사", "검사일"]]) == ["-", "-", "-"]
