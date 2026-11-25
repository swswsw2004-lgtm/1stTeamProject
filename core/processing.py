"""
영상처리 알고리즘 3종 (역할3)

분류별 1종:
  1) 명암·분포 조정 : CLAHE            apply_clahe()
  2) 노이즈·평활화  : Bilateral 필터   apply_bilateral()
  3) 영역·경계 추출 : Otsu 이진화      apply_otsu()

모든 함수는 입력을 먼저 검사하고, 문제가 있으면 ProcessingError를 낸다.
화면(pages/3_영상처리.py)에서는 이 에러 메시지를 그대로 사용자에게 보여 주면 된다.
"""
import cv2
import numpy as np

ALGO_VERSION = "1.1.0"  # 알고리즘 코드가 바뀌면 올린다 (processing_history에 같이 저장)


class ProcessingError(ValueError):
    """입력 영상이나 파라미터가 잘못됐을 때 내는 에러."""


# ---------------------------------------------------------------
# 입력 검사
# ---------------------------------------------------------------
def check_image(img):
    """2차원 8비트(uint8) 영상인지 확인한다."""
    if img is None:
        raise ProcessingError("영상이 없습니다.")
    if not isinstance(img, np.ndarray):
        raise ProcessingError("영상 형식이 올바르지 않습니다 (numpy 배열이 아님).")
    if img.size == 0:
        raise ProcessingError("빈 영상입니다.")
    if img.ndim != 2:
        raise ProcessingError(f"흑백 2차원 영상만 처리할 수 있습니다 (현재 {img.ndim}차원).")
    if img.dtype != np.uint8:
        raise ProcessingError(
            f"8비트 영상만 처리할 수 있습니다 (현재 {img.dtype}). "
            "CT는 window_to_uint8()로 먼저 변환해 주세요."
        )
    return img


