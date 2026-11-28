"""
core/images.py 테스트 (역할2)
실행: python -X utf8 -m pytest tests/test_images.py -v

Firebase 없이 가짜 저장소(FakeImageStore)와 임시 폴더(tmp_path)로 시험한다.
DICOM 테스트는 작은 합성 DICOM(4x4)을 메모리에서 만들어 쓴다.
"""
import io

import pytest
from PIL import Image

from core.images import (
    FileGroup,
    build_image_doc,
    check_can_register,
    count_images,
    detect_format,
    inspect_files,
    list_images,
    register_group,
    safe_name,
    target_dir,
)

REGISTRAR = {"uid": "reg1", "role": "registrar"}
REVIEWER = {"uid": "rev1", "role": "reviewer"}
CASE = {"case_id": "CASE-001", "patient_id": "STS_001"}


class FakeImageStore:
    """FirestoreImageStore와 같은 함수 이름을 가진 메모리 저장소."""
    def __init__(self, fail_add=False):
        self.docs = {}
        self.fail_add = fail_add

    def add_image(self, doc):
        if self.fail_add:
            raise RuntimeError("Firestore 연결 끊김 (시험용)")
        image_id = f"img{len(self.docs) + 1}"
        self.docs[image_id] = dict(doc)
        return image_id

    def list_images(self, case_id):
        return [d | {"id": k} for k, d in self.docs.items() if d["case_id"] == case_id]

    def series_exists(self, case_id, series_uid):
        return any(d.get("series_uid") == series_uid for d in self.list_images(case_id))


def png_bytes(w=8, h=6):
    buf = io.BytesIO()
    Image.new("L", (w, h), 128).save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("L", (8, 8), 50).save(buf, format="JPEG")
    return buf.getvalue()


# ─────────────── 형식 판별 ───────────────
def test_detect_format_by_content_not_extension():
    """형식은 확장자가 아니라 내용으로 판단"""
    assert detect_format("a.png", png_bytes()) == "PNG"
    assert detect_format("a.dat", jpeg_bytes()) == "JPEG"
    assert detect_format("a.dcm", b"\x00" * 128 + b"DICM" + b"\x00" * 10) == "DICOM"
    assert detect_format("a.dcm", b"hello world") is None


def test_png_jpeg_pass_and_become_groups():
    """PNG JPEG는 검사를 통과하고 그룹이 된다"""
    r = inspect_files([("a.png", png_bytes(8, 6)), ("b.jpg", jpeg_bytes())])
    assert r.ok, r.errors
    assert [(g.format, g.modality, g.num_files) for g in r.groups] == [("PNG", "OT", 1), ("JPEG", "OT", 1)]
    assert r.groups[0].meta == {"rows": 6, "cols": 8}


@pytest.mark.parametrize("files, keyword", [
    ([], "없습니다"),
    ([("a.txt", b"hello")], "지원하지 않는 형식"),
    ([("a.png", b"")], "빈 파일"),
    ([("a.jpg", png_bytes())], "확장자는 JPEG"),
    ([("a.png", png_bytes()[:20])], "손상"),
])
def test_rejects_bad_files_with_reason(files, keyword):
    """잘못된 파일은 이유와 함께 거절"""
    r = inspect_files(files)
    assert not r.ok
    assert any(keyword in e for e in r.errors), r.errors


def test_one_bad_file_rejects_whole_upload():
    """하나라도 잘못되면 전체를 통과시키지 않는다"""
    r = inspect_files([("ok.png", png_bytes()), ("bad.txt", b"xx")])
    assert not r.ok
    assert len(r.errors) == 1 and "bad.txt" in r.errors[0]


def test_rejects_too_large_file(monkeypatch):
    """너무 큰 파일 거절"""
    import core.images as images
    monkeypatch.setattr(images, "MAX_FILE_BYTES", 10)
    r = inspect_files([("a.png", png_bytes())])
    assert any("너무 큽니다" in e for e in r.errors)


