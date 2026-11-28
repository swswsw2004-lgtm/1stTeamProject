"""
케이스 등록·목록 + 영상 등록 화면
담당: 역할2
위치: pages/1_cases.py
필요: 역할1의 core/auth.py, core/firebase.py / secrets.toml의 storage_dir
"""
from datetime import date

import pandas as pd
import streamlit as st

from core.auth import require_login
from core.cases import (
    CAN_CREATE_ROLES,
    EXAM_TYPES,
    FirestoreCaseStore,
    create_case,
    filter_cases,
    list_cases,
    suggest_next_case_id,
    validate_filters,
)
from core.dicom_io import DicomLoadError, find_series
from core.firebase import get_db
from core.images import (
    FirestoreImageStore,
    filter_images,
    inspect_files,
    list_images,
    read_folder_files,
    register_group,
    summarize_by_case,
    summary_label,
)

st.set_page_config(page_title="케이스", page_icon="🗂️", layout="wide")
user = require_login()

STATUS_LABELS = {"received": "접수", "assigned": "배정", "in_review": "검토 중",
                 "completed": "완료", "re_review": "재검토"}


@st.cache_data(ttl=60, show_spinner=False)
def load_cases() -> list[dict]:
    """화면이 다시 그려질 때마다 DB를 읽지 않도록 60초 캐시 (무료 사용량 절약)."""
    return list_cases(FirestoreCaseStore(get_db()))


@st.cache_data(ttl=60, show_spinner=False)
def load_images(case_id: str) -> list[dict]:
    return list_images(FirestoreImageStore(get_db()), case_id)


@st.cache_data(ttl=60, show_spinner=False)
def load_image_summary() -> dict:
    """케이스별 영상 종류 개수 (목록의 '영상' 칸·영상 종류 필터용). images 전체를 한 번만 읽어 캐시."""
    return summarize_by_case(FirestoreImageStore(get_db()).list_all_images())


def clear_image_caches() -> None:
    load_images.clear()
    load_image_summary.clear()


@st.cache_data(show_spinner="데이터 폴더를 훑는 중입니다...")
def scan_folder(root: str):
    """서버 데이터 폴더의 시리즈 목록 (헤더만 읽음, 결과는 캐시)."""
    return [(s.patient_id, s.modality, s.description, s.series_uid, [str(f) for f in s.files])
            for s in find_series(root)]


def show_flash(key: str) -> None:
    """새로고침(st.rerun) 뒤에도 결과 메시지가 사라지지 않도록 session_state에 잠시 보관했다가 보여준다."""
    for ok, msg in st.session_state.pop(key, []):
        (st.success if ok else st.error)(msg)


st.title("🗂️ 케이스")
st.caption("교육용 모의 케이스 · 데이터 출처: TCIA Soft-tissue-Sarcoma (CC BY 3.0)")

cases = load_cases()

# ── 등록 폼: 등록 권한이 있는 역할에게만 보여준다 (저장 직전에도 create_case가 다시 검사함) ──
if user.get("role") in CAN_CREATE_ROLES:
    with st.expander("➕ 새 케이스 등록", expanded=not cases):
        with st.form("case_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            case_id = c1.text_input(
                "케이스 ID", value=suggest_next_case_id([c.get("case_id") for c in cases]),
                help="영문 대문자·숫자·-·_ 3~30자 (예: CASE-001)")
            patient_id = c2.text_input("환자 ID (공개 데이터)", placeholder="STS_001")
            c3, c4 = st.columns(2)
            exam_type = c3.selectbox("검사 구분", EXAM_TYPES)
            exam_date = c4.date_input("검사일", value=date.today(), max_value=date.today())
            description = st.text_area("설명 (선택)", max_chars=500)
            submitted = st.form_submit_button("등록", type="primary")

        if submitted:
            ok, msg = create_case(FirestoreCaseStore(get_db()), user, case_id, patient_id,
                                  exam_type, exam_date, description)
            if ok:
                load_cases.clear()      # 목록을 새로 읽도록 캐시 비우기
                st.session_state["flash_case"] = [(True, msg)]
                st.rerun()
            else:
                st.error(msg)
        show_flash("flash_case")
