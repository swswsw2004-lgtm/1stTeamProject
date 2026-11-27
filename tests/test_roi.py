"""core/roi.py 테스트 (역할3) — ROI 통계 계산 정확성, 잘못된 ROI 거절
실행: python -m pytest -q
"""
import numpy as np
import pytest

from core.processing import ProcessingError
from core.roi import clamp_roi_size, crop, roi_histogram, roi_stats


def hu_image():
    """100x100 가짜 CT: 바탕 -100 HU(지방), 가운데 40x40 = 40 HU(근육), 그 안 10x10 = 200 HU."""
    img = np.full((100, 100), -100.0)
    img[30:70, 30:70] = 40.0
    img[45:55, 45:55] = 200.0
    return img


# ---------- 통계 정확성 ----------
def test_stats_uniform_region():
    s = roi_stats(hu_image(), (30, 30, 10, 10))      # 근육만 들어간 칸
    assert s["n_px"] == 100
    assert s["mean"] == 40.0 and s["std"] == 0.0 and s["var"] == 0.0
    assert s["min"] == s["max"] == s["median"] == 40.0


def test_stats_mixed_region_matches_numpy():
    img = hu_image()
    roi = (40, 40, 20, 20)                             # 근육 300 px + 200 HU 100 px
    s = roi_stats(img, roi)
    region = img[40:60, 40:60]
    assert s["mean"] == pytest.approx(region.mean())   # (300*40 + 100*200)/400 = 80
    assert s["mean"] == pytest.approx(80.0)
    assert s["var"] == pytest.approx(region.var())
    assert s["std"] == pytest.approx(np.sqrt(s["var"]))
    assert (s["min"], s["max"]) == (40.0, 200.0)


def test_stats_records_roi_position():
    s = roi_stats(hu_image(), (5, 6, 7, 8))
    assert (s["x"], s["y"], s["w"], s["h"]) == (5, 6, 7, 8)


def test_area_mm2_uses_pixel_spacing():
    s = roi_stats(hu_image(), (0, 0, 10, 20), pixel_spacing=(0.5, 0.8))
    assert s["area_mm2"] == pytest.approx(200 * 0.5 * 0.8)


def test_works_on_uint8_too():
    img = np.zeros((10, 10), np.uint8)
    img[:, 5:] = 255
    assert roi_stats(img, (0, 0, 10, 10))["mean"] == pytest.approx(127.5)


def test_stats_does_not_modify_original():
    img = hu_image()
    before = img.copy()
    roi_stats(img, (0, 0, 50, 50), pixel_spacing=(1, 1))
    roi_histogram(img, (0, 0, 50, 50))
    assert np.array_equal(img, before)


def test_crop_shape():
    assert crop(hu_image(), (10, 20, 30, 40)).shape == (40, 30)


# ---------- 히스토그램 ----------
def test_histogram_counts_sum_to_pixels():
    counts, edges = roi_histogram(hu_image(), (20, 20, 60, 60), bins=30)
    assert counts.sum() == 60 * 60
    assert len(edges) == 31


def test_histogram_value_range():
    counts, edges = roi_histogram(hu_image(), (0, 0, 100, 100), bins=3, value_range=(-150, 250))
    assert edges[0] == -150 and edges[-1] == 250
    assert counts.sum() == 100 * 100


# ---------- 잘못된 입력 거절 ----------
@pytest.mark.parametrize("roi", [
    (0, 0, 0, 10),        # 크기 0
    (95, 0, 10, 10),      # 영상 밖
    (-1, 0, 5, 5),        # 음수
    (0, 0, 5),            # 값 3개
])
def test_rejects_bad_roi(roi):
    with pytest.raises(ProcessingError):
        roi_stats(hu_image(), roi)


@pytest.mark.parametrize("bad", [None, np.array([]), np.zeros((5, 5, 3))])
def test_rejects_bad_image(bad):
    with pytest.raises(ProcessingError):
        roi_stats(bad, (0, 0, 1, 1))


@pytest.mark.parametrize("spacing", [(0, 1), (-1, 1), ("a", 1), (1,)])
def test_rejects_bad_pixel_spacing(spacing):
    with pytest.raises(ProcessingError):
        roi_stats(hu_image(), (0, 0, 5, 5), pixel_spacing=spacing)


@pytest.mark.parametrize("kwargs", [{"bins": 1}, {"bins": 1000}, {"bins": 2.5}, {"value_range": (10, 10)}])
def test_histogram_rejects_bad_options(kwargs):
    with pytest.raises(ProcessingError):
        roi_histogram(hu_image(), (0, 0, 10, 10), **kwargs)


# ---------- 화면 슬라이더용 크기 맞추기 ----------
def test_clamp_roi_size_keeps_inside():
    assert clamp_roi_size(336, 281, 233, 128, (512, 512)) == (336, 281, 176, 128)
    assert clamp_roi_size(0, 0, 0, 0, (512, 512)) == (0, 0, 1, 1)
    assert clamp_roi_size(600, 600, 10, 10, (512, 512)) == (511, 511, 1, 1)
