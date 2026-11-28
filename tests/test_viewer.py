"""
core/viewer.py 테스트 (역할2) — 창·확대·이동·초기화
실행: python -X utf8 -m pytest tests/test_viewer.py -v
"""
from dataclasses import replace

import numpy as np
import pytest

from core.viewer import (
    DEFAULT_PRESET,
    WINDOW_PRESETS,
    ViewerError,
    ViewState,
    clamp_view,
    crop_box,
    describe_view,
    render,
    to_display,
)

SHAPE = (267, 512, 512)


def test_default_view_is_reset_state():
    """화면 초기화: 가운데 슬라이스, 확대 없음, 연부조직 창"""
    v = ViewState.default(SHAPE)
    assert v.slice_index == 133 and v.zoom == 1.0
    assert (v.center_row, v.center_col) == (256, 256)
    assert (v.level, v.width) == WINDOW_PRESETS[DEFAULT_PRESET] == (40, 400)


def test_clamp_keeps_values_inside_image():
    v = ViewState(999, 20.0, -100, 9999, 40, 400)
    c = clamp_view(v, SHAPE)
    assert c.slice_index == 266 and c.zoom == 8.0
    half = 512 / 16
    assert c.center_row == half and c.center_col == 512 - half


def test_pan_is_limited_so_view_stays_inside():
    """2배 확대면 가운데는 128~384 사이로만 이동"""
    c = clamp_view(ViewState(0, 2.0, 10, 500, 40, 400), SHAPE)
    assert (c.center_row, c.center_col) == (128, 384)
    assert crop_box(c, 512, 512) == (0, 256, 256, 512)


def test_crop_box_size_matches_zoom():
    v = clamp_view(ViewState(0, 4.0, 256, 256, 40, 400), SHAPE)
    r0, r1, c0, c1 = crop_box(v, 512, 512)
    assert (r1 - r0, c1 - c0) == (128, 128) and (r0, c0) == (192, 192)


def test_clamp_rejects_empty_volume():
    with pytest.raises(ViewerError):
        clamp_view(ViewState.default((1, 1, 1)), (0, 512, 512))


def test_to_display_window_and_monochrome1():
    hu = np.array([[-1000.0, 40.0, 1000.0]])
    img = to_display(hu, 40, 400)
    assert img.dtype == np.uint8 and img[0, 0] == 0 and img[0, 2] == 255 and 120 <= img[0, 1] <= 135
    inv = to_display(hu, 40, 400, photometric="MONOCHROME1")
    assert inv[0, 0] == 255 and inv[0, 2] == 0


@pytest.mark.parametrize("hu, width", [(np.zeros(5), 400), (np.zeros((2, 2)), 0)])
def test_to_display_rejects_bad_input(hu, width):
    with pytest.raises(ViewerError):
        to_display(hu, 40, width)


def test_render_zoom_shows_only_cropped_area_and_keeps_original():
    img = np.zeros((512, 512), np.uint8)
    img[:256, :256] = 200                          # 왼쪽 위 1/4만 밝게
    original = img.copy()
    full = render(img, ViewState(0, 1.0, 256, 256, 40, 400), out_size=256)
    assert full.shape == (256, 256)
    zoomed = render(img, clamp_view(ViewState(0, 2.0, 0, 0, 40, 400), SHAPE), out_size=256)
    assert zoomed.shape == (256, 256) and (zoomed == 200).all()   # 확대하면 밝은 부분만 보임
    assert (img == original).all()                                 # 원본은 그대로


def test_render_color_image():
    rgb = np.zeros((40, 40, 3), np.uint8)
    out = render(rgb, ViewState(0, 2.0, 20, 20, 40, 400), out_size=80)
    assert out.shape == (80, 80, 3)


def test_describe_view_text():
    v = replace(ViewState.default(SHAPE), zoom=2.0)
    text = describe_view(v, SHAPE, pixel_spacing=(0.977, 0.977), z_mm=-11.5)
    assert "134/267" in text and "2.0배" in text and "z -11.50 mm" in text and "250 mm" in text
