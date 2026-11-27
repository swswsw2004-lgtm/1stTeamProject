"""
영상처리 화면 — 알고리즘 선택, 파라미터 조절, 원본/결과 비교
담당: 역할3
위치: pages/3_processing.py

흐름: 로그인 확인 → 데이터 폴더에서 CT 시리즈 고르기 → 슬라이스·창(window) 고르기
      → 알고리즘·파라미터 고르기 (Otsu는 ROI도) → 원본/결과 나란히 보기

사용하는 모듈
- 역할1 core.auth.require_login       : 로그인 안 했으면 화면 멈춤
- 역할2 core.dicom_io                 : 시리즈 찾기(find_series), 3D 볼륨 읽기(load_series)
- 역할3 core.processing               : window_to_uint8, run_algorithm, ALGORITHMS(파라미터 범위)
"""
import cv2
import numpy as np
import streamlit as st

from core.auth import require_login
from core.dicom_io import DicomLoadError, find_series, load_series
from core.processing import ALGO_VERSION, ALGORITHMS, ProcessingError, run_algorithm, window_to_uint8

st.set_page_config(page_title="영상처리", page_icon="🧪", layout="wide")
user = require_login()

st.title("🧪 영상처리")
st.caption("교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma (CC BY 3.0) · 분석 수치는 진단 결과가 아닙니다.")

WINDOW_PRESETS = {
    "연부조직 (L40 / W400)": (40, 400),
    "좁은 연부조직 (L40 / W150)": (40, 150),
    "뼈 (L400 / W1500)": (400, 1500),
    "직접 입력": None,
}


# ---------------------------------------------------------------
# 데이터 불러오기 (캐시: 폴더 훑기·CT 읽기를 매번 다시 하지 않도록)
# ---------------------------------------------------------------
@st.cache_data(show_spinner="DICOM 폴더를 훑는 중입니다 (처음 한 번만 오래 걸려요)...")
def scan_ct_series(root):
    """데이터 폴더 안의 CT 시리즈 목록 (픽셀은 안 읽음)."""
    return [
        {
            "patient_id": s.patient_id,
            "description": s.description,
            "series_uid": s.series_uid,
            "n_files": s.n_files,
            "files": tuple(str(f) for f in s.files),
        }
        for s in find_series(root)
        if s.modality == "CT"
    ]


@st.cache_resource(max_entries=2, show_spinner="CT 시리즈를 읽는 중입니다...")
def load_ct(files):
    """CT 한 시리즈를 3D 볼륨(HU)으로 읽는다. 약 280MB라 최근 2개만 메모리에 둔다."""
    return load_series(list(files))


def param_widget(name, spec, key):
    """ALGORITHMS에 적힌 범위대로 슬라이더·체크박스를 만든다."""
    if spec.get("type") == "bool":
        return st.checkbox(name, value=spec["default"], key=key)
    if isinstance(spec["default"], int) and isinstance(spec["step"], int):
        return st.slider(name, spec["min"], spec["max"], spec["default"], spec["step"], key=key)
    return st.slider(name, float(spec["min"]), float(spec["max"]), float(spec["default"]),
                     float(spec["step"]), key=key)


def draw_roi(img, roi):
    """원본 위에 ROI를 빨간 사각형으로 그린다 (화면 표시용, 원본 배열은 안 바꿈)."""
    rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if roi:
        x, y, w, h = roi
        cv2.rectangle(rgb, (x, y), (x + w - 1, y + h - 1), (255, 0, 0), 2)
    return rgb


# ---------------------------------------------------------------
# 1. 영상 고르기 (사이드바)
# ---------------------------------------------------------------
with st.sidebar:
    st.header("1. 영상 선택")
    root = st.text_input("데이터 폴더", value="data/sts",
                         help="data/README.md 방법으로 받은 DICOM 폴더 (Git에는 올라가지 않음)")
    try:
        series_list = scan_ct_series(root)
    except DicomLoadError as e:
        st.error(str(e))
        st.stop()
    if not series_list:
        st.warning("이 폴더에서 CT 시리즈를 찾지 못했습니다. 데이터 폴더 경로를 확인해 주세요.")
        st.stop()

    patients = sorted({s["patient_id"] for s in series_list})
    patient = st.selectbox("환자", patients)
    candidates = [s for s in series_list if s["patient_id"] == patient]
    series = st.selectbox(
        "CT 시리즈", candidates,
        format_func=lambda s: f"{s['description'] or '(설명 없음)'} · {s['n_files']}장",
    )

