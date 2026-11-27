"""
core/fusion.py 테스트 (역할2) — PET/CT 융합
실행: python -X utf8 -m pytest tests/test_fusion.py -v

실제 데이터와 같은 상황(PET이 CT보다 넓게 찍힘, 픽셀 크기 다름)을 작은 가짜 볼륨으로 만들어 시험한다.
"""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from core.dicom_io import Series
from core.fusion import (
    FusionError,
    blend,
    colorize,
    contours_on_slice,
    default_pet_max,
    draw_contours,
    matching_pet_index,
    patient_to_pixel,
    pet_on_ct_slice,
    pixel_to_patient,
    roi_names,
)

AXIAL = np.array([1.0, 0, 0, 0, 1.0, 0])


def make_series(modality, volume, origin_xy, spacing, z_list, frame="1.2.3", patient="STS_001"):
    """origin_xy: 첫 픽셀 중심의 (x, y) mm, spacing: 픽셀 간격 mm (행=열)."""
    positions = np.array([[origin_xy[0], origin_xy[1], z] for z in z_list], dtype=float)
    return Series(patient_id=patient, series_uid=modality, modality=modality, description=modality,
                  volume=np.asarray(volume, dtype=np.float32), positions=positions, orientation=AXIAL,
                  pixel_spacing=(spacing, spacing),
                  slice_spacing=float(np.median(np.diff(z_list))) if len(z_list) > 1 else 0.0,
                  photometric="MONOCHROME2", frame_of_reference_uid=frame, files=[], header=None)


@pytest.fixture
def ct_pt():
    """CT: 40×40, 1mm, 시작 (-20,-20) → 촬영 폭 40mm
    PET: 12×12, 5mm, 시작 (-30,-30) → 촬영 폭 60mm (CT보다 넓음, 실제 데이터와 같은 상황)
    PET에서 환자 좌표 (10, -5) mm 근처만 밝게(1000) 만든다."""
    z = [0.0, 3.27, 6.54]
    ct = make_series("CT", np.zeros((3, 40, 40)), (-20, -20), 1.0, z)
    pet = np.zeros((3, 12, 12))
    # PET 픽셀 (행, 열) → mm: x = -30 + 열*5, y = -30 + 행*5  →  (x=10, y=-5) 는 열 8, 행 5
    pet[:, 5, 8] = 1000
    pt = make_series("PT", pet, (-30, -30), 5.0, [0.02, 3.29, 6.52])   # z가 소수점까지 같지 않음
    return ct, pt


# ─────────────── 좌표 ───────────────
def test_pixel_patient_round_trip(ct_pt):
    """픽셀 → mm → 픽셀 이 원래대로 돌아온다"""
    ct, _ = ct_pt
    p = pixel_to_patient(ct, 1, np.array(7), np.array(13))
    assert np.allclose(p, [-20 + 13, -20 + 7, 3.27])
    r, c = patient_to_pixel(ct, 1, p)
    assert np.isclose(r, 7) and np.isclose(c, 13)


def test_matching_pet_slice_uses_nearest_z(ct_pt):
    """CT z와 소수점이 조금 다른 PET 슬라이스를 찾는다"""
    ct, pt = ct_pt
    assert [matching_pet_index(ct, pt, i) for i in range(3)] == [0, 1, 2]


def test_pet_lands_on_same_patient_position(ct_pt):
    """PET의 밝은 점(10, -5mm)이 CT 격자에서도 같은 mm 위치에 놓인다 (단순 확대였다면 어긋남)"""
    ct, pt = ct_pt
    pet, pi = pet_on_ct_slice(ct, pt, 1)
    assert pi == 1 and pet.shape == (40, 40)
    r, c = np.unravel_index(np.nanargmax(pet), pet.shape)
    x, y = -20 + c, -20 + r          # CT 픽셀 → mm
    assert abs(x - 10) <= 1 and abs(y - (-5)) <= 1
    assert np.nanmax(pet) == pytest.approx(1000, rel=0.01)


def test_naive_scaling_would_be_wrong(ct_pt):
    """비교: PET을 CT 크기로 그냥 늘리면 밝은 점이 다른 곳에 놓인다 (mm 정합이 필요한 이유)"""
    import cv2
    _, pt = ct_pt
    naive = cv2.resize(pt.volume[1], (40, 40), interpolation=cv2.INTER_LINEAR)
    r, c = np.unravel_index(np.argmax(naive), naive.shape)
    x, y = -20 + c, -20 + r
    assert abs(x - 10) > 2 or abs(y - (-5)) > 2


