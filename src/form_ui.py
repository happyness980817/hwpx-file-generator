"""Customer application fields. Examples are hints, never submitted values."""
import hashlib
import re
from datetime import date

import streamlit as st

from .form_examples import CERTIFICATIONS, FIELD_PLACEHOLDERS, PLAN_PLACEHOLDERS
from .models import (
    CHANNELS, COUNTRIES, MAX_PRODUCTS, PLAN_FIELDS, QUANTITIES, TRADEMARK_STATUSES,
    apply_form_defaults, empty_country, empty_product,
)

PHONE_PREFIXES = ['010', '011', '016', '017', '018', '019', '02', '031', '032', '033',
                  '041', '042', '043', '044', '051', '052', '053', '054', '055',
                  '061', '062', '063', '064', '070', '0502', '0503', '0504', '0505', '0506', '0507']


def split_phone(value: str) -> tuple[str, str, str]:
    """Split familiar Korean numbers and preserve unrecognised prefixes."""
    value = value.strip()
    if not value:
        return '010', '', ''
    parts = value.split('-')
    if len(parts) == 3:
        return tuple(part.strip() for part in parts)
    digits = re.sub(r'\D', '', value)
    for prefix in sorted(PHONE_PREFIXES, key=len, reverse=True):
        if digits.startswith(prefix) and len(digits) - len(prefix) in (7, 8):
            return prefix, digits[len(prefix):-4], digits[-4:]
    if len(digits) > 8:
        return digits[:-8], digits[-8:-4], digits[-4:]
    return '010', value, ''


def join_phone(prefix: str, middle: str, last: str) -> str:
    if not middle.strip() and not last.strip():
        return ''
    return '-'.join((prefix.strip(), middle.strip(), last.strip()))


