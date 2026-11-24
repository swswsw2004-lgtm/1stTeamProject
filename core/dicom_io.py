"""
DICOM 로딩·정렬·값 변환 모듈
담당: 역할2 (케이스·영상 관리·뷰어)
위치: core/dicom_io.py

다른 역할이 쓰는 방법 (역할3 등):
    from core.dicom_io import find_series, load_series

    infos = find_series("data/sts")                 # 폴더 안의 시리즈 목록
    ct_info = [s for s in infos if s.patient_id == "STS_001" and s.modality == "CT"][0]
    ct = load_series(ct_info.files)                 # 3D 볼륨으로 읽기

    ct.volume          # numpy 배열 (슬라이스, 행, 열) = (z, y, x), float32
                       #   CT  → HU 값
                       #   PT  → 원래 단위 값 (이 데이터는 Bq/mL, SUV 아님)
    ct.positions       # 슬라이스별 ImagePositionPatient (z, 3), mm
    ct.pixel_spacing   # (행 간격 mm, 열 간격 mm)
    ct.slice_spacing   # 실제 슬라이스 간격 mm (부피 계산에는 이 값을 사용)

데이터 주의점 (data/DATA_NOTES.md 참고):
    - 정렬은 파일명이 아니라 ImagePositionPatient 기준
    - RescaleSlope/Intercept는 환자·슬라이스마다 다를 수 있어 슬라이스별로 적용
    - CT·PET의 z값은 소수점까지 같지 않을 수 있어, 비교는 허용 오차로 한다
    - 원본 파일은 읽기만 하고 절대 수정하지 않는다
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

# 3D 볼륨으로 읽을 수 있는 모달리티. RTSTRUCT는 영상이 아니라 윤곽 좌표라서 제외.
IMAGE_MODALITIES = {"CT", "PT", "MR"}

# 헤더만 볼 때 건너뛸 확장자 (DICOM이 아닌 것이 확실한 파일)
SKIP_SUFFIXES = {".csv", ".md", ".txt", ".py", ".json", ".tcia", ".xlsx", ".png", ".jpg", ".jpeg"}


class DicomLoadError(Exception):
    """화면에 그대로 보여줄 수 있는 한국어 오류 메시지를 담는 예외."""


# ─────────────────────────────────────────────
# 자료형
# ─────────────────────────────────────────────
@dataclass
class SeriesInfo:
    """폴더를 훑어서 찾은 시리즈 요약 (픽셀은 아직 안 읽음)."""
    patient_id: str
    study_uid: str
    series_uid: str
    modality: str
    description: str
    files: list[Path] = field(default_factory=list)

    @property
    def n_files(self) -> int:
        return len(self.files)


@dataclass
class Series:
    """3D 볼륨으로 읽은 영상 시리즈."""
    patient_id: str
    series_uid: str
    modality: str
    description: str
    volume: np.ndarray            # (z, y, x) float32, 물리값(CT=HU)
    positions: np.ndarray         # (z, 3) 슬라이스별 ImagePositionPatient, mm
    orientation: np.ndarray       # (6,) ImageOrientationPatient
    pixel_spacing: tuple[float, float]   # (행 간격, 열 간격) mm
    slice_spacing: float          # 실제 슬라이스 간격 mm (중앙값)
    photometric: str              # MONOCHROME1이면 화면 표시 때 밝기 반전 필요
    frame_of_reference_uid: str
    files: list[Path]             # 정렬된 순서의 원본 파일 경로
    header: pydicom.Dataset       # 첫 슬라이스 헤더 (SUV 태그 등 추가 정보용)

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.volume.shape

    @property
    def z_positions(self) -> np.ndarray:
        """슬라이스 위치(mm). 축상(axial) 영상에서는 ImagePositionPatient의 z값."""
        return slice_locations(self.positions, self.orientation)

    def nearest_slice(self, z_mm: float, tol_mm: float = 0.5) -> int | None:
        """z 위치(mm)에 가장 가까운 슬라이스 번호. 허용 오차 밖이면 None.
        CT↔PET 같은 높이 슬라이스 찾기에 사용 (z가 소수점까지 같지 않을 수 있음)."""
        zs = self.z_positions
        idx = int(np.argmin(np.abs(zs - z_mm)))
        return idx if abs(zs[idx] - z_mm) <= tol_mm else None


# ─────────────────────────────────────────────
# 1) 폴더에서 시리즈 찾기
# ─────────────────────────────────────────────
def find_series(root: str | Path) -> list[SeriesInfo]:
    """폴더 아래 DICOM 파일을 헤더만 읽어 SeriesInstanceUID별로 묶는다.
    DICOM이 아닌 파일은 조용히 건너뛴다."""
    root = Path(root)
    if not root.exists():
        raise DicomLoadError(f"폴더를 찾을 수 없습니다: {root}")

    groups: dict[str, SeriesInfo] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=True)
        except (InvalidDicomError, OSError, ValueError):
            continue
        uid = str(getattr(ds, "SeriesInstanceUID", ""))
        if not uid:
            continue
        if uid not in groups:
            groups[uid] = SeriesInfo(
                patient_id=str(getattr(ds, "PatientID", "")),
                study_uid=str(getattr(ds, "StudyInstanceUID", "")),
                series_uid=uid,
                modality=str(getattr(ds, "Modality", "")),
                description=str(getattr(ds, "SeriesDescription", "")),
            )
        groups[uid].files.append(p)

    return sorted(groups.values(), key=lambda s: (s.patient_id, s.modality, s.description))


# ─────────────────────────────────────────────
# 2) 정렬
# ─────────────────────────────────────────────
def slice_normal(orientation) -> np.ndarray:
    """ImageOrientationPatient(행 방향 3개 + 열 방향 3개)로 슬라이스 수직 방향을 구한다."""
    o = np.asarray(orientation, dtype=float)
    if o.shape != (6,):
        raise DicomLoadError("ImageOrientationPatient 값이 6개가 아닙니다.")
    return np.cross(o[:3], o[3:])


def slice_locations(positions, orientation) -> np.ndarray:
    """각 슬라이스의 위치(mm) = ImagePositionPatient를 수직 방향으로 투영한 값.
    축상 영상(수직 방향 = z축)에서는 ImagePositionPatient의 z값과 같다."""
    return np.asarray(positions, dtype=float) @ slice_normal(orientation)


def sort_datasets(datasets: list) -> list[int]:
    """슬라이스들을 위치(mm) 오름차순으로 정렬한 인덱스를 돌려준다.
    파일명·InstanceNumber는 믿지 않는다."""
    if not datasets:
        raise DicomLoadError("정렬할 슬라이스가 없습니다.")
    for i, ds in enumerate(datasets):
        if getattr(ds, "ImagePositionPatient", None) is None:
            raise DicomLoadError(f"{i}번째 슬라이스에 ImagePositionPatient가 없어 정렬할 수 없습니다.")
    orientation = datasets[0].ImageOrientationPatient
    positions = [ds.ImagePositionPatient for ds in datasets]
    locs = slice_locations(positions, orientation)
    return [int(i) for i in np.argsort(locs, kind="stable")]


# ─────────────────────────────────────────────
# 3) 값 변환
# ─────────────────────────────────────────────
def to_physical(raw: np.ndarray, ds) -> np.ndarray:
    """저장된 픽셀값 → 물리값.  값 = raw × RescaleSlope + RescaleIntercept
    CT는 HU, PET은 Units 태그의 단위(이 데이터는 BQML = Bq/mL).
    슬라이스마다 Slope/Intercept가 다를 수 있으므로 반드시 그 슬라이스의 헤더로 계산한다.
    (Intercept를 -1024로 고정하면 STS_001처럼 Intercept가 0인 데이터가 틀어진다)"""
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    return raw.astype(np.float32) * np.float32(slope) + np.float32(intercept)


def estimate_slice_spacing(locations: np.ndarray) -> float:
    """정렬된 슬라이스 위치에서 실제 간격(mm)의 중앙값.
    SliceThickness와 다를 수 있다 (예: CT 두께 3.75mm, 실제 간격 3.27mm).
    부피 계산에는 이 값을 쓴다."""
    if len(locations) < 2:
        return 0.0
    return float(np.median(np.diff(locations)))


# ─────────────────────────────────────────────
# 4) 시리즈 → 3D 볼륨
# ─────────────────────────────────────────────
def load_series(files: list[str | Path]) -> Series:
    """한 시리즈의 파일들을 읽어 정렬·물리값 변환된 3D 볼륨으로 만든다.
    - 서로 다른 시리즈가 섞여 있거나, 영상이 아닌 모달리티(RTSTRUCT)면 DicomLoadError
    - 원본 파일은 읽기만 한다"""
    if not files:
        raise DicomLoadError("읽을 파일이 없습니다.")

    datasets, paths = [], []
    for f in files:
        try:
            datasets.append(pydicom.dcmread(f))
            paths.append(Path(f))
        except (InvalidDicomError, OSError) as e:
            raise DicomLoadError(f"DICOM 파일이 아니거나 읽을 수 없습니다: {Path(f).name}") from e

    first = datasets[0]
    modality = str(getattr(first, "Modality", ""))
    if modality not in IMAGE_MODALITIES:
        raise DicomLoadError(
            f"'{modality}'는 영상 시리즈가 아니라서 볼륨으로 읽을 수 없습니다. "
            "(RTSTRUCT는 윤곽 좌표 파일입니다)"
        )

    uids = {str(getattr(ds, "SeriesInstanceUID", "")) for ds in datasets}
    if len(uids) != 1:
        raise DicomLoadError(f"서로 다른 시리즈 {len(uids)}개가 섞여 있습니다. 시리즈별로 나눠서 읽어 주세요.")

    shapes = {(int(ds.Rows), int(ds.Columns)) for ds in datasets}
    if len(shapes) != 1:
        raise DicomLoadError(f"슬라이스 크기가 서로 다릅니다: {sorted(shapes)}")

    order = sort_datasets(datasets)
    datasets = [datasets[i] for i in order]
    paths = [paths[i] for i in order]

    volume = np.stack([to_physical(ds.pixel_array, ds) for ds in datasets])
    positions = np.array([[float(v) for v in ds.ImagePositionPatient] for ds in datasets])
    orientation = np.array([float(v) for v in first.ImageOrientationPatient])
    locations = slice_locations(positions, orientation)

    spacing = getattr(first, "PixelSpacing", None)
    if spacing is None:
        raise DicomLoadError("PixelSpacing이 없어 실제 크기(mm)를 계산할 수 없습니다.")

    return Series(
        patient_id=str(getattr(first, "PatientID", "")),
        series_uid=uids.pop(),
        modality=modality,
        description=str(getattr(first, "SeriesDescription", "")),
        volume=volume,
        positions=positions,
        orientation=orientation,
        pixel_spacing=(float(spacing[0]), float(spacing[1])),
        slice_spacing=estimate_slice_spacing(locations),
        photometric=str(getattr(first, "PhotometricInterpretation", "MONOCHROME2")),
        frame_of_reference_uid=str(getattr(first, "FrameOfReferenceUID", "")),
        files=paths,
        header=first,
    )


def load_rtstruct(path: str | Path) -> pydicom.Dataset:
    """RTSTRUCT 파일을 읽어 그대로 돌려준다 (윤곽 → 마스크 변환은 역할3 core/roi.py)."""
    ds = pydicom.dcmread(path)
    if str(getattr(ds, "Modality", "")) != "RTSTRUCT":
        raise DicomLoadError(f"RTSTRUCT 파일이 아닙니다 (Modality={getattr(ds, 'Modality', '?')}).")
    return ds