def test_outside_pet_or_no_matching_slice_is_nan(ct_pt):
    ct, pt = ct_pt
    far = make_series("PT", pt.volume, (-30, -30), 5.0, [100.0, 103.27, 106.54])
    pet, pi = pet_on_ct_slice(ct, far, 1)
    assert pi is None and np.isnan(pet).all()


def test_rejects_different_frame_or_patient(ct_pt):
    ct, pt = ct_pt
    with pytest.raises(FusionError, match="좌표계"):
        pet_on_ct_slice(ct, make_series("PT", pt.volume, (-30, -30), 5.0, [0, 3.27, 6.54], frame="9.9"), 0)
    with pytest.raises(FusionError, match="환자"):
        pet_on_ct_slice(ct, make_series("PT", pt.volume, (-30, -30), 5.0, [0, 3.27, 6.54], patient="STS_002"), 0)


# ─────────────── 색·겹치기 ───────────────
def test_colorize_and_blend():
    pet = np.array([[0.0, 500.0], [1000.0, np.nan]], dtype=np.float32)
    rgb = colorize(pet, vmax=1000)
    assert rgb.shape == (2, 2, 3) and rgb.dtype == np.uint8
    ct = np.full((2, 2), 100, dtype=np.uint8)

    assert (blend(ct, rgb, 0.0) == 100).all()                       # 투명도 0 → CT만
    assert (blend(ct, rgb, 1.0) == rgb).all()                       # 투명도 1 → PET만
    half = blend(ct, rgb, 0.5, pet_values=pet, threshold=100)
    assert (half[0, 0] == 100).all() and (half[1, 1] == 100).all()  # 배경·NaN은 CT 그대로
    assert not (half[1, 0] == 100).all()                            # 밝은 곳만 색이 섞임


@pytest.mark.parametrize("kwargs, keyword", [
    ({"alpha": 1.5}, "투명도"),
    ({"alpha": 0.5, "shape": (3, 3)}, "크기"),
])
def test_blend_rejects_bad_input(kwargs, keyword):
    ct = np.zeros((2, 2), np.uint8)
    rgb = np.zeros(kwargs.pop("shape", (2, 2)) + (3,), np.uint8)
    with pytest.raises(FusionError, match=keyword):
        blend(ct, rgb, **kwargs)


def test_colorize_rejects_bad_settings():
    with pytest.raises(FusionError):
        colorize(np.zeros((2, 2)), vmax=0)
    with pytest.raises(FusionError):
        colorize(np.zeros((2, 2)), vmax=1, cmap="rainbow")


def test_default_pet_max_ignores_few_hot_pixels(ct_pt):
    _, pt = ct_pt
    assert default_pet_max(pt) < 1000      # 점 몇 개(1000) 때문에 상한이 끝까지 올라가지 않음


# ─────────────── RTSTRUCT 윤곽 ───────────────
def fake_rtstruct():
    """GTV_Mass: z=3.27 높이에 한 변 10mm 정사각형 (x 0~10, y 0~10) / GTV_Edema: z=0"""
    square = [0, 0, 3.27, 10, 0, 3.27, 10, 10, 3.27, 0, 10, 3.27]
    edema = [-5, -5, 0.0, 5, -5, 0.0, 5, 5, 0.0]
    return NS(
        StructureSetROISequence=[NS(ROINumber=1, ROIName="GTV_Mass"), NS(ROINumber=2, ROIName="GTV_Edema")],
        ROIContourSequence=[NS(ReferencedROINumber=1, ContourSequence=[NS(ContourData=square)]),
                            NS(ReferencedROINumber=2, ContourSequence=[NS(ContourData=edema)])],
    )


def test_contour_converted_to_ct_pixels(ct_pt):
    ct, _ = ct_pt
    rt = fake_rtstruct()
    assert roi_names(rt) == ["GTV_Mass", "GTV_Edema"]
    polys = contours_on_slice(rt, "GTV_Mass", ct, 1)
    assert len(polys) == 1
    # mm (0,0)~(10,10) → CT 픽셀 [열, 행] (20,20)~(30,30)
    assert np.allclose(polys[0], [[20, 20], [30, 20], [30, 30], [20, 30]])
    assert contours_on_slice(rt, "GTV_Mass", ct, 0) == []        # 다른 높이에는 없음


def test_contour_unknown_roi_name(ct_pt):
    ct, _ = ct_pt
    with pytest.raises(FusionError, match="GTV_Mass, GTV_Edema"):
        contours_on_slice(fake_rtstruct(), "Tumor", ct, 1)


def test_draw_contours_keeps_original():
    img = np.zeros((40, 40), np.uint8)
    out = draw_contours(img, [np.array([[5, 5], [30, 5], [30, 30]])])
    assert out.shape == (40, 40, 3) and out[5, 5:30, 1].max() == 255
    assert img.max() == 0