# ─────────────── 권한 ───────────────
def test_reviewer_cannot_register(tmp_path):
    """검토담당자는 등록할 수 없다"""
    store = FakeImageStore()
    group = inspect_files([("a.png", png_bytes())]).groups[0]
    ok, msg = register_group(store, tmp_path, REVIEWER, CASE, group)
    assert not ok and "등록 담당자" in msg
    assert store.docs == {} and not (tmp_path / "originals").exists()


@pytest.mark.parametrize("user", [None, {}, {"uid": "x"}])
def test_rejects_when_not_logged_in(user):
    """로그인 안하면 거절"""
    assert not check_can_register(user)[0]


# ─────────────── 저장 + 기록 ───────────────
def test_register_saves_original_and_creates_doc(tmp_path):
    """등록하면 원본이 저장되고 images 문서가 생긴다"""
    store = FakeImageStore()
    data = png_bytes()
    group = inspect_files([("scan.png", data)]).groups[0]
    ok, msg = register_group(store, tmp_path, REGISTRAR, CASE, group, now="2026-11-27T00:00:00+00:00")
    assert ok, msg

    doc = store.docs["img1"]
    assert doc["file_path"] == "originals/CASE-001/OT_scan.png"
    assert (tmp_path / doc["file_path"] / "scan.png").read_bytes() == data   # 원본 그대로
    assert doc["case_id"] == "CASE-001" and doc["format"] == "PNG" and doc["modality"] == "OT"
    assert doc["num_files"] == 1 and doc["size_bytes"] == len(data)
    assert doc["uploaded_by"] == "reg1" and doc["source"].startswith("TCIA")
    assert count_images(store, "CASE-001") == 1
    assert count_images(store, "CASE-999") == 0


def test_existing_target_is_not_overwritten(tmp_path):
    """같은 저장위치가 있으면 덮어쓰지 않고 거절"""
    store = FakeImageStore()
    group = inspect_files([("scan.png", png_bytes())]).groups[0]
    assert register_group(store, tmp_path, REGISTRAR, CASE, group)[0]
    before = (tmp_path / "originals/CASE-001/OT_scan.png/scan.png").read_bytes()

    group2 = inspect_files([("scan.png", png_bytes(16, 16))]).groups[0]
    ok, msg = register_group(store, tmp_path, REGISTRAR, CASE, group2)
    assert not ok and "덮어쓰지" in msg
    assert (tmp_path / "originals/CASE-001/OT_scan.png/scan.png").read_bytes() == before
    assert len(store.docs) == 1


def test_record_failure_removes_saved_files(tmp_path):
    """기록 저장이 실패하면 방금 저장한 파일도 지운다"""
    store = FakeImageStore(fail_add=True)
    group = inspect_files([("scan.png", png_bytes())]).groups[0]
    ok, msg = register_group(store, tmp_path, REGISTRAR, CASE, group)
    assert not ok and "파일도 지웠습니다" in msg
    case_dir = tmp_path / "originals/CASE-001"
    assert not any(case_dir.iterdir())          # 파일과 기록이 어긋나지 않음
    assert store.docs == {}


def test_file_failure_writes_no_record(tmp_path):
    """파일 저장이 실패하면 기록하지 않는다"""
    store = FakeImageStore()
    blocker = tmp_path / "originals"
    blocker.write_text("폴더가 아니라 파일이라 그 안에 저장할 수 없음")
    group = inspect_files([("scan.png", png_bytes())]).groups[0]
    ok, msg = register_group(store, tmp_path, REGISTRAR, CASE, group)
    assert not ok and "파일 저장에 실패" in msg
    assert store.docs == {}


