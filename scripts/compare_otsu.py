"""
Otsu 개선 전/후 비교 (역할3, 보고서 03장 그림·검증용)

같은 CT 장, 같은 종양 ROI에서
  ① 개선 전: apply_otsu(img, roi)
  ② 개선 후: apply_otsu(img, roi, ignore_bright=True, invert=True)
를 돌리고, RTSTRUCT 정답 종양 윤곽과 얼마나 겹치는지(Dice)를 계산한다.

사용법:
  python scripts/compare_otsu.py "CT파일.dcm" "RTSTRUCT_폴더"

결과:
  - results/otsu_before_after.png : 원본+정답 윤곽 / 개선 전 / 개선 후
  - 터미널: 임계값, 면적(px, mm²), 정답과의 Dice
"""
import sys
import warnings
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pydicom

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.processing import apply_otsu, window_to_uint8

warnings.filterwarnings("ignore")
OUT = Path("results")


def contour_mask(ds, rt, name_hint="Mass"):
    """이 CT 장 높이(z)에 있는 RTSTRUCT 윤곽을 픽셀 마스크로 바꾼다.
    윤곽 이름에 name_hint가 들어간 것이 있으면 그것만 쓴다 (예: GTV_Mass, 부종 GTV_Edema 제외)."""
    names = {r.ROINumber: r.ROIName for r in rt.StructureSetROISequence}
    print("  RTSTRUCT 윤곽 이름:", ", ".join(names.values()))
    rois = [r for r in rt.ROIContourSequence if name_hint.lower() in names.get(r.ReferencedROINumber, "").lower()]
    if not rois:
        rois = list(rt.ROIContourSequence)
        print(f"  '{name_hint}'가 들어간 윤곽이 없어서 전체 윤곽을 사용합니다.")
    else:
        print("  사용한 윤곽:", ", ".join(names[r.ReferencedROINumber] for r in rois))

    z = float(ds.ImagePositionPatient[2])
    x0, y0 = float(ds.ImagePositionPatient[0]), float(ds.ImagePositionPatient[1])
    row_mm, col_mm = (float(v) for v in ds.PixelSpacing)
    mask = np.zeros((ds.Rows, ds.Columns), np.uint8)
    for roi in rois:
        for c in getattr(roi, "ContourSequence", []):
            p = np.array(c.ContourData, float).reshape(-1, 3)
            if abs(p[0, 2] - z) < 1.0:
                cols = (p[:, 0] - x0) / col_mm   # mm → 픽셀 (축상 영상 기준)
                rows = (p[:, 1] - y0) / row_mm
                pts = np.round(np.stack([cols, rows], axis=1)).astype(np.int32)
                cv2.fillPoly(mask, [pts], 1)
    return mask.astype(bool)


def bbox_roi(mask, shape, margin=10):
    ys, xs = np.nonzero(mask)
    x, y = max(xs.min() - margin, 0), max(ys.min() - margin, 0)
    x2, y2 = min(xs.max() + 1 + margin, shape[1]), min(ys.max() + 1 + margin, shape[0])
    return int(x), int(y), int(x2 - x), int(y2 - y)


def dice(a, b):
    """두 영역이 얼마나 겹치는지 (1 = 완전히 같음, 0 = 하나도 안 겹침)."""
    s = a.sum() + b.sum()
    return float(2 * (a & b).sum() / s) if s else 0.0


def main():
    if len(sys.argv) < 3:
        print('사용법: python scripts/compare_otsu.py "CT파일.dcm" "RTSTRUCT_폴더"')
        return
    ds = pydicom.dcmread(sys.argv[1], force=True)
    hu = ds.pixel_array * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
    img = window_to_uint8(hu)

    rt_files = sorted(Path(sys.argv[2]).glob("*.dcm"))
    if not rt_files:
        print("RTSTRUCT 폴더에 .dcm 파일이 없습니다.")
        return
    rt = pydicom.dcmread(rt_files[0], force=True)
    print("[정답 윤곽]")
    gt = contour_mask(ds, rt)
    if not gt.any():
        print(f"  이 CT 장 높이(z={float(ds.ImagePositionPatient[2]):.1f})에 종양 윤곽이 없습니다. "
              "scripts/pick_tumor_slice.py로 종양이 보이는 장을 먼저 찾아 주세요.")
        return
    roi = bbox_roi(gt, img.shape)
    px_mm2 = float(ds.PixelSpacing[0]) * float(ds.PixelSpacing[1])
    print(f"  정답 종양 면적: {gt.sum()} px ({gt.sum() * px_mm2:.0f} mm²), ROI={roi}")

    before, fb = apply_otsu(img, roi=roi)
    after, fa = apply_otsu(img, roi=roi, ignore_bright=True, invert=True)
    db, da = dice(before > 0, gt), dice(after > 0, gt)

    print("\n[결과]")
    print(f"  개선 전: 임계값 {fb['threshold']:.0f}, 면적 {fb['area_px']} px ({fb['area_px'] * px_mm2:.0f} mm²), Dice {db:.3f}")
    print(f"  개선 후: 임계값 {fa['threshold']:.0f}, 면적 {fa['area_px']} px ({fa['area_px'] * px_mm2:.0f} mm²), "
          f"Dice {da:.3f}  (제외한 밝은 픽셀 {fa['ignored_px']} px)")

    x, y, w, h = roi
    pad = 30
    crop = (slice(max(y - pad, 0), y + h + pad), slice(max(x - pad, 0), x + w + pad))
    fig, ax = plt.subplots(1, 3, figsize=(15, 5.4))
    panels = [
        ("Original (green=RTSTRUCT tumor, red=ROI)", img, None),
        (f"Before: otsu(roi)\nthr={fb['threshold']:.0f}, Dice={db:.2f}", before, None),
        (f"After: ignore_bright + invert\nthr={fa['threshold']:.0f}, Dice={da:.2f}", after, None),
    ]
    for a, (title, im, _) in zip(ax, panels):
        a.imshow(im[crop], cmap="gray", vmin=0, vmax=255)
        a.contour(gt[crop], levels=[0.5], colors="lime", linewidths=1.2)
        a.add_patch(plt.Rectangle((x - crop[1].start, y - crop[0].start), w, h,
                                  fill=False, edgecolor="red", linewidth=1.2))
        a.set_title(title)
        a.axis("off")
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "otsu_before_after.png", dpi=110)
    print(f"\n저장: {OUT / 'otsu_before_after.png'}")


if __name__ == "__main__":
    main()
