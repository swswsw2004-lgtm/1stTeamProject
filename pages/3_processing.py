"""
영상처리 화면 — 알고리즘 선택, 파라미터 조절, 원본/결과 비교
담당: 역할3
위치: pages/3_processing.py

흐름: 로그인 확인 → 데이터 폴더에서 CT 시리즈 고르기 → 슬라이스·창(window) 고르기
      → 알고리즘·파라미터 고르기 (Otsu는 ROI도) → 원본/결과 나란히 보기
      → 케이스를 골라 처리 이력 저장 → 이력 목록 · 저장된 설정으로 다시 실행(재현 확인)

사용하는 모듈
- 역할1 core.auth.require_login       : 로그인 안 했으면 화면 멈춤
- 역할2 core.dicom_io                 : 시리즈 찾기(find_series), 3D 볼륨 읽기(load_series)
- 역할3 core.processing               : window_to_uint8, run_algorithm, ALGORITHMS(파라미터 범위)
- 역할3 core.roi                      : ROI 통계(평균·표준편차·분산·면적 mm²)와 히스토그램
- 역할3 core.history                  : 처리 이력 저장(권한·중복 확인)·조회·재현
- 역할1·2 core.cases / core.images     : 환자 ID로 케이스 찾기, 시리즈 UID로 image_id 찾기
"""
import cv2
import pandas as pd
import streamlit as st

from core.auth import require_login
from core.dicom_io import DicomLoadError, find_series, load_series
from core.processing import ALGO_VERSION, ALGORITHMS, ProcessingError, run_algorithm, window_to_uint8
from core.cases import FirestoreCaseStore, list_cases
from core.firebase import get_db
from core.history import (FirestoreHistoryStore, HistoryError, check_can_save_history, list_histories,
                          load_result_image, new_request_id, rerun_history, same_result, save_history)
from core.images import FirestoreImageStore, list_images
from core.roi import clamp_roi_size, roi_histogram, roi_stats
from core.workflow import STATUS_NAMES

st.set_page_config(page_title="영상처리", page_icon="🧪", layout="wide")
user = require_login()

try:  # 결과 PNG: STORAGE/results/<케이스ID>/<이력ID>.png (secrets.toml이 없으면 기본 위치)
    STORAGE = st.secrets.get("storage_dir", "./data/storage")
except Exception:
    STORAGE = "./data/storage"

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


