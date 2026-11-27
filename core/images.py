"""
영상 등록 모듈: 형식 검사 → 원본 보존 저장 → images 기록
담당: 역할2 (케이스·영상 관리·뷰어)
위치: core/images.py
기준: docs/firestore.md 2-3 `images/{image_id}` (시리즈 1개 = 문서 1개)

흐름 (화면에서 쓰는 순서):
    files = [(파일이름, bytes), ...]                 # 업로드 파일 또는 서버 폴더에서 읽은 파일
    check = inspect_files(files, case)               # 1) 형식 검사 (저장 전에 전부 확인)
    if check.errors: 화면에 check.errors 표시 → 끝   #    하나라도 잘못되면 아무것도 저장하지 않음
    for group in check.groups:                       # 2) 시리즈(또는 PNG/JPEG 1장)마다
        ok, msg = register_group(store, storage_root, user, case, group)

지킨 규칙 (PROJECT_CONTEXT.md 0장):
    - 원본은 storage_root/originals/<케이스ID>/... 에 복사본으로 저장, 같은 폴더가 있으면 덮어쓰지 않고 거절
    - 영상 파일은 Firestore에 넣지 않고 상대 경로·메타데이터만 기록
    - 저장 일관성: 파일 저장 실패 → 기록 안 함 / 기록 실패 → 방금 저장한 파일 삭제
    - 저장 직전에 권한 검사 (등록 담당자·관리자)

역할4 core/review_store.py의 count_images()는 이 모듈이 만드는 images 문서를 case_id로 센다.
"""
from __future__ import annotations

import io
import re
import shutil
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.cases import CAN_CREATE_ROLES, now_iso

SOURCE = "TCIA Soft-tissue-Sarcoma (CC BY 3.0)"
DICOM_MODALITIES = {"CT", "PT", "RTSTRUCT"}       # 이 프로젝트에서 쓰는 DICOM 종류
IMAGE_SUFFIXES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
MAX_FILE_BYTES = 50 * 1024 * 1024                 # 파일 1개 최대 50MB (CT 1장은 약 0.5MB)
MAX_FILES = 2000

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


# ─────────────────────────────────────────────
# 검사 결과 자료형
# ─────────────────────────────────────────────
@dataclass
class FileGroup:
    """저장 단위. DICOM은 시리즈 1개, PNG/JPEG는 파일 1개."""
    format: str                      # DICOM / PNG / JPEG
    modality: str                    # CT / PT / RTSTRUCT / OT
    series_uid: str | None
    description: str
    files: list[tuple[str, bytes]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)   # rows, cols, pixel_spacing_mm, slice_spacing_mm, ...

    @property
    def num_files(self) -> int:
        return len(self.files)

    @property
    def size_bytes(self) -> int:
        return sum(len(b) for _, b in self.files)

    @property
    def label(self) -> str:
        return f"{self.modality} · {self.description or self.format} · {self.num_files}개"


@dataclass
class InspectResult:
    groups: list[FileGroup] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)     # 거절 이유 (화면에 그대로 표시)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.groups)


# ─────────────────────────────────────────────
# 1) 형식 검사
# ─────────────────────────────────────────────
def detect_format(name: str, data: bytes) -> str | None:
    """파일 내용(앞부분 바이트)으로 형식을 판단한다. 확장자만 믿지 않는다.
    DICOM 파일은 128바이트 뒤에 'DICM' 표시가 있다."""
    if len(data) >= 132 and data[128:132] == b"DICM":
        return "DICOM"
    if data.startswith(PNG_MAGIC):
        return "PNG"
    if data.startswith(JPEG_MAGIC):
        return "JPEG"
    return None


