"""Regression against the independent pre-migration engine and format guards."""
import copy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import pytest

from src.config import TEMPLATES
from src.errors import DocumentError
from src.hwpx import (
    EXPECTED_HASH, cell_at, descendants, load_template, parse, text_of,
    validate_input, validate_package,
)
from src.models import sample_data
from src.service import generate_documents

REFERENCE = json.loads((Path(__file__).parent / 'fixtures/generator_reference.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', REFERENCE['cases'], ids=lambda c: c['name'])
def test_matches_pre_migration_documents(case, tmp_path):
    data = copy.deepcopy(case['data'])
    result = generate_documents(data, tmp_path)
    assert data == case['data']
    for actual, report, expected in zip(result['files'], result['report']['files'], case['files'], strict=True):
        assert actual['name'] == expected['filename']
        assert report['warnings'] == expected['warnings']
        assert report['validation'] == expected['validation']
        with zipfile.ZipFile(io.BytesIO(actual['bytes'])) as archive:
            canonical = ET.canonicalize(archive.read('Contents/section0.xml').decode('utf-8'))
            assert hashlib.sha256(canonical.encode('utf-8')).hexdigest() == expected['sectionSHA256']
            assert hashlib.sha256(archive.read('Preview/PrvText.txt')).hexdigest() == expected['previewSHA256']
            kind = 'application' if '사용신청서' in actual['name'] else 'plan'
            original = load_template(TEMPLATES / f'{kind}.hwpx', kind)
            changed = {'Contents/section0.xml', 'Contents/content.hpf', 'META-INF/container.xml', 'Preview/PrvText.txt', 'Preview/PrvImage.png'}
            assert 'Preview/PrvImage.png' not in archive.namelist()
            for name, content in original.entries.items():
                if name not in changed:
                    assert archive.read(name) == content
            if kind == 'application':
                doc = parse(archive.read('Contents/section0.xml'))
                assert text_of(cell_at(descendants(doc, 'hp:tbl'), 0, 9, 0)) == text_of(cell_at(original.tables, 0, 9, 0))
    assert {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in TEMPLATES.glob('*.hwpx')} == EXPECTED_HASH


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
    (lambda d: d['products'].append(copy.deepcopy(d['products'][0])), '상품 1개'),
    (lambda d: d['products'][0].update(countries=[{}] * 4), '최대 3개'),
    (lambda d: d['products'][0].update(factories=[{}] * 5), '최대 4개'),
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
    with zipfile.ZipFile(io.BytesIO(result['files'][0]['bytes'])) as archive:
        entries = {n: archive.read(n) for n in archive.namelist()}
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
