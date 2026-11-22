"""
TCIA Soft-tissue-Sarcoma 데이터 중 PET/CT 검사의 CT·PET·RTSTRUCT만 내려받는 스크립트
담당: 역할2 (케이스·영상 관리·뷰어)
데이터 출처: TCIA Soft-tissue-Sarcoma, DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0
다운로드 경로: NCI Imaging Data Commons (IDC)

사용법:
    pip install idc-index pandas
    python scripts/download_sts.py --ids STS_001 STS_002 STS_003 --dry-run
    python scripts/download_sts.py --ids STS_001 STS_002 STS_003 --out data/sts
"""
import argparse
from pathlib import Path

from idc_index import IDCClient

COLLECTION = "soft_tissue_sarcoma"          # IDC에서의 컬렉션 ID
NEEDED = {"CT", "PT", "RTSTRUCT"}           # DICOM Modality 값 (PET은 'PT')


def find_series(client):
    """PET이 들어 있는 검사(Study) 안의 CT·PT·RTSTRUCT 시리즈를 조회한다."""
    query = f"""
        WITH pet_studies AS (
            SELECT DISTINCT StudyInstanceUID
            FROM index
            WHERE collection_id = '{COLLECTION}' AND Modality = 'PT'
        )
        SELECT PatientID, StudyInstanceUID, SeriesInstanceUID, Modality,
               SeriesDescription, instanceCount, series_size_MB
        FROM index
        WHERE collection_id = '{COLLECTION}'
          AND StudyInstanceUID IN (SELECT StudyInstanceUID FROM pet_studies)
          AND Modality IN ('CT', 'PT', 'RTSTRUCT')
        ORDER BY PatientID, Modality
    """
    return client.sql_query(query)


def keep_needed_series(df):
    """CT, PT는 그대로 쓰고, RTSTRUCT는 RTstruct_PET / RTstruct_CT만 남긴다.
    이름에 'Aligned'(오타 'Alligned' 포함)가 들어간 MR 정합용 시리즈는 제외한다."""
    desc = df["SeriesDescription"].fillna("").str.lower()
    is_aligned = desc.str.contains("align")
    keep_rt = (df["Modality"] == "RTSTRUCT") & desc.isin(["rtstruct_pet", "rtstruct_ct"])
    keep_img = df["Modality"].isin(["CT", "PT"])
    return df[(keep_img | keep_rt) & ~is_aligned]


def pick_patients(df, n, patient_ids=None):
    """CT·PT·RTSTRUCT가 모두 있는 환자 중에서 고른다."""
    complete = [
        pid for pid, g in df.groupby("PatientID")
        if NEEDED.issubset(set(g["Modality"]))
    ]
    chosen = [p for p in patient_ids if p in complete] if patient_ids else complete[:n]
    return df[df["PatientID"].isin(chosen)], len(complete)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--patients", type=int, default=3, help="받을 환자 수")
    parser.add_argument("--out", default="data/sts", help="저장 폴더")
    parser.add_argument("--ids", nargs="*", help="환자 ID 지정 (예: --ids STS_001 STS_002)")
    parser.add_argument("--dry-run", action="store_true", help="목록과 용량만 출력")
    args = parser.parse_args()

    client = IDCClient()
    df = keep_needed_series(find_series(client))
    sel, n_complete = pick_patients(df, args.patients, args.ids)

    print(f"CT·PET·RTSTRUCT가 모두 있는 환자: {n_complete}명 중 {sel['PatientID'].nunique()}명 선택")
    print(sel[["PatientID", "Modality", "SeriesDescription", "instanceCount", "series_size_MB"]]
          .to_string(index=False))
    print(f"\n예상 용량: {sel['series_size_MB'].sum():.1f} MB")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sel.to_csv(out / "series_list.csv", index=False)   # 재현용 목록
    print(f"시리즈 목록 저장: {out / 'series_list.csv'}")

    if args.dry_run:
        print("\n[dry-run] 다운로드하지 않았습니다. --dry-run 을 빼고 다시 실행하세요.")
        return

    client.download_from_selection(
        seriesInstanceUID=sel["SeriesInstanceUID"].tolist(),
        downloadDir=str(out),
    )
    print("다운로드 완료")


if __name__ == "__main__":
    main()