def inspect_files(files: list[tuple[str, bytes]], case: dict | None = None) -> InspectResult:
    """올린 파일 전체를 저장 전에 검사한다. 문제가 하나라도 있으면 errors에 이유를 모으고,
    화면은 아무것도 저장하지 않는다 (일부만 저장되어 기록이 어긋나는 것 방지)."""
    result = InspectResult()
    if not files:
        result.errors.append("선택한 파일이 없습니다.")
        return result
    if len(files) > MAX_FILES:
        result.errors.append(f"한 번에 {MAX_FILES}개까지 올릴 수 있습니다 (현재 {len(files)}개).")
        return result

    dicom_files = []
    for name, data in files:
        short = PurePosixPath(name.replace("\\", "/")).name
        if not data:
            result.errors.append(f"{short}: 빈 파일입니다.")
            continue
        if len(data) > MAX_FILE_BYTES:
            result.errors.append(f"{short}: 파일이 너무 큽니다 ({len(data) / 1e6:.0f}MB, 최대 {MAX_FILE_BYTES // 1e6:.0f}MB).")
            continue
        fmt = detect_format(short, data)
        if fmt is None:
            result.errors.append(f"{short}: 지원하지 않는 형식입니다. DICOM, PNG, JPEG만 등록할 수 있습니다.")
        elif fmt == "DICOM":
            dicom_files.append((short, data))
        else:
            _inspect_image(short, data, fmt, result)

    if dicom_files:
        _inspect_dicom(dicom_files, case, result)
    return result


def _inspect_image(name: str, data: bytes, fmt: str, result: InspectResult) -> None:
    """PNG/JPEG: 실제로 열리는 영상인지 확인 (확장자만 바꾼 파일·깨진 파일 거절)."""
    from PIL import Image  # streamlit 설치 시 함께 설치됨

    expected = IMAGE_SUFFIXES.get(PurePosixPath(name).suffix.lower())
    if expected and expected != fmt:
        result.errors.append(f"{name}: 확장자는 {expected}인데 내용은 {fmt}입니다. 파일을 확인해 주세요.")
        return
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception:
        result.errors.append(f"{name}: 영상 파일이 손상되어 열 수 없습니다.")
        return
    result.groups.append(FileGroup(
        format=fmt, modality="OT", series_uid=None, description=name,
        files=[(name, data)], meta={"rows": height, "cols": width},
    ))


def _inspect_dicom(files: list[tuple[str, bytes]], case: dict | None, result: InspectResult) -> None:
    """DICOM: 헤더를 읽어 시리즈별로 묶고, 모달리티·환자·필수 태그를 확인한다."""
    import pydicom

    if case is not None and not case.get("patient_id"):
        result.errors.append("이 케이스에는 환자 ID가 없어 DICOM의 환자를 확인할 수 없습니다. "
                             "환자 ID가 있는 케이스에 등록해 주세요.")
        return

    by_series: dict[str, list] = {}
    for name, data in files:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")    # 손상 파일 경고는 아래에서 직접 안내
                ds = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)
        except Exception:
            ds = None
        # 손상 파일은 오류 없이 빈 헤더로 읽히기도 하므로, 기본 태그가 하나도 없으면 손상으로 본다
        if ds is None or not (getattr(ds, "SOPInstanceUID", None) or getattr(ds, "Modality", None)):
            result.errors.append(f"{name}: DICOM 헤더를 읽을 수 없습니다 (파일 손상).")
            continue
        modality = str(getattr(ds, "Modality", ""))
        uid = str(getattr(ds, "SeriesInstanceUID", ""))
        if not uid:
            result.errors.append(f"{name}: SeriesInstanceUID가 없어 시리즈를 구분할 수 없습니다.")
            continue
        if modality not in DICOM_MODALITIES:
            result.errors.append(f"{name}: '{modality}' 영상은 이 시스템에서 다루지 않습니다 (CT·PT·RTSTRUCT만 가능).")
            continue
        if case and case.get("patient_id"):
            pid = str(getattr(ds, "PatientID", ""))
            if pid != case["patient_id"]:
                result.errors.append(
                    f"{name}: 환자 ID가 케이스와 다릅니다 (파일 {pid or '없음'}, 케이스 {case['patient_id']}).")
                continue
        by_series.setdefault(uid, []).append((name, data, ds))

    for uid, items in by_series.items():
        ds0 = items[0][2]
        modality = str(ds0.Modality)
        sop_uids = [str(getattr(ds, "SOPInstanceUID", "")) for _, _, ds in items]
        if len(set(sop_uids)) != len(sop_uids):
            result.errors.append(f"{modality} 시리즈에 같은 슬라이스(SOPInstanceUID)가 두 번 들어 있습니다.")
            continue
        try:
            meta = _dicom_meta(modality, [ds for _, _, ds in items])
        except ValueError as e:
            result.errors.append(f"{modality} 시리즈({getattr(ds0, 'SeriesDescription', '')}): {e}")
            continue
        result.groups.append(FileGroup(
            format="DICOM", modality=modality, series_uid=uid,
            description=str(getattr(ds0, "SeriesDescription", "")),
            files=[(n, d) for n, d, _ in items], meta=meta,
        ))


