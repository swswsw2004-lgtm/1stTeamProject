# DICOM 태그 확인 결과 (Soft-tissue-Sarcoma, STS_001~003)

> 작성: 역할2 · 2026-11-22 · 원본 표: `data/sts/tag_summary.csv` (`scripts/check_tags.py`로 생성)
> 확인 범위: 각 시리즈의 **첫 파일 헤더** 기준. "확인 필요" 표시는 슬라이스별로 다를 수 있는 값.

## 1. 받은 데이터
| 환자 | CT | PT | RTSTRUCT |
|---|---|---|---|
| STS_001 | CT IMAGES - RESEARCH, 267장 | PET AC, 267장 | RTstruct_CT, RTstruct_PET |
| STS_002 | Standard/Full, 267장 | WB_2D_AC, 267장 | RTstruct_CT, RTstruct_PET |
| STS_003 | Standard/Full, 267장 | PED_2D_AC, 267장 | RTstruct_CT, RTstruct_PET |

## 2. 영상 크기·좌표
| 항목 | CT | PET | 의미 |
|---|---|---|---|
| 행×열 | 512 × 512 | 128 × 128 | |
| PixelSpacing | 0.977 mm | 4.69 mm(001) / 5.47 mm(002·003) | PET 픽셀 1개 ≈ CT 픽셀 5~6개 |
| 촬영 범위(FOV) | 약 500 mm | 약 600 mm(001) / 700 mm(002·003) | PET이 CT보다 넓게 찍힘 → 단순 확대로는 안 맞음 |
| 슬라이스 수 | 267 | 267 | 환자별로 CT·PET 장수와 z 범위가 같음 |
| 슬라이스 간격(z, 실측) | 3.27 mm | 3.19~3.29 mm | 소수점 반올림 차이로 보임 |
| SliceThickness | 3.75 mm | 3.27 mm | CT는 두께 > 간격(겹쳐 찍음) |
| 방향 | 축상(axial) 표준 | 축상(axial) 표준 | 회전 처리 불필요 |
| Photometric | MONOCHROME2 | MONOCHROME2 | 밝기 반전 불필요(코드는 MONOCHROME1 대비 유지) |
| FrameOfReferenceUID | 환자별로 CT·PT·RTSTRUCT 모두 동일 | | 같은 환자 좌표계 → 별도 정합 불필요, 리샘플링만 하면 됨 |

## 3. 팀이 알아야 할 점
1. **[역할2·융합] CT·PET 슬라이스는 z값으로 1:1 매칭 가능.** 단 z가 소수점까지 똑같지 않을 수 있으니 `==` 대신 가장 가까운 z(허용 오차 예: 0.5 mm)로 찾는다.
2. **[역할2·융합] PET을 CT 위에 겹칠 때는 크기 배율만 맞추면 안 된다.** PET 촬영 범위가 CT보다 넓으므로, `ImagePositionPatient`의 x·y 시작점까지 써서 mm 좌표 기준으로 PET을 CT 격자에 리샘플링한다.
3. **[역할2·역할3] HU 변환은 반드시 태그 값으로.** RescaleIntercept가 STS_001은 0, STS_002·003은 -1024로 다르다. 항상 `pixel × RescaleSlope + RescaleIntercept`.
4. **[역할2] PET RescaleSlope는 환자마다 다르고(0.51 / 0.24 / 0.79), 슬라이스마다 다를 수 있음(확인 필요).** 슬라이스마다 자기 Slope를 적용한다.
5. **[역할3] 부피 계산에는 SliceThickness가 아니라 실제 슬라이스 간격(약 3.27 mm)을 쓴다.** 두께(3.75 mm)로 계산하면 부피가 약 15% 커진다.
6. **[역할3] RTSTRUCT 안에 윤곽이 2개다: `GTV_Mass`(종양 덩어리), `GTV_Edema`(주변 부종).** 종양 부피·평균값 기준을 팀에서 확정 필요.
   - `RTstruct_PET` → 기준 영상 PT, `RTstruct_CT` → 기준 영상 CT
   - 윤곽 슬라이스 수(두 ROI 합): STS_001 75, STS_002 32, STS_003 44
7. **[특화·선택 기능] SUV 계산에 필요한 태그가 3명 모두 있음.** Units = BQML, DecayCorrection = START, 체중·투여량·투여 시각 존재.

| 환자 | 체중 | 투여량 | 투여 시각 | 시리즈 시작 | 경과 |
|---|---|---|---|---|---|
| STS_001 | 71 kg | 388.8 MBq | 10:35:00 | 11:20:11 | 45분 11초 |
| STS_002 | 99 kg | 433.3 MBq | 13:51:00 | 14:57:59 | 66분 59초 |
| STS_003 | 80 kg | 359.9 MBq | 10:21:00 | 11:21:48 | 60분 48초 |

   - SUVbw = PET값(Bq/mL) × 체중(g) ÷ [투여량 × 2^(−경과시간 / 반감기)]
   - FDG 반감기 약 109.8분. `RadionuclideHalfLife` 태그로 확인 필요

## 4. 용량·성능 참고
- CT 1명분 약 267 × 512 × 512 × 2바이트 ≈ 140 MB. 3명 합계 약 455 MB.
- 뷰어는 환자 1명씩 불러오고 `st.cache_data` 등으로 캐시하는 방식 권장 (JCloud 메모리는 역할1과 협의).

## 출처
TCIA Soft-tissue-Sarcoma, DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0 · 교육용 모의 케이스