"""Create isolated local outputs and prepare five download files plus a ZIP."""
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
from .product_list import generate_product_list


def generate_documents(data: dict, output_root: Path | None = None, *, temporary=False) -> dict:
    if temporary:
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="kbrand-") as folder:
            result = _generate_documents(data, Path(folder))
            result["folder"] = ""
            return result
    return _generate_documents(data, output_root)


def _generate_documents(data: dict, output_root: Path | None = None) -> dict:
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
        if len(files) != 4:
            raise ValueError("Expected four HWPX files")
    except (ValueError, KeyError, OSError) as exc:
        raise DocumentError("생성 결과 검증에 실패했습니다. 파일을 제공하지 않습니다.") from exc
    content, validation = generate_product_list(data, TEMPLATES / 'product_list.xlsx')
    name = files[0]['name'].removesuffix('_사용신청서_검토용.hwpx') + '_상품리스트.xlsx'
    (generated_dir / name).write_bytes(content)
    files.append({'name': name, 'bytes': content})
    report['files'].append({'filename': name, **validation})
    (generated_dir / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for item in files:
            z.writestr(item["name"], item["bytes"])
    return {"files": files, "zip": archive.getvalue(), "report": report, "folder": str(generated_dir), "fingerprint": fingerprint(data)}


