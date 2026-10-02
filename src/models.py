"""Input schema, fictional examples and change detection."""
import hashlib
import json

PLAN_FIELDS = {
    "counterfeitRisk": "위조 피해·우려",
    "ipDefense": "해외 지식재산권·방어역량",
    "countries": "활용국가",
    "channelPlan": "활용채널 상세 계획",
    "marketing": "수출 마케팅 전략",
    "expectedEffects": "기대효과",
    "improvement": "개선계획",
}
CHANNELS = ["제품", "포장", "온라인몰", "홈페이지/SNS", "전시·박람회", "기타"]


def empty_data() -> dict:
    return {
        "company": {k: "" for k in ("nameKo", "nameEn", "registrationNumber", "representative", "address", "department", "category")},
        "contact": {"name": "", "phone": "", "email": ""},
        "manager": {"name": "", "phone": "", "email": ""},
        "provider": {"name": "", "contact": "", "phone": ""},
        "projectType": "", "applicationDate": "",
        "products": [{**{k: "" for k in ("brandKo", "brandEn", "nameKo", "nameEn", "category", "exportScale", "certificationHeld", "certifications", "trademarks", "productionLocation", "productionType")}, "countries": [], "factories": []}],
        "plan": {**{k: "" for k in PLAN_FIELDS}, "channels": [], "ipHistory": ""},
    }


def sample_data() -> dict:
    data = empty_data()
    data["company"].update(nameKo="가온식품(테스트)", nameEn="GAON FOODS TEST", representative="테스트 대표", department="해외영업팀", category="중소기업")
    data["contact"].update(name="테스트 담당자", email="sales@example.com")
    data["projectType"] = "라벨"
    data["products"][0].update(brandKo="가온", brandEn="GAON", nameKo="현미 과자(테스트)", nameEn="BROWN RICE SNACK TEST", category="가공식품", productionLocation="국내생산", productionType="위탁생산(OEM/ODM)", countries=[{"country": "일본", "trademarkStatus": "", "trademarkNumberOrReason": "", "quantity": "", "method": "라벨"}], factories=[{"country": "대한민국", "productionType": "위탁생산(OEM/ODM)"}])
    data["plan"]["channels"] = ["포장", "온라인몰"]
    return data


def example_plan(data: dict) -> dict:
    countries = ", ".join(r["country"] for r in data["products"][0]["countries"] if r.get("country")) or "대상국 확인 필요"
    return {
        "counterfeitRisk": "[테스트 예시] 유사 상품과의 혼동을 줄이기 위한 표시 방안을 검토합니다. 실제 위조 피해 발생 여부와 사례는 고객사 확인이 필요합니다.",
        "ipDefense": "[테스트 예시] 국가별 상표 출원·등록 현황과 권리 보호 담당 체계를 확인한 뒤 대응 계획을 구체화합니다.",
        "countries": f"[테스트 예시] {countries}. 실제 사업 대상국과 판매 현황은 고객사 확인이 필요합니다.",
        "channelPlan": "[테스트 예시] 선택한 활용채널에 인증상표를 적용하는 방안을 검토합니다. 적용 위치·수량·일정은 확인 후 확정합니다.",
        "marketing": "[테스트 예시] 현지 유통채널에 제품 정보를 일관되게 제공하고 소비자 안내 자료를 정비하는 방안을 제안합니다.",
        "expectedEffects": "[테스트 예시] 제품 식별과 소비자 정보 전달 개선을 기대합니다. 매출·수출 증가 수치는 근거 확인 전 기재하지 않습니다.",
        "improvement": "[테스트 예시] 상표 표시 기준과 담당자 점검 절차를 정리하는 방안을 제안합니다. 분쟁 이력은 별도 확인이 필요합니다.",
    }


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


