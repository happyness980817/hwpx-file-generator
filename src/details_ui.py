"""Optional detailed editor for every existing HWPX input field."""
import copy
import streamlit as st
from pydantic import ValidationError
from .draft_schema import DocumentInput
from .models import CHANNELS, PLAN_FIELDS


def fields(target, specifications, prefix):
    cols = st.columns(2)
    revision = st.session_state.get('revision', 0)
    for i, spec in enumerate(specifications):
        name, label, *options = spec
        key = f'detail_{revision}_{prefix}_{name}'
        with cols[i % 2]:
            value = target.get(name, '')
            if options:
                choices = [''] + options[0]
                target[name] = st.selectbox(label, choices, index=choices.index(value) if value in choices else 0, format_func=lambda x: x or '확인 필요', key=key)
            else:
                target[name] = st.text_input(label, value=value, max_chars=80 if name == 'nameKo' and prefix == 'company' else 500, key=key)


def render_details(data, on_save):
    st.caption('자료에서 추출한 내용을 직접 보완할 수 있습니다. 모르는 항목은 빈칸으로 남겨 주세요.')
    working = copy.deepcopy(data)
    with st.form('details_form'):
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
        with st.expander('활용계획서 문안', expanded=False):
            plan = working['plan']
            revision = st.session_state.get('revision', 0)
            plan['channels'] = st.multiselect('활용채널', CHANNELS, default=plan['channels'], key=f'detail_{revision}_channels')
            history = ['', '없음', '있음']
            plan['ipHistory'] = st.selectbox('선행 IP 침해·카피 분쟁 이력', history, index=history.index(plan['ipHistory']), format_func=lambda x: x or '확인 필요', key=f'detail_{revision}_history')
            for name, label in PLAN_FIELDS.items():
                plan[name] = st.text_area(label, value=plan[name], max_chars=1800, height=130, key=f'detail_{revision}_plan_{name}')
        submitted = st.form_submit_button('수정 내용 적용', type='primary', width='stretch')
    if submitted:
        try:
            checked = DocumentInput.model_validate(working).model_dump()
        except (ValidationError, ValueError):
            st.error('날짜 형식(YYYY-MM-DD)과 입력 길이를 확인해 주세요.')
        else:
            on_save(checked)
            st.rerun()
