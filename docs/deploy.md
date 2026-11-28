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
```

## 3. 테스트 결과 (11/27)

| 확인 | 결과 |
|---|---|
| SSH 접속 | ✅ |
| 패키지 설치 (Python 3.14, OpenCV 5.1, Streamlit 1.67) | ✅ |
| 서버에서 pytest | ✅ 237 passed |
| 외부(휴대폰 LTE)에서 `http://s.jedutools.io:51183` 접속 | ✅ |
| 테스트 계정 로그인 | ✅ |

## 4. 막힌 점과 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| Streamlit 기본 포트(8501)로는 외부 접속 불가 | JCloud는 7777·80·443·3000·8080만 외부에 연결 | `--server.port 8080` 사용 |
| SSH 22번 포트가 아님 | JCloud는 내부 7777 → 외부 11183으로 SSH 연결 | `ssh -p 11183` |
| RAM 2GiB로 CT 로딩 시 부족 우려 | micro 사양 | 스왑 2GiB 추가, 영상처리 화면은 CT 캐시 최대 2개(`max_entries=2`) |
| 서버 Python이 3.14로 매우 최신 | Ubuntu 26.04 기본 | 사용 패키지 모두 3.14용 버전 제공 확인, 테스트 전체 통과 |

## 5. 12/6 1차 배포 때 할 일

- [ ] 앱을 계속 실행 (SSH를 끊어도, 서버가 재시작돼도 자동 실행 — systemd 서비스 등록)
- [ ] DICOM 데이터를 서버에 받기 (역할2 `scripts/download_sts.py`, 디스크 남은 공간 약 3.4GB 확인)
- [ ] 영상 원본·결과 저장 폴더 위치 정하기 (재시작 후에도 남는 곳)
- [ ] 최신 dev 반영 절차 정리 (`git pull` → `pip install -r requirements.txt` → 재시작)
- [ ] 역할별 테스트 계정으로 외부 접속 시나리오 확인 → `docs/test_scenarios` 기록
