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
def test_등록하면_firestore_문서_필드가_모두_채워진다():
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


def test_관리자도_등록할_수_있다():
    ok, _ = register(FakeCaseStore(), user=ADMIN)
    assert ok


def test_케이스ID는_대문자로_통일되고_공백이_제거된다():
    store = FakeCaseStore()
    ok, _ = register(store, case_id="  case-007 ")
    assert ok
    assert "CASE-007" in store.docs


def test_검사일은_date객체로_넣어도_된다():
    store = FakeCaseStore()
    ok, _ = register(store, exam_date=date(2026, 11, 1))
    assert ok
    assert store.docs["CASE-001"]["exam_date"] == "2026-11-01"


# ─────────────── 권한 ───────────────
def test_검토담당자는_등록할_수_없다():
    store = FakeCaseStore()
    ok, msg = register(store, user=REVIEWER)
    assert not ok and "등록 담당자" in msg
    assert store.docs == {}          # 저장되지 않아야 한다


@pytest.mark.parametrize("user", [None, {}, {"uid": "x"}, {"role": "registrar"}])
def test_로그인하지_않으면_거절(user):
    ok, msg = check_can_create(user)
    assert not ok and "로그인" in msg


# ─────────────── 중복 방지 ───────────────
def test_같은_ID로_두번_등록하면_두번째는_거절되고_덮어쓰지_않는다():
    store = FakeCaseStore()
    assert register(store, description="첫 번째")[0]
    ok, msg = register(store, description="두 번째")
    assert not ok and "이미 있습니다" in msg
    assert store.docs["CASE-001"]["description"] == "첫 번째"


def test_대소문자만_다른_ID도_중복으로_본다():
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
def test_잘못된_케이스ID_거절(case_id, keyword):
    errors = validate_case_input(case_id, "STS_001", "PET/CT", "2026-11-23", today=TODAY)
    assert any(keyword in e for e in errors)


def test_환자ID가_비면_거절():
    assert validate_case_input("CASE-001", "  ", "PET/CT", "2026-11-23", today=TODAY)


def test_검사구분은_목록에_있는_값만():
    errors = validate_case_input("CASE-001", "STS_001", "MRI", "2026-11-23", today=TODAY)
    assert any("검사 구분" in e for e in errors)


@pytest.mark.parametrize("bad", ["2026/11/23", "2026-13-01", "어제", ""])
def test_검사일_형식이_틀리면_거절(bad):
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", bad, today=TODAY)
    assert any("형식" in e for e in errors)


def test_검사일이_미래면_거절():
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", "2026-11-25", today=TODAY)
    assert any("이후" in e for e in errors)


def test_설명이_너무_길면_거절():
    errors = validate_case_input("CASE-001", "STS_001", "PET/CT", "2026-11-23", "가" * 501, today=TODAY)
    assert any("500자" in e for e in errors)


def test_문제가_여러개면_모두_알려준다():
    store = FakeCaseStore()
    ok, msg = register(store, case_id="", patient_id="", exam_type="X", exam_date="bad")
    assert not ok
    assert msg.count(" / ") == 3     # 4개 문제가 한 번에 안내됨
    assert store.docs == {}


# ─────────────── 기타 ───────────────
def test_normalize_case_id():
    assert normalize_case_id(" sts_001 ") == "STS_001"
    assert normalize_case_id(None) == ""


def test_다음_케이스ID_제안():
    assert suggest_next_case_id([]) == "CASE-001"
    assert suggest_next_case_id(["CASE-001", "CASE-003", "STS_001"]) == "CASE-004"


def test_목록은_최근_등록순():
    store = FakeCaseStore()
    store.docs = {
        "A": build_case_doc("A01", "STS_001", "CT", "2026-11-01", "", "reg1", now="2026-11-20T00:00:00+00:00"),
        "B": build_case_doc("B01", "STS_002", "CT", "2026-11-01", "", "reg1", now="2026-11-22T00:00:00+00:00"),
    }
    assert [c["case_id"] for c in list_cases(store)] == ["B01", "A01"]
