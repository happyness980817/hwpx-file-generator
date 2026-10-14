"""Display-only examples from the supplied K-brand forms.

Never merge these examples into document data or send them to the writing agent
as company evidence. A placeholder is not a supplied answer.

Certification source: [별첨2] 제품별 인증제도 예시.hwp, Google Drive file
1BZAPVQCboD3SNgmS7-MatvLTEzmjl7ab (24 product groups, 26 distinct schemes).
Only spacing/punctuation variants of the same scheme have been deduplicated.
Plan source: user-supplied 필작성[붙임2] 국가인증상표 도입 필요성 및 활용계획서.hwp.
The source's checked channels/dispute history are examples, not default answers.
"""

CERTIFICATIONS: list[str] = [
    "단체표준인증",
    "우수화장품 제조 및 품질관리기준",
    "환경성적표지인증",
    "신제품인증(NEP 마크)",
    "환경표지 인증",
    "식품 HACCP",
    "방송통신기자재 등의 적합성평가",
    "에너지소비효율등급표시제도",
    "ICT 융합 품질인증",
    "전기용품 및 생활용품 안전관리제도(KC)",
    "정보통신망연결기기 정보보호인증",
    "KS 표시인증제도",
    "의료기기 허가",
    "전승공예품인증",
    "유기가공식품 인증",
    "농산물·농산가공품의 품위·성분 및 유해물질 등 검정",
    "어린이기호식품 품질인증",
    "농산물우수관리인증 (GAP)",
    "친환경농축산물 인증",
    "산림인증제도(KFCC)",
    "우수문화상품 지정",
    "고령친화 우수제품",
    "건강기능식품 기능성 원료 및 기준·규격 인정",
    "전통식품품질 인증",
    "해외 우수 한식당 지정",
    "우수 외식사업자 지정",
]

PLAN_PLACEHOLDERS: dict[str, str] = {
    "counterfeitRisk": (
        "(예시) 당사의 양반김 관련 제품 중에서 이와 비슷한 양산김이라는 모방품이 "
        "유통되고 있으며 이를 통해 당사 제품의 매출 감소 가능성이 있음. "
        "본 제품의 디자인을 모방한 제품이 나오고 있어 매출 감소 피해가 우려됨."
    ),
    "ipDefense": (
        "(예시) 현재까지는 신고, 삭제요청, 경고, 법적조치를 취하였으나, "
        "현지 대응 당국의 느린 대처로 많은 피해가 발생하고 있었음. "
        "법률대리인을 꾸리기에도 많은 시간과 비용이 들고 다양한 의사결정이 "
        "필요했기 때문에 매번 불편함을 느낌."
    ),
    "countries": "(예시) 인도",
    "channelPlan": (
        "(예시) 인도 포장지에 K라벨 부착이 되어 인도 제품 판매 시 이를 활용하여 "
        "고객이 K라벨을 보고 이를 통한 매출 증대 예상. 추가로 유튜브 SNS에 "
        "‘당사 K라벨을 확인하세요’를 통해서 제품의 신뢰도 제고 향상 예상."
    ),
    "marketing": (
        "(예시) 유튜브 SNS에 ‘당사 K라벨을 확인하세요’를 통해서 "
        "제품의 신뢰도 제고 향상 예상."
    ),
    "expectedEffects": (
        "(예시) 인도 포장지에 K라벨 부착이 되어 인도 제품 판매 시 이를 활용하여 "
        "고객이 K라벨을 보고 이를 통한 매출 증대 예상. 추가로 유튜브 SNS에 "
        "‘당사 K라벨을 확인하세요’를 통해서 제품의 신뢰도 제고 향상 예상. "
        "아울러 이를 통해 K라벨을 신뢰하고 구매하는 고객을 통해 "
        "약 10%가량의 매출 향상 기대."
    ),
    "improvement": (
        "(예시) 현재는 가품 이슈가 크게는 없어도 심증적으로 일부 가품이 "
        "나오는 것으로 추정됨. 다만 이력관리 데이터가 없어 이를 구체적으로 "
        "알아보기 어려움."
    ),
}

FIELD_PLACEHOLDERS: dict[str, str] = {
    "company.nameKo": "(예시) 삼성전자",
    "company.nameEn": "(예시) SAMSUNG ELECTRONICS",
    "company.registrationNumber": "(예시) 123-45-67890",
    "company.representative": "(예시) 홍길동",
    "company.address": "(예시) 서울특별시 강남구 ○○로 123",
    "company.department": "(예시) 해외영업팀",
    "contact.name": "(예시) 홍길동",
    "contact.email": "(예시) sales@example.com",
    "manager.name": "(예시) 김담당",
    "manager.email": "(예시) manager@example.com",
    "product.brandKo": "(예시) 삼성 갤럭시 S24",
    "product.brandEn": "(예시) SAMSUNG Galaxy S24",
    "product.nameKo": "(예시) 스마트폰",
    "product.nameEn": "(예시) Smartphone",
    "product.category": "(예시) 전기·전자",
    "product.exportScale": "(예시) 2027년 수출 예상액 100만 달러",
    "country.trademarkNumberOrReason": "(예시) 출원·등록번호 또는 미출원 사유",
    "variant.name": "(예시) 갤럭시 S24 256GB",
    "variant.specification": "(예시) 256GB / 검정",
}
