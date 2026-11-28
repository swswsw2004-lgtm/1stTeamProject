from datetime import datetime, timezone

import pytest

from core import memos as mm
from core.memos import MEMO, REPORT
from core.workflow import (
    ADMIN, REGISTRAR, REVIEWER,
    RECEIVED, ASSIGNED, IN_REVIEW, COMPLETED, RE_REVIEW,
)


class FakeStore:
    def __init__(self):
        self.cases = {}
        self.memos = {}
        self.race = False

    def get_case(self, case_id):
        case = self.cases.get(case_id)
        return dict(case) if case else None

    def get_memo(self, memo_id):
        memo = self.memos.get(memo_id)
        return dict(memo) if memo else None

    def list_memos(self, case_id):
        return [dict(m) for m in self.memos.values() if m["case_id"] == case_id]

    def add_memo(self, memo_id, memo):
        if memo_id in self.memos:
            return False
        self.memos[memo_id] = memo
        return True

    def update_memo(self, memo_id, expected_content, changes):
        memo = self.memos[memo_id]
        if self.race:
            memo["content"] = "다른 사람이 먼저 고친 내용"
        if memo["content"] != expected_content:
            return False
        memo.update(changes)
        return True


ADMIN_USER = {"uid": "admin1", "role": ADMIN}
REGISTRAR_USER = {"uid": "reg1", "role": REGISTRAR}
REVIEWER_USER = {"uid": "rev1", "role": REVIEWER}
OTHER_REVIEWER = {"uid": "rev2", "role": REVIEWER}


@pytest.fixture
def store():
    s = FakeStore()
    s.cases["C1"] = {"case_id": "C1", "patient_id": "STS_001", "exam_type": "PET/CT",
                     "exam_date": "2026-11-23", "status": IN_REVIEW, "assignee": "rev1"}
    return s


def set_status(store, status):
    store.cases["C1"]["status"] = status


def assert_rejected(result, keyword):
    ok, message = result
    assert not ok
    assert keyword in message


def test_write_memo(store):
    ok, _ = mm.write_memo(store, "m1", "C1", REVIEWER_USER, "  병변 경계 확인 필요  ",
                          image_id="img1", history_id="h1")
    assert ok
    memo = store.memos["m1"]
    assert memo["content"] == "병변 경계 확인 필요"
    assert memo["kind"] == MEMO
    assert memo["author_uid"] == "rev1"
    assert memo["image_id"] == "img1" and memo["history_id"] == "h1"
    assert memo["edit_log"] == []
    assert memo["created_at"] == memo["updated_at"]


def test_write_report_makes_has_report_true(store):
    assert not mm.has_report(store.list_memos("C1"))
    assert mm.write_memo(store, "r1", "C1", REVIEWER_USER, "소견 없음", kind=REPORT)[0]
    assert mm.has_report(store.list_memos("C1"))


def test_memo_is_not_report(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "메모")
    assert not mm.has_report(store.list_memos("C1"))


def test_only_one_report_per_case(store):
    mm.write_memo(store, "r1", "C1", REVIEWER_USER, "첫 리포트", kind=REPORT)
    result = mm.write_memo(store, "r2", "C1", REVIEWER_USER, "두 번째", kind=REPORT)
    assert_rejected(result, "하나만")
    assert "r2" not in store.memos


def test_same_request_saved_once(store):
    first = mm.write_memo(store, "m1", "C1", REVIEWER_USER, "메모")
    second = mm.write_memo(store, "m1", "C1", REVIEWER_USER, "메모")
    assert first[0]
    assert_rejected(second, "이미 저장된")
    assert len(store.memos) == 1


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_content_rejected(store, content):
    assert_rejected(mm.write_memo(store, "m1", "C1", REVIEWER_USER, content), "내용을 입력")
    assert store.memos == {}


def test_too_long_content_rejected(store):
    result = mm.write_memo(store, "m1", "C1", REVIEWER_USER, "가" * (mm.MAX_LENGTH + 1))
    assert_rejected(result, "자 이하")
    assert mm.write_memo(store, "m2", "C1", REVIEWER_USER, "가" * mm.MAX_LENGTH)[0]