def _dicom_meta(modality: str, datasets: list) -> dict:
    """images 문서에 넣을 메타데이터. 실측 슬라이스 간격은 core.dicom_io와 같은 방식으로 계산."""
    from core.dicom_io import estimate_slice_spacing, slice_locations

    ds0 = datasets[0]
    if modality == "RTSTRUCT":
        ref = None
        try:
            ref = str(ds0.ReferencedFrameOfReferenceSequence[0].RTReferencedStudySequence[0]
                      .RTReferencedSeriesSequence[0].SeriesInstanceUID)
        except (AttributeError, IndexError):
            pass
        return {"rows": None, "cols": None, "pixel_spacing_mm": None,
                "slice_spacing_mm": None, "referenced_series_uid": ref}

    for ds in datasets:
        for tag in ("ImagePositionPatient", "ImageOrientationPatient", "PixelSpacing", "Rows", "Columns"):
            if getattr(ds, tag, None) is None:
                raise ValueError(f"필수 태그 {tag}가 없는 슬라이스가 있습니다.")
    sizes = {(int(ds.Rows), int(ds.Columns)) for ds in datasets}
    if len(sizes) != 1:
        raise ValueError(f"슬라이스 크기가 서로 다릅니다 {sorted(sizes)}.")
    locs = sorted(slice_locations([ds.ImagePositionPatient for ds in datasets], ds0.ImageOrientationPatient))
    if len(set(round(z, 3) for z in locs)) != len(locs):
        raise ValueError("같은 위치의 슬라이스가 두 장 이상 있습니다.")
    rows, cols = sizes.pop()
    return {
        "rows": rows, "cols": cols,
        "pixel_spacing_mm": [float(ds0.PixelSpacing[0]), float(ds0.PixelSpacing[1])],
        "slice_spacing_mm": round(estimate_slice_spacing(locs), 4) if len(locs) > 1 else None,
        "referenced_series_uid": None,
    }


# ─────────────────────────────────────────────
# 2) 권한
# ─────────────────────────────────────────────
def check_can_register(user) -> tuple[bool, str]:
    if not user or not user.get("uid") or not user.get("role"):
        return False, "로그인이 필요합니다."
    if user.get("role") not in CAN_CREATE_ROLES:
        return False, "영상 등록은 등록 담당자·관리자만 할 수 있습니다."
    return True, "가능합니다."


# ─────────────────────────────────────────────
# 3) 원본 저장 + 기록 (저장 일관성)
# ─────────────────────────────────────────────
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    """경로 조작(../)과 특수문자를 막은 파일·폴더 이름."""
    cleaned = _SAFE.sub("_", PurePosixPath(name.replace("\\", "/")).name).strip("._")
    return cleaned or "file"


def target_dir(case_id: str, group: FileGroup) -> PurePosixPath:
    """원본 저장 위치 (storage_root 기준 상대 경로).
    DICOM: originals/CASE-001/CT_<시리즈UID 끝 12자리>   PNG/JPEG: originals/CASE-001/OT_<파일이름>"""
    tail = (group.series_uid or "")[-12:] if group.series_uid else safe_name(group.description)
    return PurePosixPath("originals") / safe_name(case_id) / f"{group.modality}_{safe_name(tail)}"