def test_same_file_names_get_numbered(tmp_path):
    """같은 이름 파일은 번호를 붙여 모두 저장"""
    store = FakeImageStore()
    group = FileGroup("DICOM", "CT", "1.2.3.456789012345", "test",
                      files=[("a/x.dcm", b"1"), ("b/x.dcm", b"2")])
    assert register_group(store, tmp_path, REGISTRAR, CASE, group)[0]
    saved = sorted(p.name for p in (tmp_path / store.docs["img1"]["file_path"]).iterdir())
    assert saved == ["x.dcm", "x_1.dcm"]


def test_rejects_same_series_twice(tmp_path):
    """같은 시리즈를 두번 등록하면 거절"""
    store = FakeImageStore()
    g = FileGroup("DICOM", "CT", "1.2.3.999", "CT", files=[("a.dcm", b"1")])
    assert register_group(store, tmp_path, REGISTRAR, CASE, g)[0]
    ok, msg = register_group(store, tmp_path, REGISTRAR, CASE, g)
    assert not ok and "이미 등록된 시리즈" in msg


def test_rejects_missing_case(tmp_path):
    """케이스가 없으면 거절"""
    g = FileGroup("PNG", "OT", None, "a.png", files=[("a.png", b"1")])
    assert not register_group(FakeImageStore(), tmp_path, REGISTRAR, None, g)[0]


# ─────────────── 경로·이름 안전 ───────────────
@pytest.mark.parametrize("name, expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\me\\scan 1.png", "scan_1.png"),
    ("케이스.png", "png"),
    ("..", "file"),
])
def test_safe_name_blocks_paths_and_symbols(name, expected):
    """safe name은 경로조작과 특수문자를 막는다"""
    assert safe_name(name) == expected


def test_target_dir_by_case_and_modality():
    """저장 경로는 케이스와 모달리티별로 나뉜다"""
    g = FileGroup("DICOM", "PT", "1.2.840.113619.2.55.3.1234", "PET AC")
    path = target_dir("CASE-001", g)
    assert path.parent == target_dir("CASE-001", FileGroup("DICOM", "CT", "9.9", "CT")).parent
    assert str(path).startswith("originals/CASE-001/PT_")
    assert str(path).endswith("55.3.1234")          # 시리즈 UID 끝자리로 시리즈 구분


def test_list_order_ct_pt_rtstruct():
    """목록은 CT PT RTSTRUCT 순서"""
    store = FakeImageStore()
    for m in ["RTSTRUCT", "PT", "CT"]:
        store.add_image(build_image_doc("CASE-001", FileGroup("DICOM", m, m, m), "p", "reg1"))
    assert [d["modality"] for d in list_images(store, "CASE-001")] == ["CT", "PT", "RTSTRUCT"]


# ─────────────── DICOM (pydicom 필요) ───────────────
def dicom_bytes(*, z, series_uid, modality="CT", patient="STS_001", sop_uid=None, rows=4):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    import numpy as np

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = sop_uid or generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientID = patient
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.SeriesDescription = f"test {modality}"
    ds.Rows, ds.Columns = rows, 4
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
    ds.PixelSpacing = [0.5, 0.5]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0.0, 0.0, z]
    ds.PixelData = np.zeros((rows, 4), dtype=np.int16).tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def test_dicom_grouped_with_measured_spacing(tmp_path):
    """DICOM 시리즈는 시리즈별로 묶이고 실측 간격이 기록된다"""
    files = [(f"{i}.dcm", dicom_bytes(z=z, series_uid="1.2.3.100")) for i, z in enumerate([6.54, 0.0, 3.27])]
    files.append(("pt.dcm", dicom_bytes(z=0.0, series_uid="1.2.3.200", modality="PT")))
    r = inspect_files(files, CASE)
    assert r.ok, r.errors
    ct = next(g for g in r.groups if g.modality == "CT")
    assert ct.num_files == 3
    assert ct.meta["slice_spacing_mm"] == pytest.approx(3.27)
    assert ct.meta["rows"] == 4 and ct.meta["pixel_spacing_mm"] == [0.5, 0.5]

    store = FakeImageStore()
    for g in r.groups:
        assert register_group(store, tmp_path, REGISTRAR, CASE, g)[0]
    assert count_images(store, "CASE-001") == 2


