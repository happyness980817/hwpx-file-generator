"""Bounded material uploads; originals stay in server session memory only."""
import base64
from dataclasses import dataclass
import io
from pathlib import PurePosixPath
import re
import zipfile
from xml.etree import ElementTree as ET

from .errors import DocumentError

MAX_FILES = 5
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MIME = {
    '.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.txt': 'text/plain', '.csv': 'text/csv', '.hwpx': 'application/hwp+zip',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
}
EXTENSIONS = [ext[1:] for ext in MIME]


@dataclass(frozen=True)
class Material:
    name: str
    content: bytes

    def input_part(self):
        ext = PurePosixPath(self.name).suffix.lower()
        if ext == '.hwpx':
            return {'type': 'input_text', 'text': f'첨부 자료 {self.name}\n{hwpx_text(self.content)}'}
        encoded = base64.b64encode(self.content).decode('ascii')
        data_url = f'data:{MIME[ext]};base64,{encoded}'
        if MIME[ext].startswith('image/'):
            return {'type': 'input_image', 'image_url': data_url, 'detail': 'auto'}
        return {'type': 'input_file', 'filename': self.name, 'file_data': data_url}


def _zip_entries(content, ext):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(item.file_size for item in entries) > 60 * 1024 * 1024:
                raise DocumentError('압축을 풀었을 때 너무 큰 문서입니다. 필요한 부분을 PDF로 저장해 주세요.')
            if any(item.flag_bits & 1 for item in entries):
                raise DocumentError('암호가 설정된 문서는 암호를 해제한 뒤 올려 주세요.')
            required = {'.docx': 'word/document.xml', '.pptx': 'ppt/presentation.xml', '.xlsx': 'xl/workbook.xml', '.hwpx': 'Contents/section0.xml'}[ext]
            if required not in archive.namelist():
                raise DocumentError('파일 내용과 확장자가 일치하지 않습니다.')
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise DocumentError('문서 파일이 손상되었습니다. 다시 저장한 파일을 올려 주세요.') from exc


def hwpx_text(content):
    _zip_entries(content, '.hwpx')
    pieces = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        sections = sorted((name for name in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml', name)), key=lambda name: int(re.search(r'\d+', name)[0]))
        for name in sections:
            try:
                raw = archive.read(name)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError) as exc:
                raise DocumentError('HWPX 본문을 읽을 수 없습니다. 다시 저장한 파일을 올려 주세요.') from exc
            # XML may be UTF-16/32: remove encoding padding before checking declarations.
            declaration_bytes = raw.replace(b'\x00', b'').upper()
            if b'<!DOCTYPE' in declaration_bytes or b'<!ENTITY' in declaration_bytes:
                raise DocumentError('이 HWPX의 XML 선언은 지원하지 않습니다.')
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                raise DocumentError('HWPX 본문을 읽을 수 없습니다.') from exc
            pieces.extend(''.join(node.itertext()) for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 't')
    text = '\n'.join(pieces)
    if len(text) > 60000:
        raise DocumentError('HWPX 본문이 너무 깁니다. 필요한 부분을 나누어 올려 주세요.')
    if not text.strip():
        raise DocumentError('HWPX에서 글자를 찾지 못했습니다. PDF로 저장해서 올려 주세요.')
    return text


def prepare_materials(entries):
    if len(entries) > MAX_FILES:
        raise DocumentError('자료는 한 번에 최대 5개까지 올려 주세요.')
    if sum(len(content) for _, content in entries) > MAX_TOTAL_BYTES:
        raise DocumentError('자료 전체 크기는 25MB 이하여야 합니다.')
    result = []
    for filename, content in entries:
        name = PurePosixPath(filename.replace('\\', '/')).name
        ext = PurePosixPath(name).suffix.lower()
        if ext not in MIME:
            raise DocumentError('지원하지 않는 파일입니다. HWP 파일은 PDF 또는 HWPX로 저장해 주세요.')
        if not content or len(content) > MAX_FILE_BYTES:
            raise DocumentError('빈 파일은 사용할 수 없으며, 파일당 최대 크기는 10MB입니다.')
        if ext in ('.docx', '.pptx', '.xlsx', '.hwpx'):
            _zip_entries(content, ext)
        if ext == '.pdf' and not content.lstrip().startswith(b'%PDF-'):
            raise DocumentError('올바른 PDF 파일이 아닙니다.')
        signatures = {'.png': b'\x89PNG\r\n\x1a\n', '.jpg': b'\xff\xd8\xff', '.jpeg': b'\xff\xd8\xff', '.webp': b'RIFF'}
        if ext in signatures and not content.startswith(signatures[ext]):
            raise DocumentError('이미지 형식을 확인해 주세요.')
        if ext == '.webp' and content[8:12] != b'WEBP':
            raise DocumentError('올바른 WebP 파일이 아닙니다.')
        if ext in ('.txt', '.csv'):
            try:
                text = content.decode('utf-8-sig')
            except UnicodeDecodeError:
                try:
                    text = content.decode('cp949')
                except UnicodeDecodeError as exc:
                    raise DocumentError('텍스트 파일은 UTF-8 또는 한국어 인코딩으로 저장해 주세요.') from exc
            if '\x00' in text or len(text) > 60000:
                raise DocumentError('텍스트가 너무 길거나 올바르지 않습니다. 필요한 부분만 올려 주세요.')
            content = text.encode('utf-8')
        result.append(Material(name[:180 - len(ext)] + ext if len(name) > 180 else name, content))
    return result
