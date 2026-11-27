"""pages/3_processing.py 화면 테스트 (역할3)
Streamlit AppTest로 화면을 실제로 실행해서, 가짜 CT 시리즈로 동작과 에러 안내를 확인한다.
"""
import copy
from pathlib import Path

import pydicom
import pytest
from pydicom.data import get_testdata_file
from streamlit.testing.v1 import AppTest

from core.auth import User

PAGE = str(Path(__file__).resolve().parents[1] / "pages" / "3_processing.py")


@pytest.fixture
def ct_folder(tmp_path):
    """pydicom 샘플 CT 1장을 높이(z)만 바꿔 5장짜리 시리즈로 만든다."""
    base = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    for i in range(5):
        ds = copy.deepcopy(base)
        ds.ImagePositionPatient = [0.0, 0.0, float(i * 3)]
        ds.save_as(tmp_path / f"{i}.dcm")
    return str(tmp_path)


def open_page(folder=None, logged_in=True):
    at = AppTest.from_file(PAGE, default_timeout=60)
    if logged_in:
        at.session_state["user"] = User(uid="u1", email="t@t", name="tester", role="reviewer")
    at.run()
    if folder is not None:
        at.text_input[0].set_value(folder).run()
    return at


def pick(at, label):
    return [w for w in at.selectbox if w.label == label][0]


def test_requires_login():
    at = open_page(logged_in=False)
    assert any("로그인" in w.value for w in at.warning)


def test_missing_folder_shows_error():
    at = open_page("/no/such/folder")
    assert any("폴더를 찾을 수 없습니다" in e.value for e in at.error)


@pytest.mark.parametrize("algo", ["clahe", "bilateral", "otsu"])
def test_each_algorithm_runs(ct_folder, algo):
    at = open_page(ct_folder)
    pick(at, "알고리즘").set_value(algo).run()
    assert not at.exception and not at.error
    assert any(m.label == "평균 밝기" for m in at.metric)


def test_otsu_roi_outside_image_is_rejected(ct_folder):
    at = open_page(ct_folder)
    pick(at, "알고리즘").set_value("otsu").run()
    [s for s in at.slider if s.label == "ROI x"][0].set_value(120).run()
    [s for s in at.slider if s.label == "ROI 너비"][0].set_value(60).run()
    assert any("ROI가 영상 밖으로" in e.value for e in at.error)
