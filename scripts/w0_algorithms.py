"""
W0 알고리즘 3종 시험 적용 (역할3)

분류별 1종씩:
  1) 명암·분포 조정  : CLAHE
  2) 노이즈·평활화   : Bilateral 필터
  3) 영역·경계 추출  : Otsu 이진화

사용법:
  python w0_algorithms.py                       # pydicom 내장 샘플 CT로 실행
  python w0_algorithms.py data/CT/xxx.dcm       # 우리 데이터 CT 1장으로 실행
결과: results/ 폴더에 비교 이미지 3장 저장
"""
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")  # 화면 없이 파일로만 저장
import matplotlib.pyplot as plt
import numpy as np
import pydicom

# 한글 깨짐 방지(설치된 한글 폰트가 없으면 영어로만 보임)
for font in ["Malgun Gothic", "AppleGothic", "NanumGothic"]:
    if font in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
        plt.rcParams["font.family"] = font
        break
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = Path("results")


# ---------- 0. CT 읽기 + 8비트 변환 ----------
def load_ct_hu(path):
    """DICOM을 읽어서 HU(하운스필드 단위) 배열로 바꾼다."""
    ds = pydicom.dcmread(path)
    img = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    return img * slope + intercept


def window_to_uint8(hu, level=40, width=400):
    """연부조직 창(L40/W400)으로 잘라서 0~255 8비트로 만든다.
    OpenCV의 Otsu·Bilateral 등은 8비트 입력을 기본으로 쓰기 때문."""
    low, high = level - width / 2, level + width / 2
    img = np.clip(hu, low, high)
    return ((img - low) / (high - low) * 255).astype(np.uint8)


# ---------- 1. 알고리즘 3종 ----------
def apply_clahe(img, clip_limit=2.0, tile=8):
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    return clahe.apply(img)


def apply_bilateral(img, d=9, sigma_color=50, sigma_space=50):
    return cv2.bilateralFilter(img, d, sigma_color, sigma_space)


def apply_otsu(img):
    """Otsu는 임계값을 자동으로 찾아준다. 찾은 값도 같이 돌려준다(처리 이력에 저장할 특징값)."""
    thr, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary, thr


# ---------- 2. 비교 이미지 저장 ----------
def save_compare(original, result, title, param_text, filename, show_hist=True):
    cols = 3 if show_hist else 2
    fig, ax = plt.subplots(1, cols, figsize=(5 * cols, 5))
    ax[0].imshow(original, cmap="gray", vmin=0, vmax=255)
    ax[0].set_title("Original (W400/L40)")
    ax[1].imshow(result, cmap="gray", vmin=0, vmax=255)
    ax[1].set_title(f"{title}\n{param_text}")
    for a in ax[:2]:
        a.axis("off")
    if show_hist:
        ax[2].hist(original.ravel(), bins=64, alpha=0.5, label="Original")
        ax[2].hist(result.ravel(), bins=64, alpha=0.5, label=title)
        ax[2].set_title("Histogram")
        ax[2].legend()
    fig.tight_layout()
    OUT_DIR.mkdir(exist_ok=True)
    fig.savefig(OUT_DIR / filename, dpi=120)
    plt.close(fig)
    print(f"저장: {OUT_DIR / filename}")


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        from pydicom.data import get_testdata_file
        path = get_testdata_file("CT_small.dcm")
        print("우리 데이터 경로를 안 넣어서 pydicom 내장 샘플 CT로 실행합니다.")

    hu = load_ct_hu(path)
    img = window_to_uint8(hu)
    print(f"입력: {path}  크기={img.shape}  HU 범위={hu.min():.0f}~{hu.max():.0f}")

    # 1) CLAHE
    out1 = apply_clahe(img, clip_limit=2.0, tile=8)
    save_compare(img, out1, "CLAHE", "clipLimit=2.0, tile=8x8", "1_clahe.png")

    # 2) Bilateral
    out2 = apply_bilateral(img, d=9, sigma_color=50, sigma_space=50)
    save_compare(img, out2, "Bilateral", "d=9, sigmaColor=50, sigmaSpace=50", "2_bilateral.png")

    # 3) Otsu
    out3, thr = apply_otsu(img)
    area_px = int((out3 > 0).sum())
    save_compare(img, out3, "Otsu", f"auto threshold={thr:.0f}, area={area_px}px",
                 "3_otsu.png", show_hist=False)


if __name__ == "__main__":
    main()
