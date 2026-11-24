"""
케이스 등록·조회 모듈
담당: 역할2 (케이스·영상 관리·뷰어)
위치: core/cases.py
기준: docs/firestore.md 2-2 `cases/{case_id}` (역할1), 상태 코드는 core/workflow.py (역할4)

구조 (역할4 workflow.py와 같은 방식):
    - 입력 검사·권한 검사·문서 만들기 → 이 파일의 함수 (DB 없이 테스트 가능)
    - 실제 저장 → store 객체 (FirestoreCaseStore). 테스트에서는 가짜 store를 넣는다.

화면에서 쓰는 법:
    from core.cases import FirestoreCaseStore, create_case
    ok, msg = create_case(FirestoreCaseStore(get_db()), user,
                          case_id="CASE-001", patient_id="STS_001",
                          exam_type="PET/CT", exam_date="2026-11-24", description="...")
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

# 상태 코드는 역할4와 같은 값을 쓴다 (workflow.py의 RECEIVED와 동일)
STATUS_RECEIVED = "received"

# 케이스를 만들 수 있는 역할 — 11/24 회의 확정 전 초안.
# 역할1의 core/permissions.py가 merge되면 그쪽 함수로 바꾼다.
CAN_CREATE_ROLES = {"registrar", "admin"}

EXAM_TYPES = ("PET/CT", "CT", "PET")

# 케이스 ID: 영문 대문자·숫자로 시작, 대문자·숫자·-·_ 3~30자 (예: CASE-001, STS_001)
# 형식(CASE-001 vs STS_001)은 회의 확정 사항(docs/firestore.md 4장 1번). 둘 다 통과한다.
CASE_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,29}$")
DESCRIPTION_MAX = 500


def now_iso() -> str:
    """현재 시간 (UTC ISO 문자열). 역할4 status_logs와 같은 형식.
    시간 저장 형식이 회의에서 Timestamp로 바뀌면 이 함수만 고친다."""
    return datetime.now(timezone.utc).isoformat()


def _role(user) -> str | None:
    return user.get("role") if user else None


def _uid(user) -> str | None:
    return user.get("uid") if user else None


# ─────────────────────────────────────────────
# 입력 검사
# ─────────────────────────────────────────────
def normalize_case_id(case_id: str) -> str:
    """앞뒤 공백 제거 + 대문자로 통일 ('case-001 ' → 'CASE-001')."""
    return (case_id or "").strip().upper()


def validate_case_input(case_id: str, patient_id: str, exam_type: str,
                        exam_date: str | date, description: str = "",
                        today: date | None = None) -> list[str]:
    """입력값을 검사해서 문제 목록을 돌려준다. 빈 목록이면 통과.
    화면에 그대로 보여줄 수 있는 한국어 문장으로 만든다."""
    errors = []
    today = today or date.today()

    cid = normalize_case_id(case_id)
    if not cid:
        errors.append("케이스 ID를 입력하세요.")
    elif not CASE_ID_PATTERN.match(cid):
        errors.append("케이스 ID는 영문 대문자·숫자·-·_ 로 3~30자여야 합니다. (예: CASE-001)")

    if not (patient_id or "").strip():
        errors.append("환자 ID를 입력하세요. (예: STS_001)")

    if exam_type not in EXAM_TYPES:
        errors.append(f"검사 구분은 {', '.join(EXAM_TYPES)} 중 하나여야 합니다.")

    d = _parse_date(exam_date)
    if d is None:
        errors.append("검사일 형식이 올바르지 않습니다. (YYYY-MM-DD)")
    elif d > today:
        errors.append("검사일은 오늘 이후일 수 없습니다.")

    if len(description or "") > DESCRIPTION_MAX:
        errors.append(f"설명은 {DESCRIPTION_MAX}자 이하로 입력하세요.")
    return errors


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


# ─────────────────────────────────────────────
# 권한
# ─────────────────────────────────────────────
def check_can_create(user) -> tuple[bool, str]:
    """케이스 생성 권한. 화면에서 버튼을 숨기는 것과 별개로, 저장 직전에 반드시 다시 검사한다."""
    if not user or not _uid(user) or not _role(user):
        return False, "로그인이 필요합니다."
    if _role(user) not in CAN_CREATE_ROLES:
        return False, "케이스 등록은 등록 담당자·관리자만 할 수 있습니다."
    return True, "가능합니다."


# ─────────────────────────────────────────────
# 문서 만들기 · 저장
# ─────────────────────────────────────────────
def build_case_doc(case_id, patient_id, exam_type, exam_date, description, registered_by,
                   now: str | None = None) -> dict:
    """docs/firestore.md 2-2 필드 그대로 cases 문서를 만든다."""
    now = now or now_iso()
    return {
        "case_id": normalize_case_id(case_id),
        "patient_id": patient_id.strip(),
        "exam_type": exam_type,
        "exam_date": _parse_date(exam_date).isoformat(),
        "description": (description or "").strip(),
        "status": STATUS_RECEIVED,
        "assignee": None,
        "registered_by": registered_by,
        "registered_at": now,
        "updated_at": now,
        "is_mock": True,          # 교육용 모의 케이스
    }


def create_case(store, user, case_id, patient_id, exam_type, exam_date,
                description: str = "", today: date | None = None) -> tuple[bool, str]:
    """케이스 등록. (성공 여부, 화면에 보여줄 메시지)를 돌려준다.
    순서: 권한 검사 → 입력 검사 → 저장(같은 ID가 있으면 거절)"""
    ok, msg = check_can_create(user)
    if not ok:
        return False, msg

    errors = validate_case_input(case_id, patient_id, exam_type, exam_date, description, today)
    if errors:
        return False, " / ".join(errors)

    doc = build_case_doc(case_id, patient_id, exam_type, exam_date, description, _uid(user))
    # 같은 ID가 이미 있으면 덮어쓰지 않고 거절 → 연속 클릭으로 인한 중복 등록도 막힌다
    if not store.create_case(doc["case_id"], doc):
        return False, f"케이스 ID '{doc['case_id']}'가 이미 있습니다. 다른 ID를 입력하세요."
    return True, f"케이스 '{doc['case_id']}'를 등록했습니다."


def suggest_next_case_id(existing_ids, prefix: str = "CASE-") -> str:
    """CASE-001, CASE-002 … 다음 번호를 제안한다 (화면의 기본값용)."""
    nums = [int(m.group(1)) for cid in existing_ids
            if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", cid or ""))]
    return f"{prefix}{(max(nums) + 1) if nums else 1:03d}"


def list_cases(store) -> list[dict]:
    """전체 케이스를 최근 등록순으로. (검색·필터는 11/27 작업)"""
    return sorted(store.list_cases(), key=lambda c: c.get("registered_at") or "", reverse=True)


# ─────────────────────────────────────────────
# 실제 Firestore 저장소
# ─────────────────────────────────────────────
class FirestoreCaseStore:
    """cases 컬렉션 읽기·쓰기. db는 core.firebase.get_db()로 받은 클라이언트."""
    COLLECTION = "cases"

    def __init__(self, db):
        self.db = db

    def create_case(self, case_id: str, doc: dict) -> bool:
        """문서가 없을 때만 만든다. 이미 있으면 False (덮어쓰기 금지)."""
        from google.api_core.exceptions import AlreadyExists  # firebase-admin 설치 시 함께 설치됨
        try:
            self.db.collection(self.COLLECTION).document(case_id).create(doc)
            return True
        except AlreadyExists:
            return False

    def list_cases(self) -> list[dict]:
        return [d.to_dict() for d in self.db.collection(self.COLLECTION).stream()]

    def get_case(self, case_id: str) -> dict | None:
        snap = self.db.collection(self.COLLECTION).document(case_id).get()
        return snap.to_dict() if snap.exists else None