try:
    ct = load_ct(series["files"])
except DicomLoadError as e:
    st.error(str(e))
    st.stop()

with st.sidebar:
    n_slices = ct.volume.shape[0]
    idx = st.slider("슬라이스", 1, n_slices, n_slices // 2 + 1) - 1
    z = float(ct.z_positions[idx])
    st.caption(f"z = {z:.1f} mm · 픽셀 {ct.pixel_spacing[0]:.2f} × {ct.pixel_spacing[1]:.2f} mm")

    preset = st.selectbox("창 (window)", list(WINDOW_PRESETS))
    if WINDOW_PRESETS[preset] is None:
        level = st.number_input("창 중심 (level)", -2000, 4000, 40)
        width = st.number_input("창 너비 (width)", 1, 6000, 400)
    else:
        level, width = WINDOW_PRESETS[preset]

hu = ct.volume[idx]
try:
    img = window_to_uint8(hu, level=level, width=width)
except ProcessingError as e:
    st.error(str(e))
    st.stop()

# ---------------------------------------------------------------
# 2. 알고리즘·파라미터 고르기
# ---------------------------------------------------------------
st.subheader("2. 알고리즘 선택")
name = st.selectbox("알고리즘", list(ALGORITHMS), format_func=lambda k: ALGORITHMS[k]["label"])

params = {}
specs = ALGORITHMS[name]["params"]
if specs:
    cols = st.columns(len(specs))
    for col, (pname, spec) in zip(cols, specs.items()):
        with col:
            params[pname] = param_widget(pname, spec, key=f"{name}_{pname}")

roi = None
if name == "otsu":
    use_roi = st.checkbox("ROI 안에서만 계산하기", value=True,
                          help="슬라이스 전체에 걸면 근육·지방·침대까지 같이 나뉘어서 종양만 따로 안 잡혀요.")
    if use_roi:
        H, W = img.shape
        c1, c2, c3, c4 = st.columns(4)
        x = c1.slider("ROI x", 0, W - 1, W // 4)
        y = c2.slider("ROI y", 0, H - 1, H // 4)
        w = c3.slider("ROI 너비", 1, W, W // 4)
        h = c4.slider("ROI 높이", 1, H, H // 4)
        roi = (x, y, w, h)  # 영상 밖으로 나가면 core.processing.check_roi가 이유와 함께 거절

# ---------------------------------------------------------------
# 3. 실행 + 원본/결과 비교
# ---------------------------------------------------------------
st.subheader("3. 원본 / 결과 비교")
try:
    result, features = run_algorithm(name, img, params, roi=roi)
except ProcessingError as e:
    st.error(f"처리할 수 없습니다: {e}")
    st.stop()

left, right = st.columns(2)
with left:
    st.image(draw_roi(img, roi), caption=f"원본 · 슬라이스 {idx + 1}/{n_slices} · {preset}",
             width="stretch")
with right:
    st.image(result, caption=f"결과 · {ALGORITHMS[name]['label']}", clamp=True,
             width="stretch")

st.subheader("4. 특징값")
area_mm2 = None
if "area_px" in features:
    area_mm2 = features["area_px"] * ct.pixel_spacing[0] * ct.pixel_spacing[1]
metric_cols = st.columns(4)
metric_cols[0].metric("평균 밝기", f"{features['mean']:.1f}")
metric_cols[1].metric("표준편차", f"{features['std']:.1f}")
if "threshold" in features:
    metric_cols[2].metric("Otsu 임계값", f"{features['threshold']:.0f}")
    metric_cols[3].metric("흰색 면적", f"{features['area_px']} px", f"{area_mm2:.0f} mm²", delta_color="off")

# 처리 이력(processing_history)에 저장될 형태 미리보기 — 저장 기능은 core/history.py에서 연결 예정
with st.expander("처리 이력에 저장될 값 미리보기"):
    st.json({
        "case_id": None,
        "patient_id": patient,
        "series_uid": series["series_uid"],
        "slice_index": idx,
        "algorithm": name,
        "algo_version": ALGO_VERSION,
        "params": params,
        "window": {"level": level, "width": width},
        "roi": dict(zip(("x", "y", "w", "h"), roi)) if roi else None,
        "features": {**features, **({"area_mm2": round(area_mm2, 1)} if area_mm2 is not None else {})},
        "executed_by": user["uid"],
    })
