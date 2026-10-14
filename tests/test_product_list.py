import io
import xml.etree.ElementTree as ET
import zipfile

from src.config import TEMPLATES
from src.models import empty_product, sample_data
from src.product_list import NS, generate_product_list


def cells(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
    values = {}
    for cell in sheet.findall('.//s:sheetData/s:row/s:c', NS):
        values[cell.get('r')] = ''.join(cell.itertext())
    return sheet, values


def test_variants_form_four_columns_and_no_example_rows_remain():
    data = sample_data()
    data['products'][0]['variants'] = [{'name':'소포장', 'specification':'10개'}, {'name':'대포장', 'specification':'20개'}]
    second = empty_product()
    second.update(nameKo='두 번째 상품')
    data['products'].append(second)
    output, report = generate_product_list(data, TEMPLATES / 'product_list.xlsx')
    sheet, values = cells(output)
    assert values['A2'] == data['products'][0]['nameKo']
    assert values['C2'] == '소포장' and values['D2'] == '10개'
    assert values['C3'] == '대포장' and values['D3'] == '20개'
    assert values['A4'] == values['C4'] == '두 번째 상품'
    assert [values[f'B{i}'] for i in range(2, 5)] == ['1', '2', '1']
    assert values['D4'] == ''
    assert not any('샘플' in value for value in values.values())
    assert len(sheet.findall('s:sheetData/s:row', NS)) == 4
    assert sheet.find('s:conditionalFormatting', NS).get('sqref') == 'A2:D4'
    assert report['validation']['productRows'] == 3
    assert any('D4' in warning for warning in report['warnings'])


def test_excel_formula_like_user_values_are_literal_strings():
    data = sample_data()
    data['products'][0].update(nameKo='=1+1', variants=[{'name':'+SUM(1,2)', 'specification':'@test'}])
    output, _ = generate_product_list(data, TEMPLATES / 'product_list.xlsx')
    sheet, values = cells(output)
    assert values['A2'] == '=1+1' and values['C2'] == '+SUM(1,2)' and values['D2'] == '@test'
    assert not sheet.findall('.//s:sheetData//s:f', NS)
    assert all(cell.get('t') == 'inlineStr' for cell in sheet.findall('.//s:sheetData/s:row/s:c', NS)
               if cell.get('r') in {'A2', 'C2', 'D2'})
