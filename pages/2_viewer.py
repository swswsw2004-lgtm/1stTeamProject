"""
이미지 뷰어 + PET/CT 융합 화면
담당: 역할2 (케이스·영상 관리·뷰어 / 특화 기능: CT 위 PET 오버레이·투명도·좌표 정합)
위치: pages/2_viewer.py

흐름: 케이스 선택 → 등록된 CT(필수)·PET·RTSTRUCT 선택 → 슬라이스·창·확대·이동 → 화면 초기화
      탭1 원본/처리 결과 비교 (역할3 알고리즘 미리보기, 저장은 영상처리 화면에서)
      탭2 PET/CT 융합 (PET을 CT 격자에 mm 기준으로 맞춰 반투명 컬러로 겹침 + 종양 윤곽)
원본 파일·볼륨은 읽기만 하고 바꾸지 않는다. 분석 수치는 교육용 결과이며 진단에 쓰지 않는다.
"""
from pathlib import Path

import numpy as np
import streamlit as st

from core.auth import require_login
from core.cases import FirestoreCaseStore, list_cases
from core.dicom_io import DicomLoadError, load_rtstruct, load_series
from core.firebase import get_db
from core.fusion import (
    PET_COLORMAPS,
    FusionError,
    blend,
    colorize,
    contours_on_slice,
    default_pet_max,
    draw_contours,
    pet_on_ct_slice,
    roi_names,
)
from core.images import FirestoreImageStore, list_images
from core.processing import ALGORITHMS, ProcessingError, run_algorithm
from core.viewer import (
    DEFAULT_PRESET,
    WINDOW_PRESETS,
    ViewerError,
    ViewState,
    clamp_view,
    describe_view,
    render,
    to_display,
)

st.set_page_config(page_title="뷰어", page_icon="🩻", layout="wide")
user = require_login()

STORAGE = st.secrets.get("storage_dir", "./data/storage")
OUT = 480                      # 화면에 그리는 한 칸의 크기(px)
CUSTOM = "직접 입력"


# ─────────────────────────────────────────────
# 데이터 읽기 (캐시)
# ─────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_cases_cached() -> list[dict]:
    return list_cases(FirestoreCaseStore(get_db()))


@st.cache_data(ttl=60, show_spinner=False)
def load_images_cached(case_id: str) -> list[dict]:
    return list_images(FirestoreImageStore(get_db()), case_id)


def series_files(file_path: str) -> list[str]:
    folder = Path(STORAGE) / file_path
    if not folder.is_dir():
        raise DicomLoadError(f"원본 폴더를 찾을 수 없습니다 ({file_path}). 이 PC(서버)에 등록된 영상인지 확인해 주세요.")
    return [str(p) for p in sorted(folder.iterdir()) if p.is_file()]


@st.cache_resource(max_entries=4, show_spinner="영상을 읽는 중입니다 (CT 267장은 처음 한 번 10~20초)...")
def open_series(file_path: str):
    """3D 볼륨으로 읽기 (역할2 core.dicom_io: 위치 정렬 + 슬라이스별 HU 변환). 같은 시리즈는 다시 읽지 않음."""
    return load_series(series_files(file_path))


@st.cache_resource(max_entries=4, show_spinner=False)
def open_rtstruct(file_path: str):
    files = series_files(file_path)
    if not files:
        raise DicomLoadError("RTSTRUCT 파일이 없습니다.")
    return load_rtstruct(files[0])


def label(d: dict) -> str:
    return f"{d.get('modality')} · {d.get('series_description') or '-'} · {d.get('num_files') or '?'}장"


# ─────────────────────────────────────────────
# 보기 상태 (session_state) · 화면 초기화
# ─────────────────────────────────────────────
def reset_view(shape) -> None:
    """화면 초기화: 가운데 슬라이스 · 확대 1배 · 가운데 · 연부조직 창 (버튼 콜백에서 호출)."""
    v = ViewState.default(shape)
    st.session_state.update({
        "v_slice": v.slice_index + 1, "v_zoom": 1.0, "v_row": int(v.center_row), "v_col": int(v.center_col),
        "v_preset": DEFAULT_PRESET, "v_level": int(v.level), "v_width": int(v.width),
    })


