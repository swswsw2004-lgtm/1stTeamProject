"""
실제 데이터로 core/dicom_io.py 동작 확인 (11/23 완료 기준: 슬라이스 정렬 확인)
담당: 역할2
사용법:
    python -X utf8 scripts/check_loading.py --root data/sts

확인 항목:
    - 환자별 CT·PT를 3D 볼륨으로 읽기 (267장)
    - 슬라이스 위치가 오름차순으로 정렬됐는지
    - CT 값이 HU 범위로 나오는지 (공기 ≈ -1000, 물 ≈ 0)
    - CT 슬라이스마다 같은 높이의 PET 슬라이스를 찾을 수 있는지
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.dicom_io import find_series, load_series  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/sts")
    args = parser.parse_args()

    infos = find_series(args.root)
    patients = sorted({i.patient_id for i in infos})
    print(f"시리즈 {len(infos)}개, 환자 {patients}\n")

    all_ok = True
    for pid in patients:
        loaded = {}
        for info in [i for i in infos if i.patient_id == pid and i.modality in ("CT", "PT")]:
            t0 = time.time()
            s = load_series(info.files)
            sec = time.time() - t0
            zs = s.z_positions
            sorted_ok = bool(np.all(np.diff(zs) > 0))
            all_ok &= sorted_ok
            loaded[s.modality] = s
            print(f"[{pid}] {s.modality:<2} {s.description:<22} shape={s.shape} "
                  f"({sec:.1f}초, {s.volume.nbytes / 1e6:.0f}MB)")
            print(f"     z: {zs[0]:.2f} → {zs[-1]:.2f} mm, 간격 {s.slice_spacing:.2f} mm, "
                  f"정렬 {'OK' if sorted_ok else '실패!'}")
            print(f"     값 범위: {s.volume.min():.1f} ~ {s.volume.max():.1f}, "
                  f"픽셀 {s.pixel_spacing[0]:.3f} mm, {s.photometric}")

        if "CT" in loaded and "PT" in loaded:
            ct, pt = loaded["CT"], loaded["PT"]
            matched = sum(pt.nearest_slice(z) is not None for z in ct.z_positions)
            same_for = ct.frame_of_reference_uid == pt.frame_of_reference_uid
            print(f"     CT↔PET 같은 높이 매칭: {matched}/{len(ct.z_positions)}장, "
                  f"좌표계 동일: {'예' if same_for else '아니오'}")
            all_ok &= matched == len(ct.z_positions)
        print()

    print("전체 결과:", "모두 정상" if all_ok else "확인 필요한 항목 있음 (위에서 '실패' 확인)")


if __name__ == "__main__":
    main()