def register_group(store, storage_root: str | Path, user, case: dict, group: FileGroup,
                   now: str | None = None) -> tuple[bool, str]:
    """검사를 통과한 그룹 1개를 저장하고 images 문서를 만든다. (성공 여부, 메시지)"""
    ok, msg = check_can_register(user)
    if not ok:
        return False, msg
    if not case or not case.get("case_id"):
        return False, "케이스를 찾을 수 없습니다."
    case_id = case["case_id"]

    if group.series_uid and store.series_exists(case_id, group.series_uid):
        return False, f"이 케이스에 이미 등록된 시리즈입니다 ({group.label})."

    rel = target_dir(case_id, group)
    root = Path(storage_root)
    dest = root / rel
    if dest.exists():
        return False, f"저장 위치에 같은 폴더가 이미 있어 덮어쓰지 않았습니다 ({rel})."

    # ① 임시 폴더에 먼저 쓰고 → ② 다 쓰면 한 번에 이름 변경 (중간 실패 시 반쪽 폴더가 남지 않게)
    tmp = dest.parent / f".tmp-{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir(parents=True, exist_ok=False)
        used = set()
        for i, (name, data) in enumerate(group.files):
            fname = safe_name(name)
            if fname in used:                      # 같은 이름 파일이 있으면 번호를 붙임
                p = PurePosixPath(fname)
                fname = f"{p.stem}_{i}{p.suffix}"
            used.add(fname)
            (tmp / fname).write_bytes(data)
        tmp.rename(dest)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return False, f"파일 저장에 실패해 등록하지 않았습니다 ({e.__class__.__name__})."

    doc = build_image_doc(case_id, group, str(rel), user["uid"], now)
    try:
        image_id = store.add_image(doc)
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)    # 기록 실패 → 방금 저장한 파일 삭제 (어긋남 방지)
        return False, f"기록 저장에 실패해 파일도 지웠습니다. 다시 시도해 주세요 ({e.__class__.__name__})."
    return True, f"{group.label} 등록 완료 (ID {image_id})."


def build_image_doc(case_id: str, group: FileGroup, rel_path: str, uploaded_by: str,
                    now: str | None = None) -> dict:
    """docs/firestore.md 2-3 필드 그대로."""
    meta = group.meta
    return {
        "case_id": case_id,
        "modality": group.modality,
        "format": group.format,
        "series_uid": group.series_uid,
        "series_description": group.description,
        "file_path": rel_path,
        "num_files": group.num_files,
        "size_bytes": group.size_bytes,
        "rows": meta.get("rows"),
        "cols": meta.get("cols"),
        "pixel_spacing_mm": meta.get("pixel_spacing_mm"),
        "slice_spacing_mm": meta.get("slice_spacing_mm"),
        "referenced_series_uid": meta.get("referenced_series_uid"),
        "source": SOURCE,
        "uploaded_by": uploaded_by,
        "uploaded_at": now or now_iso(),
    }


def read_folder_files(paths: list[str | Path]) -> list[tuple[str, bytes]]:
    """서버 데이터 폴더(data/sts 등)의 시리즈 파일을 업로드와 같은 형태로 읽는다 (원본은 읽기만)."""
    return [(Path(p).name, Path(p).read_bytes()) for p in paths]


# ─────────────────────────────────────────────
# 4) 조회
# ─────────────────────────────────────────────
def list_images(store, case_id: str) -> list[dict]:
    order = {"CT": 0, "PT": 1, "RTSTRUCT": 2, "OT": 3}
    return sorted(store.list_images(case_id),
                  key=lambda d: (order.get(d.get("modality"), 9), d.get("series_description") or ""))


def count_images(store, case_id: str) -> int:
    """역할4 배정 조건(영상 1개 이상)에 쓰는 개수. 시리즈 1개 = 1개."""
    return len(store.list_images(case_id))


# ─────────────────────────────────────────────
# 실제 Firestore 저장소
# ─────────────────────────────────────────────
class FirestoreImageStore:
    COLLECTION = "images"

    def __init__(self, db):
        self.db = db

    def _by_case(self, case_id):
        from google.cloud.firestore_v1.base_query import FieldFilter
        return self.db.collection(self.COLLECTION).where(filter=FieldFilter("case_id", "==", case_id))

    def add_image(self, doc: dict) -> str:
        ref = self.db.collection(self.COLLECTION).document()   # 자동 ID
        ref.set(doc)
        return ref.id

    def list_images(self, case_id: str) -> list[dict]:
        return [d.to_dict() | {"id": d.id} for d in self._by_case(case_id).stream()]

    def series_exists(self, case_id: str, series_uid: str) -> bool:
        return any(d.get("series_uid") == series_uid for d in self.list_images(case_id))
