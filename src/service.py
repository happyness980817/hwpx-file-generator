"""Create isolated local outputs and prepare two download files plus a ZIP."""
from pathlib import Path
import hashlib
import io
import json
import uuid
import zipfile

from .config import ROOT, TEMPLATES
from .errors import DocumentError
from .hwpx import generate, validate_input
from .models import fingerprint


def generate_documents(data: dict, output_root: Path | None = None) -> dict:
    validate_input(data)
    try:
        input_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DocumentError("입력에 XML에 쓸 수 없는 제어문자입니다.") from exc
    job = (output_root or ROOT / "result") / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=False)
    input_path = job / "input.json"
    input_path.write_bytes(input_bytes)
    generated_dir, report = generate(input_path, job, TEMPLATES)
    try:
        generated_dir = generated_dir.resolve()
        if not generated_dir.is_relative_to(job.resolve()):
            raise ValueError("Unexpected output path")
        files = []
        for item in report["files"]:
            target = (generated_dir / item["filename"]).resolve()
            if target.parent != generated_dir or target.suffix != ".hwpx":
                raise ValueError("Unexpected filename")
            content = target.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Output hash mismatch")
            files.append({"name": target.name, "bytes": content})
        if len(files) != 2:
            raise ValueError("Expected two files")
    except (ValueError, KeyError, OSError) as exc:
        raise DocumentError("생성 결과 검증에 실패했습니다. 파일을 제공하지 않습니다.") from exc
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for item in files:
            z.writestr(item["name"], item["bytes"])
    return {"files": files, "zip": archive.getvalue(), "report": report, "folder": str(generated_dir), "fingerprint": fingerprint(data)}