else:
    st.info("케이스 등록은 등록 담당자·관리자만 할 수 있습니다. 아래에서 목록을 볼 수 있습니다.")

# ── 검색·필터 (11/27) ──
image_summary = load_image_summary()
st.subheader("케이스 목록")
with st.container(border=True):
    keyword = st.text_input("🔍 검색", placeholder="케이스 ID·환자 ID·설명 (여러 단어는 모두 포함)")
    f1, f2, f3 = st.columns(3)
    statuses = f1.multiselect("상태", list(STATUS_LABELS), format_func=STATUS_LABELS.get)
    exam_types = f2.multiselect("검사 구분", EXAM_TYPES)
    modalities = f3.multiselect("영상 종류 (모두 가진 케이스)", ["CT", "PT", "RTSTRUCT", "OT"],
                                format_func=lambda m: {"OT": "PNG·JPEG"}.get(m, m))
    use_dates = st.checkbox("검사일로 거르기")
    date_from = date_to = None
    if use_dates:
        d1, d2 = st.columns(2)
        date_from = d1.date_input("시작일", value=date(2026, 1, 1))
        date_to = d2.date_input("종료일", value=date.today())

filter_errors = validate_filters(date_from, date_to)
if filter_errors:
    for e in filter_errors:
        st.error(e)
    shown = []
else:
    shown = filter_cases(cases, keyword, statuses, exam_types, date_from, date_to,
                         modalities, image_summary)

st.caption(f"{len(shown)}건 표시 / 전체 {len(cases)}건")
if not cases:
    st.write("등록된 케이스가 없습니다.")
elif not shown:
    st.write("조건에 맞는 케이스가 없습니다. 검색어나 필터를 바꿔 보세요.")
else:
    table = pd.DataFrame([{
        "케이스 ID": c.get("case_id"),
        "환자 ID": c.get("patient_id"),
        "검사 구분": c.get("exam_type"),
        "검사일": c.get("exam_date"),
        "상태": STATUS_LABELS.get(c.get("status"), c.get("status")),
        "영상": summary_label(image_summary.get(c.get("case_id"), {})),
        "등록일": (c.get("registered_at") or "")[:10],
        "설명": c.get("description"),
    } for c in shown])
    st.dataframe(table, hide_index=True, use_container_width=True)

if st.button("🔄 새로고침"):
    load_cases.clear()
    clear_image_caches()
    st.rerun()


# ═════════════════════════════════════════════
# 영상 등록 (11/25 작업: 형식 검사 · 원본 보존 저장 · images 기록)
# ═════════════════════════════════════════════
def save_groups(case: dict, files: list[tuple[str, bytes]]) -> None:
    """검사 → (전부 통과 시) 시리즈별 저장. 하나라도 잘못되면 아무것도 저장하지 않는다."""
    check = inspect_files(files, case)
    if check.errors:
        st.error("등록하지 않았습니다. 아래 문제를 해결한 뒤 다시 시도해 주세요.")
        for e in check.errors[:20]:
            st.write(f"- {e}")
        if len(check.errors) > 20:
            st.write(f"- … 외 {len(check.errors) - 20}건")
        return
    storage_root = st.secrets.get("storage_dir", "./data/storage")
    store = FirestoreImageStore(get_db())
    results = [register_group(store, storage_root, user, case, group) for group in check.groups]
    clear_image_caches()
    st.session_state["flash_images"] = results     # 새로고침 후 위쪽 목록과 함께 결과 표시
    st.rerun()


st.divider()
st.subheader("🩻 케이스별 영상")
if not cases:
    st.write("먼저 케이스를 등록해 주세요.")
    st.stop()

# 위에서 거른 케이스가 있으면 그 안에서 고른다 (없으면 전체)
# 다른 경로(테스트 스크립트 등)로 만들어져 일부 필드가 빠진 케이스도 있을 수 있으므로 .get()으로 읽는다
pick_from = shown or cases
by_id = {c.get("case_id") or c.get("id"): c for c in pick_from if c.get("case_id") or c.get("id")}
selected_id = st.selectbox(
    "케이스 선택", list(by_id),
    format_func=lambda cid: f"{cid} · {by_id[cid].get('patient_id') or '환자 ID 없음'} · "
                            f"{by_id[cid].get('exam_type') or '검사 구분 없음'}")
