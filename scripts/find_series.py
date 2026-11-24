"""
다운받은 TCIA 폴더 안의 DICOM을 훑어서 시리즈별로 정리해 주는 스크립트.

사용법:
  python find_series.py "다운받은_폴더_경로"

출력:
  - 환자별로 어떤 시리즈(CT / PT / RTSTRUCT / MR ...)가 있는지, 몇 장인지
  - CT 시리즈마다 가운데 슬라이스 파일 경로 (w0_algorithms.py에 바로 넣으면 됨)
"""
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import pydicom

warnings.filterwarnings("ignore")  # 헤더 형식 경고는 결과에 영향 없어서 숨김


def scan(root):
    series = defaultdict(list)
    info = {}
    for path in Path(root).rglob("*.dcm"):
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)  # 헤더만 읽어서 빠름
        except Exception:
            continue
        uid = getattr(ds, "SeriesInstanceUID", str(path.parent))
        series[uid].append(path)
        if uid not in info:
            info[uid] = {
                "patient": getattr(ds, "PatientID", "?"),
                "modality": getattr(ds, "Modality", "?"),
                "desc": getattr(ds, "SeriesDescription", ""),
            }
    return series, info


def slice_z(path):
    """ImagePositionPatient의 z값(몸 높이 방향 위치)으로 슬라이스 순서를 맞춘다."""
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        return float(ds.ImagePositionPatient[2])
    except Exception:
        return 0.0


def main():
    if len(sys.argv) < 2:
        print('사용법: python find_series.py "다운받은_폴더_경로"')
        return
    series, info = scan(sys.argv[1])
    if not series:
        print("DICOM(.dcm) 파일을 하나도 못 찾았어요. 폴더 경로를 다시 확인해 주세요.")
        return

    by_patient = defaultdict(list)
    for uid, files in series.items():
        by_patient[info[uid]["patient"]].append((uid, files))

    for patient in sorted(by_patient):
        print(f"\n===== 환자 {patient} =====")
        for uid, files in sorted(by_patient[patient], key=lambda x: info[x[0]]["modality"]):
            m = info[uid]
            print(f"  [{m['modality']:<8}] {len(files):>4}장  {m['desc']}")
            print(f"             폴더: {files[0].parent}")
            if m["modality"] == "CT":
                files_sorted = sorted(files, key=slice_z)
                middle = files_sorted[len(files_sorted) // 2]
                print(f"             가운데 슬라이스: {middle}")


if __name__ == "__main__":
    main()
