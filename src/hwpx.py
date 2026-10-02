"""Fill the two pinned K-brand HWPX templates using Python's ZIP/XML libraries.

Only mapped text cells are edited. Styles, section controls and other package
parts remain intact. This validates structure, not Hancom's page rendering.
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

EXPECTED_HASH = {
    'application': '53c61c99f5daffa8840b5af1c3aa5a998d9a8fb6df738b8ed55b19de975857c8',
    'plan': 'ca22b89b730dc58248ac5f1bdf24e17b9ba33e781ce4410e7b6f27b236541e82',
}


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
    ensure(isinstance(products, list) and len(products) == 1, '이 버전은 상품 1개만 지원합니다. 여러 상품은 자동으로 누락시키지 않고 중단합니다.')
    product = products[0]
    ensure(isinstance(product, dict), 'products[0]: 객체여야 합니다.')
    for key, maximum in (('countries', 3), ('factories', 4)):
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
    ensure(len(tables) == (5 if kind == 'application' else 3), f'{kind}: 표 개수가 예상과 다릅니다.')
    return Template(kind, entries, doc, header, root, tables)


def needed(ctx, value, label, limit=3000):
    normalized = '' if value is None or value == '' else string_value(value, label, limit)
    if not normalized:
        ctx.warnings.append(f'{label}: 확인 필요')
        return '확인 필요'
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


def set_cell(ctx, table, row, col, value):
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
    return '  '.join(f'{"☑" if v == selected else "☐"} {v}' for v in values) + ('' if selected else '  (확인 필요)')


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
    set_cell(ctx, 0, 12, 3, f"{needed(ctx, provider.get('contact'), '수행업체 담당자')} / {needed(ctx, provider.get('phone'), '수행업체 연락처')}")
    # Original privacy consent at table 0, row 9, col 0 is never edited.
    product = data['products'][0]
    countries = product.get('countries') or [{}]
    country_names = ', '.join(needed(ctx, n.get('country'), '사용국가') for n in countries)
    scale = needed(ctx, product.get('exportScale'), '수출규모(단위·기간 포함)')
    for col, key, label in [(1, 'brandKo', '브랜드 국문'), (2, 'nameKo', '상품 국문')]:
        set_cell(ctx, 1, 1, col, needed(ctx, product.get(key), label))
    set_cell(ctx, 1, 1, 3, country_names)
    set_cell(ctx, 1, 1, 4, scale)
    set_cell(ctx, 1, 6, 4, scale)
    for row, col, key, label in [
        (0, 1, 'brandKo', '브랜드 국문'), (0, 3, 'brandEn', '브랜드 영문'),
        (1, 1, 'nameKo', '상품 국문'), (1, 3, 'nameEn', '상품 영문'),
        (2, 1, 'category', '상품분류'), (5, 1, 'certifications', '보유인증'), (6, 1, 'trademarks', '상표현황'),
    ]:
        set_cell(ctx, 2, row, col, needed(ctx, product.get(key), label))
    set_cell(ctx, 2, 3, 1, '상품 전면·후면 사진 첨부 필요')
    ctx.warnings.append('사진 자동 삽입 미구현: 한글에서 상품 전면·후면 사진을 추가해야 합니다.')
    set_cell(ctx, 2, 4, 1, choices(ctx, ['유', '무'], product.get('certificationHeld'), '인증 보유 여부'))
    set_cell(ctx, 3, 0, 1, choices(ctx, ['국내생산', '해외생산', '국내/해외 병행생산'], product.get('productionLocation'), '생산지'))
    set_cell(ctx, 3, 1, 1, choices(ctx, ['자체생산', '위탁생산(OEM/ODM)', '자체/위탁 병행생산'], product.get('productionType'), '생산형태'))
    for i, factory in enumerate(product.get('factories') or [{}]):
        set_cell(ctx, 3, 3 + i, 1, str(i + 1))
        set_cell(ctx, 3, 3 + i, 2, needed(ctx, factory.get('country'), '공장 제조국'))
        set_cell(ctx, 3, 3 + i, 3, needed(ctx, factory.get('productionType'), '공장 생산형태'))
    for i, country in enumerate(countries):
        for col, value, label in [(0, country.get('country'), '사용국가'), (1, product.get('brandKo'), '브랜드'), (2, product.get('nameKo'), '상품')]:
            set_cell(ctx, 4, i + 1, col, needed(ctx, value, label))
        set_cell(ctx, 4, i + 1, 3, choices(ctx, ['등록완료', '출원중', '미출원'], country.get('trademarkStatus'), '국가별 상표상태'))
        set_cell(ctx, 4, i + 1, 4, needed(ctx, country.get('trademarkNumberOrReason'), '상표번호/미출원 사유'))
        set_cell(ctx, 4, i + 1, 5, needed(ctx, country.get('quantity'), '부착 예정수량'))
        set_cell(ctx, 4, i + 1, 6, choices(ctx, ['라벨', '맞춤제작'], country.get('method'), '국가별 사용방식'))
    set_root_paragraph(ctx, lambda s: s.startswith('[붙임1-1]'), f"[붙임1-1] 상품별 세부정보({needed(ctx, product.get('nameKo'), '상품명')})")
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
    set_cell(ctx, 1, 1, 1, '  '.join(f'{"☑" if v in selected else "☐"} {v}' for v in allowed) + ('' if selected else ' (확인 필요)'))
    if not selected:
        ctx.warnings.append('활용채널: 선택 확인 필요')
    set_cell(ctx, 2, 0, 1, '타사의 선행 IP 무단침해/카피 분쟁 요소가 있었습니까?\n' + choices(ctx, ['없음', '있음'], plan.get('ipHistory'), '분쟁 이력'))
    set_root_paragraph(ctx, lambda s: '회색 안내문은' in s, '검토용 초안 · 제안 문안 및 확인 필요 항목은 고객사 확인 후 확정')
    fill_footer(ctx, data)


def fill_footer(ctx, data):
    company = data['company']
    application = ctx.kind == 'application'
    set_root_paragraph(ctx, lambda s: s.startswith('[붙임1]' if application else '[붙임2]'), '[검토용] 사용신청서 · 입력자료 미검증' if application else '[검토용] 활용계획서 · 고객사 확인 전')
    set_root_paragraph(ctx, lambda s: '신청기업명 :' in s, f"               신청기업명 : {needed(ctx, company.get('nameKo'), '기업명')}")
    set_root_paragraph(ctx, lambda s: '대  표  자 :' in s, f"                       대  표  자 : {needed(ctx, company.get('representative'), '대표자')}    (직인)")
    if data.get('applicationDate'):
        year, month, day = data['applicationDate'].split('-')
        set_root_paragraph(ctx, lambda s: re.fullmatch(r'\s*년\s*월\s*일\s*', s), f'{year}년 {int(month)}월 {int(day)}일')
    else:
        ctx.warnings.append('신청일 미입력: 원본의 날짜 빈칸 유지')
    ctx.warnings.append('고객사 개인정보 동의·서명·직인은 자동 작성하지 않았습니다.')


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
        refs = {key: {n.getAttribute('id') for n in descendants(header, tag)} for key, tag in [('charPrIDRef', 'hh:charPr'), ('paraPrIDRef', 'hh:paraPr'), ('styleIDRef', 'hh:style')]}
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
    replacements = {'Contents/section0.xml': serialize(ctx.doc), 'Contents/content.hpf': serialize(hpf), 'Preview/PrvText.txt': preview.encode('utf-8'), 'META-INF/container.xml': serialize(container)}
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
    for kind, label, fill in [('application', '사용신청서', fill_application), ('plan', '활용계획서', fill_plan)]:
        ctx = load_template(templates_dir / f'{kind}.hwpx', kind)
        fill(ctx, data)
        title = f'{company}_{label}_검토용'
        products.append(dict(title=title, **pack(ctx, title)))
    # Prepare and validate BOTH documents before publishing any output files.
    run_dir = out_dir / f'{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}'
    run_dir.mkdir(parents=True, exist_ok=False)
    report = dict(generatedAt=datetime.now(timezone.utc).isoformat(), source=data.get('source'), inputSHA256=sha(input_bytes), templateSHA256=EXPECTED_HASH.copy(), engine='Python + zipfile + xml.dom.minidom (no HWP automation)', scope='한 상품 / 최대 3개 국가 / 텍스트 및 선택표시', visualValidation='생성기 자체는 렌더링하지 않음. 한컴에서 열어 표·쪽 배치 확인 필요.', files=[])
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
