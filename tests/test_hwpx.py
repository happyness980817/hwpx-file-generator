"""Pinned user templates, data identity, missing-field shading and format guards."""
import copy
import hashlib
import io
from unittest.mock import patch
import zipfile

import pytest

from src.config import TEMPLATES
from src.errors import DocumentError
from src.hwpx import (
    EXPECTED_HASH, YELLOW, cell_at, children, descendants, load_template, parse, text_of,
    validate_input, validate_package,
)
from src.models import COUNTRIES, MAX_PRODUCTS, empty_data, sample_data
from src.service import generate_documents


def archive_parts(file):
    with zipfile.ZipFile(io.BytesIO(file['bytes'])) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_new_reference_templates_preserve_unedited_parts_and_consent(tmp_path):
    data = sample_data()
    before = copy.deepcopy(data)
    result = generate_documents(data, tmp_path)
    assert data == before
    for actual, kind in zip(result['files'][:4], EXPECTED_HASH, strict=True):
        entries = archive_parts(actual)
        original = load_template(TEMPLATES / f'{kind}.hwpx', kind)
        changed = {'Contents/section0.xml', 'Contents/header.xml', 'Contents/content.hpf',
                   'META-INF/container.xml', 'Preview/PrvText.txt', 'Preview/PrvImage.png'}
        assert 'Preview/PrvImage.png' not in entries
        for name, content in original.entries.items():
            if name not in changed:
                assert entries[name] == content
        if kind == 'application':
            tables = descendants(parse(entries['Contents/section0.xml']), 'hp:tbl')
            assert text_of(cell_at(tables, 0, 9, 0)) == text_of(cell_at(original.tables, 0, 9, 0))
    assert {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in TEMPLATES.glob('*.hwpx')} == EXPECTED_HASH


@pytest.mark.parametrize('kind,index', [('pledge', 2), ('intervention', 3)])
def test_legal_declarations_preserve_each_legal_paragraph(kind, index, tmp_path):
    data = sample_data()
    data['company'].update(registrationNumber='123-45-67890', representative='김대표')
    data['applicationDate'] = '2026-10-14'
    result = generate_documents(data, tmp_path)
    doc = parse(archive_parts(result['files'][index])['Contents/section0.xml'])
    original = load_template(TEMPLATES / f'{kind}.hwpx', kind)
    output = [text_of(p) for p in descendants(doc, 'hp:p') if not descendants(p, 'hp:tbl')]
    legal = [text_of(p) for p in descendants(original.doc, 'hp:p')
             if not descendants(p, 'hp:tbl') and len(text_of(p).strip()) > 60]
    assert len(legal) >= 3
    assert all(text in output for text in legal)
    joined = '\n'.join(output)
    assert data['company']['nameKo'] in joined and '2026년 10월 14일' in joined
    assert '☑' not in joined  # An agent cannot assent or sign for the customer.
    if kind == 'intervention':
        assert '123-45-67890' in joined
    else:
        assert '김대표' in joined
        assert '[ ] 위 사항' in joined


def cell_color(cell, header):
    ref = cell.getAttribute('borderFillIDRef')
    style = next(item for item in descendants(header, 'hh:borderFill') if item.getAttribute('id') == ref)
    return [item.getAttribute('faceColor') for item in descendants(style, 'hc:winBrush')]


def test_unknown_values_are_blank_yellow_and_known_values_remain_unshaded(tmp_path):
    data = empty_data()
    data['company']['nameKo'] = '실제 입력한 기업'
    result = generate_documents(data, tmp_path)
    entries = archive_parts(result['files'][0])
    header = parse(entries['Contents/header.xml'])
    tables = descendants(parse(entries['Contents/section0.xml']), 'hp:tbl')
    company = cell_at(tables, 0, 0, 2)
    missing_number = cell_at(tables, 0, 1, 2)
    missing_brand = cell_at(tables, 2, 0, 1)
    assert text_of(company) == '실제 입력한 기업' and YELLOW not in cell_color(company, header)
    for cell in [missing_number, missing_brand]:
        assert text_of(cell) == ''
        assert YELLOW in cell_color(cell, header)
    assert YELLOW in cell_color(cell_at(tables, 0, 9, 0), header)
    assert '확인 필요' not in entries['Preview/PrvText.txt'].decode('utf-8')


