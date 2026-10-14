"""Fill the four pinned K-brand HWPX templates using Python's ZIP/XML libraries.

Mapped fields, repeated product/country rows and missing-field shading are edited.
Original legal text and unrelated package parts remain intact. This validates structure, not Hancom's page rendering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import uuid
from xml.dom import Node, minidom
import zipfile

from .errors import DocumentError
from .models import MAX_PRODUCTS, COUNTRIES

EXPECTED_HASH = {
    'application': '5e54216f44b393c8f5c30f8af651d663f031a4c15429582d3db8ac4bf92c5710',
    'plan': '043047b6298620a4ce96ef51d29f8631bc6e6177aea35d5c391780bdb4196b3a',
    'pledge': 'fe2a8ec9cf060bd52c5688076b24511067ea0631f1fd3733c117e3cd3f59e584',
    'intervention': '7c1fad395a0791a4bf681082ddb93720f6847f598432f0688af7e2edd89baf23',
}
TABLE_COUNTS = {'application': 5, 'plan': 3, 'pledge': 3, 'intervention': 2}
YELLOW = '#FFF2CC'


def ensure(condition, message):
    if not condition:
        raise DocumentError(message)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def children(node, name):
    return [n for n in node.childNodes if n.nodeType == Node.ELEMENT_NODE and n.tagName == name]


def descendants(node, name):
    return list(node.getElementsByTagName(name))


def text_of(node):
    if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
        return node.data
    return ''.join(text_of(n) for n in node.childNodes)


def document_text(doc):
    return '\n'.join(''.join(text_of(t) for run in children(p, 'hp:run') for t in children(run, 'hp:t')) for p in descendants(doc, 'hp:p'))


def parse(content):
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig')
    ensure(not re.search(r'<!DOCTYPE|<!ENTITY', content, re.I), 'DOCTYPE/ENTITY 문서는 지원하지 않습니다.')
    return minidom.parseString(content)


def serialize(doc):
    return doc.toxml(encoding='UTF-8')


def string_value(value, label, limit=3000):
    ensure(isinstance(value, (str, int, float)) and not isinstance(value, bool), f'{label}: 문자열 또는 숫자가 필요합니다.')
    ensure(not isinstance(value, float) or math.isfinite(value), f'{label}: 유한한 숫자가 필요합니다.')
    text = str(value).strip().replace('\r\n', '\n').replace('\r', '\n')
    ensure(not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', text), f'{label}: XML에 쓸 수 없는 제어문자입니다.')
    # Match the old generator's UTF-16 length limit, including emoji.
    ensure(len(text.encode('utf-16-le')) // 2 <= limit, f'{label}: {limit}자 한도를 초과했습니다. 내용을 나누어 주세요.')
    return text


def validate_input(data):
    ensure(isinstance(data, dict), 'JSON 객체가 필요합니다.')
    company = data.get('company')
    ensure(isinstance(company, dict), 'company 객체가 필요합니다.')
    ensure(isinstance(company.get('nameKo'), str) and company['nameKo'].strip(), '회사명(company.nameKo)을 먼저 입력해 주세요.')
    for key in ('contact', 'manager', 'provider', 'plan'):
        ensure(data.get(key) is None or isinstance(data[key], dict), f'{key}: 객체여야 합니다.')
    products = data.get('products')
    ensure(isinstance(products, list) and 1 <= len(products) <= MAX_PRODUCTS, f'상품은 1~{MAX_PRODUCTS}개까지 지원합니다.')
    for product in products:
        ensure(isinstance(product, dict), 'products: 객체여야 합니다.')
        for key, maximum in (('countries', len(COUNTRIES)), ('factories', 4), ('variants', 50)):
            rows = product.get(key)
            ensure(rows is None or isinstance(rows, list) and len(rows) <= maximum, f'{key}: 최대 {maximum}개까지 지원합니다.')
            for row in rows or []:
                ensure(isinstance(row, dict), f'{key}: 각 행은 객체여야 합니다.')
        for key in ('frontImage', 'backImage', 'images'):
            ensure(product.get(key) in (None, '', False), '이 버전은 사진 자동 삽입을 지원하지 않습니다. 사진 입력을 무시하지 않고 중단합니다.')
    supplied_date = data.get('applicationDate')
    if supplied_date not in (None, ''):
        try:
            ensure(isinstance(supplied_date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', supplied_date), 'applicationDate: 실제 날짜 YYYY-MM-DD가 필요합니다.')
            date.fromisoformat(supplied_date)
        except ValueError as exc:
            raise DocumentError('applicationDate: 실제 날짜 YYYY-MM-DD가 필요합니다.') from exc


@dataclass
class Template:
    kind: str
    entries: dict[str, bytes]
    doc: minidom.Document
    header: minidom.Document
    root: minidom.Element
    tables: list
    updates: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_template(path, kind):
    content = Path(path).read_bytes()
    ensure(sha(content) == EXPECTED_HASH[kind], f'{kind}: 원본 양식이 다릅니다. 새 양식의 셀 매핑과 해시를 다시 검증해 주세요.')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        ensure(archive.testzip() is None, '원본 ZIP CRC 검증 실패')
        entries = {n.filename: archive.read(n) for n in archive.infolist() if not n.is_dir()}
    ensure(entries['mimetype'] == b'application/hwp+zip', 'HWPX mimetype이 아닙니다.')
    doc, header = parse(entries['Contents/section0.xml']), parse(entries['Contents/header.xml'])
    root = descendants(doc, 'hs:sec')[0]
    tables = descendants(root, 'hp:tbl')
    ensure(len(tables) == TABLE_COUNTS[kind], f'{kind}: 표 개수가 예상과 다릅니다.')
    return Template(kind, entries, doc, header, root, tables)


class Missing(str):
    """Carry the missing-input flag even when a cell contains checkbox labels."""


def needed(ctx, value, label, limit=3000):
    normalized = '' if value is None or value == '' else string_value(value, label, limit)
    if not normalized:
        ctx.warnings.append(f'{label}: 확인 필요')
        return Missing('')
    return normalized


def cell_at(tables, table, row, col):
    matches = []
    for tr in children(tables[table], 'hp:tr'):
        for cell in children(tr, 'hp:tc'):
            addresses = children(cell, 'hp:cellAddr')
            if addresses and addresses[0].getAttribute('rowAddr') == str(row) and addresses[0].getAttribute('colAddr') == str(col):
                matches.append(cell)
    ensure(len(matches) == 1, f'셀 ({table},{row},{col})을 유일하게 찾지 못했습니다.')
    return matches[0]


def element(doc, name, attributes=None, text=None):
    node = doc.createElement(name)
    for key, value in (attributes or {}).items():
        node.setAttribute(key, value)
    if text is not None:
        node.appendChild(doc.createTextNode(text))
    return node


def replace_text(node, text):
    for child in list(node.childNodes):
        node.removeChild(child)
    node.appendChild(node.ownerDocument.createTextNode(text))


def text_run(doc, style, text):
    run = element(doc, 'hp:run', {'charPrIDRef': style})
    run.appendChild(element(doc, 'hp:t', text=text))
    return run


def shade_cell(ctx, cell):
    ref = cell.getAttribute('borderFillIDRef')
    cache = getattr(ctx, '_yellow_borders', {})
    if ref not in cache:
        styles = descendants(ctx.header, 'hh:borderFill')
        source = next(n for n in styles if n.getAttribute('id') == ref)
        clone = source.cloneNode(True)
        new_id = str(max(int(n.getAttribute('id')) for n in styles) + 1)
        clone.setAttribute('id', new_id)
        for brush in children(clone, 'hc:fillBrush'):
            clone.removeChild(brush)
        brush = element(ctx.header, 'hc:fillBrush')
        brush.appendChild(element(ctx.header, 'hc:winBrush', {'faceColor': YELLOW, 'hatchColor': '#000000', 'alpha': '0'}))
        clone.appendChild(brush)
        source.parentNode.appendChild(clone)
        source.parentNode.setAttribute('itemCnt', str(len(styles) + 1))
        cache[ref] = new_id
        ctx._yellow_borders = cache
    cell.setAttribute('borderFillIDRef', cache[ref])


def yellow_style(ctx, ref):
    cache = getattr(ctx, '_yellow_chars', {})
    if ref not in cache:
        styles = descendants(ctx.header, 'hh:charPr')
        source = next(n for n in styles if n.getAttribute('id') == ref)
        clone = source.cloneNode(True)
        new_id = str(max(int(n.getAttribute('id')) for n in styles) + 1)
        clone.setAttribute('id', new_id)
        clone.setAttribute('shadeColor', YELLOW)
        source.parentNode.appendChild(clone)
        source.parentNode.setAttribute('itemCnt', str(len(styles) + 1))
        cache[ref] = new_id
        ctx._yellow_chars = cache
    return cache[ref]


def set_cell(ctx, table, row, col, value, *, missing=False):
    text = string_value(value, f'셀 {table}/{row}/{col}')
    cell = cell_at(ctx.tables, table, row, col)
    sublist = children(cell, 'hp:subList')[0]
    paragraphs = children(sublist, 'hp:p')
    ensure(paragraphs, '셀 문단이 없습니다.')
    ensure(not descendants(sublist, 'hp:tbl') and not descendants(sublist, 'hp:pic'), '중첩 표/사진이 있는 셀은 덮어쓰지 않습니다.')
    style = '8' if ctx.kind == 'application' else '9'
    ensure(any(n.getAttribute('id') == style for n in descendants(ctx.header, 'hh:charPr')), f'글자 스타일 {style} 없음')
    attributes = dict(paragraphs[0].attributes.items()) | {'pageBreak': '0', 'columnBreak': '0'}
    for child in list(sublist.childNodes):
        sublist.removeChild(child)
    for line in text.split('\n'):
        paragraph = element(ctx.doc, 'hp:p', attributes)
        paragraph.appendChild(text_run(ctx.doc, style, line))
        sublist.appendChild(paragraph)
    if missing or isinstance(value, Missing) or not text.strip():
        shade_cell(ctx, cell)
    ctx.updates.append(dict(table=table, row=row, col=col, text=text))


def set_root_paragraph(ctx, predicate, text):
    candidates = [p for p in children(ctx.root, 'hp:p') if not descendants(p, 'hp:tbl') and predicate(text_of(p))]
    ensure(len(candidates) == 1, f'본문 문단 매칭 실패: {text[:45]}')
    paragraph = candidates[0]
    runs = children(paragraph, 'hp:run')
    style = next((r for r in runs if children(r, 'hp:t')), runs[0]).getAttribute('charPrIDRef')
    for run in runs:
        for node in children(run, 'hp:t'):
            run.removeChild(node)
    for node in children(paragraph, 'hp:linesegarray'):
        paragraph.removeChild(node)
    paragraph.appendChild(text_run(ctx.doc, style, text))


def choices(ctx, values, selected, label):
    if selected is None or selected == '':
        ctx.warnings.append(f'{label}: 선택 확인 필요')
    else:
        ensure(selected in values, f'{label}: 허용값은 {", ".join(values)}입니다.')
    text = '  '.join(f'{"☑" if v == selected else "☐"} {v}' for v in values)
    return text if selected else Missing(text)


def resize_table_rows(table, count, *, total=False):
    """Repeat a verified data row; preserve the header and optional total row."""
    rows = children(table, 'hp:tr')
    template = rows[1].cloneNode(True)
    end = rows[-1].cloneNode(True) if total else None
    for row in rows[1:]:
        table.removeChild(row)
    for index in range(count):
        table.appendChild(template.cloneNode(True))
    if end is not None:
        table.appendChild(end)
    height = 0
    for index, row in enumerate(children(table, 'hp:tr')):
        for cell in children(row, 'hp:tc'):
            children(cell, 'hp:cellAddr')[0].setAttribute('rowAddr', str(index))
        height += max(int(children(cell, 'hp:cellSz')[0].getAttribute('height')) for cell in children(row, 'hp:tc'))
    table.setAttribute('rowCnt', str(count + 1 + int(total)))
    children(table, 'hp:sz')[0].setAttribute('height', str(height))


def duplicate_product_pages(ctx, count):
    paragraphs = children(ctx.root, 'hp:p')
    start = next(i for i, p in enumerate(paragraphs) if text_of(p).startswith('[붙임1-1]'))
    prototype = [p.cloneNode(True) for p in paragraphs[start:]]
    next_id = max(int(t.getAttribute('id')) for t in ctx.tables) + 1
    for _ in range(count - 1):
        for i, original in enumerate(prototype):
            clone = original.cloneNode(True)
            if i == 0:
                clone.setAttribute('pageBreak', '1')
            for table in descendants(clone, 'hp:tbl'):
                table.setAttribute('id', str(next_id))
                next_id += 1
            ctx.root.appendChild(clone)
    ctx.tables = descendants(ctx.root, 'hp:tbl')


def fill_application(ctx, data):
    company = data['company']
    contact, manager, provider = (data.get(k) or {} for k in ('contact', 'manager', 'provider'))
    mapping = [
        (0, 2, company, 'nameKo', '기업명(국문)'), (0, 5, company, 'nameEn', '기업명(영문)'),
        (1, 2, company, 'registrationNumber', '사업자번호'), (1, 5, company, 'representative', '대표자'),
        (2, 2, company, 'address', '주소'), (4, 2, company, 'department', '담당부서'),
        (5, 2, contact, 'name', '담당자'), (5, 5, contact, 'phone', '담당자 연락처'),
        (6, 2, contact, 'email', '담당자 이메일'), (7, 2, manager, 'name', '부서장'),
        (7, 5, manager, 'phone', '부서장 연락처'), (8, 2, manager, 'email', '부서장 이메일'),
    ]
    for row, col, source, key, label in mapping:
        set_cell(ctx, 0, row, col, needed(ctx, source.get(key), label, 500))
    set_cell(ctx, 0, 3, 2, choices(ctx, ['중소기업', '중견기업', '대기업'], company.get('category'), '기업구분'))
    set_cell(ctx, 0, 10, 2, choices(ctx, ['라벨', '맞춤제작'], data.get('projectType'), '사업과제'))
    set_cell(ctx, 0, 11, 3, needed(ctx, provider.get('name'), '희망 수행업체'))
    set_cell(ctx, 0, 12, 3, f"{needed(ctx, provider.get('contact'), '수행업체 담당자')} / {needed(ctx, provider.get('phone'), '수행업체 연락처')}",
             missing=not provider.get('contact') or not provider.get('phone'))
    shade_cell(ctx, cell_at(ctx.tables, 0, 9, 0))  # Leave consent unselected.
    products = data['products']
    duplicate_product_pages(ctx, len(products))
    resize_table_rows(ctx.tables[1], len(products), total=True)
    for index, product in enumerate(products):
        names = ', '.join(row.get('country', '') for row in product.get('countries', []) if row.get('country'))
        for col, value, label in [(0, str(index + 1), '번호'), (1, product.get('brandKo'), '브랜드명'),
                                   (2, product.get('nameKo'), '상품명'), (3, names, '사용국가'),
                                   (4, product.get('exportScale'), '수출규모(단위·기간 포함)')]:
            set_cell(ctx, 1, index + 1, col, needed(ctx, value, label))
        fill_product(ctx, product, 2 + index * 3)
    # Different currencies/periods cannot be summed without additional input.
    total = products[0].get('exportScale') if len(products) == 1 else ''
    set_cell(ctx, 1, len(products) + 1, 4, needed(ctx, total, '수출규모 합계(동일 기간·통화 확인)'))
    headings = [p for p in children(ctx.root, 'hp:p') if not descendants(p, 'hp:tbl') and text_of(p).startswith('[붙임1-1]')]
    for index, (paragraph, product) in enumerate(zip(headings, products, strict=True)):
        write_paragraph(ctx, paragraph, f"[붙임1-1] 상품별 세부정보 {index + 1} ({product.get('nameKo', '')})")
    fill_footer(ctx, data)


def fill_product(ctx, product, first):
    for row, col, key, label in [
        (0, 1, 'brandKo', '브랜드 국문'), (0, 3, 'brandEn', '브랜드 영문'),
        (1, 1, 'nameKo', '상품 국문'), (1, 3, 'nameEn', '상품 영문'),
        (2, 1, 'category', '상품분류'), (5, 1, 'certifications', '보유인증'), (6, 1, 'trademarks', '상표현황'),
    ]:
        set_cell(ctx, first, row, col, needed(ctx, product.get(key), label))
    set_cell(ctx, first, 3, 1, '', missing=True)
    ctx.warnings.append('상품 전면·후면 사진과 증빙서류는 제출 전 첨부해 주세요.')
    set_cell(ctx, first, 4, 1, choices(ctx, ['유', '무'], product.get('certificationHeld'), '인증 보유 여부'))
    set_cell(ctx, first + 1, 0, 1, choices(ctx, ['국내생산', '해외생산', '국내/해외 병행생산'], product.get('productionLocation'), '생산지'))
    set_cell(ctx, first + 1, 1, 1, choices(ctx, ['자체생산', '위탁생산(OEM/ODM)', '자체/위탁 병행생산'], product.get('productionType'), '생산형태'))
    for i, factory in enumerate(product.get('factories') or [{}]):
        set_cell(ctx, first + 1, 3 + i, 1, str(i + 1))
        set_cell(ctx, first + 1, 3 + i, 2, needed(ctx, factory.get('country'), '공장 제조국'))
        set_cell(ctx, first + 1, 3 + i, 3, needed(ctx, factory.get('productionType'), '공장 생산형태'))
    countries = product.get('countries') or [{}]
    resize_table_rows(ctx.tables[first + 2], len(countries))
    for i, country in enumerate(countries):
        for col, value, label in [(0, country.get('country'), '사용국가'), (1, product.get('brandKo'), '브랜드'), (2, product.get('nameKo'), '상품')]:
            set_cell(ctx, first + 2, i + 1, col, needed(ctx, value, label))
        # The original form lists three statuses; keep the customer's finer status
        # verbatim instead of coercing an application/registration stage to completed.
        status = country.get('trademarkStatus')
        if status in ('출원예정', '출원완료', '등록예정', '등록중'):
            set_cell(ctx, first + 2, i + 1, 3, status)
        else:
            set_cell(ctx, first + 2, i + 1, 3, choices(ctx, ['등록완료', '출원중', '미출원'], status, '국가별 상표상태'))
        set_cell(ctx, first + 2, i + 1, 4, needed(ctx, country.get('trademarkNumberOrReason'), '상표번호/미출원 사유'))
        set_cell(ctx, first + 2, i + 1, 5, needed(ctx, country.get('quantity'), '부착 예정수량'))
        set_cell(ctx, first + 2, i + 1, 6, choices(ctx, ['라벨', '맞춤제작'], country.get('method'), '국가별 사용방식'))


def write_paragraph(ctx, paragraph, text, *, missing=False, signature=False):
    runs = children(paragraph, 'hp:run')
    style = next((r.getAttribute('charPrIDRef') for r in runs if children(r, 'hp:t')), runs[0].getAttribute('charPrIDRef') if runs else '0')
    for run in runs:
        for node in children(run, 'hp:t'):
            run.removeChild(node)
    # Do not touch paragraph controls or legal text in nested tables.
    if signature:
        paragraph.appendChild(text_run(ctx.doc, yellow_style(ctx, style) if missing else style, text))
        paragraph.appendChild(text_run(ctx.doc, yellow_style(ctx, style), '                 (직인)'))
    else:
        paragraph.appendChild(text_run(ctx.doc, yellow_style(ctx, style) if missing else style, text))


def fill_footer(ctx, data):
    company = data['company']
    for p in descendants(ctx.doc, 'hp:p'):
        if descendants(p, 'hp:tbl'):
            continue
        text = text_of(p)
        if re.fullmatch(r'\s*년\s*월\s*일\s*', text):
            if data.get('applicationDate'):
                year, month, day = data['applicationDate'].split('-')
                write_paragraph(ctx, p, f'{year}년 {int(month)}월 {int(day)}일')
            else:
                write_paragraph(ctx, p, '        년      월      일', missing=True)
                ctx.warnings.append('신청일: 확인 필요')
        elif '신청기업명 :' in text:
            write_paragraph(ctx, p, f"신청기업명 : {company['nameKo']}")
        elif '대  표  자 :' in text:
            write_paragraph(ctx, p, f"대  표  자 : {needed(ctx, company.get('representative'), '대표자')}", signature=True, missing=not company.get('representative'))
        elif ctx.kind == 'intervention' and text.startswith('기업명:'):
            write_paragraph(ctx, p, f"기업명: {company['nameKo']}")
        elif ctx.kind == 'intervention' and text.startswith('사업자등록번호:'):
            value = needed(ctx, company.get('registrationNumber'), '사업자등록번호')
            write_paragraph(ctx, p, f'사업자등록번호: {value}', missing=not value)
        elif ctx.kind == 'intervention' and text.startswith('기 업 명'):
            write_paragraph(ctx, p, f"기 업 명   {company['nameKo']}", signature=True)
        elif ctx.kind == 'pledge' and '[ ] 위 사항' in text:
            write_paragraph(ctx, p, text, missing=True)
    ctx.warnings.append('동의·서명·직인은 직접 확인하고 작성해 주세요.')


def fill_declaration(ctx, data):
    fill_footer(ctx, data)



def fill_plan(ctx, data):
    plan = data.get('plan') or {}
    for table, row, col, key, label in [
        (0, 0, 1, 'counterfeitRisk', '위조 피해·우려'), (0, 1, 1, 'ipDefense', '해외 IP·방어역량'),
        (1, 0, 1, 'countries', '활용국가'), (1, 2, 1, 'channelPlan', '활용채널 상세'),
        (1, 3, 1, 'marketing', '수출 마케팅 전략'), (1, 4, 1, 'expectedEffects', '기대효과'),
        (2, 1, 1, 'improvement', '개선계획'),
    ]:
        set_cell(ctx, table, row, col, needed(ctx, plan.get(key), label))
    allowed = ['제품', '포장', '온라인몰', '홈페이지/SNS', '전시·박람회', '기타']
    selected = plan.get('channels')
    if selected is None:
        selected = []
    ensure(isinstance(selected, list) and all(x in allowed for x in selected), 'plan.channels에 잘못된 활용채널이 있습니다.')
    set_cell(ctx, 1, 1, 1, '  '.join(f'{"☑" if v in selected else "☐"} {v}' for v in allowed), missing=not selected)
    if not selected:
        ctx.warnings.append('활용채널: 선택 확인 필요')
    set_cell(ctx, 2, 0, 1, '타사의 선행 IP 무단침해/카피 분쟁 요소가 있었습니까?\n' + choices(ctx, ['없음', '있음'], plan.get('ipHistory'), '분쟁 이력'), missing=not plan.get('ipHistory'))
    guide = next(p for p in children(ctx.root, 'hp:p') if not descendants(p, 'hp:tbl') and '회색 안내문은' in text_of(p))
    ctx.root.removeChild(guide)
    fill_footer(ctx, data)


def validate_package(content, updates, expected_tables):
    ensure(content[:4] == b'PK\x03\x04', 'ZIP local header 없음')
    first_name_len = int.from_bytes(content[26:28], 'little')
    ensure(content[30:30 + first_name_len] == b'mimetype' and content[8:10] == b'\x00\x00', 'mimetype은 첫 항목·무압축이어야 합니다.')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        ensure(archive.testzip() is None, 'ZIP CRC 검증 실패')
        names = archive.namelist()
        ensure(len(names) == len(set(names)), '중복 ZIP 항목')
        ensure(archive.read('mimetype') == b'application/hwp+zip', 'HWPX mimetype이 아닙니다.')
        xml_files = [n for n in names if re.search(r'\.(xml|hpf|rdf)$', n, re.I)]
        parsed = {n: parse(archive.read(n)) for n in xml_files}
        doc, header = parsed['Contents/section0.xml'], parsed['Contents/header.xml']
        tables = descendants(doc, 'hp:tbl')
        ensure(len(tables) == expected_tables, '출력 표 개수가 바뀌었습니다.')
        refs = {key: {n.getAttribute('id') for n in descendants(header, tag)} for key, tag in [('charPrIDRef', 'hh:charPr'), ('paraPrIDRef', 'hh:paraPr'), ('styleIDRef', 'hh:style'), ('borderFillIDRef', 'hh:borderFill')]}
        for node in doc.getElementsByTagName('*'):
            for key, valid in refs.items():
                if node.hasAttribute(key):
                    ensure(node.getAttribute(key) in valid, f'없는 스타일 참조 {key}={node.getAttribute(key)}')
        sections = [n for n in names if re.fullmatch(r'Contents/section\d+\.xml', n)]
        ensure(int(descendants(header, 'hh:head')[0].getAttribute('secCnt')) == len(sections), '구역 수 불일치')
        for item in descendants(parsed['Contents/content.hpf'], 'opf:item'):
            ensure(item.getAttribute('href') in names, f"누락 manifest 파일: {item.getAttribute('href')}")
        for update in updates:
            cell = cell_at(tables, update['table'], update['row'], update['col'])
            actual = '\n'.join(text_of(p) for p in children(children(cell, 'hp:subList')[0], 'hp:p'))
            ensure(actual == update['text'], f"입력값 불일치 {update['table']}/{update['row']}/{update['col']}")
        ensure(archive.read('Preview/PrvText.txt').decode('utf-8') == document_text(doc), '미리보기 텍스트 불일치')
    return dict(zipCRC='pass', xmlFilesParsed=len(xml_files), styleReferences='pass', manifestReferences='pass', sectionCount=len(sections), tableCount=len(tables), verifiedCells=len(updates), mimetypeFirstStored=True)


def pack(ctx, title):
    for node in descendants(ctx.doc, 'hp:linesegarray'):
        node.parentNode.removeChild(node)
    hpf = parse(ctx.entries['Contents/content.hpf'])
    replace_text(descendants(hpf, 'opf:title')[0], title)
    for node in descendants(hpf, 'opf:meta'):
        if node.getAttribute('name') == 'lastsaveby':
            replace_text(node, 'K-brand Python generator')
        if node.getAttribute('name') == 'ModifiedDate':
            replace_text(node, datetime.now(timezone.utc).isoformat())
    container = parse(ctx.entries['META-INF/container.xml'])
    for node in list(container.getElementsByTagName('*')):
        if node.getAttribute('full-path') == 'Preview/PrvImage.png':
            node.parentNode.removeChild(node)
    preview = document_text(ctx.doc)
    replacements = {'Contents/section0.xml': serialize(ctx.doc), 'Contents/header.xml': serialize(ctx.header), 'Contents/content.hpf': serialize(hpf), 'Preview/PrvText.txt': preview.encode('utf-8'), 'META-INF/container.xml': serialize(container)}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('mimetype', b'application/hwp+zip', compress_type=zipfile.ZIP_STORED)
        for name, content in ctx.entries.items():
            if name not in ('mimetype', 'Preview/PrvImage.png'):
                archive.writestr(name, replacements.get(name, content))
    content = output.getvalue()
    validation = validate_package(content, ctx.updates, len(ctx.tables))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name, original in ctx.entries.items():
            if name != 'Preview/PrvImage.png' and name not in replacements:
                ensure(archive.read(name) == original, f'비대상 파일이 변경됨: {name}')
    validation['unchangedPackageEntries'] = 'pass'
    return dict(bytes=content, text=preview, validation=validation, warnings=list(dict.fromkeys(ctx.warnings)))


def generate(data_path: Path, out_dir: Path, templates_dir: Path):
    input_bytes = data_path.read_bytes()
    data = json.loads(input_bytes.decode('utf-8-sig'))
    validate_input(data)
    company = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', string_value(data['company']['nameKo'], '기업명', 80))
    products = []
    for kind, label, fill in [('application', '사용신청서', fill_application), ('plan', '활용계획서', fill_plan), ('pledge', '확약서_정보제공동의서', fill_declaration), ('intervention', '제3자_부당개입_배제_확약서', fill_declaration)]:
        ctx = load_template(templates_dir / f'{kind}.hwpx', kind)
        fill(ctx, data)
        title = f'{company}_{label}_검토용'
        products.append(dict(title=title, **pack(ctx, title)))
    # Prepare and validate all four documents before publishing any output files.
    run_dir = out_dir / f'{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}'
    run_dir.mkdir(parents=True, exist_ok=False)
    report = dict(generatedAt=datetime.now(timezone.utc).isoformat(), source=data.get('source'), inputSHA256=sha(input_bytes), templateSHA256=EXPECTED_HASH.copy(), engine='Python + zipfile + xml.dom.minidom (no HWP automation)', scope='최대 20개 상품 / 상품별 최대 73개 국가 / 미입력 칸 노란 표시', visualValidation='생성기 자체는 렌더링하지 않음. 한컴에서 열어 표·쪽 배치 확인 필요.', files=[])
    for product in products:
        filename = f"{product['title']}.hwpx"
        with (run_dir / filename).open('xb') as stream:
            stream.write(product['bytes'])
        with (run_dir / f"{product['title']}.txt").open('x', encoding='utf-8', newline='') as stream:
            stream.write(product['text'])
        report['files'].append(dict(filename=filename, bytes=len(product['bytes']), sha256=sha(product['bytes']), validation=product['validation'], warnings=product['warnings']))
    with (run_dir / 'validation.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return run_dir, report
