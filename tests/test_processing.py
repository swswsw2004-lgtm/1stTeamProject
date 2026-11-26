"""core/processing.py 테스트 (역할3)
실행: python -m pytest -q
"""
import numpy as np
import pytest

from core.processing import (
    ProcessingError, apply_bilateral, apply_clahe, apply_otsu,
    default_params, run_algorithm, window_to_uint8,
)


def sample():
    """64x64 영상, 가운데 32x32 밝은 사각형(가짜 종양) + 약한 잡음."""
    rng = np.random.default_rng(0)
    img = np.full((64, 64), 60, np.uint8)
    img[16:48, 16:48] = 180
    noise = rng.integers(-5, 6, img.shape)
    return np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)


# ---------- 전처리 ----------
def test_window_to_uint8_range():
    hu = np.array([[-1000, 40, 1000]], np.float32)
    out = window_to_uint8(hu)
    assert out.dtype == np.uint8
    assert out[0, 0] == 0 and out[0, 2] == 255


def test_window_rejects_zero_width():
    with pytest.raises(ProcessingError):
        window_to_uint8(np.zeros((4, 4)), width=0)


# ---------- 정상 동작 ----------
def test_clahe_keeps_shape_and_type():
    out = apply_clahe(sample())
    assert out.shape == (64, 64) and out.dtype == np.uint8


def test_bilateral_reduces_noise():
    img = sample()
    out = apply_bilateral(img)
    # 사각형 안쪽 잡음(표준편차)이 줄어야 함
    assert out[20:44, 20:44].std() < img[20:44, 20:44].std()


def test_otsu_finds_square():
    binary, f = apply_otsu(sample())
    assert f["area_px"] == 32 * 32
    assert 60 < f["threshold"] < 180


def test_otsu_with_roi_only_inside():
    binary, f = apply_otsu(sample(), roi=(10, 10, 20, 20))
    assert binary[:10, :].sum() == 0 and binary[:, :10].sum() == 0  # ROI 밖은 0
    assert f["area_px"] == 14 * 14  # ROI(10~30) 안의 사각형(16~30) 부분


def test_same_params_same_result():
    """재현성: 같은 설정이면 같은 결과"""
    a, _ = run_algorithm("clahe", sample(), {"clip_limit": 3.0})
    b, _ = run_algorithm("clahe", sample(), {"clip_limit": 3.0})
    assert np.array_equal(a, b)


def test_run_algorithm_features():
    _, f = run_algorithm("otsu", sample())
    assert {"threshold", "area_px", "mean", "std"} <= set(f)


def test_default_params():
    assert default_params("bilateral") == {"d": 9, "sigma_color": 50.0, "sigma_space": 50.0}
    assert default_params("otsu") == {"ignore_bright": False, "invert": False}


# ---------- 잘못된 입력 거절 ----------
@pytest.mark.parametrize("bad", [
    None,
    np.array([], np.uint8),
    np.zeros((8, 8, 3), np.uint8),     # 컬러(3차원)
    np.zeros((8, 8), np.int16),        # 8비트 아님 (CT 원본 그대로)
    [[1, 2], [3, 4]],                  # numpy 배열 아님
])
def test_rejects_bad_image(bad):
    with pytest.raises(ProcessingError):
        apply_clahe(bad)


@pytest.mark.parametrize("kwargs", [
    {"clip_limit": 0},
    {"clip_limit": -1},
    {"clip_limit": "2"},
    {"tile": 1},
    {"tile": 8.5},
])
def test_clahe_rejects_bad_params(kwargs):
    with pytest.raises(ProcessingError):
        apply_clahe(sample(), **kwargs)


@pytest.mark.parametrize("kwargs", [{"d": 0}, {"d": 30}, {"sigma_color": 0}])
def test_bilateral_rejects_bad_params(kwargs):
    with pytest.raises(ProcessingError):
        apply_bilateral(sample(), **kwargs)


