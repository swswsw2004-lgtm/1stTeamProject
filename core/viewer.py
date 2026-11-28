"""
이미지 뷰어 로직: 창(window) · 확대/축소 · 이동 · 화면 초기화
담당: 역할2 (케이스·영상 관리·뷰어)
위치: core/viewer.py

화면(pages/2_viewer.py)은 이 함수들로 '보여줄 그림'만 만든다. 원본 볼륨(HU 값)은 바꾸지 않는다.
창 변환은 역할3 core.processing.window_to_uint8을 그대로 써서 영상처리 화면과 같은 결과가 나오게 한다.

    view = ViewState.default(shape)              # 화면 초기화 상태
    view = clamp_view(view, shape)               # 사용자가 바꾼 값을 영상 범위 안으로
    img8 = to_display(hu_slice, level, width, photometric)
    shown = render(img8, view, out_size=512)     # 확대·이동 적용
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from core.processing import ProcessingError, window_to_uint8

# 역할3 영상처리 화면과 같은 값 (연부조직 육종 데이터라 연부조직 창이 기본)
WINDOW_PRESETS = {
    "연부조직 (L40 / W400)": (40, 400),
    "좁은 연부조직 (L40 / W150)": (40, 150),
    "폐 (L-600 / W1500)": (-600, 1500),
    "뼈 (L400 / W1500)": (400, 1500),
}
DEFAULT_PRESET = "연부조직 (L40 / W400)"
ZOOM_MIN, ZOOM_MAX = 1.0, 8.0


class ViewerError(ValueError):
    """화면에 그대로 보여줄 한국어 메시지를 담는 오류."""


@dataclass(frozen=True)
class ViewState:
    """현재 보기 상태. 화면 초기화 = default()로 되돌리기."""
    slice_index: int
    zoom: float          # 1 = 전체, 2 = 2배 확대 ...
    center_row: float    # 확대했을 때 화면 가운데에 올 픽셀 위치 (이동)
    center_col: float
    level: float
    width: float

    @staticmethod
    def default(shape: tuple[int, int, int]) -> "ViewState":
        """(슬라이스 수, 행, 열) 볼륨의 처음 보기: 가운데 슬라이스, 확대 없음, 연부조직 창."""
        n, rows, cols = shape
        level, width = WINDOW_PRESETS[DEFAULT_PRESET]
        return ViewState(n // 2, 1.0, rows / 2, cols / 2, level, width)


def clamp_view(view: ViewState, shape: tuple[int, int, int]) -> ViewState:
    """잘못된 값(범위 밖 슬라이스·확대·이동)을 영상 안쪽으로 맞춘다.
    확대했을 때 보이는 영역이 영상 밖으로 나가지 않도록 가운데 위치를 제한한다."""
    n, rows, cols = shape
    if n < 1 or rows < 1 or cols < 1:
        raise ViewerError("표시할 영상이 없습니다.")
    zoom = float(min(max(view.zoom, ZOOM_MIN), ZOOM_MAX))
    half_r, half_c = rows / (2 * zoom), cols / (2 * zoom)
    return replace(
        view,
        slice_index=int(min(max(view.slice_index, 0), n - 1)),
        zoom=zoom,
        center_row=float(min(max(view.center_row, half_r), rows - half_r)),
        center_col=float(min(max(view.center_col, half_c), cols - half_c)),
    )


def crop_box(view: ViewState, rows: int, cols: int) -> tuple[int, int, int, int]:
    """확대·이동 상태에서 실제로 보이는 영역 (r0, r1, c0, c1). 끝은 포함하지 않음."""
    h, w = max(1, round(rows / view.zoom)), max(1, round(cols / view.zoom))
    r0 = int(round(view.center_row - h / 2))
    c0 = int(round(view.center_col - w / 2))
    r0, c0 = min(max(r0, 0), rows - h), min(max(c0, 0), cols - w)
    return r0, r0 + h, c0, c0 + w


def to_display(hu_slice: np.ndarray, level: float, width: float, photometric: str = "MONOCHROME2") -> np.ndarray:
    """HU(또는 PET 값) 2D → 0~255 표시용. MONOCHROME1이면 밝기를 뒤집는다."""
    if hu_slice is None or hu_slice.ndim != 2:
        raise ViewerError("2차원 슬라이스만 표시할 수 있습니다.")
    try:
        img = window_to_uint8(hu_slice, level=level, width=width)
    except ProcessingError as e:
        raise ViewerError(str(e)) from e
    return 255 - img if photometric == "MONOCHROME1" else img


def render(img: np.ndarray, view: ViewState, out_size: int = 512) -> np.ndarray:
    """보이는 영역을 잘라 out_size 크기로 키운다 (흑백·컬러 모두). 원본 배열은 바꾸지 않음."""
    rows, cols = img.shape[:2]
    r0, r1, c0, c1 = crop_box(view, rows, cols)
    part = img[r0:r1, c0:c1]
    scale = out_size / max(part.shape[0], part.shape[1])
    size = (max(1, round(part.shape[1] * scale)), max(1, round(part.shape[0] * scale)))
    # 확대할 때는 픽셀이 보이도록 nearest, 축소할 때는 area (계단·물결 무늬 방지)
    interp = cv2.INTER_NEAREST if scale >= 1 else cv2.INTER_AREA
    return cv2.resize(part, size, interpolation=interp)


def describe_view(view: ViewState, shape, pixel_spacing=None, z_mm: float | None = None) -> str:
    """화면 아래 표시 문구 (현재 위치·확대·창)."""
    n = shape[0]
    text = (f"슬라이스 {view.slice_index + 1}/{n} · 확대 {view.zoom:.1f}배 · "
            f"창 L{view.level:g}/W{view.width:g}")
    if z_mm is not None:
        text += f" · z {z_mm:.2f} mm"
    if pixel_spacing:
        fov = shape[2] * pixel_spacing[1] / view.zoom
        text += f" · 보이는 폭 {fov:.0f} mm"
    return text
