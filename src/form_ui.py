"""Inline application fields, with yellow cues for missing values."""
import copy
import hashlib
from datetime import date
import streamlit as st
from .models import COUNTRIES, MAX_PRODUCTS, PLAN_FIELDS, CHANNELS, empty_product


def render_fields(data, revision):
    working = copy.deepcopy(data)
    missing = []

    def field(target, name, label, prefix, choices=None, long=False):
        key = f'edit_{revision}_{prefix}_{name}'
        value = target.get(name, '')
        if choices is not None:
            options = [''] + list(choices)
            if value and value not in options:
                options.append(value)
            target[name] = st.selectbox(label, options, index=options.index(value),
                                        format_func=lambda x: x or '선택', key=key)
        elif long:
            target[name] = st.text_area(label, value=value, height=110, max_chars=1800, key=key)
        else:
            target[name] = st.text_input(label, value=value, max_chars=80 if name == 'nameKo' and prefix == 'company' else 500, key=key)
        if not target[name].strip():
            missing.append(key)

    def grid(target, specs, prefix, count=2):
        cols=st.columns(count)
        for i, spec in enumerate(specs):
            with cols[i % count]:
                field(target, spec[0], spec[1], prefix, spec[2] if len(spec)>2 else None)

    with st.container(border=True):
        st.subheader('회사 정보', anchor=False)
        grid(working['company'], [('nameKo','회사명'),('representative','대표자'),
             ('registrationNumber','사업자등록번호'),('address','주소')], 'company')
        grid(working['contact'], [('name','담당자'),('phone','연락처'),('email','이메일')], 'contact',3)
        with st.expander('회사 추가 정보'):
            grid(working['company'], [('nameEn','영문 회사명'),('department','담당부서'),
                 ('category','기업구분',['중소기업','중견기업','대기업'])], 'company')
            grid(working['manager'], [('name','부서장'),('phone','부서장 연락처'),('email','부서장 이메일')], 'manager',3)
            grid(working, [('projectType','사업과제',['라벨','맞춤제작'])], 'application')
            grid(working['provider'], [('name','희망 수행업체'),('contact','수행업체 담당자'),('phone','수행업체 연락처')], 'provider',3)
            key=f'edit_{revision}_application_date'
            supplied=working.get('applicationDate','')
            selected=st.date_input('신청일',value=date.fromisoformat(supplied) if supplied else None,format='YYYY-MM-DD',key=key)
            working['applicationDate']=selected.isoformat() if selected else ''
            if not selected:missing.append(key)

    remove=None
    for index, product in enumerate(working['products']):
        prefix=f'product{index}'
        with st.container(border=True):
            title, action=st.columns([5,1])
            title.subheader(f'상품 {index+1}',anchor=False)
            if len(working['products'])>1 and action.button('삭제',key=f'remove_product_{index}',width='stretch'):
                remove=index
            grid(product,[('brandKo','브랜드명'),('nameKo','대상제품')],prefix)
            countries, scale=st.columns([3,2])
            rows={row['country']:row for row in product.get('countries',[]) if row.get('country')}
            key=f'edit_{revision}_{prefix}_countries'
            with countries:
                options=list(dict.fromkeys(COUNTRIES+list(rows)))
                selected=st.multiselect('수출국가',options,default=list(rows),placeholder='국가 선택 (복수 선택 가능)',key=key)
                product['countries']=[rows.get(country,{'country':country,'trademarkStatus':'','trademarkNumberOrReason':'','quantity':'','method':''}) for country in selected]
                if not selected:missing.append(key)
            with scale:
                field(product,'exportScale','수출(예상) 규모',prefix)
            with st.expander('상품 세부정보 · 인증 · 세부 제품'):
                grid(product,[('brandEn','영문 브랜드명'),('nameEn','영문 상품명'),('category','상품분류'),
                    ('certificationHeld','인증 보유 여부',['유','무']),('certifications','보유 인증'),('trademarks','상표 현황'),
                    ('productionLocation','생산지',['국내생산','해외생산','국내/해외 병행생산']),
                    ('productionType','생산형태',['자체생산','위탁생산(OEM/ODM)','자체/위탁 병행생산'])],prefix)
                st.caption('세부 제품명과 사양은 엑셀 상품리스트에 반영됩니다.')
                existing_variants=product.get('variants') or []
                variants=existing_variants or [{'name':'','specification':''}]
                for vi, variant in enumerate(variants):
                    grid(variant,[('name',f'세부 제품명 {vi+1}'),('specification','사양')],f'{prefix}_variant{vi}')
                product['variants']=variants if existing_variants or any(any(v.values()) for v in variants) else []
                if st.button('세부 제품 추가',key=f'add_variant_{index}',disabled=len(variants)>=50):
                    product['variants']=variants+[{'name':'','specification':''}]
                    return working, True
                for row in product['countries']:
                    country_id=hashlib.sha256(row['country'].encode('utf-8')).hexdigest()[:12]
                    st.markdown(f'**{row["country"]}**')
                    grid(row,[('trademarkStatus','상표 상태',['등록완료','출원중','미출원']),
                        ('trademarkNumberOrReason','상표번호 / 미출원 사유'),('quantity','부착 예정수량'),
                        ('method','사용방식',['라벨','맞춤제작'])],f'{prefix}_country{country_id}')
                with st.expander('생산공장'):
                    existing_factories=product.get('factories') or []
                    factories=existing_factories or [{}]
                    for fi, factory in enumerate(factories):
                        grid(factory,[('country',f'공장 {fi+1} 제조국'),
                            ('productionType','공장 생산형태',['자체생산','위탁생산(OEM/ODM)','자체/위탁 병행생산'])],f'{prefix}_factory{fi}')
                    product['factories']=factories if existing_factories or any(any(f.values()) for f in factories) else []
                    if st.button('공장 추가',key=f'add_factory_{index}',disabled=len(factories)>=4):
                        product['factories']=factories+[{}]
                        return working, True
    if remove is not None:
        working['products'].pop(remove)
        return working, True
    if st.button('상품 추가',icon=':material/add:',width='stretch',disabled=len(working['products'])>=MAX_PRODUCTS):
        working['products'].append(empty_product())
        return working, True
    with st.expander('활용계획서 내용'):
        plan=working['plan']
        key=f'edit_{revision}_plan_channels'
        plan['channels']=st.multiselect('활용채널',CHANNELS,default=plan['channels'],key=key)
        if not plan['channels']:missing.append(key)
        field(plan,'ipHistory','분쟁 이력','plan',['없음','있음'])
        for name,label in PLAN_FIELDS.items():
            field(plan,name,label,'plan',long=True)
    css='\n'.join(f'.st-key-{key} input,.st-key-{key} textarea,.st-key-{key} [data-baseweb="select"]>div {{background-color:#FFF2CC!important;}}' for key in missing)
    st.markdown('<style>'+css+'</style>',unsafe_allow_html=True)
    return working, False