# ─────────────────────────────────────────────
# 화면
# ─────────────────────────────────────────────
st.title("🩻 뷰어 · PET/CT 융합")
st.caption("교육용 모의 케이스 · 분석 수치는 교육용 결과이며 진단에 쓰지 않습니다 · 데이터: TCIA Soft-tissue-Sarcoma (CC BY 3.0)")

cases = [c for c in load_cases_cached() if c.get("case_id")]
if not cases:
    st.info("등록된 케이스가 없습니다. cases 화면에서 케이스와 영상을 먼저 등록해 주세요.")
    st.stop()

by_id = {c["case_id"]: c for c in cases}
case_id = st.selectbox("케이스", list(by_id),
                       format_func=lambda cid: f"{cid} · {by_id[cid].get('patient_id') or '환자 ID 없음'}")
images = [d for d in load_images_cached(case_id) if d.get("file_path") and d.get("format") == "DICOM"]
cts = [d for d in images if d.get("modality") == "CT"]
pts = [d for d in images if d.get("modality") == "PT"]
rts = [d for d in images if d.get("modality") == "RTSTRUCT"]
if not cts:
    st.info("이 케이스에 등록된 CT가 없습니다. cases 화면의 '케이스별 영상'에서 CT를 등록해 주세요.")
    st.stop()

ct_doc = st.selectbox("CT 시리즈", cts, format_func=label)
try:
    ct = open_series(ct_doc["file_path"])
except DicomLoadError as e:
    st.error(str(e))
    st.stop()
shape = ct.volume.shape

# 다른 시리즈로 바꾸면 보기 상태를 처음으로
if st.session_state.get("v_series") != ct.series_uid:
    reset_view(shape)
    st.session_state["v_series"] = ct.series_uid

# ── 조작 ──
c1, c2, c3 = st.columns([3, 2, 1])
c1.slider("슬라이스", 1, shape[0], key="v_slice")
preset = c2.selectbox("창 (window)", list(WINDOW_PRESETS) + [CUSTOM], key="v_preset")
c3.button("↺ 화면 초기화", on_click=reset_view, args=(shape,), use_container_width=True)
if preset == CUSTOM:
    w1, w2 = st.columns(2)
    level = w1.number_input("창 중심 (level, HU)", -2000, 4000, step=10, key="v_level")
    width = w2.number_input("창 너비 (width, HU)", 1, 6000, step=10, key="v_width")
else:
    level, width = WINDOW_PRESETS[preset]

z1, z2, z3 = st.columns(3)
zoom = z1.slider("확대", 1.0, 8.0, step=0.5, key="v_zoom")
z2.slider("이동: 위↔아래 (행)", 0, shape[1], key="v_row", disabled=zoom == 1.0)
z3.slider("이동: 왼쪽↔오른쪽 (열)", 0, shape[2], key="v_col", disabled=zoom == 1.0)

view = clamp_view(ViewState(st.session_state["v_slice"] - 1, zoom, st.session_state["v_row"],
                            st.session_state["v_col"], level, width), shape)
idx = view.slice_index
try:
    ct_u8 = to_display(ct.volume[idx], level, width, ct.photometric)
except ViewerError as e:
    st.error(str(e))
    st.stop()
st.caption(describe_view(view, shape, ct.pixel_spacing, float(ct.z_positions[idx])))

tab_view, tab_fusion = st.tabs(["🖼️ 원본 / 처리 결과 비교", "🔥 PET/CT 융합"])

# ── 탭1: 원본 / 처리 결과 비교 ──
with tab_view:
    names = ["(처리 없음)"] + list(ALGORITHMS)
    algo = st.selectbox("비교할 처리", names,
                        format_func=lambda n: ALGORITHMS[n]["label"] if n in ALGORITHMS else n)
    left, right = st.columns(2)
    left.image(render(ct_u8, view, OUT), caption="원본", clamp=True)
    if algo in ALGORITHMS:
        try:
            result, features = run_algorithm(algo, ct_u8)       # 역할3 알고리즘 · 기본 파라미터
            right.image(render(result, view, OUT), caption=f"처리 결과 · {ALGORITHMS[algo]['label']}", clamp=True)
            right.caption(f"평균 {features['mean']:.1f} · 표준편차 {features['std']:.1f} (기본 파라미터 미리보기 · "
                          "파라미터 조절·이력 저장은 processing 화면)")
        except ProcessingError as e:
            right.error(str(e))
    else:
        right.info("오른쪽에 처리 결과를 보려면 위에서 처리 방법을 고르세요.")

