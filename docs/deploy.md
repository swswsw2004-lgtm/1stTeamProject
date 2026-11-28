# JCloud 배포 기록 (역할1)

> 키 파일(.pem), 비밀번호, secrets.toml 내용은 이 문서에 적지 않는다. (팀 단톡방으로만 공유)

## 1. 서버 정보 (2026-11-27 접속 확인)

| 항목 | 값 |
|---|---|
| 클라우드 | JCloud (`students` 공용 프로젝트) |
| 인스턴스 이름 | `202312718-asw` |
| 운영체제 | Ubuntu 26.04 (`ubuntu.26.04.image.v10.16`) |
| 사양 | micro — vCPU 2, RAM 2GiB (+ 스왑 2GiB), 디스크 10GiB |
| Python | 3.14.4 |
| 시계 동기화 | `System clock synchronized: yes` |
| 키 페어 이름 | `swteamproject` (파일은 단톡방으로만 공유) |

### 접속 방식 (포트 포워딩)
JCloud는 서버마다 공인 IP를 주지 않고, 공용 주소 `s.jedutools.io`의 포트를 서버 내부 포트로 연결한다.
외부에서 열 수 있는 내부 포트는 7777, 80, 443, 3000, 8080 뿐이다.

| 내부 포트 | 외부 주소 | 용도 |
|---|---|---|
| 7777 | `s.jedutools.io:11183` | SSH 접속 |
| 8080 | `s.jedutools.io:51183` | **Streamlit 앱 (제출용 주소: http://s.jedutools.io:51183)** |
| 80 / 443 / 3000 | `:21183` / `:31183` / `:41183` | 사용 안 함 |

## 2. 설치 순서 (재현용)

```bash
# 내 컴퓨터 → 서버 접속
ssh -i ~/.ssh/swteamproject.pem -p 11183 ubuntu@s.jedutools.io

# (서버) 메모리 보충: 스왑 2GB
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# (서버) 앱 설치
sudo apt update && sudo apt install -y python3-venv python3-pip git
git clone https://github.com/swswsw2004-lgtm/1stTeamProject.git
cd 1stTeamProject && git switch dev
python3 -m venv .venv && source .venv/bin/activate
pip install --no-cache-dir -r requirements.txt
pytest -q

# (내 컴퓨터) 비밀 설정 파일 보내기  ※ scp는 대문자 -P
scp -i ~/.ssh/swteamproject.pem -P 11183 .streamlit/secrets.toml ubuntu@s.jedutools.io:~/1stTeamProject/.streamlit/
# (서버) 나만 읽을 수 있게
chmod 600 ~/1stTeamProject/.streamlit/secrets.toml

# (서버) 앱 실행 — 8080 포트로 띄워야 외부(51183)에서 접속됨
streamlit run app.py --server.address 0.0.0.0 --server.port 8080 --server.headless true

# (서버) 원본 저장 위치는 절대 경로로 (앱을 어디서 켜도 같은 곳에 저장)
sed -i 's#^storage_dir = .*#storage_dir = "/home/ubuntu/1stTeamProject/data/storage"#' .streamlit/secrets.toml
```

### 2-1. DICOM 데이터 올리기 (11/28)
서버(RAM 2GiB)에서 `scripts/download_sts.py`를 실행하면 메모리 부족으로 `Killed`된다. 그래서 **내 컴퓨터에서 받아 압축해 올린다.**

```bash
# (내 컴퓨터) 받기 → 압축 → 업로드
pip install idc-index
python -X utf8 scripts/download_sts.py --ids STS_001 STS_002 STS_003 --out data/sts
git checkout -- data/sts/series_list.csv          # 스크립트가 다시 쓴 목록 파일 되돌리기
tar -czf ~/sts.tar.gz -C data sts                  # 455MB → 압축 199MB
scp -i ~/.ssh/swteamproject.pem -P 11183 ~/sts.tar.gz ubuntu@s.jedutools.io:~/

# (서버) 풀기 → 압축 파일 삭제 → Windows 줄바꿈 차이로 바뀐 것으로 보이는 CSV 되돌리기
cd ~/1stTeamProject
tar -xzf ~/sts.tar.gz -C data && rm ~/sts.tar.gz
git checkout -- data/sts/series_list.csv data/sts/tag_summary.csv
```
결과: `data/sts/soft_tissue_sarcoma/STS_001~003` (약 436MB), 남은 디스크 약 2.9GB

### 2-2. 앱 상시 실행 (systemd 서비스, 11/28)
SSH를 끊어도, 서버가 재시작돼도 앱이 켜져 있도록 서비스로 등록한다.

```bash
sudo tee /etc/systemd/system/pacs.service > /dev/null <<'UNIT'
[Unit]
Description=PET/CT 교육용 웹 PACS (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/1stTeamProject
ExecStart=/home/ubuntu/1stTeamProject/.venv/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8080 --server.headless true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pacs
```
- 상태 확인: `sudo systemctl status pacs --no-pager` → `active (running)`, `enabled`
- 로그 보기 (오류가 날 때): `sudo journalctl -u pacs -n 50 --no-pager`
- 로그의 `External URL: http://113.198.66.75:8080`은 Streamlit의 추측값. **실제 외부 주소는 `http://s.jedutools.io:51183`**

### 2-3. 재배포 (dev에 새 코드가 merge됐을 때)
```bash
cd ~/1stTeamProject && source .venv/bin/activate
git pull
pip install --no-cache-dir -r requirements.txt
pytest -q                          # 서버 환경에서도 통과하는지 먼저 확인
sudo systemctl restart pacs        # 재시작해야 새 코드가 실행됨
```
- 최종 제출 전에는 `git switch main && git pull` 후 재시작해서 **제출 커밋과 서버 코드를 일치**시킨다.

## 3. 테스트 결과 (11/27~28)

| 확인 | 결과 |
|---|---|
| SSH 접속 | ✅ |
| 패키지 설치 (Python 3.14, OpenCV 5.1, Streamlit 1.67) | ✅ |
| 서버에서 pytest | ✅ 237 passed |
| 외부(휴대폰 LTE)에서 `http://s.jedutools.io:51183` 접속 | ✅ |
| 테스트 계정 로그인 | ✅ |
| DICOM 3명분 업로드 (11/28) | ✅ 436MB, 남은 디스크 2.9GB |
| 상시 실행 — SSH 종료 후에도 외부 접속 (11/28) | ✅ `active (running)`, 메모리 약 70MB |
| 재배포 — PR #21(뷰어·융합) 반영 (11/28) | ✅ 서버 pytest 315 passed |

## 4. 막힌 점과 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| Streamlit 기본 포트(8501)로는 외부 접속 불가 | JCloud는 7777·80·443·3000·8080만 외부에 연결 | `--server.port 8080` 사용 |
| SSH 22번 포트가 아님 | JCloud는 내부 7777 → 외부 11183으로 SSH 연결 | `ssh -p 11183` |
| RAM 2GiB로 CT 로딩 시 부족 우려 | micro 사양 | 스왑 2GiB 추가, 영상처리 화면은 CT 캐시 최대 2개(`max_entries=2`) |
| 서버 Python이 3.14로 매우 최신 | Ubuntu 26.04 기본 | 사용 패키지 모두 3.14용 버전 제공 확인, 테스트 전체 통과 |
| 서버에서 데이터 받기 스크립트가 `Killed` | `idc-index`가 전체 영상 목록을 메모리에 올려 RAM 2GiB 초과 | 내 컴퓨터에서 받아 `tar`로 압축 후 `scp`로 업로드 (2-1) |
| 업로드 후 서버에서 CSV 2개가 `modified`로 표시 | Windows Git이 줄 끝을 CRLF로 바꾼 파일을 그대로 압축해 옮김 | `git checkout -- <파일>`로 되돌림 (안 하면 서버 `git pull`이 막힘) |
| SSH를 끊으면 앱도 꺼짐 | 터미널에서 직접 실행한 프로그램은 접속 종료 시 함께 종료 | systemd 서비스로 등록 (2-2) |

## 5. 남은 일

- [x] 앱 상시 실행 (systemd) — 11/28
- [x] DICOM 데이터 서버에 올리기 — 11/28
- [x] 영상 원본 저장 폴더 절대 경로 — 11/28 (`/home/ubuntu/1stTeamProject/data/storage`)
- [x] 재배포 절차 정리 — 11/28 (2-3)
- [ ] 역할별 테스트 계정으로 외부 접속 검증 시나리오 실행·기록
- [ ] 최종 제출 전: 서버를 `main` 최종 커밋으로 재배포, 커밋 SHA 기록