def test_rejects_dicom_with_other_patient():
    """DICOM 환자ID가 케이스와 다르면 거절"""
    r = inspect_files([("a.dcm", dicom_bytes(z=0, series_uid="1.2.3", patient="STS_999"))], CASE)
    assert any("환자 ID가 케이스와 다릅니다" in e for e in r.errors)


def test_rejects_dicom_for_case_without_patient():
    """환자ID가 없는 케이스에는 DICOM을 등록하지 않음"""
    pytest.importorskip("pydicom")
    r = inspect_files([("a.dcm", b"\x00" * 128 + b"DICM" + b"\x00" * 10)], {"case_id": "MOCK-0002"})
    assert any("환자 ID가 없어" in e for e in r.errors)


def test_rejects_unsupported_modality():
    """지원하지 않는 모달리티 거절"""
    r = inspect_files([("a.dcm", dicom_bytes(z=0, series_uid="1.2.3", modality="MR"))], CASE)
    assert any("'MR'" in e for e in r.errors)


def test_rejects_duplicate_slice():
    """같은 슬라이스가 두번 들어있으면 거절"""
    b = dicom_bytes(z=0, series_uid="1.2.3", sop_uid="1.2.3.4.5")
    r = inspect_files([("a.dcm", b), ("a_copy.dcm", b)], CASE)
    assert any("두 번" in e for e in r.errors)


def test_rejects_different_slice_sizes():
    """슬라이스 크기가 다르면 거절"""
    r = inspect_files([("a.dcm", dicom_bytes(z=0, series_uid="1.2.3")),
                       ("b.dcm", dicom_bytes(z=1, series_uid="1.2.3", rows=2))], CASE)
    assert any("크기" in e for e in r.errors)


def test_rejects_broken_dicom():
    """DICOM처럼 보이지만 손상된 파일 거절"""
    pytest.importorskip("pydicom")
    broken = b"\x00" * 128 + b"DICM" + b"\xff" * 20
    r = inspect_files([("bad.dcm", broken)], CASE)
    assert any("헤더를 읽을 수 없습니다" in e for e in r.errors)


# ─────────────── 검색·필터 (11/27) ───────────────
from core.images import filter_images, summarize_by_case, summary_label  # noqa: E402


def test_summarize_by_case():
    """케이스별 영상 요약"""
    docs = [
        {"case_id": "CASE-001", "modality": "CT"}, {"case_id": "CASE-001", "modality": "PT"},
        {"case_id": "CASE-001", "modality": "RTSTRUCT"}, {"case_id": "CASE-001", "modality": "RTSTRUCT"},
        {"case_id": "TEST-001"},                          # 종류가 없는 빈 시험용 문서는 세지 않음
    ]
    s = summarize_by_case(docs)
    assert s == {"CASE-001": {"CT": 1, "PT": 1, "RTSTRUCT": 2}}
    assert summary_label(s["CASE-001"]) == "CT·PT·RT×2"
    assert summary_label({}) == "없음"


def test_filter_images():
    """영상 목록 필터"""
    docs = [{"modality": "CT", "series_description": "CT IMAGES - RESEARCH"},
            {"modality": "PT", "series_description": "PET AC"},
            {"modality": "RTSTRUCT", "series_description": "RTstruct_PET"},
            {"modality": "RTSTRUCT", "series_description": "RTstruct_CT"}]
    assert len(filter_images(docs)) == 4
    assert [d["modality"] for d in filter_images(docs, modalities=["RTSTRUCT"])] == ["RTSTRUCT", "RTSTRUCT"]
    assert [d["series_description"] for d in filter_images(docs, keyword="pet")] == ["PET AC", "RTstruct_PET"]