def test_unknown_kind_rejected(store):
    assert_rejected(mm.write_memo(store, "m1", "C1", REVIEWER_USER, "x", kind="note"), "알 수 없는")


def test_missing_request_id_rejected(store):
    assert_rejected(mm.write_memo(store, "", "C1", REVIEWER_USER, "x"), "요청 번호")


@pytest.mark.parametrize("user,keyword", [
    (None, "로그인"),
    (ADMIN_USER, "검토 담당자만"),
    (REGISTRAR_USER, "검토 담당자만"),
    (OTHER_REVIEWER, "배정된 담당자"),
])
def test_write_permission(store, user, keyword):
    assert_rejected(mm.write_memo(store, "m1", "C1", user, "메모"), keyword)
    assert store.memos == {}


def test_write_on_missing_case(store):
    assert_rejected(mm.write_memo(store, "m1", "NOPE", REVIEWER_USER, "메모"), "찾을 수 없습니다")


@pytest.mark.parametrize("status,keyword", [
    (RECEIVED, "이 상태에서는"),
    (ASSIGNED, "이 상태에서는"),
    (COMPLETED, "완료된 케이스"),
])
def test_write_blocked_by_status(store, status, keyword):
    set_status(store, status)
    assert_rejected(mm.write_memo(store, "m1", "C1", REVIEWER_USER, "메모"), keyword)


def test_write_allowed_in_re_review(store):
    set_status(store, RE_REVIEW)
    assert mm.write_memo(store, "m1", "C1", REVIEWER_USER, "재검토 메모")[0]


