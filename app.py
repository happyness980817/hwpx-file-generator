from __future__ import annotations

import copy
import json

import streamlit as st

from src.auth_ui import require_login
from src.ai import ai_ready, draft_with_ai
from src.errors import DocumentError
from src.models import CHANNELS, PLAN_FIELDS, empty_data, example_plan, fingerprint, sample_data
from src.service import generate_documents

st.set_page_config(page_title="K-브랜드 문서 작업실", page_icon="📄", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1140px; padding-top: 2.5rem; padding-bottom: 4rem;}
h1 {letter-spacing: -.05em;} h2,h3 {letter-spacing: -.025em;}
[data-testid="stSidebar"] {border-right: 1px solid #e3e7e2;}
.eyebrow {font-size: .8rem; font-weight: 700; letter-spacing: .13em; color: #3d7463; margin-bottom: .6rem;}
</style>""", unsafe_allow_html=True)

require_login()

STEPS = ["1 · 고객 정보", "2 · 문안 검토", "3 · 파일 다운로드"]
if "data" not in st.session_state:
    st.session_state.data = empty_data()
    st.session_state.notes = ""
    st.session_state.request = ""
if "pending_step" in st.session_state:
    st.session_state.step = st.session_state.pop("pending_step")


def reset(sample=False):
    data = sample_data() if sample else empty_data()
    st.session_state.pop("result", None)
    st.session_state.data = data
    # Explicitly replace widget values: deleting keys alone can restore stale browser values.
    for group in ("company", "contact", "manager", "provider"):
        for name, value in data[group].items():
            st.session_state[f"field_{group}_{name}"] = value
    for name in ("projectType", "applicationDate"):
        st.session_state[f"field_application_{name}"] = data[name]
    product = data["products"][0]
    for name, value in product.items():
        if name not in ("countries", "factories"):
            st.session_state[f"field_product_{name}"] = value
    for group, prefix, count, names in [("countries", "country", 3, ("country", "trademarkStatus", "trademarkNumberOrReason", "quantity", "method")), ("factories", "factory", 4, ("country", "productionType"))]:
        for i in range(count):
            row = product[group][i] if i < len(product[group]) else {}
            for name in names:
                st.session_state[f"field_{prefix}{i}_{name}"] = row.get(name, "")
    for name, value in data["plan"].items():
        st.session_state[f"plan_{name}"] = value
    st.session_state.ai_consent = False
    st.session_state.note_input = ""
    st.session_state.request_input = ""
    st.session_state.notes = ""
    st.session_state.request = ""
    st.session_state.step = STEPS[0]


def navigate(step):
    st.session_state.pending_step = step
    st.rerun()


def invalidate():
    st.session_state.pop("result", None)


with st.sidebar:
    st.markdown("### K-BRAND\n문서 작업실")
    st.caption("국가인증상표 신청 서류")
    st.divider()
    step = st.radio("작성 단계", STEPS, key="step", label_visibility="collapsed")
    st.divider()
    st.button("가상 고객 자료로 시작", on_click=reset, args=(True,), width="stretch")
    st.caption("테스트용 가상 자료로 현재 입력을 교체합니다.")
    st.button("입력 초기화", on_click=reset, width="stretch")
    st.divider()
    st.caption("로그인 연결됨 · 고객 DB·Storage 미연결")
    st.caption("입력은 현재 브라우저 세션에서 유지됩니다. 생성 파일은 이 PC의 result 폴더에 저장됩니다.")

st.markdown('<div class="eyebrow">K-BRAND / DOCUMENT STUDIO</div>', unsafe_allow_html=True)
st.title("고객 자료를 신청 서류로")
st.caption("고객 정보를 정리하고 문안을 검토한 뒤, 두 가지 한글 문서를 내려받으세요.")
st.progress((STEPS.index(step) + 1) / 3)
st.info("제품 1개 · 사용국가 최대 3개 · 공장 최대 4개를 지원합니다. 생성 파일은 검토용이며 사진과 서명은 한글에서 추가해 주세요.")


def fields(target, specifications, prefix):
    cols = st.columns(2)
    for i, spec in enumerate(specifications):
        name, label, *options = spec
        with cols[i % 2]:
            value = target.get(name, "")
            if options:
                choices = [""] + options[0]
                target[name] = st.selectbox(label, choices, index=choices.index(value) if value in choices else 0, format_func=lambda x: x or "미확인 / 선택 안 함", key=f"field_{prefix}_{name}")
            else:
                target[name] = st.text_input(label, value=value, max_chars=80 if name == "nameKo" and prefix == "company" else 500, key=f"field_{prefix}_{name}")


if step == STEPS[0]:
    st.subheader("01. 고객 기본정보")
    st.caption("회사명은 필수입니다. 모르는 항목은 비워두시면 문서에 ‘확인 필요’로 표시됩니다. 입력 후 아래 저장 버튼을 눌러 주세요.")
    working = copy.deepcopy(st.session_state.data)
    with st.form("customer_form"):
        with st.expander("회사·담당자", expanded=True):
            fields(working["company"], [("nameKo", "회사명 *"), ("nameEn", "영문 회사명"), ("registrationNumber", "사업자등록번호"), ("representative", "대표자"), ("address", "주소"), ("department", "담당부서"), ("category", "기업구분", ["중소기업", "중견기업", "대기업"])], "company")
            st.markdown("**실무 담당자**")
            fields(working["contact"], [("name", "담당자 이름"), ("phone", "담당자 연락처"), ("email", "담당자 이메일")], "contact")
            st.markdown("**부서장**")
            fields(working["manager"], [("name", "부서장 이름"), ("phone", "부서장 연락처"), ("email", "부서장 이메일")], "manager")
        with st.expander("신청 정보·수행업체"):
            fields(working, [("projectType", "사업과제", ["라벨", "맞춤제작"]), ("applicationDate", "신청일 (YYYY-MM-DD, 선택)")], "application")
            fields(working["provider"], [("name", "희망 수행업체"), ("contact", "수행업체 담당자"), ("phone", "수행업체 연락처")], "provider")
        product = working["products"][0]
        with st.expander("상품·생산 정보"):
            fields(product, [("brandKo", "브랜드명"), ("brandEn", "영문 브랜드명"), ("nameKo", "상품명"), ("nameEn", "영문 상품명"), ("category", "상품분류"), ("exportScale", "수출규모 (단위·기간 포함)"), ("certificationHeld", "인증 보유 여부", ["유", "무"]), ("certifications", "보유 인증 상세"), ("trademarks", "상표 현황"), ("productionLocation", "생산지", ["국내생산", "해외생산", "국내/해외 병행생산"]), ("productionType", "생산형태", ["자체생산", "위탁생산(OEM/ODM)", "자체/위탁 병행생산"])], "product")
            factories = []
            for i in range(4):
                st.caption(f"공장 {i+1} · 해당하는 행만 입력")
                row = copy.deepcopy(product["factories"][i]) if i < len(product["factories"]) else {}
                fields(row, [("country", "제조국"), ("productionType", "공장 생산형태", ["자체생산", "위탁생산(OEM/ODM)", "자체/위탁 병행생산"])], f"factory{i}")
                if any(row.values()):
                    factories.append(row)
            product["factories"] = factories
        with st.expander("사용국가·상표 정보"):
            countries = []
            for i in range(3):
                st.markdown(f"**사용국가 {i+1}**")
                row = copy.deepcopy(product["countries"][i]) if i < len(product["countries"]) else {}
                fields(row, [("country", "사용국가"), ("trademarkStatus", "상표 상태", ["등록완료", "출원중", "미출원"]), ("trademarkNumberOrReason", "상표번호 / 미출원 사유"), ("quantity", "부착 예정수량"), ("method", "사용방식", ["라벨", "맞춤제작"])], f"country{i}")
                if any(row.values()):
                    countries.append(row)
            product["countries"] = countries
        notes = st.text_area("고객사 추가 자료", value=st.session_state.notes, key="note_input", height=120, max_chars=12000, placeholder="제품 특성, 판매채널, 고객이 확인해 준 사실 등을 붙여 넣으세요.")
        request = st.text_area("문안 작성 요청사항", value=st.session_state.request, key="request_input", height=90, max_chars=2000, placeholder="예: 일본 온라인몰 진출 계획을 중심으로 작성해 주세요.")
        saved = st.form_submit_button("고객 정보 저장 → 문안 검토", type="primary", width="stretch")
    if saved:
        if not working["company"]["nameKo"].strip():
            st.error("회사명을 입력해 주세요.")
        else:
            from datetime import date
            try:
                if working["applicationDate"]:
                    if date.fromisoformat(working["applicationDate"]).isoformat() != working["applicationDate"]:
                        raise ValueError()
            except ValueError:
                st.error("신청일은 실제 날짜를 YYYY-MM-DD 형식으로 입력해 주세요.")
            else:
                st.session_state.data = working
                st.session_state.notes, st.session_state.request = notes, request
                invalidate()
                navigate(STEPS[1])

elif step == STEPS[1]:
    st.subheader("02. 문안 검토·수정")
    st.caption("직접 작성하거나 테스트 예시 문안을 불러오세요. AI 작성은 API 키와 모델을 설정한 경우에만 사용할 수 있습니다.")
    ready = ai_ready()
    if not ready:
        st.caption("AI 미연결 · 직접 입력과 파일 생성은 정상 사용할 수 있습니다.")
    consent = st.checkbox("입력한 회사·제품 자료와 추가 자료를 OpenAI로 전송하여 문안을 작성합니다.", key="ai_consent", disabled=not ready)
    a, b = st.columns(2)
    if a.button("테스트 예시 문안 넣기", width="stretch"):
        examples = example_plan(st.session_state.data)
        st.session_state.data["plan"].update(examples)
        for name, value in examples.items():
            st.session_state[f"plan_{name}"] = value
        invalidate()
    if b.button("AI로 문안 작성", disabled=not (ready and consent and st.session_state.data["company"]["nameKo"].strip()), width="stretch"):
        try:
            with st.spinner("고객 자료를 바탕으로 문안을 작성하고 있습니다…"):
                generated = draft_with_ai(st.session_state.data, st.session_state.notes, st.session_state.request)
            st.session_state.data["plan"].update(generated)
            for name, value in generated.items():
                st.session_state[f"plan_{name}"] = value
            invalidate()
            st.success("초안을 작성했습니다. 사실과 계획을 확인한 뒤 저장해 주세요.")
        except DocumentError as exc:
            st.error(str(exc))
    st.caption("위 작성 버튼을 누르면 현재 문안을 교체합니다. 활용채널과 분쟁 이력은 아래에서 직접 확인해 주세요.")
    plan = copy.deepcopy(st.session_state.data["plan"])
    with st.form("plan_form"):
        plan["channels"] = st.multiselect("활용채널", CHANNELS, default=plan["channels"], key="plan_channels")
        history = ["", "없음", "있음"]
        plan["ipHistory"] = st.selectbox("선행 IP 침해·카피 분쟁 이력", history, index=history.index(plan["ipHistory"]), format_func=lambda x: x or "미확인", key="plan_ipHistory")
        for name, label in PLAN_FIELDS.items():
            plan[name] = st.text_area(label, value=plan[name], key=f"plan_{name}", height=130, max_chars=1800)
        saved = st.form_submit_button("문안 저장 → 파일 다운로드", type="primary", width="stretch")
    if saved:
        st.session_state.data["plan"] = plan
        invalidate()
        navigate(STEPS[2])

else:
    st.subheader("03. 한글파일 생성·다운로드")
    data = st.session_state.data
    a, b, c = st.columns(3)
    a.caption("고객사")
    a.write(data["company"]["nameKo"] or "미입력")
    b.caption("상품")
    b.write(data["products"][0]["nameKo"] or "미입력")
    c.caption("생성 문서")
    c.write("2개")
    st.caption("사용신청서 + 도입 필요성 및 활용계획서 · 저장한 입력값을 기준으로 생성합니다.")
    with st.expander("저장한 문안 확인"):
        for name, label in PLAN_FIELDS.items():
            st.markdown(f"**{label}**")
            st.text(data["plan"][name] or "확인 필요")
    if st.button("HWPX 파일 두 개 생성", type="primary", disabled=not data["company"]["nameKo"].strip(), width="stretch"):
        try:
            with st.spinner("원본 양식에 내용을 채우고 파일 구조를 검증하고 있습니다…"):
                st.session_state.result = generate_documents(data)
        except (DocumentError, OSError) as exc:
            st.error(str(exc) if isinstance(exc, DocumentError) else "결과 파일을 저장하지 못했습니다. 로컬 폴더 권한과 디스크 공간을 확인해 주세요.")
    result = st.session_state.get("result")
    if result and result["fingerprint"] == fingerprint(data):
        st.success("한글파일 두 개를 생성했습니다. 아래에서 내려받으실 수 있습니다.")
        st.download_button("두 문서 ZIP으로 다운로드", result["zip"], "K-브랜드_검토용_2종.zip", "application/zip", type="primary", width="stretch", on_click="ignore")
        cols = st.columns(2)
        for col, item in zip(cols, result["files"]):
            col.download_button(item["name"], item["bytes"], item["name"], "application/octet-stream", width="stretch", on_click="ignore")
        warnings = list(dict.fromkeys(w for f in result["report"]["files"] for w in f["warnings"]))
        with st.expander(f"제출 전 확인사항 {len(warnings)}개", expanded=True):
            for warning in warnings:
                st.write("• " + warning)
            st.write("• 실제 한글 프로그램에서 표와 쪽 배치를 확인해 주세요.")
        with st.expander("개발용 생성 결과"):
            st.code(result["folder"], language=None)
            st.json(result["report"])
    st.divider()
    st.download_button("저장한 입력 JSON 내려받기", json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "input.json", "application/json", on_click="ignore")
