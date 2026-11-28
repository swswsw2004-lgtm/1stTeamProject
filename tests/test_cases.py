"""
core/cases.py 테스트 (역할2)
실행: python -X utf8 -m pytest tests/test_cases.py -v
Firebase 없이 돌아가도록 가짜 저장소(FakeCaseStore)를 쓴다.
"""
from datetime import date

import pytest

from core.cases import (
    STATUS_RECEIVED,
    build_case_doc,
    check_can_create,
    create_case,
    list_cases,
    normalize_case_id,
    suggest_next_case_id,
    validate_case_input,
)

TODAY = date(2026, 11, 24)

REGISTRAR = {"uid": "reg1", "role": "registrar"}
ADMIN = {"uid": "admin1", "role": "admin"}
REVIEWER = {"uid": "rev1", "role": "reviewer"}


class FakeCaseStore:
    """Firestore 대신 쓰는 메모리 저장소 (FirestoreCaseStore와 같은 함수 이름)."""
    def __init__(self):
        self.docs = {}

    def create_case(self, case_id, doc):
        if case_id in self.docs:
            return False
        self.docs[case_id] = dict(doc)
        return True

    def list_cases(self):
        return [dict(d) for d in self.docs.values()]


def register(store, user=REGISTRAR, **over):
    args = dict(case_id="CASE-001", patient_id="STS_001", exam_type="PET/CT",
                exam_date="2026-11-23", description="좌측 대퇴부 연부조직 종양")
    args.update(over)
    return create_case(store, user, today=TODAY, **args)


# ─────────────── 정상 등록 ───────────────
def test_create_fills_all_firestore_fields():
    """등록하면 firestore 문서 필드가 모두 채워진다"""
    store = FakeCaseStore()
    ok, msg = register(store)
    assert ok, msg
    doc = store.docs["CASE-001"]
    assert doc["case_id"] == "CASE-001"
    assert doc["patient_id"] == "STS_001"
    assert doc["exam_type"] == "PET/CT"
    assert doc["exam_date"] == "2026-11-23"
    assert doc["status"] == STATUS_RECEIVED == "received"   # 역할4 workflow.py와 같은 코드
    assert doc["assignee"] is None
    assert doc["registered_by"] == "reg1"
    assert doc["registered_at"] == doc["updated_at"]
    assert doc["is_mock"] is True


def test_admin_can_create():
    """관리자도 등록할 수 있다"""
    ok, _ = register(FakeCaseStore(), user=ADMIN)
    assert ok


def test_case_id_is_uppercased_and_trimmed():
    """케이스ID는 대문자로 통일되고 공백이 제거된다"""
    store = FakeCaseStore()
    ok, _ = register(store, case_id="  case-007 ")
    assert ok
    assert "CASE-007" in store.docs


def test_exam_date_accepts_date_object():
    """검사일은 date객체로 넣어도 된다"""
    store = FakeCaseStore()
    ok, _ = register(store, exam_date=date(2026, 11, 1))
    assert ok
    assert store.docs["CASE-001"]["exam_date"] == "2026-11-01"


# ─────────────── 권한 ───────────────
def test_reviewer_cannot_create():
    """검토담당자는 등록할 수 없다"""
    store = FakeCaseStore()
    ok, msg = register(store, user=REVIEWER)
    assert not ok and "등록 담당자" in msg
    assert store.docs == {}          # 저장되지 않아야 한다


@pytest.mark.parametrize("user", [None, {}, {"uid": "x"}, {"role": "registrar"}])
def test_rejects_when_not_logged_in(user):
    """로그인하지 않으면 거절"""
    ok, msg = check_can_create(user)
    assert not ok and "로그인" in msg


# ─────────────── 중복 방지 ───────────────
def test_duplicate_id_rejected_without_overwrite():
    """같은 ID로 두번 등록하면 두번째는 거절되고 덮어쓰지 않는다"""
    store = FakeCaseStore()
    assert register(store, description="첫 번째")[0]
    ok, msg = register(store, description="두 번째")
    assert not ok and "이미 있습니다" in msg
    assert store.docs["CASE-001"]["description"] == "첫 번째"


