"""Validate required fields only when submitting; incomplete previews are allowed."""
import re
from .errors import DocumentError


def validate_submission(data):
    required = [('company', 'nameKo', '회사명'), ('company', 'representative', '대표자'),
                ('company', 'registrationNumber', '사업자등록번호'), ('company', 'address', '주소'),
                ('contact', 'name', '담당자'), ('contact', 'phone', '연락처'), ('contact', 'email', '이메일')]
    missing = [label for section, key, label in required if not data[section][key].strip()]
    for index, product in enumerate(data['products'], 1):
        for key, label in [('brandKo', '브랜드명'), ('nameKo', '대상제품')]:
            if not product[key].strip():
                missing.append(f'상품 {index} {label}')
        if not product['countries']:
            missing.append(f'상품 {index} 수출국가')
    if missing:
        raise DocumentError('필수항목을 입력해 주세요: ' + ', '.join(missing))
    number = data['company']['registrationNumber']
    if len(re.sub(r'[-\s]', '', number)) != 10 or not re.fullmatch(r'[0-9\s-]+', number):
        raise DocumentError('사업자등록번호는 숫자 10자리로 입력해 주세요.')
    if not re.fullmatch(r'0\d{1,3}-\d{3,4}-\d{4}', data['contact']['phone']):
        raise DocumentError('연락처의 가운데 번호와 끝 번호를 확인해 주세요.')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', data['contact']['email'].strip()):
        raise DocumentError('이메일 주소를 확인해 주세요.')
