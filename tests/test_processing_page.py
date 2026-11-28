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


def test_roi_sliders_stay_inside_image(ct_folder):
    """x를 오른쪽 끝 가까이 옮기면 너비 최댓값이 자동으로 줄어서 영상 밖으로 못 나감"""
    at = open_page(ct_folder)
    [s for s in at.slider if s.label == "ROI x"][0].set_value(120).run()
    width = [s for s in at.slider if s.label == "ROI 너비"][0]
    assert width.max == 128 - 120
    assert width.value <= 8
    assert not at.error


def test_roi_at_right_edge_does_not_crash(ct_folder):
    """x를 맨 오른쪽(127)에 두면 너비는 1밖에 못 고름 → 슬라이더 대신 글로 보여 주고 에러 없음"""
    at = open_page(ct_folder)
    [s for s in at.slider if s.label == "ROI x"][0].set_value(127).run()
    assert not at.exception and not at.error
    assert not [s for s in at.slider if s.label == "ROI 너비"]


def test_single_slice_series(tmp_path):
    """1장짜리 시리즈도 슬라이스 슬라이더 없이 열림"""
    base = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    base.save_as(tmp_path / "only.dcm")
    at = open_page(str(tmp_path))
    assert not at.exception and not at.error
    assert not [s for s in at.slider if s.label == "슬라이스"]


def test_roi_analysis_shows_stats(ct_folder):
    at = open_page(ct_folder)
    labels = [m.label for m in at.metric]
    assert "ROI 평균 (HU)" in labels and "ROI 면적" in labels
    assert not at.exception and not at.error


def test_roi_can_be_turned_off(ct_folder):
    at = open_page(ct_folder)
    [c for c in at.checkbox if c.label == "ROI 사용"][0].uncheck().run()
    assert not [s for s in at.slider if s.label == "ROI x"]
    assert "ROI 평균 (HU)" not in [m.label for m in at.metric]
