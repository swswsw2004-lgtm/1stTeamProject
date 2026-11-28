"""역할별 메뉴 구성 (역할1)

app.py가 이 목록으로 왼쪽 메뉴를 만든다. 새 화면을 추가하면 여기에 한 줄 추가한다.
메뉴에서 숨기는 것은 편의 기능이고, 실제 권한 검사는 각 화면과 core 모듈의 저장 함수에서 한다.
"""
from __future__ import annotations

ALL = ("registrar", "reviewer", "admin")

# (화면 파일, 메뉴 이름, 아이콘, 볼 수 있는 역할, 메뉴 묶음)
MENU = [
    ("pages/1_cases.py", "케이스", "🗂️", ALL, "영상"),
    ("pages/2_viewer.py", "뷰어 · PET/CT 융합", "🩻", ALL, "영상"),
    ("pages/3_processing.py", "영상처리 · ROI", "🧪", ("reviewer", "admin"), "영상"),
    ("pages/4_review.py", "검토 업무", "📝", ("reviewer", "admin"), "업무"),
    ("pages/5_dashboard.py", "진행 현황", "📊", ("admin",), "업무"),
]


def menu_for(role: str) -> dict[str, list[tuple[str, str, str]]]:
    """역할에 맞는 메뉴를 묶음별로 돌려준다. (테스트하기 쉽도록 화면 코드와 분리)"""
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for path, title, icon, roles, group in MENU:
        if role in roles:
            groups.setdefault(group, []).append((path, title, icon))
    return groups
