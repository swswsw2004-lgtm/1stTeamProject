"""
ROI(관심 영역) 분석 — 통계와 히스토그램
담당: 역할3
위치: core/roi.py

ROI는 (x, y, 너비, 높이) 픽셀 좌표 사각형이다. 영상 밖이거나 크기가 0이면
core.processing.check_roi가 ProcessingError로 이유와 함께 거절한다.

사용 예:
    from core.roi import roi_stats, roi_histogram
    stats = roi_stats(hu, (276, 214, 112, 108), pixel_spacing=ct.pixel_spacing)
    counts, edges = roi_histogram(hu, (276, 214, 112, 108), bins=50)

- 입력은 CT HU 배열(float)이나 8비트 처리 결과(uint8) 모두 가능
- HU로 계산하면 "종양 안 평균이 몇 HU인지"처럼 물리적인 의미가 있는 값이 나온다
"""
import numpy as np

from core.processing import ProcessingError, check_roi


def _check_array(arr):
    if arr is None or not isinstance(arr, np.ndarray):
        raise ProcessingError("ROI를 계산할 영상이 없습니다.")
    if arr.ndim != 2 or arr.size == 0:
        raise ProcessingError("ROI 계산은 흑백 2차원 영상만 가능합니다.")
    return arr


def crop(arr, roi):
    """ROI 부분만 잘라 낸다 (원본은 바꾸지 않음)."""
    _check_array(arr)
    x, y, w, h = check_roi(arr, roi)
    return arr[y:y + h, x:x + w]


def roi_stats(arr, roi, pixel_spacing=None):
    """ROI 안의 픽셀 통계.

    pixel_spacing=(행 간격 mm, 열 간격 mm)을 주면 면적을 mm²로도 계산한다.
    반환 값은 processing_history의 features나 roi 필드에 그대로 저장할 수 있는 dict.
    """
    x, y, w, h = check_roi(_check_array(arr), roi)
    values = arr[y:y + h, x:x + w].astype(np.float64)
    stats = {
        "x": x, "y": y, "w": w, "h": h,
        "n_px": int(values.size),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "var": float(values.var()),
        "min": float(values.min()),
        "max": float(values.max()),
        "median": float(np.median(values)),
    }
    if pixel_spacing is not None:
        try:
            row_mm, col_mm = (float(v) for v in pixel_spacing)
        except (TypeError, ValueError):
            raise ProcessingError("pixel_spacing은 (행 간격, 열 간격) 두 숫자여야 합니다.") from None
        if row_mm <= 0 or col_mm <= 0:
            raise ProcessingError("pixel_spacing은 0보다 커야 합니다.")
        stats["area_mm2"] = float(values.size * row_mm * col_mm)
    return stats


def roi_histogram(arr, roi, bins=50, value_range=None):
    """ROI 안의 밝기 분포. (개수 배열, 구간 경계 배열)을 돌려준다.

    value_range=(최솟값, 최댓값)을 주면 그 범위만 센다 (예: HU -200 ~ 300).
    """
    values = crop(arr, roi)
    if isinstance(bins, bool) or not isinstance(bins, (int, np.integer)) or not (2 <= bins <= 512):
        raise ProcessingError("히스토그램 구간 수(bins)는 2~512 사이 정수여야 합니다.")
    if value_range is not None:
        lo, hi = value_range
        if not lo < hi:
            raise ProcessingError("히스토그램 범위는 최솟값 < 최댓값이어야 합니다.")
    counts, edges = np.histogram(values, bins=int(bins), range=value_range)
    return counts, edges


def clamp_roi_size(x, y, w, h, shape):
    """화면 슬라이더용: ROI가 영상 밖으로 나가지 않게 너비·높이를 줄여 준다.
    (x, y는 그대로 두고 w ≤ 가로 - x, h ≤ 세로 - y)"""
    H, W = shape
    x = min(max(int(x), 0), W - 1)
    y = min(max(int(y), 0), H - 1)
    w = min(max(int(w), 1), W - x)
    h = min(max(int(h), 1), H - y)
    return x, y, w, h