def test_edit_keeps_history(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    assert mm.edit_memo(store, "m1", REVIEWER_USER, "두 번째")[0]
    assert mm.edit_memo(store, "m1", REVIEWER_USER, "세 번째")[0]

    memo = store.memos["m1"]
    assert memo["content"] == "세 번째"
    assert [e["prev"] for e in memo["edit_log"]] == ["처음", "두 번째"]
    assert all(e["by_uid"] == "rev1" for e in memo["edit_log"])
    assert memo["updated_at"] == memo["edit_log"][-1]["at"]


def test_edit_same_content_rejected(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    assert_rejected(mm.edit_memo(store, "m1", REVIEWER_USER, "  처음 "), "바뀐 내용이 없습니다")
    assert store.memos["m1"]["edit_log"] == []


def test_double_click_edit_logs_once(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    first = mm.edit_memo(store, "m1", REVIEWER_USER, "수정")
    second = mm.edit_memo(store, "m1", REVIEWER_USER, "수정")
    assert first[0] and not second[0]
    assert len(store.memos["m1"]["edit_log"]) == 1


def test_edit_race(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    store.race = True
    assert_rejected(mm.edit_memo(store, "m1", REVIEWER_USER, "내 수정"), "먼저 저장")
    assert store.memos["m1"]["content"] == "다른 사람이 먼저 고친 내용"


def test_completed_case_cannot_be_edited_until_re_review(store):
    mm.write_memo(store, "r1", "C1", REVIEWER_USER, "리포트", kind=REPORT)
    set_status(store, COMPLETED)
    assert_rejected(mm.edit_memo(store, "r1", REVIEWER_USER, "고침"), "완료된 케이스")
    assert store.memos["r1"]["content"] == "리포트"

    set_status(store, RE_REVIEW)
    assert mm.edit_memo(store, "r1", REVIEWER_USER, "재검토 후 고침")[0]
    assert store.memos["r1"]["edit_log"][0]["prev"] == "리포트"


def test_edit_permission(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    assert_rejected(mm.edit_memo(store, "m1", OTHER_REVIEWER, "x"), "배정된 담당자")
    assert_rejected(mm.edit_memo(store, "m1", ADMIN_USER, "x"), "검토 담당자만")
    assert_rejected(mm.edit_memo(store, "m1", None, "x"), "로그인")
    assert_rejected(mm.edit_memo(store, "nope", REVIEWER_USER, "x"), "찾을 수 없습니다")


def test_edit_empty_rejected(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "처음")
    assert_rejected(mm.edit_memo(store, "m1", REVIEWER_USER, " "), "내용을 입력")


def test_list_case_memos_sorted(store):
    mm.write_memo(store, "m1", "C1", REVIEWER_USER, "첫째")
    mm.write_memo(store, "m2", "C1", REVIEWER_USER, "둘째")
    store.memos["m1"]["created_at"] = "2026-11-24T10:00:00+00:00"
    store.memos["m2"]["created_at"] = "2026-11-24T09:00:00+00:00"
    ok, memos = mm.list_case_memos(store, "C1", ADMIN_USER)
    assert ok
    assert [m["content"] for m in memos] == ["둘째", "첫째"]


def test_list_case_memos_needs_login(store):
    assert_rejected(mm.list_case_memos(store, "C1", None), "로그인")
    assert_rejected(mm.list_case_memos(store, "NOPE", ADMIN_USER), "찾을 수 없습니다")


def test_build_report_draft(store):
    case = store.get_case("C1")
    histories = [
        {"executed_at": "2026-11-24T10:05:00+00:00", "algorithm": "otsu", "params": {},
         "features": None},
        {"executed_at": "2026-11-24T10:00:00+00:00", "algorithm": "clahe",
         "params": {"clip_limit": 2.0}, "features": {"mean": 41.2, "std": 10.9}},
    ]
    logs = [
        {"at": "2026-11-24T09:00:00+00:00", "from_status": RECEIVED, "to_status": ASSIGNED,
         "reason": ""},
        {"at": "2026-11-24T11:00:00+00:00", "from_status": COMPLETED, "to_status": RE_REVIEW,
         "reason": "수치 재확인"},
    ]
    text = mm.build_report_draft(case, histories, logs)
    assert "케이스: C1 (환자 STS_001)" in text
    assert "현재 상태: 검토 중" in text
    assert text.index("clahe") < text.index("otsu")
    assert "ROI mean 41.2, std 10.9" in text
    assert "접수 → 배정" in text
    assert "완료 → 재검토 (사유: 수치 재확인)" in text
    assert text.rstrip().endswith("[소견]")


def test_build_report_draft_empty():
    case = {"case_id": "C9", "status": RECEIVED}
    text = mm.build_report_draft(case, [], [])
    assert text.count("- 없음") == 2
    assert "환자 -" in text


def test_report_draft_uses_korean_time():
    case = {"case_id": "C1", "status": IN_REVIEW}
    logs = [{"at": "2026-11-27T02:22:00+00:00", "from_status": RECEIVED,
             "to_status": ASSIGNED, "reason": ""}]
    histories = [{"executed_at": "2026-11-27T02:30:00+00:00", "algorithm": "clahe",
                  "params": {}, "features": None}]
    text = mm.build_report_draft(case, histories, logs)
    assert "- 2026-11-27 11:22 접수 → 배정" in text
    assert "- 2026-11-27 11:30 clahe" in text
    assert "T02:" not in text


def test_report_draft_accepts_datetime_from_firestore():
    case = {"case_id": "C1", "status": IN_REVIEW}
    histories = [
        {"executed_at": datetime(2026, 11, 27, 3, 0, tzinfo=timezone.utc), "algorithm": "otsu",
         "params": {}, "features": None},
        {"executed_at": "2026-11-27T02:00:00+00:00", "algorithm": "clahe",
         "params": {}, "features": None},
        {"executed_at": datetime(2026, 11, 27, 1, 0), "algorithm": "bilateral",
         "params": {}, "features": None},
    ]
    text = mm.build_report_draft(case, histories, [])
    assert text.index("bilateral") < text.index("clahe") < text.index("otsu")
    assert "2026-11-27 12:00 otsu" in text
    assert "2026-11-27 10:00 bilateral" in text


def test_report_draft_missing_values():
    case = {"case_id": "C9", "status": RECEIVED, "patient_id": None, "exam_type": None}
    histories = [{"algorithm": "otsu", "params": {}, "features": None}]
    text = mm.build_report_draft(case, histories, [])
    assert "None" not in text
    assert "환자 -" in text and "검사: - / -" in text
    assert "- - otsu" in text
