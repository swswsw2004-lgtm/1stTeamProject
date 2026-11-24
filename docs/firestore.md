# Firestore 데이터 구조 (초안 v0.2)

> 작성: 역할1 · 2026-11-23 (v0.2: 11/24 역할4 workflow.py와 필드 이름 맞춤) · **상태: 초안 — 11/24 회의에서 확정**
> 기준: `PROJECT_CONTEXT.md` 5장, `data/DATA_NOTES.md`(역할2 태그 정리)
> 확정 후 이름을 바꿀 때는 이 문서를 먼저 고치고 PR로 공유한다.

---

## 0. 공통 규칙

| 규칙 | 내용 | 예 |
|---|---|---|
| 필드 이름 | 영어 소문자 + 밑줄(snake_case) | `case_id`, `uploaded_at` (O) / `caseId`, `UploadedAt` (X) |
| 시간 | **회의에서 결정** (4장 6번): Firestore Timestamp 또는 UTC ISO 문자열 | `2026-11-24T09:00:00+00:00` |
| 사람 | 이름이 아니라 **Firebase UID**를 저장 (이름은 `users`에서 조회) | `assignee: "Xy12..."` |
| 날짜만 필요한 값 | 문자열 `YYYY-MM-DD` | `exam_date: "2026-11-23"` |
| 영상 파일 | **Firestore에 넣지 않음.** JCloud 디스크에 저장하고 **경로만** 저장 (문서 최대 1 MiB) | `file_path: "originals/STS_001/CT"` |
| 파일 경로 | `storage_dir` 기준 **상대 경로** (서버가 바뀌어도 그대로 사용) | `results/STS_001/abc123.png` |
| 비어 있는 값 | 필드를 빼지 말고 `null` 저장 | `roi: null` |
| 쓰기 전 검사 | 모든 저장·수정 함수는 실행 전에 권한 검사 (`core/permissions.py`) | |

DB 연결은 항상 `from core.firebase import get_db` 를 사용한다.

---

## 1. 컬렉션 한눈에 보기

```
users/{uid}                         사용자·역할              (역할1)
cases/{case_id}                     케이스                   (역할2 생성 · 역할4 상태/배정)
images/{image_id}                   영상 시리즈 1개 = 문서 1개  (역할2)
processing_history/{history_id}     영상처리·ROI 이력         (역할3)
memos/{memo_id}                     검토 메모·요약 리포트      (역할4)
status_logs/{log_id}                상태 변경 기록             (역할4)
tumor_metrics/{metric_id}           종양 정량 결과 (특화, W3)   (역할3 계산 · 역할1 구조)
```

연결 관계: `cases` 1개 ─ `images` 여러 개 ─ `processing_history` 여러 개 / `cases` 1개 ─ `memos`·`status_logs`·`tumor_metrics` 여러 개 (모두 `case_id`로 연결)

---

## 2. 컬렉션별 필드

### 2-1. `users/{uid}` — 담당: 역할1
문서 ID = Firebase Authentication의 UID

| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `email` | string | 로그인 이메일 | `admin1@test.com` |
| `name` | string | 화면 표시 이름 | `관리자1` |
| `role` | string | `registrar` / `reviewer` / `admin` | `admin` |
| `created_at` | timestamp | 계정 등록 시간 | |

- 쓰기: 역할1의 계정 생성 스크립트만 (화면에서 역할 변경 불가)
- 읽기: 로그인 시 `core/auth.py` 가 역할 조회

### 2-2. `cases/{case_id}` — 담당: 역할2(생성·검색), 역할4(상태·배정)
문서 ID = 모의 케이스 ID

| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `case_id` | string | 모의 케이스 ID (문서 ID와 같음) | `CASE-001` |
| `patient_id` | string | 공개 데이터의 환자 ID (DICOM PatientID) | `STS_001` |
| `exam_type` | string | 검사 구분 | `PET/CT` |
| `exam_date` | string | 검사일 `YYYY-MM-DD` | `2026-11-23` |
| `description` | string | 설명 | `좌측 대퇴부 연부조직 종양` |
| `status` | string | 상태 코드 (3장) | `received` |
| `assignee` | string \| null | 배정된 검토 담당자 UID (역할4 workflow.py와 같은 이름) | `null` |
| `registered_by` | string | 등록한 사람 UID | |
| `registered_at` | timestamp | 등록 시간 | |
| `updated_at` | timestamp | 마지막 변경 시간 | |
| `is_mock` | bool | 교육용 모의 케이스 표시 (항상 `true`) | `true` |

### 2-3. `images/{image_id}` — 담당: 역할2
문서 ID = 자동 생성. **슬라이스 1장이 아니라 시리즈 1개(예: CT 267장)를 문서 1개로 저장**한다.
(267장마다 문서를 만들면 환자 1명에 문서 800개 이상 → 조회가 느리고 무료 사용량을 빨리 씀)

| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `case_id` | string | 소속 케이스 | `CASE-001` |
| `modality` | string | `CT` / `PT` / `RTSTRUCT` / `OT`(PNG·JPEG) | `CT` |
| `format` | string | `DICOM` / `PNG` / `JPEG` | `DICOM` |
| `series_uid` | string \| null | DICOM SeriesInstanceUID | |
| `series_description` | string | 시리즈 설명 | `RTstruct_PET` |
| `file_path` | string | 원본 폴더(또는 파일) 상대 경로 | `originals/CASE-001/CT` |
| `num_files` | int | 파일(슬라이스) 수 | `267` |
| `size_bytes` | int | 전체 용량 | |
| `rows`, `cols` | int \| null | 영상 크기 | `512`, `512` |
| `pixel_spacing_mm` | array[float] \| null | 픽셀 간격 [행, 열] | `[0.977, 0.977]` |
| `slice_spacing_mm` | float \| null | **실측** z 간격 (부피 계산용, SliceThickness 아님) | `3.27` |
| `referenced_series_uid` | string \| null | RTSTRUCT가 기준으로 삼은 영상 시리즈 | |
| `source` | string | 데이터 출처 | `TCIA Soft-tissue-Sarcoma (CC BY 3.0)` |
| `uploaded_by` | string | 등록자 UID | |
| `uploaded_at` | timestamp | 등록 시간 | |

### 2-4. `processing_history/{history_id}` — 담당: 역할3
문서 ID = 요청 ID(화면에서 만든 고유값). **같은 요청을 두 번 저장하면 두 번째는 거절** → 연속 클릭 중복 기록 방지

| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `case_id` | string | 케이스 | |
| `image_id` | string | 처리한 영상 시리즈 | |
| `slice_index` | int \| null | 처리한 슬라이스 번호(z 정렬 기준) | `120` |
| `algorithm` | string | 알고리즘 키 | `clahe` / `bilateral` / `otsu` |
| `algorithm_version` | string | 구현 버전 (코드 바꾸면 올림) | `1.0` |
| `params` | map | 설정값 | `{"clip_limit": 2.0, "tile": 8}` |
| `roi` | map \| null | ROI 좌표·크기(픽셀) | `{"x": 200, "y": 180, "w": 60, "h": 60}` |
| `features` | map \| null | ROI 특징값 | `{"mean": 41.2, "var": 120.5, "std": 10.9}` |
| `result_path` | string | 결과 영상 상대 경로 (원본과 다른 파일) | `results/CASE-001/abc.png` |
| `executed_by` | string | 실행자 UID | |
| `executed_at` | timestamp | 실행 시간 | |

