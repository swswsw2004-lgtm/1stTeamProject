"""
core/dicom_io.py 테스트 (역할2)
실행: python -X utf8 -m pytest tests/test_dicom_io.py -v

실제 환자 데이터 없이도 돌아가도록, 작은 합성 DICOM(4x4 픽셀)을 임시 폴더에 만들어 시험한다.
"""
import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from core.dicom_io import (
    DicomLoadError,
    estimate_slice_spacing,
    find_series,
    load_rtstruct,
    load_series,
    sort_datasets,
    to_physical,
)

CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2"
PT_STORAGE = "1.2.840.10008.5.1.4.1.1.128"
RT_STORAGE = "1.2.840.10008.5.1.4.1.1.481.3"


def make_slice(path, *, z, raw_value, series_uid, modality="CT", slope=1.0, intercept=0.0,
               rows=4, cols=4, patient="TEST_001", photometric="MONOCHROME2", ipp=True):
    """4x4 크기의 아주 작은 DICOM 슬라이스 하나를 파일로 만든다."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = PT_STORAGE if modality == "PT" else CT_STORAGE
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientID = patient
    ds.StudyInstanceUID = "1.2.3.4"
    ds.SeriesInstanceUID = series_uid
    ds.FrameOfReferenceUID = "1.2.3.5"
    ds.Modality = modality
    ds.SeriesDescription = f"test {modality}"
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation = 1            # 부호 있는 정수
    ds.PixelSpacing = [0.5, 0.75]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    if ipp:
        ds.ImagePositionPatient = [-10.0, -20.0, z]
    ds.RescaleSlope = slope
    ds.RescaleIntercept = intercept
    ds.PixelData = np.full((rows, cols), raw_value, dtype=np.int16).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path


@pytest.fixture
def shuffled_ct(tmp_path):
    """파일명 순서와 실제 z 순서가 다른 CT 5장 (정렬 시험용)."""
    uid = generate_uid()
    # 파일명 a~e 순서 ≠ z 순서
    plan = [("a.dcm", 6.54), ("b.dcm", 0.0), ("c.dcm", 13.08), ("d.dcm", 3.27), ("e.dcm", 9.81)]
    files = []
    for name, z in plan:
        # 원래 값을 z에 따라 다르게 넣어 두면, 정렬 후 값 순서로 확인할 수 있다
        files.append(make_slice(tmp_path / name, z=z, raw_value=round(z * 100),
                                series_uid=uid, intercept=-1024))
    return tmp_path, files


# ─────────────── 정렬 ───────────────
def test_정렬은_파일명이_아니라_z위치_기준(shuffled_ct):
    _, files = shuffled_ct
    s = load_series(files)
    assert np.allclose(s.z_positions, [0.0, 3.27, 6.54, 9.81, 13.08])
    assert [p.name for p in s.files] == ["b.dcm", "d.dcm", "a.dcm", "e.dcm", "c.dcm"]
    # 볼륨의 슬라이스 순서도 z 순서와 같아야 한다
    assert np.allclose(s.volume[:, 0, 0], np.array([0, 327, 654, 981, 1308]) - 1024)


def test_ImagePositionPatient가_없으면_정렬_거절(tmp_path):
    uid = generate_uid()
    f1 = make_slice(tmp_path / "1.dcm", z=0, raw_value=0, series_uid=uid)
    f2 = make_slice(tmp_path / "2.dcm", z=0, raw_value=0, series_uid=uid, ipp=False)
    with pytest.raises(DicomLoadError, match="ImagePositionPatient"):
        load_series([f1, f2])


def test_sort_datasets_빈_목록_거절():
    with pytest.raises(DicomLoadError):
        sort_datasets([])


# ─────────────── 값 변환 ───────────────
def test_HU변환은_슬라이스_자기_Intercept를_사용():
    raw = np.array([[0, 1000]], dtype=np.int16)
    ds_0 = Dataset();    ds_0.RescaleSlope, ds_0.RescaleIntercept = 1, 0        # STS_001 형태
    ds_1024 = Dataset(); ds_1024.RescaleSlope, ds_1024.RescaleIntercept = 1, -1024  # STS_002 형태
    assert to_physical(raw, ds_0).tolist() == [[0, 1000]]
    assert to_physical(raw, ds_1024).tolist() == [[-1024, -24]]


def test_Rescale태그가_없으면_원래값_그대로():
    raw = np.array([[5, -3]], dtype=np.int16)
    assert to_physical(raw, Dataset()).tolist() == [[5, -3]]


def test_PET은_슬라이스마다_다른_Slope를_적용(tmp_path):
    uid = generate_uid()
    f1 = make_slice(tmp_path / "p1.dcm", z=0.0, raw_value=100, series_uid=uid, modality="PT", slope=0.5)
    f2 = make_slice(tmp_path / "p2.dcm", z=3.27, raw_value=100, series_uid=uid, modality="PT", slope=2.0)
    s = load_series([f2, f1])
    assert s.modality == "PT"
    assert s.volume[0, 0, 0] == pytest.approx(50.0)    # z=0   → 100 × 0.5
    assert s.volume[1, 0, 0] == pytest.approx(200.0)   # z=3.27 → 100 × 2.0
    assert s.volume.dtype == np.float32


# ─────────────── 간격·위치 ───────────────
def test_슬라이스간격은_실측값_중앙값(shuffled_ct):
    _, files = shuffled_ct
    s = load_series(files)
    assert s.slice_spacing == pytest.approx(3.27)
    assert s.pixel_spacing == (0.5, 0.75)
    assert s.shape == (5, 4, 4)


def test_estimate_slice_spacing_반올림_차이는_중앙값으로_흡수():
    # 실제 PET에서 관측된 3.19 / 3.27 / 3.29 간격 혼재 상황
    locs = np.cumsum([0, 3.27, 3.19, 3.27, 3.29, 3.27])
    assert estimate_slice_spacing(locs) == pytest.approx(3.27)
    assert estimate_slice_spacing(np.array([1.0])) == 0.0


def test_nearest_slice_허용오차(shuffled_ct):
    _, files = shuffled_ct
    s = load_series(files)
    assert s.nearest_slice(3.30) == 1          # 3.27과 0.03mm 차이 → 찾음
    assert s.nearest_slice(5.00, tol_mm=0.5) is None   # 가장 가까운 것도 1.5mm 이상 차이 → 없음


# ─────────────── 잘못된 입력 거절 ───────────────
def test_서로_다른_시리즈가_섞이면_거절(tmp_path):
    f1 = make_slice(tmp_path / "1.dcm", z=0, raw_value=0, series_uid=generate_uid())
    f2 = make_slice(tmp_path / "2.dcm", z=1, raw_value=0, series_uid=generate_uid())
    with pytest.raises(DicomLoadError, match="섞여"):
        load_series([f1, f2])


def test_슬라이스_크기가_다르면_거절(tmp_path):
    uid = generate_uid()
    f1 = make_slice(tmp_path / "1.dcm", z=0, raw_value=0, series_uid=uid, rows=4, cols=4)
    f2 = make_slice(tmp_path / "2.dcm", z=1, raw_value=0, series_uid=uid, rows=2, cols=2)
    with pytest.raises(DicomLoadError, match="크기"):
        load_series([f1, f2])


def test_DICOM이_아닌_파일은_거절(tmp_path):
    bad = tmp_path / "fake.dcm"
    bad.write_bytes(b"this is not dicom")
    with pytest.raises(DicomLoadError, match="DICOM"):
        load_series([bad])


def test_빈_목록은_거절():
    with pytest.raises(DicomLoadError):
        load_series([])


def test_RTSTRUCT는_볼륨으로_읽지_않음(tmp_path):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = RT_STORAGE
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = RT_STORAGE, meta.MediaStorageSOPInstanceUID
    ds.Modality = "RTSTRUCT"
    ds.SeriesInstanceUID = generate_uid()
    path = tmp_path / "rt.dcm"
    ds.save_as(path, enforce_file_format=True)

    with pytest.raises(DicomLoadError, match="RTSTRUCT"):
        load_series([path])
    assert load_rtstruct(path).Modality == "RTSTRUCT"


# ─────────────── 폴더 훑기 ───────────────
def test_find_series는_시리즈별로_묶고_DICOM_아닌_파일은_건너뜀(shuffled_ct):
    folder, _ = shuffled_ct
    (folder / "series_list.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (folder / "noext").write_bytes(b"not dicom")
    pt_uid = generate_uid()
    make_slice(folder / "pt1.dcm", z=0, raw_value=1, series_uid=pt_uid, modality="PT")

    infos = find_series(folder)
    assert [(i.modality, i.n_files) for i in infos] == [("CT", 5), ("PT", 1)]
    assert all(i.patient_id == "TEST_001" for i in infos)


def test_find_series_없는_폴더는_거절(tmp_path):
    with pytest.raises(DicomLoadError, match="폴더"):
        find_series(tmp_path / "없는폴더")


def test_원본_파일은_수정되지_않음(shuffled_ct):
    _, files = shuffled_ct
    before = {f: f.read_bytes() for f in files}
    load_series(files)
    assert all(f.read_bytes() == before[f] for f in files)
