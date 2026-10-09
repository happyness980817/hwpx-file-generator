import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openai import APIConnectionError
from src.agent import compose_from_materials
from src.draft_schema import AgentDraft
from src.errors import DocumentError
from src.materials import prepare_materials, MAX_FILE_BYTES, MAX_FILES
from src.models import sample_data, example_plan
from src.service import generate_documents


def agent_result():
    data = sample_data()
    data['plan'].update(example_plan(data))
    return dict(data=data, summary='제품과 회사 정보를 추출했습니다.', questions=['상표 등록 현황을 확인해 주세요.'], source_notes='회사소개서: 가온식품')


def test_hwpx_material_extracts_text_without_writing_upload(tmp_path):
    output = generate_documents(sample_data(), tmp_path)
    attachment = output['files'][0]
    part = prepare_materials([('../' + attachment['name'], attachment['bytes'])])[0].input_part()
    assert part['type'] == 'input_text' and '가온식품' in part['text']
    assert '../' not in part['text']


@pytest.mark.parametrize('filename,content', [('a.pdf', b'not pdf'), ('a.png', b'not image'), ('a.docx', b'not zip'), ('a.hwp', b'unsupported'), ('a.txt', b''), ('a.txt', b'\x00')])
def test_invalid_materials_are_rejected(filename, content):
    with pytest.raises(DocumentError):
        prepare_materials([(filename, content)])


def test_limits_are_checked_before_ai():
    with pytest.raises(DocumentError, match='5개'):
        prepare_materials([('a.txt', b'hello')] * (MAX_FILES + 1))
    with pytest.raises(DocumentError, match='10MB'):
        prepare_materials([('a.pdf', b'x' * (MAX_FILE_BYTES + 1))])


def test_archive_bomb_and_entities_are_rejected():
    for body in (b'<!DOCTYPE a [<!ENTITY a "x">]><a>&a;</a>', '<!DOCTYPE a [<!ENTITY a "x">]><a>&a;</a>'.encode('utf-16'), b'x' * (61 * 1024 * 1024)):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('Contents/section0.xml', body)
        with pytest.raises(DocumentError):
            prepare_materials([('a.hwpx', out.getvalue())])[0].input_part()


def test_structured_file_request_preserves_input_and_has_no_storage_password():
    data = sample_data()
    before = json.dumps(data, ensure_ascii=False)
    files = prepare_materials([('회사소개.txt', '회사 가온식품'.encode())])
    with patch('src.agent.settings', return_value={'OPENAI_API_KEY': 'test-secret', 'OPENAI_MODEL': 'configured-model'}), patch('src.agent.ai_ready', return_value=True), patch('src.agent.OpenAI') as client:
        api = client.return_value.__enter__.return_value.responses.parse
        api.return_value = SimpleNamespace(status='completed', output_parsed=AgentDraft.model_validate(agent_result()))
        result = compose_from_materials(data, files, '제품명 유지')
        assert result['data']['company']['nameKo'] == data['company']['nameKo']
        sent = api.call_args.kwargs
        assert sent['store'] is False and sent['model'] == 'configured-model'
        assert sent['input'][0]['content'][1]['type'] == 'input_file'
        assert 'test-secret' not in json.dumps(sent['input'])
        assert json.dumps(data, ensure_ascii=False) == before
        api.return_value = SimpleNamespace(status='incomplete', output_parsed=None)
        with pytest.raises(DocumentError):
            compose_from_materials(data, files, '수정')
        api.side_effect = APIConnectionError(request=None)
        with pytest.raises(DocumentError) as error:
            compose_from_materials(data, files, '수정')
        assert 'test-secret' not in str(error.value)


def test_temporary_generation_leaves_only_download_bytes(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    result = generate_documents(sample_data(), temporary=True)
    assert len(result['files']) == 2 and result['zip'] and result['folder'] == ''
    assert not list(tmp_path.iterdir())


def test_image_filename_is_included_with_image():
    files = prepare_materials([('제품사진.png', b'\x89PNG\r\n\x1a\n')])
    with patch('src.agent.settings', return_value={'OPENAI_API_KEY': 'test', 'OPENAI_MODEL': 'test'}), patch('src.agent.ai_ready', return_value=True), patch('src.agent.OpenAI') as client:
        api = client.return_value.__enter__.return_value.responses.parse
        api.return_value = SimpleNamespace(status='completed', output_parsed=AgentDraft.model_validate(agent_result()))
        compose_from_materials(sample_data(), files, '제품 정보 추출')
        content = api.call_args.kwargs['input'][0]['content']
        assert json.loads(content[1]['text'])['attachment_filename'] == '제품사진.png'
        assert content[2]['type'] == 'input_image'