### 2-5. `memos/{memo_id}` — 담당: 역할4
| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `case_id` | string | 케이스 | |
| `kind` | string | `memo`(검토 메모) / `report`(요약 리포트) | `report` |
| `content` | string | 내용 | |
| `image_id` | string \| null | 연결된 영상 | |
| `history_id` | string \| null | 연결된 처리 이력 | |
| `author_uid` | string | 작성자 UID | |
| `created_at` | timestamp | 작성 시간 | |
| `updated_at` | timestamp | 마지막 수정 시간 | |
| `edit_log` | array[map] | 수정 이력 `{prev, by_uid, at}` | |

### 2-6. `status_logs/{log_id}` — 담당: 역할4
| 필드 | 타입 | 설명 |
|---|---|---|
| `case_id` | string | 케이스 |
| `from_status` | string | 이전 상태 |
| `to_status` | string | 바뀐 상태 |
| `actor` | string | 실행한 사람 UID (역할4 workflow.py와 같은 이름) |
| `reason` | string | 사유 (재검토 등은 필수) |
| `at` | timestamp 또는 string | 시간 (역할4 코드는 현재 UTC ISO 문자열) |

### 2-7. `tumor_metrics/{metric_id}` — 특화 기능 (W3, 12/7~)
| 필드 | 타입 | 설명 | 예 |
|---|---|---|---|
| `case_id` | string | 케이스 | |
| `rtstruct_image_id` | string | 사용한 RTSTRUCT | |
| `roi_name` | string | 윤곽 이름 | `GTV_Mass` |
| `volume_ml` | float | 종양 부피(교육용 계산값) | `152.4` |
| `mean_value` | float | 종양 내부 평균 PET 값 | |
| `value_unit` | string | 값 단위 | `BQML` / `SUVbw` |
| `num_slices` | int | 윤곽이 있는 슬라이스 수 | `32` |
| `slice_spacing_mm` | float | 부피 계산에 쓴 z 간격 | `3.27` |
| `computed_by`, `computed_at` | string, timestamp | 계산한 사람·시간 | |

---

## 3. 상태 코드 (역할4 `core/workflow.py` 기준)

| 코드 | 화면 표시 | 다음으로 갈 수 있는 상태 |
|---|---|---|
| `received` | 접수 | `assigned` |
| `assigned` | 배정 | `in_review` |
| `in_review` | 검토 중 | `completed` |
| `completed` | 완료 | `re_review` |
| `re_review` | 재검토 | `in_review` |

---

## 4. 회의에서 정할 것

1. **케이스 ID 형식**: `CASE-001`처럼 따로 만들기 vs 환자 ID `STS_001`을 그대로 쓰기
2. **images 단위**: 시리즈 1개 = 문서 1개로 확정할지 (위 2-3 제안)
3. **상태 코드**: 위 3장 영어 코드와 `re_review` 이후 흐름 (역할4)
4. **종양 기준**: 부피·평균값을 `GTV_Mass`만으로 계산할지, `GTV_Edema` 포함할지 (역할2·3, DATA_NOTES 6번)
5. **처리 대상 단위**: `processing_history`를 슬라이스 1장 기준으로 저장할지 (`slice_index`)
6. **시간 저장 형식**: Firestore Timestamp vs UTC ISO 문자열 (역할4 코드는 현재 ISO 문자열 — 둘 다 시간순 정렬 가능, 한 가지로 통일)
7. **사용자 정보 전달 형식**: `require_login()`이 돌려주는 `User`를 `user.uid`/`user["uid"]`/`user.get("uid")` 모두로 쓸 수 있게 함 (역할4 코드와 호환)

---

## 5. 참고: 조회할 때 주의

- `where`(조건) 여러 개 + `order_by`(정렬)를 같이 쓰면 Firestore가 **복합 색인**을 요구하며 오류를 낸다. 오류 메시지에 있는 링크를 누르면 색인이 만들어진다(1~2분 소요). 만든 색인은 역할1에게 알려 `firestore.indexes.json`에 기록한다.
- 무료(Spark) 요금제 한도: 하루 읽기 5만·쓰기 2만 회. 화면이 다시 그려질 때마다 DB를 읽지 않도록 `st.cache_data` 등을 활용한다.