def check_number(name, value, low, high, integer=False):
    """파라미터가 숫자이고 [low, high] 범위 안에 있는지 확인한다."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ProcessingError(f"{name} 값은 숫자여야 합니다 (현재 {value!r}).")
    if integer and int(value) != value:
        raise ProcessingError(f"{name} 값은 정수여야 합니다 (현재 {value}).")
    if not (low <= value <= high):
        raise ProcessingError(f"{name} 값은 {low}~{high} 사이여야 합니다 (현재 {value}).")
    return int(value) if integer else float(value)


def check_bool(name, value):
    """옵션 값이 True/False인지 확인한다."""
    if not isinstance(value, (bool, np.bool_)):
        raise ProcessingError(f"{name} 값은 True 또는 False여야 합니다 (현재 {value!r}).")
    return bool(value)


def check_roi(img, roi):
    """ROI(x, y, w, h)가 영상 안에 있고 크기가 0이 아닌지 확인한다."""
    if roi is None:
        return None
    if len(roi) != 4:
        raise ProcessingError("ROI는 (x, y, 너비, 높이) 4개 값이어야 합니다.")
    x, y, w, h = (check_number(n, v, 0, 100000, integer=True)
                  for n, v in zip(("ROI x", "ROI y", "ROI 너비", "ROI 높이"), roi))
    if w == 0 or h == 0:
        raise ProcessingError("ROI 크기가 0입니다. 너비와 높이를 1 이상으로 지정해 주세요.")
    H, W = img.shape
    if x + w > W or y + h > H:
        raise ProcessingError(f"ROI가 영상 밖으로 나갑니다 (영상 크기 {W}x{H}).")
    return x, y, w, h


# ---------------------------------------------------------------
# 전처리: CT(HU) → 8비트
# ---------------------------------------------------------------
def window_to_uint8(hu, level=40, width=400):
    """CT HU 값을 창(level/width)으로 잘라 0~255 8비트로 바꾼다.
    기본값 L40/W400은 연부조직 창 (우리 데이터가 연부조직 육종이라서)."""
    if not isinstance(hu, np.ndarray) or hu.size == 0:
        raise ProcessingError("변환할 CT 영상이 없습니다.")
    level = check_number("창 중심(level)", level, -2000, 4000)
    width = check_number("창 너비(width)", width, 1, 6000)
    low, high = level - width / 2, level + width / 2
    img = np.clip(hu.astype(np.float32), low, high)
    return ((img - low) / (high - low) * 255).astype(np.uint8)


# ---------------------------------------------------------------
# 알고리즘 3종
# ---------------------------------------------------------------
def apply_clahe(img, clip_limit=2.0, tile=8):
    """CLAHE: 영상을 작은 구역(tile)으로 나눠 구역마다 대비를 높인다.
    clip_limit가 클수록 대비가 세지지만 잡음도 같이 커진다."""
    check_image(img)
    clip_limit = check_number("clip_limit", clip_limit, 0.1, 40)
    tile = check_number("tile", tile, 2, 64, integer=True)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    return clahe.apply(img)


def apply_bilateral(img, d=9, sigma_color=50, sigma_space=50):
    """Bilateral 필터: 가까우면서 밝기도 비슷한 픽셀끼리만 평균을 내서
    잡음은 줄이고 경계는 덜 흐리게 한다."""
    check_image(img)
    d = check_number("d", d, 1, 25, integer=True)
    sigma_color = check_number("sigma_color", sigma_color, 1, 300)
    sigma_space = check_number("sigma_space", sigma_space, 1, 300)
    return cv2.bilateralFilter(img, d, sigma_color, sigma_space)


def otsu_threshold(values):
    """Otsu 임계값을 직접 계산한다 (0~255 정수 픽셀 배열).
    임계값 t로 나눴을 때 두 무리의 '무리 사이 분산'이 가장 큰 t를 고른다.
    OpenCV(cv2.THRESH_OTSU)와 같은 값을 돌려주며, 일부 픽셀만 골라서 계산할 수 있게 직접 구현했다."""
    values = np.asarray(values).ravel()
    if values.size == 0:
        raise ProcessingError("임계값을 계산할 픽셀이 없습니다 (밝은 픽셀을 빼고 나니 남은 픽셀이 0개).")
    hist = np.bincount(values.astype(np.int64), minlength=256)[:256].astype(np.float64)
    prob = hist / hist.sum()
    levels = np.arange(256, dtype=np.float64)
    w0 = np.cumsum(prob)                  # 어두운 무리 비율
    mu = np.cumsum(prob * levels)         # 누적 평균
    mu_total = mu[-1]
    w1 = 1.0 - w0                         # 밝은 무리 비율
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu_total * w0 - mu) ** 2 / (w0 * w1)
    between[~np.isfinite(between)] = -1.0
    return float(np.argmax(between))


def apply_otsu(img, roi=None, ignore_bright=False, invert=False, bright_cutoff=250):
    """Otsu 이진화: 밝은 쪽/어두운 쪽을 가장 잘 나누는 임계값을 자동으로 찾는다.

    roi=(x, y, w, h)    : 그 영역 안에서만 임계값을 찾고, 영역 밖은 0으로 둔다.
                          (슬라이스 전체에 걸면 근육·종양 vs 지방, 침대까지 같이 잡혀서 종양만 따로 안 나옴)
    ignore_bright=True  : bright_cutoff 이상인 아주 밝은 픽셀(연부조직 창에서 255로 포화된 뼈 등)을
                          빼고 임계값을 계산하고, 결과에서도 제외한다.
                          (ROI에 뼈가 섞이면 '뼈 vs 나머지'로 나뉘어 버리는 문제 해결)
    invert=True         : 임계값보다 어두운 쪽을 흰색(관심 영역)으로 표시한다.
                          (종양이 주변 근육보다 어두워서 검은색으로 나오는 문제 해결)

    반환: (이진 영상, 특징값 dict)"""
    check_image(img)
    roi = check_roi(img, roi)
    ignore_bright = check_bool("ignore_bright", ignore_bright)
    invert = check_bool("invert", invert)
    bright_cutoff = check_number("bright_cutoff", bright_cutoff, 1, 255, integer=True)

    if roi is None:
        x, y, h, w = 0, 0, img.shape[0], img.shape[1]
    else:
        x, y, w, h = roi
    target = img[y:y + h, x:x + w]

    use = target < bright_cutoff if ignore_bright else np.ones_like(target, dtype=bool)
    thr = otsu_threshold(target[use])
    region = (target <= thr) if invert else (target > thr)
    region &= use

    out = np.zeros_like(img)
    out[y:y + h, x:x + w][region] = 255
    features = {
        "threshold": thr,
        "area_px": int(region.sum()),
        "ignored_px": int((~use).sum()),
    }
    return out, features


# ---------------------------------------------------------------
# 이름으로 실행하기 (화면 슬라이더, 처리 이력 재현에서 사용)
# ---------------------------------------------------------------
ALGORITHMS = {
    "clahe": {
        "label": "CLAHE (명암·분포 조정)",
        "func": apply_clahe,
        "params": {
            "clip_limit": {"default": 2.0, "min": 0.1, "max": 40.0, "step": 0.1},
            "tile": {"default": 8, "min": 2, "max": 64, "step": 1},
        },
    },
    "bilateral": {
        "label": "Bilateral 필터 (노이즈·평활화)",
        "func": apply_bilateral,
        "params": {
            "d": {"default": 9, "min": 1, "max": 25, "step": 1},
            "sigma_color": {"default": 50.0, "min": 1.0, "max": 300.0, "step": 1.0},
            "sigma_space": {"default": 50.0, "min": 1.0, "max": 300.0, "step": 1.0},
        },
    },
    "otsu": {
        "label": "Otsu 이진화 (영역·경계 추출)",
        "func": apply_otsu,
        "params": {  # 임계값은 자동, ROI는 따로 받음
            "ignore_bright": {"default": False, "type": "bool"},
            "invert": {"default": False, "type": "bool"},
        },
    },
}


def default_params(name):
    if name not in ALGORITHMS:
        raise ProcessingError(f"지원하지 않는 알고리즘입니다: {name}")
    return {k: v["default"] for k, v in ALGORITHMS[name]["params"].items()}


def run_algorithm(name, img, params=None, roi=None):
    """알고리즘 이름과 파라미터로 실행하고 (결과 영상, 특징값)을 돌려준다.
    특징값은 processing_history의 features 필드에 그대로 저장하면 된다."""
    if name not in ALGORITHMS:
        raise ProcessingError(f"지원하지 않는 알고리즘입니다: {name}")
    params = {**default_params(name), **(params or {})}
    unknown = set(params) - set(ALGORITHMS[name]["params"])
    if unknown:
        raise ProcessingError(f"{name}에 없는 파라미터입니다: {', '.join(sorted(unknown))}")

    func = ALGORITHMS[name]["func"]
    if name == "otsu":
        result, features = func(img, roi=roi, **params)
    else:
        result = func(img, **params)
        features = {}
    features.update({"mean": float(result.mean()), "std": float(result.std())})
    return result, features