# ── 탭2: PET/CT 융합 ──
with tab_fusion:
    if not pts:
        st.info("이 케이스에 등록된 PET(PT)이 없습니다. cases 화면에서 PET을 등록하면 융합 화면을 쓸 수 있습니다.")
    else:
        pt_doc = st.selectbox("PET 시리즈", pts, format_func=label)
        try:
            pt = open_series(pt_doc["file_path"])
            pet, pet_idx = pet_on_ct_slice(ct, pt, idx)
        except (DicomLoadError, FusionError) as e:
            st.error(str(e))
            st.stop()

        f1, f2, f3, f4 = st.columns(4)
        alpha = f1.slider("PET 투명도", 0.0, 1.0, 0.5, 0.05, help="0 = CT만, 1 = PET만")
        cmap = f2.selectbox("PET 색", list(PET_COLORMAPS))
        auto_max = max(default_pet_max(pt), 1.0)
        vmax = f3.number_input("PET 표시 상한", min_value=1.0, value=float(round(auto_max)), step=100.0,
                               help="이 값 이상은 가장 밝은 색 (기본: 99.5 백분위)")
        thr_pct = f4.slider("배경 숨김 (%)", 0, 50, 5, help="상한의 이 비율 이하인 PET 값은 색을 입히지 않음")

        rt_doc = roi = None
        show_contour = False
        if rts:
            r1, r2, r3 = st.columns([2, 2, 1])
            default_rt = next((i for i, d in enumerate(rts) if "PET" in (d.get("series_description") or "")), 0)
            rt_doc = r1.selectbox("종양 윤곽 (RTSTRUCT)", rts, index=default_rt, format_func=label)
            try:
                rtstruct = open_rtstruct(rt_doc["file_path"])
                names_ = roi_names(rtstruct)
                roi = r2.selectbox("윤곽 이름", names_, index=names_.index("GTV_Mass") if "GTV_Mass" in names_ else 0)
                show_contour = r3.checkbox("윤곽 표시", value=True)
            except (DicomLoadError, FusionError) as e:
                st.warning(str(e))

        pet_rgb = colorize(pet, vmax, cmap)
        fused = blend(ct_u8, pet_rgb, alpha, pet_values=pet, threshold=vmax * thr_pct / 100)
        ct_rgb = np.repeat(ct_u8[..., None], 3, axis=2)
        n_poly = 0
        if show_contour and roi:
            try:
                polys = contours_on_slice(rtstruct, roi, ct, idx)
                n_poly = len(polys)
                fused = draw_contours(fused, polys, thickness=2)
                ct_rgb = draw_contours(ct_rgb, polys, thickness=2)
            except FusionError as e:
                st.warning(str(e))

        a, b, c = st.columns(3)
        a.image(render(ct_rgb, view, OUT), caption="CT", clamp=True)
        b.image(render(pet_rgb, view, OUT), caption="PET (CT 격자에 mm 기준으로 맞춤)", clamp=True)
        c.image(render(fused, view, OUT), caption=f"융합 · 투명도 {alpha:.2f}", clamp=True)

        unit = str(getattr(pt.header, "Units", "") or "원래 값")
        if pet_idx is None:
            st.warning("이 CT 슬라이스와 같은 높이의 PET 슬라이스가 없습니다 (PET 촬영 범위 밖).")
        else:
            dz = float(pt.z_positions[pet_idx]) - float(ct.z_positions[idx])
            inside = np.isfinite(pet)
            st.caption(
                f"CT z {float(ct.z_positions[idx]):.2f} mm ↔ PET 슬라이스 {pet_idx + 1}/{pt.volume.shape[0]} "
                f"(z 차이 {dz:+.2f} mm) · PET 픽셀 {pt.pixel_spacing[0]:.2f} mm → CT {ct.pixel_spacing[0]:.3f} mm · "
                f"PET 단위 {unit} (SUV 아님) · 이 슬라이스 PET 최댓값 "
                f"{(np.nanmax(pet) if inside.any() else 0):.0f}"
                + (f" · {roi} 윤곽 {n_poly}개" if show_contour and roi else ""))