def test_case_insensitive_duplicate():
    """대소문자만 다른 ID도 중복으로 본다"""
    store = FakeCaseStore()
    assert register(store, case_id="CASE-001")[0]
    assert not register(store, case_id="case-001")[0]


# ─────────────── 입력 검사 ───────────────
@pytest.mark.parametrize("case_id, keyword", [
    ("", "입력"),
    ("AB", "3~30자"),
    ("CASE 001", "3~30자"),
    ("케이스-1", "3~30자"),
    ("-CASE", "3~30자"),
])
def test_rejects_invalid_case_id(case_id, keyword):
    """잘못된 케이스ID 거절"""
    errors = validate_case_input(case_id, "STS_001", "PET/CT", "2026-11-23", today=TODAY)
    assert any(keyword in e for e in errors)


def test_rejects_empty_patient_id():
    """환자ID가 비면 거절"""
    assert validate_case_input("CASE-001", "  ", "PET/CT", "2026-11-23", today=TODAY)


def test_exam_type_must_be_in_list():
    """검사구분은 목록에 있는 값만"""
    errors = validate_case_input("CASE-001", "STS_001", "MRI", "2026-11-23", today=TODAY)
    assert any("검사 구분" in e for e in errors)


@pytest.mark.parametrize("bad", ["2026/11/23", "2026-13-01", "어제", ""])
def test_rejects_bad_exam_date_format(bad):
    """검사일 형식이 틀리면 거절"""
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", bad, today=TODAY)
    assert any("형식" in e for e in errors)


def test_rejects_future_exam_date():
    """검사일이 미래면 거절"""
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", "2026-11-25", today=TODAY)
    assert any("이후" in e for e in errors)


def test_rejects_too_long_description():
    """설명이 너무 길면 거절"""
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", "2026-11-23", "가" * 501, today=TODAY)
    assert any("500자" in e for e in errors)


def test_reports_all_problems_at_once():
    """문제가 여러개면 모두 알려준다"""
    store = FakeCaseStore()
    ok, msg = register(store, case_id="", patient_id="", exam_type="X", exam_date="bad")
    assert not ok
    assert msg.count(" / ") == 3     # 4개 문제가 한 번에 안내됨
    assert store.docs == {}


# ─────────────── 기타 ───────────────
def test_normalize_case_id():
    assert normalize_case_id(" sts_001 ") == "STS_001"
    assert normalize_case_id(None) == ""


def test_suggest_next_case_id():
    """다음 케이스ID 제안"""
    assert suggest_next_case_id([]) == "CASE-001"
    assert suggest_next_case_id(["CASE-001", "CASE-003", "STS_001"]) == "CASE-004"


def test_list_sorted_by_latest_registration():
    """목록은 최근 등록순"""
    store = FakeCaseStore()
    store.docs = {
        "A": build_case_doc("A01", "STS_001", "CT", "2026-11-01", "", "reg1", now="2026-11-20T00:00:00+00:00"),
        "B": build_case_doc("B01", "STS_002", "CT", "2026-11-01", "", "reg1", now="2026-11-22T00:00:00+00:00"),
    }
    assert [c["case_id"] for c in list_cases(store)] == ["B01", "A01"]


# ─────────────── 검색·필터 (11/27) ───────────────
from core.cases import filter_cases, validate_filters  # noqa: E402

