"""
받은 DICOM의 주요 태그를 시리즈별로 정리하는 스크립트 (11/21 작업: 태그 정리표)
담당: 역할2 (케이스·영상 관리·뷰어)

사용법:
    pip install pydicom
    python -X utf8 scripts/check_tags.py --root data/sts
결과:
    - 화면에 시리즈별 요약 출력
    - data/sts/tag_summary.csv (팀 공유용 정리표, 엑셀로 열림)
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import pydicom
from pydicom.multival import MultiValue


def get(ds, name, default=""):
    """태그가 없으면 빈 값을 돌려준다.
    값이 여러 개인 태그는 숫자면 숫자 목록, 글자(예: CorrectedImage)면 글자 목록으로."""
    v = getattr(ds, name, default)
    if isinstance(v, MultiValue):
        try:
            return [float(x) for x in v]
        except (TypeError, ValueError):
            return [str(x) for x in v]
    return v


def read_headers(root):
    """모든 DICOM의 헤더만 읽어 SeriesInstanceUID별로 묶는다(픽셀은 안 읽음)."""
    series = defaultdict(list)
    skipped = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() in {".csv", ".md", ".tcia", ".txt"}:
            continue
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=True)
            series[ds.SeriesInstanceUID].append(ds)
        except Exception:
            skipped += 1
    return series, skipped


def summarize_image_series(items):
    """CT·PT 시리즈: 크기, 픽셀 간격, 슬라이스 간격, z 범위, HU 변환값 등."""
    ds0 = items[0]
    # 정렬은 파일명이 아니라 ImagePositionPatient의 z값 기준
    zs = sorted(float(d.ImagePositionPatient[2]) for d in items if hasattr(d, "ImagePositionPatient"))
    gaps = [round(b - a, 3) for a, b in zip(zs, zs[1:])]
    row = {
        "Rows x Cols": f"{get(ds0, 'Rows')} x {get(ds0, 'Columns')}",
        "PixelSpacing(mm)": get(ds0, "PixelSpacing"),
        "SliceThickness(mm)": get(ds0, "SliceThickness"),
        "z 간격(mm, 실측)": sorted(set(gaps)) if gaps else "",
        "z 범위(mm)": f"{zs[0]:.1f} ~ {zs[-1]:.1f}" if zs else "",
        "ImageOrientation": get(ds0, "ImageOrientationPatient"),
        "Photometric": get(ds0, "PhotometricInterpretation"),
        "RescaleSlope": get(ds0, "RescaleSlope"),
        "RescaleIntercept": get(ds0, "RescaleIntercept"),
        "BitsStored": get(ds0, "BitsStored"),
        "FrameOfReferenceUID": get(ds0, "FrameOfReferenceUID"),
    }
    if ds0.Modality == "PT":
        # SUV 변환에 필요한 태그
        radio = ds0.get("RadiopharmaceuticalInformationSequence")
        r0 = radio[0] if radio else None
        row.update({
            "PT Units": get(ds0, "Units"),
            "PT DecayCorrection": get(ds0, "DecayCorrection"),
            "PT CorrectedImage": get(ds0, "CorrectedImage"),
            "PatientWeight(kg)": get(ds0, "PatientWeight"),
            "Radiopharmaceutical": get(r0, "Radiopharmaceutical") if r0 else "",
            "TotalDose(Bq)": get(r0, "RadionuclideTotalDose") if r0 else "",
            "InjectionStartTime": get(r0, "RadiopharmaceuticalStartTime") if r0 else "",
            "SeriesTime": get(ds0, "SeriesTime"),
            "AcquisitionTime": get(ds0, "AcquisitionTime"),
        })
    return row


def summarize_rtstruct(ds):
    """RTSTRUCT: ROI 이름, 윤곽 개수, 어느 영상 시리즈 기준인지."""
    rois = [r.ROIName for r in ds.get("StructureSetROISequence", [])]
    n_contours = sum(len(c.get("ContourSequence", [])) for c in ds.get("ROIContourSequence", []))
    ref_series = ""
    try:
        ref_series = (ds.ReferencedFrameOfReferenceSequence[0]
                      .RTReferencedStudySequence[0]
                      .RTReferencedSeriesSequence[0].SeriesInstanceUID)
    except (AttributeError, IndexError):
        pass
    return {
        "ROI 이름": rois,
        "윤곽(슬라이스) 수": n_contours,
        "기준 영상 SeriesUID": ref_series,
        "FrameOfReferenceUID": get(ds, "FrameOfReferenceUID"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/sts")
    args = parser.parse_args()
    root = Path(args.root)

    series, skipped = read_headers(root)
    uid_to_label = {}
    rows = []
    for uid, items in series.items():
        ds0 = items[0]
        base = {
            "PatientID": get(ds0, "PatientID"),
            "Modality": ds0.Modality,
            "SeriesDescription": get(ds0, "SeriesDescription"),
            "장수": len(items),
            "SeriesInstanceUID": uid,
        }
        uid_to_label[uid] = f"{base['PatientID']} {base['Modality']}"
        extra = summarize_rtstruct(ds0) if ds0.Modality == "RTSTRUCT" else summarize_image_series(items)
        rows.append({**base, **extra})

    # RTSTRUCT가 어느 영상(CT/PT) 기준인지 읽기 쉽게 표시
    for r in rows:
        ref = r.get("기준 영상 SeriesUID")
        if ref:
            r["기준 영상"] = uid_to_label.get(ref, "(받은 데이터에 없음)")

    rows.sort(key=lambda r: (r["PatientID"], r["Modality"], str(r["SeriesDescription"])))

    for r in rows:
        print("=" * 70)
        for k, v in r.items():
            if k != "SeriesInstanceUID":
                print(f"  {k:<22}: {v}")
    print("=" * 70)
    print(f"시리즈 {len(rows)}개, DICOM이 아니라서 건너뛴 파일 {skipped}개")

    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    out = root / "tag_summary.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:   # 엑셀 한글 깨짐 방지
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"정리표 저장: {out}")


if __name__ == "__main__":
    main()