@pytest.mark.parametrize("roi", [
    (0, 0, 0, 10),     # 크기 0
    (60, 60, 10, 10),  # 영상 밖으로 나감
    (-1, 0, 5, 5),     # 음수
    (0, 0, 5),         # 값 3개
])
def test_otsu_rejects_bad_roi(roi):
    with pytest.raises(ProcessingError):
        apply_otsu(sample(), roi=roi)


def test_unknown_algorithm_and_param():
    with pytest.raises(ProcessingError):
        run_algorithm("canny", sample())
    with pytest.raises(ProcessingError):
        run_algorithm("clahe", sample(), {"sigma": 3})


# ---------- Otsu 개선 (ignore_bright, invert) ----------
def tumor_with_bone():
    """STS_001에서 본 상황을 흉내 낸 영상.
    근육(밝기 120) 안에 근육보다 어두운 종양(80, 20x20) + 뼈(255, 10x10)."""
    img = np.full((64, 64), 120, np.uint8)
    img[20:40, 20:40] = 80      # 종양: 근육보다 어두움
    img[5:15, 45:55] = 255      # 뼈: 연부조직 창에서 255로 포화
    return img


def test_otsu_threshold_matches_opencv():
    import cv2
    from core.processing import otsu_threshold
    rng = np.random.default_rng(1)
    for _ in range(50):
        img = rng.integers(0, 256, (32, 32)).astype(np.uint8)
        thr, _ = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        assert otsu_threshold(img) == thr


def test_otsu_default_is_pulled_by_bone():
    """기존 방식: 뼈 때문에 '뼈 vs 나머지'로 나뉘어 종양이 안 잡힘 (개선 전 문제 재현)"""
    binary, f = apply_otsu(tumor_with_bone())
    assert f["area_px"] == 10 * 10          # 뼈만 흰색


def test_otsu_ignore_bright_and_invert_finds_tumor():
    """개선: 뼈를 빼고 계산 + 어두운 쪽을 흰색 → 종양만 정확히 잡힘"""
    binary, f = apply_otsu(tumor_with_bone(), ignore_bright=True, invert=True)
    assert f["area_px"] == 20 * 20
    assert f["ignored_px"] == 10 * 10
    assert binary[20:40, 20:40].min() == 255   # 종양 전체가 흰색
    assert binary[5:15, 45:55].max() == 0      # 뼈는 결과에서 제외


def test_otsu_ignore_bright_only_keeps_bright_side():
    """invert 없이 뼈만 빼면 '근육(밝은 쪽) vs 종양'으로 나뉘어 근육이 흰색"""
    binary, f = apply_otsu(tumor_with_bone(), ignore_bright=True)
    assert f["area_px"] == 64 * 64 - 20 * 20 - 10 * 10


def test_otsu_options_with_roi():
    binary, f = apply_otsu(tumor_with_bone(), roi=(15, 0, 45, 45), ignore_bright=True, invert=True)
    assert f["area_px"] == 20 * 20
    assert binary[:, :15].sum() == 0           # ROI 밖은 0


def test_run_algorithm_passes_otsu_options():
    _, f = run_algorithm("otsu", tumor_with_bone(), {"ignore_bright": True, "invert": True})
    assert f["area_px"] == 20 * 20


@pytest.mark.parametrize("kwargs", [
    {"ignore_bright": "yes"},
    {"invert": 1},
    {"bright_cutoff": 0},
    {"bright_cutoff": 300},
])
def test_otsu_rejects_bad_options(kwargs):
    with pytest.raises(ProcessingError):
        apply_otsu(tumor_with_bone(), **kwargs)


def test_otsu_all_pixels_ignored():
    """ROI 안이 전부 뼈(255)면 계산할 픽셀이 없어서 이유를 알려 줌"""
    with pytest.raises(ProcessingError):
        apply_otsu(tumor_with_bone(), roi=(45, 5, 10, 10), ignore_bright=True)