SAMPLE = [
    {"case_id": "CASE-001", "patient_id": "STS_001", "exam_type": "PET/CT", "exam_date": "2026-11-20",
     "status": "received", "description": "교육용 모의 케이스 · TCIA STS_001 PET/CT"},
    {"case_id": "CASE-002", "patient_id": "STS_002", "exam_type": "PET/CT", "exam_date": "2026-11-25",
     "status": "assigned", "description": ""},
    {"case_id": "TEST-001", "patient_id": "TEST_P01", "exam_type": "CT", "exam_date": "2026-11-27",
     "status": "re_review", "description": "역할4 검토 화면 쓰기 시험용"},
    {"case_id": "MOCK-0002", "exam_date": "2026-11-19", "status": "in_review"},   # 일부 필드 없음
]
SUMMARY = {"CASE-001": {"CT": 1, "PT": 1, "RTSTRUCT": 2}, "CASE-002": {"CT": 1}}


def ids(cases):
    return [c["case_id"] for c in cases]


def test_filter_without_conditions_returns_all():
    """조건이 없으면 전부"""
    assert ids(filter_cases(SAMPLE)) == ids(SAMPLE)


@pytest.mark.parametrize("keyword, expected", [
    ("sts_00", ["CASE-001", "CASE-002"]),        # 환자 ID, 대소문자 무시
    ("case-002", ["CASE-002"]),                   # 케이스 ID
    ("시험용", ["TEST-001"]),                      # 설명
    ("TCIA PET", ["CASE-001"]),                   # 단어 여러 개는 모두 포함
    ("없는말", []),
    ("   ", ["CASE-001", "CASE-002", "TEST-001", "MOCK-0002"]),   # 공백만 → 조건 없음
])
def test_filter_keyword(keyword, expected):
    """검색어"""
    assert ids(filter_cases(SAMPLE, keyword=keyword)) == expected


def test_filter_status_and_exam_type():
    """상태 검사구분 필터"""
    assert ids(filter_cases(SAMPLE, statuses=["received", "assigned"])) == ["CASE-001", "CASE-002"]
    assert ids(filter_cases(SAMPLE, exam_types=["CT"])) == ["TEST-001"]


def test_filter_exam_date_range_inclusive():
    """검사일 범위는 양끝 포함"""
    assert ids(filter_cases(SAMPLE, date_from="2026-11-20", date_to="2026-11-25")) == ["CASE-001", "CASE-002"]
    assert ids(filter_cases(SAMPLE, date_from=date(2026, 11, 26))) == ["TEST-001"]


def test_filter_modalities_requires_all():
    """영상종류 필터는 모두 가진 케이스만"""
    assert ids(filter_cases(SAMPLE, modalities=["CT"], image_summary=SUMMARY)) == ["CASE-001", "CASE-002"]
    assert ids(filter_cases(SAMPLE, modalities=["CT", "PT"], image_summary=SUMMARY)) == ["CASE-001"]
    assert ids(filter_cases(SAMPLE, modalities=["CT"])) == []          # 영상 정보가 없으면 해당 없음


def test_filter_multiple_conditions():
    """조건 여러개는 모두 만족"""
    assert ids(filter_cases(SAMPLE, keyword="STS", statuses=["assigned"],
                            modalities=["CT"], image_summary=SUMMARY)) == ["CASE-002"]


def test_filter_handles_missing_fields():
    """필드가 빠진 케이스도 오류없이 걸러진다"""
    assert ids(filter_cases(SAMPLE, keyword="mock")) == ["MOCK-0002"]
    assert "MOCK-0002" not in ids(filter_cases(SAMPLE, exam_types=["PET/CT"]))


@pytest.mark.parametrize("d1, d2, keyword", [
    ("2026-11-25", "2026-11-20", "늦습니다"),
    ("2026/11/20", None, "시작일"),
    (None, "어제", "종료일"),
])
def test_validate_filters_rejects_bad_dates(d1, d2, keyword):
    """잘못된 날짜 필터 거절"""
    assert any(keyword in e for e in validate_filters(d1, d2))


def test_validate_filters_accepts_good_dates():
    """정상 날짜 필터는 통과"""
    assert validate_filters("2026-11-01", "2026-11-30") == []
    assert validate_filters() == []
