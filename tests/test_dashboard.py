from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import firebase, review_store
from core.auth import User
from core.dashboard import needs_attention, reviewer_summary, status_counts
from core.workflow import (
    ADMIN, REGISTRAR, REVIEWER,
    RECEIVED, ASSIGNED, IN_REVIEW, COMPLETED, RE_REVIEW,
)

PAGE = str(Path(__file__).parent.parent / "pages" / "5_dashboard.py")

ADMIN_USER = User(uid="admin1", email="a@test.com", name="관리자", role=ADMIN)
REVIEWER_USER = User(uid="rev1", email="r1@test.com", name="검토자1", role=REVIEWER)

USERS = [
    {"id": "admin1", "name": "관리자", "role": ADMIN},
    {"id": "rev1", "name": "검토자1", "role": REVIEWER},
    {"id": "rev2", "name": "", "email": "r2@test.com", "role": REVIEWER},
    {"id": "reg1", "name": "등록자", "role": REGISTRAR},
]


def case(case_id, status, assignee=None):
    return {"case_id": case_id, "status": status, "assignee": assignee}


CASES = [
    case("C1", RECEIVED),
    case("C2", ASSIGNED, "rev1"),
    case("C3", IN_REVIEW, "rev1"),
    case("C4", RE_REVIEW, "rev1"),
    case("C5", COMPLETED, "rev2"),
    case("C6", COMPLETED, "rev2"),
]


def test_status_counts():
    assert status_counts(CASES) == {RECEIVED: 1, ASSIGNED: 1, IN_REVIEW: 1,
                                    COMPLETED: 2, RE_REVIEW: 1}


def test_status_counts_empty_has_all_statuses():
    assert status_counts([]) == {RECEIVED: 0, ASSIGNED: 0, IN_REVIEW: 0,
                                 COMPLETED: 0, RE_REVIEW: 0}


def test_status_counts_skips_unknown_status():
    assert sum(status_counts([case("X", "weird")]).values()) == 0


def test_reviewer_summary():
    rows = reviewer_summary(CASES, USERS)
    assert rows == [
        {"검토 담당자": "검토자1", "배정": 1, "검토 중": 2, "완료": 0},
        {"검토 담당자": "r2@test.com", "배정": 0, "검토 중": 0, "완료": 2},
    ]


def test_reviewer_summary_only_reviewers():
    names = [r["검토 담당자"] for r in reviewer_summary(CASES, USERS)]
    assert "관리자" not in names and "등록자" not in names


def test_reviewer_with_no_cases_is_listed():
    rows = reviewer_summary([], USERS)
    assert {r["검토 담당자"] for r in rows} == {"검토자1", "r2@test.com"}
    assert all(r["배정"] == r["검토 중"] == r["완료"] == 0 for r in rows)


def test_needs_attention():
    cases = CASES + [
        case("BAD1", IN_REVIEW),
        case("BAD2", ASSIGNED, "reg1"),
        case("BAD3", "weird"),
    ]
    problems = dict(needs_attention(cases, USERS))
    assert set(problems) == {"BAD1", "BAD2", "BAD3"}
    assert "담당자가 없습니다" in problems["BAD1"]
    assert "검토 담당자 계정이 아닙니다" in problems["BAD2"]
    assert "알 수 없는 상태" in problems["BAD3"]


def test_needs_attention_ok_cases():
    assert needs_attention(CASES, USERS) == []


class FakeStore:
    def __init__(self, cases, logs):
        self.cases = cases
        self.logs = logs

    def list_cases(self):
        return [dict(c) for c in self.cases]

    def list_users(self):
        return [dict(u) for u in USERS]

    def list_recent_logs(self, limit=10):
        return sorted(self.logs, key=lambda log: log["at"], reverse=True)[:limit]


LOGS = [
    {"case_id": "C2", "from_status": RECEIVED, "to_status": ASSIGNED, "actor": "admin1",
     "at": "2026-11-27T02:22:00+00:00", "reason": ""},
    {"case_id": "C4", "from_status": COMPLETED, "to_status": RE_REVIEW, "actor": "admin1",
     "at": "2026-11-27T02:31:00+00:00", "reason": "수치 재확인"},
]


@pytest.fixture
def fake(monkeypatch):
    def setup(cases=CASES, logs=LOGS):
        s = FakeStore(cases, logs)
        monkeypatch.setattr(review_store, "FirestoreReviewStore", lambda db: s)
        monkeypatch.setattr(firebase, "get_db", lambda: None)
        return s
    return setup


def open_page(user):
    at = AppTest.from_file(PAGE, default_timeout=10)
    if user is not None:
        at.session_state["user"] = user
    return at.run()


def all_text(at):
    return " ".join(str(e.value) for e in list(at.markdown) + list(at.info)
                    + list(at.warning) + list(at.subheader))


def test_page_needs_login(fake):
    fake()
    assert "로그인이 필요합니다" in all_text(open_page(None))


def test_page_admin_only(fake):
    fake()
    at = open_page(REVIEWER_USER)
    assert "관리자만 볼 수 있습니다" in all_text(at)
    assert len(at.metric) == 0


def test_page_shows_counts_and_tables(fake):
    fake()
    at = open_page(ADMIN_USER)
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"접수": "1", "배정": "1", "검토 중": "1", "완료": "2", "재검토": "1"}
    assert "전체 6건" in all_text(at)

    reviewers = at.dataframe[0].value
    assert list(reviewers["검토 담당자"]) == ["검토자1", "r2@test.com"]

    logs = at.dataframe[1].value
    assert list(logs["시간"]) == ["2026-11-27 11:31", "2026-11-27 11:22"]
    assert list(logs["변경"]) == ["완료 → 재검토", "접수 → 배정"]
    assert list(logs["실행자"]) == ["관리자", "관리자"]
    assert list(logs["사유"]) == ["수치 재확인", "-"]


def test_page_warns_about_broken_case(fake):
    fake(cases=CASES + [case("MOCK-0002", IN_REVIEW)])
    at = open_page(ADMIN_USER)
    assert "확인이 필요한 케이스 (1)" in all_text(at)
    assert "MOCK-0002" in all_text(at)


def test_page_without_data(fake):
    fake(cases=[], logs=[])
    at = open_page(ADMIN_USER)
    assert not at.exception
    assert "전체 0건" in all_text(at)
    assert "기록이 없습니다" in all_text(at)
    assert "확인이 필요한" not in all_text(at)
