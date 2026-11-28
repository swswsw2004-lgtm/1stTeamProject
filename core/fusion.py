"""
PET/CT 융합: PET을 CT 격자에 mm 기준으로 맞추고, 컬러로 반투명하게 겹친다 + RTSTRUCT 종양 윤곽 표시
담당: 역할2 (특화 기능 조각: CT 위 PET 오버레이, 투명도, 좌표 정합)
위치: core/fusion.py

왜 단순 확대로는 안 되나 (data/DATA_NOTES.md 3장):
    CT 512×512 · 0.977mm (촬영 폭 약 500mm), PET 128×128 · 4.69~5.47mm (촬영 폭 600~700mm)
    → PET이 더 넓게 찍혀 있어 그냥 4배 늘리면 위치가 어긋난다.
    → CT 각 픽셀의 환자 좌표(mm)를 구하고, 그 위치의 PET 값을 읽어 온다 (ImagePositionPatient·PixelSpacing 사용).
    CT·PET·RTSTRUCT의 FrameOfReferenceUID가 같아서(같은 좌표계) 별도 정합(회전·변형)은 하지 않는다.

    pet_slice = pet_on_ct_slice(ct, pt, ct_index)        # CT 슬라이스와 같은 크기의 PET 값 (밖은 NaN)
    rgb = blend(ct_u8, colorize(pet_slice, vmax), alpha)  # 투명도 alpha로 겹치기
    polys = contours_on_slice(rtstruct_ds, "GTV_Mass", ct, ct_index)   # CT 픽셀 좌표 다각형
"""
from __future__ import annotations

import cv2
import numpy as np

PET_COLORMAPS = {"hot": cv2.COLORMAP_HOT, "inferno": cv2.COLORMAP_INFERNO, "jet": cv2.COLORMAP_JET}


class FusionError(ValueError):
    """화면에 그대로 보여줄 한국어 메시지를 담는 오류."""


# ─────────────────────────────────────────────
# 좌표 변환 (환자 좌표 mm ↔ 픽셀)
# ─────────────────────────────────────────────
def _axes(series):
    """(행 방향 단위벡터, 열 방향 단위벡터, 행 간격 mm, 열 간격 mm)
    DICOM: ImageOrientationPatient 앞 3개 = 열 번호가 커지는 방향, 뒤 3개 = 행 번호가 커지는 방향
           PixelSpacing = [행 사이 간격, 열 사이 간격]"""
    o = np.asarray(series.orientation, dtype=float)
    col_dir, row_dir = o[:3], o[3:]
    row_sp, col_sp = series.pixel_spacing
    return row_dir, col_dir, float(row_sp), float(col_sp)


def pixel_to_patient(series, index: int, rows, cols) -> np.ndarray:
    """슬라이스 index의 픽셀 (행, 열) → 환자 좌표 (x, y, z) mm. rows·cols는 같은 모양의 배열."""
    row_dir, col_dir, row_sp, col_sp = _axes(series)
    origin = np.asarray(series.positions[index], dtype=float)
    rows = np.asarray(rows, dtype=float)[..., None]
    cols = np.asarray(cols, dtype=float)[..., None]
    return origin + cols * col_sp * col_dir + rows * row_sp * row_dir


