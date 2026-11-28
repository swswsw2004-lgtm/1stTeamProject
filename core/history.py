"""
처리 이력(processing_history) 저장·조회·재현
담당: 역할3
위치: core/history.py
기준: docs/firestore.md 2-4 `processing_history/{history_id}`

흐름
  1) 화면에서 처리 결과가 나오면 new_request_id()로 요청 ID를 하나 만든다 (같은 결과면 같은 ID 유지)
  2) save_history()가 ① 권한·상태 확인 ② 결과 영상 파일 저장 ③ Firestore 기록 을 한 번에 한다
     - 문서 ID = 요청 ID라서 같은 요청을 두 번 저장하면 두 번째는 거절 (연속 클릭 중복 방지)
     - Firestore 기록이 실패하면 방금 저장한 결과 파일을 지워서 파일과 기록이 어긋나지 않게 한다
     - 원본 영상은 읽기만 하고, 결과는 storage_root/results/<케이스ID>/<이력ID>.png 에 따로 저장
  3) 역할4 검토 화면은 review_store.list_histories(case_id)로 이 기록을 읽어 리포트 초안에 넣는다
  4) rerun_history()로 저장된 설정(창·알고리즘·파라미터·ROI) 그대로 다시 실행해 같은 결과인지 확인한다

사용 예:
    from core.history import FirestoreHistoryStore, new_request_id, save_history
    ok, msg, hid = save_history(store, storage_root, user, case, image_id=..., slice_index=...,
                                algorithm="otsu", params={...}, window={...}, roi={...},
                                features={...}, result_image=result, history_id=request_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from core.processing import ALGO_VERSION, ALGORITHMS, ProcessingError, run_algorithm, window_to_uint8
from core.workflow import EDITABLE_STATUSES, COMPLETED, REVIEWER, is_logged_in

COLLECTION = "processing_history"
ROI_KEYS = ("x", "y", "w", "h")


class HistoryError(ValueError):
    """화면에 그대로 보여 줄 한국어 메시지를 담는 오류."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_request_id() -> str:
    """요청 ID (= Firestore 문서 ID). 같은 처리 결과를 저장하는 동안 화면에서 하나를 유지한다."""
    return uuid.uuid4().hex[:20]


# ---------------------------------------------------------------
# 권한·상태 확인 (메모·리포트와 같은 규칙: core/workflow.py)
# ---------------------------------------------------------------
def check_can_save_history(case: dict | None, user) -> tuple[bool, str]:
    """배정된 검토 담당자가 '검토 중' 또는 '재검토' 상태일 때만 처리 이력을 남길 수 있다.
    (화면에서 버튼을 숨기는 것과 별개로, 저장 함수 안에서 다시 확인한다)"""
    if not is_logged_in(user):
        return False, "로그인이 필요합니다."
    if case is None:
        return False, "케이스를 찾을 수 없습니다."
    status = case.get("status")
    if status == COMPLETED:
        return False, "완료된 케이스에는 처리 이력을 남길 수 없습니다. 재검토로 바꾼 뒤 다시 시도해 주세요."
    if status not in EDITABLE_STATUSES:
        return False, "케이스가 '검토 중' 또는 '재검토' 상태일 때만 처리 이력을 남길 수 있습니다."
    if user["role"] != REVIEWER:
        return False, "처리 이력은 검토 담당자만 남길 수 있습니다."
    if case.get("assignee") != user["uid"]:
        return False, "이 케이스에 배정된 담당자만 처리 이력을 남길 수 있습니다."
    return True, "저장할 수 있습니다."


# ---------------------------------------------------------------
# 기록 만들기
# ---------------------------------------------------------------
def _roi_dict(roi) -> dict | None:
    if roi is None:
        return None
    if isinstance(roi, dict):
        missing = [k for k in ROI_KEYS if k not in roi]
        if missing:
            raise HistoryError(f"ROI에 {', '.join(missing)} 값이 없습니다.")
        return {k: (int(v) if k in ROI_KEYS else v) for k, v in roi.items()}
    if len(roi) != 4:
        raise HistoryError("ROI는 (x, y, 너비, 높이) 4개 값이어야 합니다.")
    return dict(zip(ROI_KEYS, (int(v) for v in roi)))