def int_slider(container, label, lo, hi, key=None, value=None):
    """정수 슬라이더. 고를 수 있는 값이 하나뿐이면(lo == hi) Streamlit 슬라이더가 에러를 내므로
    슬라이더 대신 값을 글로 보여 주고 그 값을 돌려준다 (예: 1장짜리 시리즈, 오른쪽 끝에 붙은 ROI)."""
    if hi <= lo:
        if key is not None:
            st.session_state[key] = lo
        container.caption(f"{label}: {lo} (고를 수 있는 값이 하나뿐)")
        return lo
    if key is not None:
        return container.slider(label, lo, hi, key=key)
    return container.slider(label, lo, hi, value if value is not None else lo)


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
    idx = int_slider(st, "슬라이스", 1, n_slices, value=n_slices // 2 + 1) - 1
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
# 2. ROI(관심 영역) 지정
# ---------------------------------------------------------------
st.subheader("2. ROI 지정")
H, W = img.shape
use_roi = st.checkbox("ROI 사용", value=True, key="use_roi",
                      help="종양처럼 보고 싶은 부분을 사각형으로 지정하면 통계와 히스토그램을 계산해요.")
roi = None
if use_roi:
    # 슬라이더를 만들기 전에 값이 영상 밖으로 나가지 않게 너비·높이를 줄여 둔다
    for k, v in (("roi_x", W // 4), ("roi_y", H // 4), ("roi_w", W // 4), ("roi_h", H // 4)):
        st.session_state.setdefault(k, v)
    st.session_state.roi_x, st.session_state.roi_y, st.session_state.roi_w, st.session_state.roi_h = clamp_roi_size(
        st.session_state.roi_x, st.session_state.roi_y, st.session_state.roi_w, st.session_state.roi_h, (H, W))
    c1, c2, c3, c4 = st.columns(4)
    x = int_slider(c1, "ROI x", 0, W - 1, key="roi_x")
    y = int_slider(c2, "ROI y", 0, H - 1, key="roi_y")
    w = int_slider(c3, "ROI 너비", 1, W - x, key="roi_w")
    h = int_slider(c4, "ROI 높이", 1, H - y, key="roi_h")
    roi = (x, y, w, h)
    st.caption(f"영상 크기 {W}×{H} · 너비는 최대 {W - x}, 높이는 최대 {H - y}까지 (영상 밖으로 나가지 않게 자동 조절)")

# ---------------------------------------------------------------
# 3. 알고리즘·파라미터 고르기
# ---------------------------------------------------------------
st.subheader("3. 알고리즘 선택")
name = st.selectbox("알고리즘", list(ALGORITHMS), format_func=lambda k: ALGORITHMS[k]["label"])

params = {}
specs = ALGORITHMS[name]["params"]
if specs:
    cols = st.columns(len(specs))
    for col, (pname, spec) in zip(cols, specs.items()):
        with col:
            params[pname] = param_widget(pname, spec, key=f"{name}_{pname}")

otsu_roi = None
if name == "otsu":
    if roi is None:
        st.info("Otsu는 ROI 없이 슬라이스 전체에 적용합니다. 근육·지방·침대까지 같이 나뉘어서 종양만 따로 안 잡힐 수 있어요.")
    else:
        apply_in_roi = st.checkbox("ROI 안에서만 계산하기", value=True,
                                   help="슬라이스 전체에 걸면 근육·지방·침대까지 같이 나뉘어서 종양만 따로 안 잡혀요.")
        otsu_roi = roi if apply_in_roi else None

# ---------------------------------------------------------------
# 4. 실행 + 원본/결과 비교
# ---------------------------------------------------------------
st.subheader("4. 원본 / 결과 비교")
try:
    result, features = run_algorithm(name, img, params, roi=otsu_roi)
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

st.subheader("5. 특징값")
area_mm2 = None
if "area_px" in features:
    area_mm2 = features["area_px"] * ct.pixel_spacing[0] * ct.pixel_spacing[1]
metric_cols = st.columns(4)
metric_cols[0].metric("평균 밝기", f"{features['mean']:.1f}")
metric_cols[1].metric("표준편차", f"{features['std']:.1f}")
if "threshold" in features:
    metric_cols[2].metric("Otsu 임계값", f"{features['threshold']:.0f}")
    metric_cols[3].metric("흰색 면적", f"{features['area_px']} px", f"{area_mm2:.0f} mm²", delta_color="off")

# ---------------------------------------------------------------
# 6. ROI 분석 (통계 + 히스토그램)
# ---------------------------------------------------------------
roi_record = None
if roi is not None:
    st.subheader("6. ROI 분석")
    try:
        hu_stats = roi_stats(hu, roi, pixel_spacing=ct.pixel_spacing)
        before = roi_stats(img, roi)
        after = roi_stats(result, roi)
        counts, edges = roi_histogram(hu, roi, bins=60, value_range=(level - width / 2, level + width / 2))
    except ProcessingError as e:
        st.error(f"ROI를 계산할 수 없습니다: {e}")
    else:
        m = st.columns(4)
        m[0].metric("ROI 평균 (HU)", f"{hu_stats['mean']:.1f}")
        m[1].metric("ROI 표준편차 (HU)", f"{hu_stats['std']:.1f}")
        m[2].metric("ROI 면적", f"{hu_stats['area_mm2']:.0f} mm²", f"{hu_stats['n_px']} px", delta_color="off")
        m[3].metric("HU 범위", f"{hu_stats['min']:.0f} ~ {hu_stats['max']:.0f}")

        st.caption("처리 전/후 ROI 비교 (8비트 밝기 기준) — 표준편차가 줄면 잡음이 줄었다는 뜻")
        st.dataframe(pd.DataFrame(
            {"평균": [before["mean"], after["mean"]], "표준편차": [before["std"], after["std"]],
             "분산": [before["var"], after["var"]]},
            index=["처리 전", f"처리 후 ({name})"],
        ).round(2))

        st.caption(f"ROI 안 HU 히스토그램 (창 범위 {level - width / 2:.0f} ~ {level + width / 2:.0f} HU)")
        centers = (edges[:-1] + edges[1:]) / 2
        st.bar_chart(pd.DataFrame({"픽셀 수": counts}, index=pd.Index(centers.round(0), name="HU")))
        roi_record = {k: hu_stats[k] for k in ("x", "y", "w", "h", "area_mm2")}
        roi_record["hu_mean"] = round(hu_stats["mean"], 2)
        roi_record["hu_std"] = round(hu_stats["std"], 2)

# ---------------------------------------------------------------
# 7. 처리 이력 저장 · 조회 (core/history.py)
# ---------------------------------------------------------------
st.subheader("7. 처리 이력")
features_rec = {**features, **({"area_mm2": round(area_mm2, 1)} if area_mm2 is not None else {})}
if roi_record:
    features_rec.update({"roi_hu_mean": roi_record["hu_mean"], "roi_hu_std": roi_record["hu_std"],
                         "roi_area_mm2": round(roi_record["area_mm2"], 1)})
window_rec = {"level": int(level), "width": int(width)}

# 같은 결과(설정이 같으면)는 같은 요청 ID → 연속 클릭해도 한 번만 저장
setting_key = repr((series["series_uid"], idx, name, sorted(params.items()), window_rec, roi, otsu_roi is not None))
if st.session_state.get("hist_setting") != setting_key:
    st.session_state["hist_setting"] = setting_key
    st.session_state["hist_request_id"] = new_request_id()
request_id = st.session_state["hist_request_id"]

try:
    db = get_db()
    cases = [c for c in list_cases(FirestoreCaseStore(db)) if c.get("patient_id") == patient]
except Exception as e:  # Firebase 설정이 없거나 네트워크 오류
    st.warning(f"Firestore에 연결하지 못해 처리 이력 저장은 쓸 수 없습니다 ({type(e).__name__}).")
    st.stop()

if not cases:
    st.info(f"환자 {patient}로 등록된 케이스가 없습니다. cases 화면에서 케이스를 먼저 등록하면 처리 이력을 남길 수 있어요.")
    st.stop()

case = st.selectbox("저장할 케이스", cases,
                    format_func=lambda c: f"{c['case_id']} · {STATUS_NAMES.get(c.get('status'), c.get('status'))}")
images = list_images(FirestoreImageStore(db), case["case_id"])
image = next((d for d in images if d.get("series_uid") == series["series_uid"]), None)
if image is None:
    st.caption("이 CT 시리즈는 케이스 영상으로 등록되어 있지 않아 image_id 없이 저장됩니다.")

can_save, reason = check_can_save_history(case, user)
if st.button("💾 처리 이력 저장", disabled=not can_save, type="primary"):
    ok, msg, hid = save_history(
        FirestoreHistoryStore(db), STORAGE, user, case,
        image_id=image["id"] if image else None, slice_index=idx, algorithm=name, params=params,
        window=window_rec, roi=roi, features=features_rec, result_image=result,
        history_id=request_id, roi_applied=otsu_roi is not None,
    )
    (st.success if ok else st.warning)(msg)
if not can_save:
    st.caption(f"저장 버튼이 꺼진 이유: {reason}")

with st.expander("저장될 값 미리보기"):
    st.json({"history_id": request_id, "case_id": case["case_id"], "image_id": image["id"] if image else None,
             "slice_index": idx, "algorithm": name, "algorithm_version": ALGO_VERSION, "params": params,
             "window": window_rec, "roi": dict(zip(("x", "y", "w", "h"), roi)) if roi else None,
             "roi_applied": otsu_roi is not None, "features": features_rec})

histories = list_histories(FirestoreHistoryStore(db), case["case_id"])
st.caption(f"{case['case_id']}의 처리 이력 {len(histories)}건 (최근 순)")
if histories:
    st.dataframe(pd.DataFrame([{
        "시각": h.get("executed_at", "")[:16], "알고리즘": h.get("algorithm"), "버전": h.get("algorithm_version"),
        "슬라이스": None if h.get("slice_index") is None else h["slice_index"] + 1,
        "파라미터": str(h.get("params") or {}), "ROI": str(h.get("roi") or "-"), "이력 ID": h["id"],
    } for h in histories]), hide_index=True)

    pick = st.selectbox("다시 실행해 볼 이력", histories, format_func=lambda h: f"{h['executed_at'][:16]} · {h['algorithm']} · {h['id']}")
    if st.button("🔁 저장된 설정으로 다시 실행 (재현 확인)"):
        same_series = image is not None and pick.get("image_id") == image["id"]
        if pick.get("slice_index") is None or not same_series:
            st.warning("지금 열린 CT 시리즈와 다른 영상의 이력입니다. 같은 시리즈를 열고 다시 시도해 주세요.")
        else:
            try:
                again, _ = rerun_history(pick, ct.volume[pick["slice_index"]])
                saved = load_result_image(STORAGE, pick["result_path"])
            except HistoryError as e:
                st.warning(str(e))
            else:
                if same_result(again, saved):
                    st.success("저장된 결과와 픽셀 하나까지 같습니다. (재현 성공)")
                else:
                    st.error("저장된 결과와 다릅니다. 알고리즘 버전이나 원본 영상이 바뀌었는지 확인해 주세요.")
                a, b = st.columns(2)
                a.image(saved, caption="저장된 결과", clamp=True, width="stretch")
                b.image(again, caption="다시 실행한 결과", clamp=True, width="stretch")