def patient_to_pixel(series, index: int, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """환자 좌표 (…, 3) mm → 슬라이스 index의 (행, 열) 실수 좌표. 슬라이스 면에 수직인 성분은 무시."""
    row_dir, col_dir, row_sp, col_sp = _axes(series)
    d = np.asarray(points, dtype=float) - np.asarray(series.positions[index], dtype=float)
    return d @ row_dir / row_sp, d @ col_dir / col_sp


# ─────────────────────────────────────────────
# PET → CT 격자
# ─────────────────────────────────────────────
def check_same_frame(ct, pt) -> None:
    if ct.frame_of_reference_uid and pt.frame_of_reference_uid and \
            ct.frame_of_reference_uid != pt.frame_of_reference_uid:
        raise FusionError("CT와 PET의 좌표계(FrameOfReferenceUID)가 달라 겹칠 수 없습니다. 같은 검사의 시리즈를 선택해 주세요.")
    if ct.patient_id and pt.patient_id and ct.patient_id != pt.patient_id:
        raise FusionError(f"CT와 PET의 환자가 다릅니다 ({ct.patient_id} / {pt.patient_id}).")


def matching_pet_index(ct, pt, ct_index: int) -> int | None:
    """CT 슬라이스와 같은 높이(z)의 PET 슬라이스 번호. 허용 오차는 PET 슬라이스 간격의 절반.
    z가 소수점까지 같지 않을 수 있어(3.19/3.27/3.29) 가장 가까운 것을 찾는다."""
    z = float(ct.z_positions[ct_index])
    tol = max(pt.slice_spacing / 2, 0.5) if pt.slice_spacing else 0.5
    return pt.nearest_slice(z, tol_mm=tol)


def pet_on_ct_slice(ct, pt, ct_index: int) -> tuple[np.ndarray, int | None]:
    """CT 슬라이스 ct_index와 같은 크기의 PET 값 배열(float32)과 사용한 PET 슬라이스 번호.
    PET 촬영 범위 밖이거나 같은 높이의 PET이 없으면 NaN."""
    check_same_frame(ct, pt)
    _, rows, cols = ct.volume.shape
    pi = matching_pet_index(ct, pt, ct_index)
    if pi is None:
        return np.full((rows, cols), np.nan, dtype=np.float32), None

    rr, cc = np.mgrid[0:rows, 0:cols]
    pts = pixel_to_patient(ct, ct_index, rr, cc)                 # CT 픽셀의 mm 위치
    pr, pc = patient_to_pixel(pt, pi, pts)                         # 그 위치의 PET 픽셀 좌표
    pet = pt.volume[pi].astype(np.float32)
    out = cv2.remap(pet, pc.astype(np.float32), pr.astype(np.float32),
                    interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
    return out, pi


# ─────────────────────────────────────────────
# 색 입히기 · 겹치기
# ─────────────────────────────────────────────
def default_pet_max(pt) -> float:
    """PET 표시 상한: 볼륨의 99.5 백분위 (아주 밝은 몇 개 점 때문에 전체가 어두워지지 않게)."""
    v = pt.volume[np.isfinite(pt.volume)]
    return float(np.percentile(v, 99.5)) if v.size else 1.0


def colorize(pet_values: np.ndarray, vmax: float, cmap: str = "hot") -> np.ndarray:
    """PET 값 → 컬러(RGB uint8). 0~vmax를 0~255로. NaN은 0."""
    if vmax <= 0:
        raise FusionError("PET 표시 상한은 0보다 커야 합니다.")
    if cmap not in PET_COLORMAPS:
        raise FusionError(f"컬러맵은 {', '.join(PET_COLORMAPS)} 중 하나여야 합니다.")
    norm = np.nan_to_num(pet_values / vmax, nan=0.0)
    u8 = (np.clip(norm, 0, 1) * 255).astype(np.uint8)
    bgr = cv2.applyColorMap(u8, PET_COLORMAPS[cmap])
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def blend(ct_u8: np.ndarray, pet_rgb: np.ndarray, alpha: float,
          pet_values: np.ndarray | None = None, threshold: float = 0.0) -> np.ndarray:
    """CT(흑백) 위에 PET(컬러)을 투명도 alpha로 겹친다 (0 = CT만, 1 = PET만).
    pet_values가 threshold 이하인 곳(배경·범위 밖)은 CT만 보이게 해서 화면 전체가 물들지 않게 한다."""
    if not 0 <= alpha <= 1:
        raise FusionError("투명도는 0~1 사이여야 합니다.")
    if ct_u8.shape[:2] != pet_rgb.shape[:2]:
        raise FusionError("CT와 PET 그림 크기가 다릅니다. pet_on_ct_slice로 먼저 맞춰 주세요.")
    ct_rgb = np.repeat(ct_u8[..., None], 3, axis=2).astype(np.float32)
    weight = np.full(ct_u8.shape, alpha, dtype=np.float32)
    if pet_values is not None:
        weight[~(np.nan_to_num(pet_values, nan=-np.inf) > threshold)] = 0.0
    out = ct_rgb * (1 - weight[..., None]) + pet_rgb.astype(np.float32) * weight[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────
# RTSTRUCT 종양 윤곽 (표시용 · 부피 계산은 역할3)
# ─────────────────────────────────────────────
def roi_names(rtstruct) -> list[str]:
    return [str(r.ROIName) for r in getattr(rtstruct, "StructureSetROISequence", [])]


def contours_on_slice(rtstruct, roi_name: str, series, index: int, tol_mm: float | None = None) -> list[np.ndarray]:
    """RTSTRUCT의 roi_name 윤곽 중 슬라이스 index 높이에 있는 것들을 (N, 2) [열, 행] 픽셀 좌표로.
    윤곽 점은 환자 좌표(mm)로 저장돼 있어 이 시리즈의 ImagePositionPatient·PixelSpacing으로 바꾼다."""
    number = None
    for r in getattr(rtstruct, "StructureSetROISequence", []):
        if str(r.ROIName) == roi_name:
            number = int(r.ROINumber)
    if number is None:
        raise FusionError(f"RTSTRUCT에 '{roi_name}' 윤곽이 없습니다. (있는 것: {', '.join(roi_names(rtstruct)) or '없음'})")

    z = float(series.z_positions[index])
    tol = tol_mm if tol_mm is not None else max((series.slice_spacing or 1.0) / 2, 0.5)
    normal = np.cross(np.asarray(series.orientation[:3], float), np.asarray(series.orientation[3:], float))
    polys = []
    for rc in getattr(rtstruct, "ROIContourSequence", []):
        if int(getattr(rc, "ReferencedROINumber", -1)) != number:
            continue
        for c in getattr(rc, "ContourSequence", []):
            pts = np.asarray([float(v) for v in c.ContourData], dtype=float).reshape(-1, 3)
            if pts.size == 0 or abs(float(np.mean(pts @ normal)) - z) > tol:
                continue
            r, col = patient_to_pixel(series, index, pts)
            polys.append(np.stack([col, r], axis=1))
    return polys


def draw_contours(rgb: np.ndarray, polys: list[np.ndarray], color=(0, 255, 0), thickness: int = 1) -> np.ndarray:
    """윤곽 다각형을 그림 위에 선으로 그린다 (원본 배열은 바꾸지 않음)."""
    out = rgb.copy() if rgb.ndim == 3 else np.repeat(rgb[..., None], 3, axis=2)
    pts = [np.round(p).astype(np.int32).reshape(-1, 1, 2) for p in polys if len(p) >= 2]
    if pts:
        cv2.polylines(out, pts, isClosed=True, color=color, thickness=thickness)
    return out
