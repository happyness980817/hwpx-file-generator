"""Required submission fields and contact validation, without external services."""
import copy

import pytest

from src.errors import DocumentError
from src.models import apply_form_defaults, empty_product, sample_data
from src.submission import validate_submission


def valid_data():
    data = apply_form_defaults(sample_data())
    data['company'].update(registrationNumber='123-45-67890', address='서울특별시 강남구 테스트로 1')
    data['contact']['phone'] = '010-1234-5678'
    return data


def test_complete_manual_submission_needs_neither_files_password_nor_plan_examples():
    data = valid_data()
    before = copy.deepcopy(data)
    assert validate_submission(data) is None
    assert data == before
    assert data['plan']['marketing'] == ''
    assert 'password' not in data and 'materials' not in data


@pytest.mark.parametrize('section,key,label', [
    ('company', 'nameKo', '회사명'), ('company', 'representative', '대표자'),
    ('company', 'registrationNumber', '사업자등록번호'), ('company', 'address', '주소'),
    ('contact', 'name', '담당자'), ('contact', 'phone', '연락처'), ('contact', 'email', '이메일'),
])
def test_every_required_company_and_contact_field_is_enforced(section, key, label):
    data = valid_data()
    data[section][key] = '   '
    with pytest.raises(DocumentError, match=label):
        validate_submission(data)


def test_each_added_product_requires_brand_target_and_country():
    data = valid_data()
    data['products'].append(empty_product())
    with pytest.raises(DocumentError) as failure:
        validate_submission(data)
    assert all(label in str(failure.value) for label in ['상품 2 브랜드명', '상품 2 대상제품', '상품 2 수출국가'])


@pytest.mark.parametrize('value', ['123-45-6789', '123-45-678901', '123-45-ABCDE', '=1234567890'])
def test_invalid_registration_numbers(value):
    data = valid_data()
    data['company']['registrationNumber'] = value
    with pytest.raises(DocumentError, match='사업자등록번호'):
        validate_submission(data)


@pytest.mark.parametrize('value', ['010-12-5678', '010-1234-567', '010-ABCD-5678', '010-1234-56789'])
def test_incomplete_or_invalid_phone(value):
    data = valid_data()
    data['contact']['phone'] = value
    with pytest.raises(DocumentError, match='연락처'):
        validate_submission(data)


@pytest.mark.parametrize('value', ['010-1234-5678', '02-123-4567', '031-1234-5678', '0502-1234-5678'])
def test_mobile_and_landline_phone_formats(value):
    data = valid_data()
    data['contact']['phone'] = value
    assert validate_submission(data) is None


@pytest.mark.parametrize('value', ['sales', 'sales@company', 'sales company@example.com', 'sales@@example.com'])
def test_invalid_email(value):
    data = valid_data()
    data['contact']['email'] = value
    with pytest.raises(DocumentError, match='이메일'):
        validate_submission(data)
