"""공통 메뉴 테스트 (역할1)

- 역할별로 보이는 메뉴가 맞는지
- 로그인 전에는 로그인 화면만 보이는지
- 메뉴에 없는 화면으로는 이동할 수 없는지 (등록자 → 진행 현황)
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.auth import User
from core.menu import MENU, menu_for

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def titles(role):
    return [title for items in menu_for(role).values() for _, title, _ in items]


def test_registrar_menu():
    assert titles("registrar") == ["케이스", "뷰어 · PET/CT 융합"]


def test_reviewer_menu():
    assert titles("reviewer") == ["케이스", "뷰어 · PET/CT 융합", "영상처리 · ROI", "검토 업무"]


def test_admin_sees_everything():
    assert titles("admin") == [title for _, title, _, _, _ in MENU]


def test_unknown_role_sees_nothing():
    assert menu_for("guest") == {}


def test_every_menu_page_file_exists():
    root = Path(APP).parent
    for path, *_ in MENU:
        assert (root / path).exists(), f"메뉴에 있는 화면 파일이 없습니다: {path}"


def test_login_screen_before_login():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert len(at.text_input) == 2          # 이메일, 비밀번호
    assert len(at.sidebar.button) == 0      # 로그아웃 버튼 없음


@pytest.mark.parametrize("role, label", [
    ("registrar", "등록 담당자"), ("reviewer", "검토 담당자"), ("admin", "관리자"),
])
def test_home_and_sidebar_after_login(role, label):
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["user"] = User(f"u-{role}", f"{role}@test.com", f"{role}1", role)
    at.run()
    assert not at.exception
    assert label in at.success[0].value
    assert [b.label for b in at.sidebar.button] == ["로그아웃"]


def test_registrar_cannot_open_dashboard_page():
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["user"] = User("u-reg", "reg@test.com", "등록자1", "registrar")
    at.run()
    with pytest.raises(ValueError):          # 메뉴에 등록되지 않은 화면
        at.switch_page("pages/5_dashboard.py")