def test_multiple_products_keep_separate_country_rows_and_all_73_countries(tmp_path):
    data = sample_data()
    first = data['products'][0]
    first['countries'] = [{'country': country, 'trademarkStatus':'출원중', 'trademarkNumberOrReason':f'A-{index}',
                           'quantity':str(index + 100), 'method':'라벨'} for index, country in enumerate(COUNTRIES)]
    second = copy.deepcopy(first)
    second.update(brandKo='두번째 브랜드', nameKo='두번째 상품', exportScale='USD 200 / 연간',
                  countries=[{'country':'미국', 'trademarkStatus':'등록완료', 'trademarkNumberOrReason':'B-US', 'quantity':'999', 'method':'맞춤제작'}])
    data['products'].append(second)
    result = generate_documents(data, tmp_path)
    entries = archive_parts(result['files'][0])
    tables = descendants(parse(entries['Contents/section0.xml']), 'hp:tbl')
    assert len(tables) == 8
    assert len(children(tables[4], 'hp:tr')) == 74
    assert len(children(tables[7], 'hp:tr')) == 2
    assert text_of(cell_at(tables, 1, 1, 2)) == first['nameKo']
    assert text_of(cell_at(tables, 1, 2, 2)) == second['nameKo']
    for index, country in enumerate(COUNTRIES, 1):
        assert text_of(cell_at(tables, 4, index, 0)) == country
        assert text_of(cell_at(tables, 4, index, 2)) == first['nameKo']
        assert text_of(cell_at(tables, 4, index, 4)) == f'A-{index - 1}'
    assert text_of(cell_at(tables, 7, 1, 1)) == second['brandKo']
    assert text_of(cell_at(tables, 7, 1, 2)) == second['nameKo']
    assert text_of(cell_at(tables, 7, 1, 4)) == 'B-US'
    assert text_of(cell_at(tables, 7, 1, 5)) == '999'
    assert text_of(cell_at(tables, 1, 3, 4)) == ''  # No invented cross-currency/period sum.
    ids = [table.getAttribute('id') for table in tables]
    assert len(ids) == len(set(ids))


def test_modified_template_rejected_without_output(tmp_path):
    templates = tmp_path / 'templates'
    templates.mkdir()
    for kind in EXPECTED_HASH:
        content = (TEMPLATES / f'{kind}.hwpx').read_bytes()
        (templates / f'{kind}.hwpx').write_bytes(content + (b'tampered' if kind == 'plan' else b''))
    with patch('src.service.TEMPLATES', templates):
        with pytest.raises(DocumentError, match='원본 양식'):
            generate_documents(sample_data(), tmp_path / 'outputs')
    assert not list((tmp_path / 'outputs').rglob('*.hwpx'))


@pytest.mark.parametrize('change, message', [
    (lambda d: d.update(products=d['products'] * (MAX_PRODUCTS + 1)), '1~20개'),
    (lambda d: d['products'][0].update(countries=[{}] * 74), '최대 73개'),
    (lambda d: d['products'][0].update(factories=[{}] * 5), '최대 4개'),
    (lambda d: d['products'][0].update(variants=[{}] * 51), '최대 50개'),
    (lambda d: d['products'][0].update(images=['image.png']), '사진 자동 삽입'),
    (lambda d: d['plan'].update(marketing='문자\x00'), '제어문자'),
    (lambda d: d['plan'].update(marketing='문자\ud800'), '제어문자'),
    (lambda d: d['plan'].update(channels=['없는 채널']), '활용채널'),
    (lambda d: d['company'].update(category='없는 구분'), '허용값'),
    (lambda d: d['plan'].update(marketing='가' * 3001), '3000자'),
])
def test_rejects_unsupported_input_without_documents(change, message, tmp_path):
    data = sample_data()
    change(data)
    with pytest.raises(DocumentError, match=message):
        generate_documents(data, tmp_path)
    assert not list(tmp_path.rglob('*.hwpx'))


@pytest.mark.parametrize('data', [None, [], {}, {'company': []}, {'company': {'nameKo': 3}}])
def test_malformed_input(data):
    with pytest.raises(DocumentError):
        validate_input(data)


def test_rejects_dtd():
    with pytest.raises(DocumentError, match='DOCTYPE/ENTITY'):
        parse('<!DOCTYPE doc [<!ENTITY bad "value">]><doc>&bad;</doc>')


def test_output_validation_detects_broken_styles_and_preview(tmp_path):
    result = generate_documents(sample_data(), tmp_path)
    entries = archive_parts(result['files'][0])
    for name, replacement, message in [
        ('Contents/section0.xml', entries['Contents/section0.xml'].replace(b'charPrIDRef="8"', b'charPrIDRef="99999"', 1), '없는 스타일'),
        ('Preview/PrvText.txt', b'wrong preview', '미리보기'),
    ]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, content in entries.items():
                archive.writestr(path, replacement if path == name else content, compress_type=zipfile.ZIP_STORED if path == 'mimetype' else zipfile.ZIP_DEFLATED)
        with pytest.raises(DocumentError, match=message):
            validate_package(stream.getvalue(), [], 5)


@pytest.mark.parametrize('status', ['출원예정', '출원중', '출원완료', '등록예정', '등록중', '등록완료'])
def test_all_requested_trademark_statuses_survive_document_generation(status, tmp_path):
    from src.models import apply_form_defaults
    data = apply_form_defaults(sample_data())
    data['products'][0]['trademarks'] = status
    data['products'][0]['countries'][0]['trademarkStatus'] = status
    result = generate_documents(data, tmp_path)
    entries = archive_parts(result['files'][0])
    tables = descendants(parse(entries['Contents/section0.xml']), 'hp:tbl')
    assert text_of(cell_at(tables, 2, 6, 1)) == status
    assert status in text_of(cell_at(tables, 4, 1, 3))
    assert '이노프렌즈' in text_of(cell_at(tables, 0, 11, 3))
    assert '100만장' in text_of(cell_at(tables, 4, 1, 5))
