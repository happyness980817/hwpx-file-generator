"""One strict schema shared by extraction, manual editing and saved drafts."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from .models import empty_data, PLAN_FIELDS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


def text_model(name, fields, overrides=None, maximum=500):
    definitions = {key: (str, Field(max_length=maximum)) for key in fields}
    definitions.update(overrides or {})
    return create_model(name, __base__=StrictModel, **definitions)


_blank = empty_data()
Production = Literal['', '자체생산', '위탁생산(OEM/ODM)', '자체/위탁 병행생산']
Method = Literal['', '라벨', '맞춤제작']
Company = text_model('Company', _blank['company'], {'nameKo': (str, Field(max_length=80)), 'category': (Literal['', '중소기업', '중견기업', '대기업'], ...)})
Contact = text_model('Contact', _blank['contact'])
Provider = text_model('Provider', _blank['provider'])
Country = text_model('Country', ['country', 'trademarkStatus', 'trademarkNumberOrReason', 'quantity', 'method'], {'trademarkStatus': (Literal['', '등록완료', '출원중', '미출원'], ...), 'method': (Method, ...)})
Factory = text_model('Factory', ['country', 'productionType'], {'productionType': (Production, ...)})
Product = text_model('Product', _blank['products'][0], {
    'certificationHeld': (Literal['', '유', '무'], ...),
    'productionLocation': (Literal['', '국내생산', '해외생산', '국내/해외 병행생산'], ...),
    'productionType': (Production, ...),
    'countries': (list[Country], Field(max_length=3)),
    'factories': (list[Factory], Field(max_length=4)),
})
Plan = text_model('Plan', PLAN_FIELDS, {
    'channels': (list[Literal['제품', '포장', '온라인몰', '홈페이지/SNS', '전시·박람회', '기타']], Field(max_length=6)),
    'ipHistory': (Literal['', '없음', '있음'], ...),
}, maximum=1800)


class DocumentInput(StrictModel):
    company: Company
    contact: Contact
    manager: Contact
    provider: Provider
    projectType: Method
    applicationDate: str = Field(max_length=10)
    products: list[Product] = Field(min_length=1, max_length=1)
    plan: Plan

    @field_validator('applicationDate')
    @classmethod
    def valid_date(cls, value):
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError('날짜는 YYYY-MM-DD 형식이어야 합니다.')
        return value


class AgentDraft(StrictModel):
    data: DocumentInput
    summary: str = Field(max_length=1600)
    questions: list[str] = Field(max_length=15)
    source_notes: str = Field(max_length=12000)
