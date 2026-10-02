import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import zipfile

import pytest

from src.errors import DocumentError
from src.models import empty_data, example_plan, sample_data
from src.service import generate_documents


def test_real_generator_and_isolated_jobs(tmp_path):
    data = sample_data()
    data["company"]["nameKo"] = "테스트 & <고객>"
    data["plan"].update(example_plan(data))
    data["plan"]["marketing"] = "첫째 줄 & 검증\n둘째 줄 <입력>"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: generate_documents(data, tmp_path), range(2)))
    assert results[0]["folder"] != results[1]["folder"]
    for result in results:
        assert len(result["files"]) == 2
        with zipfile.ZipFile(io.BytesIO(result["zip"])) as archive:
            assert len(archive.namelist()) == 2
        for file in result["files"]:
            with zipfile.ZipFile(io.BytesIO(file["bytes"])) as hwpx:
                assert hwpx.testzip() is None
                assert hwpx.infolist()[0].filename == "mimetype"
                assert hwpx.infolist()[0].compress_type == zipfile.ZIP_STORED
                text = hwpx.read("Preview/PrvText.txt").decode("utf-8")
                assert "테스트 & <고객>" in text
                if "활용계획서" in file["name"]:
                    assert data["plan"]["marketing"] in text


def test_missing_company_and_no_external_runtime(tmp_path):
    with pytest.raises(DocumentError, match="회사명"):
        generate_documents(empty_data(), tmp_path)
    with patch("subprocess.Popen", side_effect=AssertionError("External runtime forbidden")):
        result = generate_documents(sample_data(), tmp_path)
        assert len(result["files"]) == 2


def test_invalid_date(tmp_path):
    data = sample_data()
    data["applicationDate"] = "2026-02-30"
    with pytest.raises(DocumentError, match="실제 날짜"):
        generate_documents(data, tmp_path)


def test_ai_errors_keep_secrets_private():
    from openai import APIConnectionError
    from src.ai import draft_with_ai
    with patch("src.ai.settings", return_value={"OPENAI_API_KEY": "sk-private-test", "OPENAI_MODEL": "test"}), patch("openai.OpenAI") as client:
        client.return_value.__enter__.return_value.responses.parse.side_effect = APIConnectionError(request=None)
        with pytest.raises(DocumentError) as exc:
            draft_with_ai(sample_data(), "자료", "요청")
        assert "sk-private-test" not in str(exc.value)
