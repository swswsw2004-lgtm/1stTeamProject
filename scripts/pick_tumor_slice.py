"""
RTSTRUCT(종양 윤곽)를 보고, CT 시리즈 중에서 종양이 가장 크게 보이는 슬라이스를 찾아 주는 스크립트.

사용법:
  python scripts/pick_tumor_slice.py "CT_폴더" "RTSTRUCT_폴더"

출력:
  - RTSTRUCT 안에 들어 있는 윤곽 이름 목록
  - 종양이 걸쳐 있는 높이(z) 범위와 해당 CT 장수
  - 종양 윤곽이 가장 큰 높이의 CT 파일 경로 (w0_algorithms.py에 바로 넣으면 됨)
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pydicom

warnings.filterwarnings("ignore")


def polygon_area(xs, ys):
    """신발끈 공식으로 다각형 넓이(mm^2) 계산."""
    return 0.5 * abs(np.dot(xs, np.roll(ys, 1)) - np.dot(ys, np.roll(xs, 1)))


def load_ct_z(ct_dir):
    items = []
    for path in Path(ct_dir).glob("*.dcm"):
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        items.append((float(ds.ImagePositionPatient[2]), path))
    items.sort()
    return items


def load_contours(rt_dir):
    rt_files = list(Path(rt_dir).glob("*.dcm"))
    if not rt_files:
        raise FileNotFoundError(f"RTSTRUCT 폴더에 .dcm 파일이 없어요: {rt_dir}")
    ds = pydicom.dcmread(rt_files[0], force=True)
    names = {r.ROINumber: r.ROIName for r in ds.StructureSetROISequence}

    area_by_z = {}  # z(mm) -> 그 높이의 윤곽 넓이 합
    for roi in ds.ROIContourSequence:
        name = names.get(roi.ReferencedROINumber, "?")
        n = len(getattr(roi, "ContourSequence", []))
        print(f"  윤곽: {name}  (단면 {n}개)")
        for c in getattr(roi, "ContourSequence", []):
            pts = np.array(c.ContourData, dtype=float).reshape(-1, 3)
            z = round(float(pts[0, 2]), 2)
            area_by_z[z] = area_by_z.get(z, 0) + polygon_area(pts[:, 0], pts[:, 1])
    return area_by_z


def main():
    if len(sys.argv) < 3:
        print('사용법: python scripts/pick_tumor_slice.py "CT_폴더" "RTSTRUCT_폴더"')
        return
    ct_dir, rt_dir = sys.argv[1], sys.argv[2]

    print("[RTSTRUCT 내용]")
    area_by_z = load_contours(rt_dir)
    if not area_by_z:
        print("윤곽 좌표가 없어요.")
        return

    ct = load_ct_z(ct_dir)
    ct_z = np.array([z for z, _ in ct])

    zs = sorted(area_by_z)
    best_z = max(area_by_z, key=area_by_z.get)
    idx = int(np.argmin(np.abs(ct_z - best_z)))
    in_range = [i for i, z in enumerate(ct_z) if zs[0] - 0.01 <= z <= zs[-1] + 0.01]

    print("\n[결과]")
    print(f"  CT 전체: {len(ct)}장 (z {ct_z.min():.1f} ~ {ct_z.max():.1f} mm)")
    print(f"  종양이 걸친 높이: z {zs[0]:.1f} ~ {zs[-1]:.1f} mm  → CT 약 {len(in_range)}장")
    print(f"  종양 단면이 가장 큰 높이: z {best_z:.1f} mm (윤곽 넓이 약 {area_by_z[best_z]:.0f} mm^2)")
    print(f"  그 높이의 CT: {idx + 1}번째 장 / {len(ct)}장")
    print(f"  파일 경로: {ct[idx][1]}")
    if abs(ct_z[idx] - best_z) > 5:
        print("  ※ 윤곽 높이와 가장 가까운 CT 장이 5mm 넘게 떨어져 있어요. RTSTRUCT가 이 CT용이 맞는지 확인해 주세요.")


if __name__ == "__main__":
    main()