def render_fields(data, revision):
    working = apply_form_defaults(data)
    missing = []

    def field(target, name, label, prefix, choices=None, long=False, required=False,
              placeholder=None, allow_blank=True, format_func=None):
        key = f'edit_{revision}_{prefix}_{name}'
        value = target.get(name, '')
        shown_label = label + ' :red[*]' if required else label
        if choices is not None:
            options = ([''] if allow_blank else []) + list(choices)
            if value not in options:
                options.append(value)
            target[name] = st.selectbox(shown_label, options, index=options.index(value),
                format_func=format_func or (lambda item: item or '선택'), key=key)
        else:
            group = ('country' if '_country' in prefix else 'variant' if '_variant' in prefix
                     else 'product' if prefix.startswith('product') else prefix)
            hint = placeholder or FIELD_PLACEHOLDERS.get(f'{group}.{name}', '')
            if long:
                target[name] = st.text_area(shown_label, value=value, height=140,
                    max_chars=1800, placeholder=hint, key=key)
            else:
                target[name] = st.text_input(shown_label, value=value, placeholder=hint,
                    max_chars=80 if name == 'nameKo' and prefix == 'company' else 500, key=key)
        if not target[name].strip():
            missing.append(key)

    def grid(target, specs, prefix, count=2, required=False):
        cols = st.columns(count)
        for i, spec in enumerate(specs):
            with cols[i % count]:
                field(target, spec[0], spec[1], prefix,
                      spec[2] if len(spec) > 2 else None, required=required)

    def phone(target, prefix, required=False):
        label = '연락처' if prefix == 'contact' else '부서장 연락처'
        st.markdown(label + (' :red[*]' if required else ''))
        first, middle, last = split_phone(target.get('phone', ''))
        options = PHONE_PREFIXES + ([first] if first not in PHONE_PREFIXES else [])
        cols = st.columns([1.1, .12, 1, .12, 1], vertical_alignment='center')
        base = f'edit_{revision}_{prefix}_phone'
        with cols[0]:
            first = st.selectbox(f'{label} 앞자리', options, index=options.index(first),
                label_visibility='collapsed', key=f'{base}_prefix')
        cols[1].markdown('−')
        with cols[2]:
            middle = st.text_input(f'{label} 가운데 자리', value=middle,
                placeholder='1234', max_chars=max(4, len(middle)),
                label_visibility='collapsed', key=f'{base}_middle')
        cols[3].markdown('−')
        with cols[4]:
            last = st.text_input(f'{label} 끝자리', value=last,
                placeholder='5678', max_chars=max(4, len(last)),
                label_visibility='collapsed', key=f'{base}_last')
        target['phone'] = join_phone(first, middle, last)
        if not middle.strip():
            missing.append(f'{base}_middle')
        if not last.strip():
            missing.append(f'{base}_last')

    with st.container(border=True, key='company_card'):
        st.subheader('회사 정보', anchor=False)
        grid(working['company'], [('nameKo', '회사명'), ('representative', '대표자'),
             ('registrationNumber', '사업자등록번호'), ('address', '주소')], 'company', required=True)
        cols = st.columns(2)
        with cols[0]:
            field(working['contact'], 'name', '담당자', 'contact', required=True)
            phone(working['contact'], 'contact', required=True)
        with cols[1]:
            field(working['contact'], 'email', '이메일', 'contact', required=True)
            supplied = working['applicationDate']
            selected = st.date_input('신청일', value=date.fromisoformat(supplied),
                                    format='YYYY-MM-DD', key=f'edit_{revision}_application_date')
            working['applicationDate'] = selected.isoformat() if selected else ''
        field(working, 'projectType', '사용방식', 'application', ['라벨', '맞춤제작'],
              allow_blank=False, format_func=lambda item: '라벨 (권장)' if item == '라벨' else item)
        with st.expander('회사 추가 정보'):
            grid(working['company'], [('nameEn', '영문 회사명'), ('department', '담당부서'),
                 ('category', '기업구분', ['중소기업', '중견기업', '대기업'])], 'company')
            grid(working['manager'], [('name', '부서장'), ('email', '부서장 이메일')], 'manager')
            phone(working['manager'], 'manager')

    remove = None
    for index, product in enumerate(working['products']):
        prefix = f'product{index}'
        with st.container(border=True, key=f'product_card_{index}'):
            title, action = st.columns([5, 1])
            title.subheader(f'상품 {index + 1}', anchor=False)
            if len(working['products']) > 1 and action.button('삭제', key=f'remove_product_{index}', width='stretch'):
                remove = index
            grid(product, [('brandKo', '브랜드명'), ('nameKo', '대상제품')], prefix, required=True)
            countries, scale = st.columns([3, 2])
            rows = {row['country']: row for row in product.get('countries', []) if row.get('country')}
            key = f'edit_{revision}_{prefix}_countries'
            with countries:
                options = sorted(set(COUNTRIES + list(rows)))
                selected = st.multiselect('수출국가 :red[*]', options, default=list(rows),
                    placeholder='국가 선택 (복수 선택 가능)', key=key)
                product['countries'] = [rows.get(country, empty_country(country)) for country in selected]
                if not selected:
                    missing.append(key)
            with scale:
                field(product, 'exportScale', '수출(예상) 규모', prefix)

            cols = st.columns(2)
            with cols[0]:
                supplied = [item.strip() for item in re.split(r'[,;\n]', product.get('certifications', '')) if item.strip()]
                certifications = st.multiselect('보유 인증', list(dict.fromkeys(CERTIFICATIONS + supplied)),
                    default=supplied, accept_new_options=True, placeholder='인증 선택 또는 직접 입력',
                    key=f'edit_{revision}_{prefix}_certifications')
                product['certifications'] = ', '.join(certifications)
                if certifications:
                    product['certificationHeld'] = '유'
            with cols[1]:
                field(product, 'trademarks', '상표 현황', prefix, TRADEMARK_STATUSES)

            for row in product['countries']:
                country_id = hashlib.sha256(row['country'].encode('utf-8')).hexdigest()[:12]
                country_prefix = f'{prefix}_country{country_id}'
                st.markdown(f'**{row["country"]}**')
                cols = st.columns(2)
                with cols[0]:
                    field(row, 'trademarkStatus', '브랜드 상표 현황', country_prefix, TRADEMARK_STATUSES)
                    field(row, 'trademarkNumberOrReason', '상표번호 / 미출원 사유', country_prefix)
                with cols[1]:
                    field(row, 'quantity', '부착 예정수량', country_prefix, QUANTITIES, allow_blank=False)
                    field(row, 'method', '사용방식', country_prefix, ['라벨', '맞춤제작'], allow_blank=False,
                        format_func=lambda item: '라벨 (권장)' if item == '라벨' else item)
            if product['countries']:
                st.caption('부착 예정수량은 100만장을 권장합니다. 바우처 지원 여부와 비율은 해당 사업 공고에 따라 달라집니다.')

            with st.expander('상품 추가 정보'):
                grid(product, [('brandEn', '영문 브랜드명'), ('nameEn', '영문 상품명'), ('category', '상품분류'),
                    ('certificationHeld', '인증 보유 여부', ['유', '무']),
                    ('productionLocation', '생산지', ['국내생산', '해외생산', '국내/해외 병행생산']),
                    ('productionType', '생산형태', ['자체생산', '위탁생산(OEM/ODM)', '자체/위탁 병행생산'])], prefix)
                existing_variants = product.get('variants') or []
                variants = existing_variants or [{'name': '', 'specification': ''}]
                for vi, variant in enumerate(variants):
                    grid(variant, [('name', f'세부 제품명 {vi + 1}'), ('specification', '사양')], f'{prefix}_variant{vi}')
                product['variants'] = variants if existing_variants or any(any(v.values()) for v in variants) else []
                if st.button('세부 제품 추가', key=f'add_variant_{index}', disabled=len(variants) >= 50):
                    product['variants'] = variants + [{'name': '', 'specification': ''}]
                    return working, True
                existing_factories = product.get('factories') or []
                factories = existing_factories or [{}]
                for fi, factory in enumerate(factories):
                    grid(factory, [('country', f'공장 {fi + 1} 제조국'),
                        ('productionType', '공장 생산형태', ['자체생산', '위탁생산(OEM/ODM)', '자체/위탁 병행생산'])], f'{prefix}_factory{fi}')
                product['factories'] = factories if existing_factories or any(any(f.values()) for f in factories) else []
                if st.button('공장 추가', key=f'add_factory_{index}', disabled=len(factories) >= 4):
                    product['factories'] = factories + [{}]
                    return working, True
            if product['certifications']:
                product['certificationHeld'] = '유'

    if remove is not None:
        working['products'].pop(remove)
        return working, True
    if st.button('상품 추가', icon=':material/add:', width='stretch', disabled=len(working['products']) >= MAX_PRODUCTS):
        working['products'].append(empty_product())
        return working, True

    with st.expander('활용계획서 내용'):
        plan = working['plan']
        key = f'edit_{revision}_plan_channels'
        plan['channels'] = st.multiselect('활용채널', CHANNELS, default=plan['channels'],
            placeholder='채널 선택 (복수 선택 가능)', key=key)
        if not plan['channels']:
            missing.append(key)
        field(plan, 'ipHistory', '분쟁 이력', 'plan', ['없음', '있음'])
        for name, label in PLAN_FIELDS.items():
            field(plan, name, label, 'plan', long=True, placeholder=PLAN_PLACEHOLDERS.get(name, ''))

    css = '\n'.join(f'.st-key-{key} input,.st-key-{key} textarea,.st-key-{key} [data-baseweb="select"]>div {{background-color:#fff8dc!important;}}' for key in missing)
    css += '\ninput::placeholder,textarea::placeholder{color:#a1a1a6!important;opacity:1;} input:focus::placeholder,textarea:focus::placeholder{color:transparent!important;}'
    st.markdown('<style>' + css + '</style>', unsafe_allow_html=True)
    return working, False
