"""core/history.py 테스트 — Firestore 대신 가짜 저장소, 결과 파일은 tmp_path에 저장."""
import numpy as np
import pytest

from core.history import (
    HistoryError, build_history_doc, check_can_save_history, list_histories, load_result_image,
    new_request_id, rerun_history, result_rel_path, same_result, save_history,
)
from core.processing import ALGO_VERSION, run_algorithm, window_to_uint8


class FakeStore:
    def __init__(self, fail=False):
        self.docs = {}
        self.fail = fail

    def exists(self, hid):
        return hid in self.docs

    def create(self, hid, doc):
        if self.fail:
            raise ConnectionError("network")
        if hid in self.docs:
            return False
        self.docs[hid] = doc
        return True

    def list_by_case(self, case_id):
        return [d | {"id": k} for k, d in self.docs.items() if d["case_id"] == case_id]


REVIEWER = {"uid": "u-rev", "role": "reviewer"}
CASE = {"case_id": "CASE-001", "status": "in_review", "assignee": "u-rev"}


@pytest.fixture
def hu():
    rng = np.random.default_rng(0)
    img = rng.normal(0, 30, (64, 64))
    img[20:40, 20:40] += 80          # 밝은 덩어리 (종양 흉내)
    return img


def _save(store, root, hu, **kw):
    img = window_to_uint8(hu)
    roi = (16, 16, 32, 32)
    result, features = run_algorithm("otsu", img, {}, roi=roi)
    args = dict(image_id="img1", slice_index=10, algorithm="otsu", params={}, window={"level": 40, "width": 400},
                roi=roi, features=features, result_image=result, history_id="req-1", roi_applied=True)
    args.update(kw)
    return save_history(store, root, kw.pop("user", REVIEWER), kw.pop("case", CASE), **{
        k: v for k, v in args.items() if k not in ("user", "case")}), result


# ---------- 권한 ----------
@pytest.mark.parametrize("user, case, ok", [
    (None, CASE, False),
    (REVIEWER, None, False),
    (REVIEWER, CASE | {"status": "completed"}, False),
    (REVIEWER, CASE | {"status": "assigned"}, False),
    ({"uid": "u-reg", "role": "registrar"}, CASE | {"assignee": "u-reg"}, False),
    ({"uid": "other", "role": "reviewer"}, CASE, False),
    (REVIEWER, CASE, True),
    (REVIEWER, CASE | {"status": "re_review"}, True),
])
def test_권한(user, case, ok):
    assert check_can_save_history(case, user)[0] is ok


# ---------- 기록 형태 ----------
def test_기록_필드():
    doc = build_history_doc("CASE-001", "img1", np.int64(3), "clahe", {"clip_limit": np.float64(2.0)},
                            {"level": 40, "width": 400}, (1, 2, 3, 4), {"mean": np.float32(1.5)},
                            "results/CASE-001/x.png", "u1", now="2026-11-28T00:00:00+00:00")
    assert doc["algorithm_version"] == ALGO_VERSION
    assert doc["roi"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert doc["roi_applied"] is False and doc["source_history_id"] is None
    assert type(doc["slice_index"]) is int and type(doc["params"]["clip_limit"]) is float
    assert type(doc["features"]["mean"]) is float


@pytest.mark.parametrize("kw", [{"case_id": ""}, {"algorithm": "없는알고리즘"}, {"window": {"level": 40}},
                                {"roi": (1, 2, 3)}])
def test_기록_잘못된_값(kw):
    args = dict(case_id="C", image_id=None, slice_index=None, algorithm="clahe", params={}, window=None,
                roi=None, features=None, result_path="r.png", executed_by="u")
    args.update(kw)
    with pytest.raises(HistoryError):
        build_history_doc(**args)


def test_결과_경로_안전():
    assert result_rel_path("CASE-001", "abc") == "results/CASE-001/abc.png"
    assert ".." not in result_rel_path("../etc", "../x")


def test_요청ID_매번_다름():
    assert new_request_id() != new_request_id()


# ---------- 저장 ----------
def test_저장_성공(tmp_path, hu):
    store = FakeStore()
    (ok, msg, hid), result = _save(store, tmp_path, hu)
    assert ok and hid == "req-1"
    doc = store.docs["req-1"]
    assert doc["result_path"] == "results/CASE-001/req-1.png"
    assert same_result(load_result_image(tmp_path, doc["result_path"]), result)


def test_같은_요청_두번은_거절(tmp_path, hu):
    store = FakeStore()
    _save(store, tmp_path, hu)
    (ok, msg, _), _ = _save(store, tmp_path, hu)
    assert not ok and "이미 저장된" in msg and len(store.docs) == 1


def test_권한_없으면_파일도_안생김(tmp_path, hu):
    store = FakeStore()
    (ok, _, _), _ = _save(store, tmp_path, hu, case=CASE | {"status": "completed"})
    assert not ok and not store.docs and not (tmp_path / "results").exists()


def test_DB_실패하면_파일_되돌림(tmp_path, hu):
    (ok, msg, _), _ = _save(FakeStore(fail=True), tmp_path, hu)
    assert not ok and "결과 파일도 지웠" in msg
    assert not (tmp_path / "results/CASE-001/req-1.png").exists()


def test_목록은_최근순(tmp_path, hu):
    store = FakeStore()
    store.docs = {"a": {"case_id": "C", "executed_at": "2026-11-01"}, "b": {"case_id": "C", "executed_at": "2026-11-02"},
                  "c": {"case_id": "D", "executed_at": "2026-11-03"}}
    assert [h["id"] for h in list_histories(store, "C")] == ["b", "a"]


# ---------- 재현 ----------
def test_다시_실행하면_같은_결과(tmp_path, hu):
    store = FakeStore()
    (ok, _, _), result = _save(store, tmp_path, hu)
    again, _ = rerun_history(store.docs["req-1"], hu)
    assert same_result(again, result)


def test_ROI_미적용_이력은_전체로_재현(hu):
    img = window_to_uint8(hu)
    whole, _ = run_algorithm("otsu", img, {})
    doc = {"algorithm": "otsu", "params": {}, "window": {"level": 40, "width": 400},
           "roi": {"x": 16, "y": 16, "w": 32, "h": 32}, "roi_applied": False}
    assert same_result(rerun_history(doc, hu)[0], whole)


def test_재현_잘못된_이력(hu):
    with pytest.raises(HistoryError):
        rerun_history({"algorithm": "clahe", "params": {"clip_limit": -1}}, hu)


# ---------- Windows 한글 경로 (Windows에서 pytest 돌리다 발견) ----------
def test_한글_경로에도_저장하고_읽음(tmp_path, hu, monkeypatch):
    """cv2.imwrite/imread는 Windows에서 한글 경로를 못 다루므로 쓰지 않아야 한다."""
    import cv2

    def boom(*a, **k):
        raise AssertionError("cv2.imwrite/imread는 Windows 한글 경로에서 실패하므로 쓰면 안 됩니다")

    monkeypatch.setattr(cv2, "imwrite", boom)
    monkeypatch.setattr(cv2, "imread", boom)
    root = tmp_path / "바탕 화면" / "저장소"
    store = FakeStore()
    (ok, msg, _), result = _save(store, root, hu)
    assert ok, msg
    assert same_result(load_result_image(root, store.docs["req-1"]["result_path"]), result)


def test_결과_파일이_없으면_안내(tmp_path):
    with pytest.raises(HistoryError, match="찾을 수 없습니다"):
        load_result_image(tmp_path, "results/C/none.png")
