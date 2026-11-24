# 🩻 PET/CT 융합 기반 교육용 웹 PACS

초급프로젝트 PBL 분반 Term Project · 4인 팀
암 환자의 CT와 PET 영상을 웹에서 저장·검색·조회하고, 두 영상을 겹쳐 보며 종양 크기를 재볼 수 있는 **교육용** PACS입니다.

> ⚠️ 교육용 모의 케이스입니다. 분석 수치는 진단·임상 결과가 아닙니다.
> 데이터: TCIA Soft-tissue-Sarcoma, DOI 10.7937/K9/TCIA.2015.7GO2GSKS, CC BY 3.0 (자세한 내용: `data/README.md`)

| 항목 | 내용 |
|---|---|
| 개발 | Python 3.11 이상 · Streamlit |
| 로그인 / DB | Firebase Authentication / Cloud Firestore |
| 배포 | JCloud |
| 팀 공통 맥락 | `PROJECT_CONTEXT.md` (AI 도우미에게 질문할 때 먼저 넣기) |

## 폴더 구조
```
app.py          진입점 (로그인 화면)
pages/          화면 (Streamlit 멀티페이지)
core/           핵심 로직 (DB·권한·DICOM·영상처리·업무 흐름)
tests/          pytest 테스트
scripts/        데이터 다운로드·확인·실험 스크립트
data/           시연 데이터 (영상은 Git 제외, data/README.md 참고)
```

## 1. 설치 (처음 한 번)
Git Bash 기준입니다.
```bash
git clone https://github.com/swswsw2004-lgtm/1stTeamProject.git
cd 1stTeamProject
git switch dev

python -m venv .venv
source .venv/Scripts/activate      # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```
프롬프트 앞에 `(.venv)`가 보이면 가상환경이 켜진 상태입니다. **Git Bash를 새로 열 때마다** `source .venv/Scripts/activate`를 다시 실행하세요.

## 2. 비밀 설정 파일
`.streamlit/secrets.toml.example`을 복사해 `.streamlit/secrets.toml`을 만들고 값을 채웁니다. (팀 메신저로 받은 파일을 넣어도 됩니다)
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
**secrets.toml과 서비스 계정 JSON은 절대 커밋하지 않습니다.** (`.gitignore`로 제외됨)

## 3. 실행 · 테스트
```bash
streamlit run app.py     # http://localhost:8501
pytest                   # 전체 테스트
```

## 4. 데이터 받기
`data/README.md`를 참고하세요.

## 5. 협업 규칙
- `main`: 제출·배포용 / `dev`: 통합 (기본 브랜치) / 작업: `feature/기능명`, 버그: `fix/내용`
- `main`, `dev`는 직접 push 금지 — PR + 리뷰 1명 승인 후 merge
- 작업 시작 전 `git pull origin dev`로 최신 내용 받기
- 커밋 메시지는 무엇을 왜 바꿨는지 (예: `feat(auth): 이메일 로그인 추가`)
