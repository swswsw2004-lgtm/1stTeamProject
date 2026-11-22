# data/ — 시연용 데이터 (교육용 모의 케이스)

이 폴더의 **DICOM 영상 파일은 Git에 올리지 않습니다** (약 455 MB, `.gitignore`로 제외).
아래 방법으로 누구나 같은 데이터를 다시 받을 수 있습니다.

## 출처
- 데이터셋: **Soft-tissue-Sarcoma** — The Cancer Imaging Archive (TCIA)
- DOI: https://doi.org/10.7937/K9/TCIA.2015.7GO2GSKS
- 라이선스: CC BY 3.0
- 인용: Vallières, M. et al. (2015). A radiomics model from joint FDG-PET and MRI texture features for the prediction of lung metastases in soft-tissue sarcomas of the extremities. *Physics in Medicine and Biology*, 60(14), 5471–5496.
- 다운로드 경로: NCI Imaging Data Commons (`idc-index`), 컬렉션 ID `soft_tissue_sarcoma`
- 다운로드 날짜: 2026-11-22 (역할2)

## 사용 범위
- 환자 3명: **STS_001, STS_002, STS_003**
- 환자마다 PET/CT 검사의 시리즈 4개 = 총 12개 시리즈

| 종류 | 시리즈 | 비고 |
|---|---|---|
| CT | 267장, 512×512 | 융합의 바탕 영상 |
| PT (PET) | 267장, 128×128 | 감쇠보정(AC) PET |
| RTSTRUCT | `RTstruct_PET` | PET 기준 종양 윤곽 (`GTV_Mass`, `GTV_Edema`) |
| RTSTRUCT | `RTstruct_CT` | CT 기준 종양 윤곽 (`GTV_Mass`, `GTV_Edema`) |

- 제외: MRI, 이름에 `Aligned`가 붙은 MR 정합용 시리즈·윤곽, 임상 XLSX
- 시리즈 전체 목록(UID 포함): `sts/series_list.csv`
- 태그 정리표: `sts/tag_summary.csv` · 해석과 주의점: `DATA_NOTES.md`

## 다시 받는 방법
```bash
pip install idc-index pandas pydicom

# 1) 받을 목록 확인 (12개 시리즈, 약 455 MB가 나오면 정상)
python -X utf8 scripts/download_sts.py --ids STS_001 STS_002 STS_003 --dry-run

# 2) 실제 다운로드 → data/sts/ 아래에 저장
python -X utf8 scripts/download_sts.py --ids STS_001 STS_002 STS_003 --out data/sts

# 3) 태그 정리표 생성 (시리즈 12개, 건너뛴 파일 0개가 나오면 정상)
python -X utf8 scripts/check_tags.py --root data/sts
```

> **Windows(한국어) 주의:** `-X utf8`을 빼면 `idc-index` 내부에서 `UnicodeDecodeError: 'cp949' codec...` 오류가 납니다.
> PowerShell에서 `$env:PYTHONUTF8 = "1"`을 먼저 입력해도 됩니다.

> 이 데이터는 교육용 모의 케이스로만 사용하며, 화면의 분석 수치는 진단 결과가 아닙니다.