def _plain(value):
    """numpy 숫자를 Firestore에 저장할 수 있는 파이썬 기본 숫자로 바꾼다."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def build_history_doc(case_id: str, image_id: str | None, slice_index: int | None, algorithm: str,
                      params: dict, window: dict | None, roi, features: dict | None,
                      result_path: str, executed_by: str, source_history_id: str | None = None,
                      roi_applied: bool = False, now: str | None = None) -> dict:
    """docs/firestore.md 2-4 필드 + window, roi_applied, source_history_id.
    roi_applied: 알고리즘(Otsu)을 ROI 안에서만 계산했는지 (False면 roi는 통계용으로만 쓴 것)"""
    if not case_id:
        raise HistoryError("케이스 ID가 없습니다.")
    if algorithm not in ALGORITHMS:
        raise HistoryError(f"지원하지 않는 알고리즘입니다: {algorithm}")
    if window is not None and not {"level", "width"} <= set(window):
        raise HistoryError("창(window)에는 level과 width가 있어야 합니다.")
    return _plain({
        "case_id": case_id,
        "image_id": image_id,
        "slice_index": None if slice_index is None else int(slice_index),
        "algorithm": algorithm,
        "algorithm_version": ALGO_VERSION,
        "params": dict(params or {}),
        "window": dict(window) if window is not None else None,
        "roi": _roi_dict(roi),
        "roi_applied": bool(roi_applied) and roi is not None,
        "features": dict(features) if features else None,
        "result_path": result_path,
        "executed_by": executed_by,
        "executed_at": now or now_iso(),
        "source_history_id": source_history_id,
    })


# ---------------------------------------------------------------
# 결과 영상 파일
# ---------------------------------------------------------------
def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text))


def result_rel_path(case_id: str, history_id: str) -> str:
    """storage_root 기준 상대 경로: results/<케이스ID>/<이력ID>.png"""
    return str(PurePosixPath("results") / _safe(case_id) / f"{_safe(history_id)}.png")


def save_result_image(storage_root, rel_path: str, image: np.ndarray) -> Path:
    """결과 영상을 PNG로 저장한다. 같은 이름 파일이 있으면 덮어쓰지 않고 거절한다."""
    if not isinstance(image, np.ndarray) or image.ndim not in (2, 3) or image.size == 0:
        raise HistoryError("저장할 결과 영상이 올바르지 않습니다.")
    path = Path(storage_root) / rel_path
    if path.exists():
        raise HistoryError("같은 이름의 결과 파일이 이미 있습니다. 이미 저장된 요청입니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    img = image if image.dtype == np.uint8 else np.clip(image, 0, 255).astype(np.uint8)
    # cv2.imwrite는 Windows에서 경로에 한글이 있으면 저장하지 못한다.
    # 메모리에서 PNG로 만든 뒤 파이썬으로 파일에 쓰면 운영체제와 경로 글자에 상관없이 저장된다.
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HistoryError("결과 영상을 PNG로 바꾸지 못했습니다.")
    try:
        path.write_bytes(buf.tobytes())
    except OSError as e:
        raise HistoryError(f"결과 영상 파일을 저장하지 못했습니다 ({e.strerror}).") from e
    return path


def load_result_image(storage_root, rel_path: str) -> np.ndarray:
    path = Path(storage_root) / rel_path
    if not path.is_file():
        raise HistoryError(f"결과 영상 파일을 찾을 수 없습니다 ({rel_path}).")
    # cv2.imread도 Windows 한글 경로를 못 읽으므로, 파일을 바이트로 읽어서 디코딩한다.
    img = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HistoryError(f"결과 영상 파일을 읽을 수 없습니다 ({rel_path}).")
    return img


# ---------------------------------------------------------------
# 저장 (권한 확인 → 파일 → 기록, 실패하면 파일 되돌리기)
# ---------------------------------------------------------------
def save_history(store, storage_root, user, case: dict | None, *, image_id: str | None,
                 slice_index: int | None, algorithm: str, params: dict, window: dict | None,
                 roi, features: dict | None, result_image: np.ndarray, history_id: str,
                 roi_applied: bool = False,
                 source_history_id: str | None = None) -> tuple[bool, str, str | None]:
    """처리 이력 1건 저장. (성공 여부, 안내 메시지, 이력 ID)"""
    ok, msg = check_can_save_history(case, user)
    if not ok:
        return False, msg, None
    if not history_id:
        return False, "요청 ID가 없습니다.", None
    if store.exists(history_id):
        return False, "이미 저장된 요청입니다. (같은 결과를 두 번 저장하지 않습니다)", history_id

    rel_path = result_rel_path(case["case_id"], history_id)
    try:
        doc = build_history_doc(case["case_id"], image_id, slice_index, algorithm, params, window, roi,
                                features, rel_path, user["uid"], source_history_id, roi_applied)
        written = save_result_image(storage_root, rel_path, result_image)
    except HistoryError as e:
        return False, str(e), None

    try:
        created = store.create(history_id, doc)
    except Exception as e:  # 네트워크·권한 오류 등
        written.unlink(missing_ok=True)
        return False, f"처리 이력을 저장하지 못했습니다 ({type(e).__name__}). 결과 파일도 지웠습니다.", None
    if not created:
        written.unlink(missing_ok=True)
        return False, "이미 저장된 요청입니다. (같은 결과를 두 번 저장하지 않습니다)", history_id
    return True, f"처리 이력을 저장했습니다 ({history_id}).", history_id


def list_histories(store, case_id: str) -> list[dict]:
    """케이스의 처리 이력, 최근 것부터."""
    return sorted(store.list_by_case(case_id), key=lambda h: h.get("executed_at", ""), reverse=True)


# ---------------------------------------------------------------
# 재현: 저장된 설정 그대로 다시 실행
# ---------------------------------------------------------------
def rerun_history(history: dict, hu_slice: np.ndarray):
    """저장된 창·알고리즘·파라미터·ROI로 같은 슬라이스를 다시 처리한다. (결과 영상, 특징값)"""
    window = history.get("window") or {"level": 40, "width": 400}
    try:
        img = window_to_uint8(hu_slice, level=window["level"], width=window["width"])
        roi = history.get("roi")
        roi_tuple = tuple(roi[k] for k in ROI_KEYS) if roi and history.get("roi_applied") else None
        return run_algorithm(history["algorithm"], img, history.get("params") or {}, roi=roi_tuple)
    except (ProcessingError, KeyError) as e:
        raise HistoryError(f"저장된 설정으로 다시 실행할 수 없습니다: {e}") from e


def same_result(a: np.ndarray, b: np.ndarray) -> bool:
    """두 결과 영상이 픽셀 하나까지 같은지 (재현 검증)."""
    return a.shape == b.shape and bool(np.array_equal(a, b))


# ---------------------------------------------------------------
# Firestore 저장소
# ---------------------------------------------------------------
class FirestoreHistoryStore:
    def __init__(self, db):
        self.db = db

    def exists(self, history_id: str) -> bool:
        return self.db.collection(COLLECTION).document(history_id).get().exists

    def create(self, history_id: str, doc: dict) -> bool:
        """문서 ID = 요청 ID. 이미 있으면 False (Firestore create는 덮어쓰지 않음)."""
        from google.api_core.exceptions import AlreadyExists
        try:
            self.db.collection(COLLECTION).document(history_id).create(doc)
            return True
        except AlreadyExists:
            return False

    def get(self, history_id: str) -> dict | None:
        snap = self.db.collection(COLLECTION).document(history_id).get()
        return snap.to_dict() | {"id": snap.id} if snap.exists else None

    def list_by_case(self, case_id: str) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self.db.collection(COLLECTION).where(filter=FieldFilter("case_id", "==", case_id))
        return [d.to_dict() | {"id": d.id} for d in query.stream()]
