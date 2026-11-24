# pytest가 저장소 최상위 폴더를 기준으로 core 패키지를 찾을 수 있게 경로를 추가한다.
# (역할1이 pytest 설정 파일을 만들면 그쪽으로 옮겨도 됨)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