case = dict(by_id[selected_id], case_id=selected_id)

images = load_images(selected_id)
show_flash("flash_images")
if images:
    i1, i2 = st.columns([1, 2])
    img_mods = i1.multiselect("영상 종류", sorted({d.get("modality") for d in images if d.get("modality")}),
                              key="img_mods")
    img_kw = i2.text_input("시리즈 이름 검색", key="img_kw", placeholder="예: PET, RTstruct")
    shown_images = filter_images(images, img_mods, img_kw)
    st.caption(f"영상 {len(shown_images)}건 표시 / 이 케이스 전체 {len(images)}건")
if images:
    st.dataframe(pd.DataFrame([{
        "종류": d.get("modality"),
        "형식": d.get("format"),
        "시리즈": d.get("series_description"),
        "장수": d.get("num_files"),
        "크기(MB)": round((d.get("size_bytes") or 0) / 1e6, 1),
        "픽셀 간격(mm)": d.get("pixel_spacing_mm"),
        "슬라이스 간격(mm)": d.get("slice_spacing_mm"),
        "저장 위치": d.get("file_path"),
        "등록일": (d.get("uploaded_at") or "")[:10],
    } for d in shown_images]), hide_index=True, use_container_width=True)
else:
    st.info("이 케이스에 등록된 영상이 없습니다. 영상이 1개 이상 있어야 관리자가 검토 담당자를 배정할 수 있습니다.")

if user.get("role") not in CAN_CREATE_ROLES:
    st.stop()

tab_upload, tab_folder = st.tabs(["📤 파일 올리기", "📁 서버 데이터 폴더에서 가져오기"])

with tab_upload:
    st.caption("DICOM(CT·PT·RTSTRUCT, 한 시리즈의 여러 장을 함께 선택), PNG, JPEG · "
               "원본은 그대로 보존하고, 잘못된 파일이 하나라도 있으면 아무것도 등록하지 않습니다.")
    with st.form("upload_form", clear_on_submit=True):
        uploaded = st.file_uploader("파일 선택", accept_multiple_files=True)
        go = st.form_submit_button("검사 후 등록", type="primary")
    if go:
        with st.spinner("파일을 검사하고 저장하는 중입니다..."):
            save_groups(case, [(f.name, f.getvalue()) for f in uploaded or []])

with tab_folder:
    st.caption("시연용: data/README.md 방법으로 받아 둔 폴더에서 이 케이스 환자의 시리즈를 골라 등록합니다 "
               "(원본 폴더는 읽기만 하고, 저장소에 복사본을 만듭니다).")
    root = st.text_input("데이터 폴더", value="data/sts")
    patient_id = case.get("patient_id")
    series = []
    if not patient_id:
        st.warning("이 케이스에는 환자 ID가 없어 서버 폴더에서 시리즈를 찾을 수 없습니다. "
                   "환자 ID가 있는 케이스를 선택하거나 새로 등록해 주세요.")
    else:
        try:
            series = [s for s in scan_folder(root)
                      if s[0] == patient_id and s[1] in ("CT", "PT", "RTSTRUCT")]
        except DicomLoadError as e:
            st.warning(str(e))
        if not series:
            st.write(f"이 폴더에서 환자 {patient_id}의 CT·PT·RTSTRUCT 시리즈를 찾지 못했습니다.")
    if series:
        done = {d.get("series_uid") for d in images}
        choices = {f"{m} · {desc} · {len(files)}장" + (" (등록됨)" if uid in done else ""): files
                   for _, m, desc, uid, files in series}
        picked = st.multiselect("등록할 시리즈", list(choices),
                                default=[k for k in choices if not k.endswith("(등록됨)")])
        if st.button("선택한 시리즈 등록", type="primary", disabled=not picked):
            with st.spinner("시리즈를 읽고 저장하는 중입니다 (CT 267장은 몇십 초 걸릴 수 있어요)..."):
                files = [f for k in picked for f in read_folder_files(choices[k])]
                save_groups(case, files)
