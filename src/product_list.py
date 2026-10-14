"""Fill the reviewed four-column Excel template without an Office runtime."""
import copy
import hashlib
import io
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from .errors import DocumentError
from .hwpx import string_value

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
ET.register_namespace('', NS['s'])


def product_rows(data):
    rows = []
    for product in data['products']:
        variants = product.get('variants') or [{}]
        # An empty UI row does not override a known product name.
        for index, variant in enumerate(variants, 1):
            rows.append([
                product.get('nameKo', ''), index,
                variant.get('name') or product.get('nameKo', ''),
                variant.get('specification', ''),
            ])
    return rows


def generate_product_list(data, template: Path):
    rows = product_rows(data)
    with zipfile.ZipFile(template) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    sheet = ET.fromstring(entries['xl/worksheets/sheet1.xml'])
    body = sheet.find('s:sheetData', NS)
    prototype = copy.deepcopy(body.findall('s:row', NS)[1])
    for row in body.findall('s:row', NS)[1:]:
        body.remove(row)
    warnings = []
    for number, values in enumerate(rows, 2):
        row = copy.deepcopy(prototype)
        row.set('r', str(number))
        for col, cell, value in zip('ABCD', row.findall('s:c', NS), values, strict=True):
            cell.set('r', f'{col}{number}')
            for child in list(cell):
                cell.remove(child)
            if col == 'B':
                cell.set('t', 'n')
                ET.SubElement(cell, f"{{{NS['s']}}}v").text = str(value)
            else:
                text = string_value(value, f'상품리스트 {col}{number}')
                cell.set('t', 'inlineStr')
                inline = ET.SubElement(cell, f"{{{NS['s']}}}is")
                node = ET.SubElement(inline, f"{{{NS['s']}}}t")
                node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                node.text = text
                if not text:
                    warnings.append(f'상품리스트 {col}{number}: 확인 필요')
        body.append(row)
    last = len(rows) + 1
    dimension = sheet.find('s:dimension', NS)
    if dimension is not None:
        dimension.set('ref', f'A1:D{last}')
    for rule in sheet.findall('s:conditionalFormatting', NS):
        rule.set('sqref', f'A2:D{last}')
    entries['xl/worksheets/sheet1.xml'] = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    content = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise DocumentError('상품리스트 파일 검증에 실패했습니다.')
        for name in archive.namelist():
            if name.endswith('.xml'):
                ET.fromstring(archive.read(name))
    return content, dict(sha256=hashlib.sha256(content).hexdigest(), bytes=len(content),
                        validation={'zipCRC': 'pass', 'productRows': len(rows)}, warnings=warnings)
