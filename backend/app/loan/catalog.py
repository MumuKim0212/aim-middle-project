"""[역할] 기준 데이터 원본: 상품 13종·체험 고객·사유 코드·동의 코드·서류 양식·보증/협약/정책 기준(모두 예시값)."""
from __future__ import annotations

from decimal import Decimal as D

TYPE_NM = {"GENERAL": "일반대출", "POLICY": "정부대출", "INST": "기관대출", "REFI": "대환대출"}
CAT_NM = {"CREDIT": "신용", "JEONSE": "전월세", "MORTGAGE": "주택담보", "AUTO": "자동차", "DEPOSIT": "예금담보"}
T5 = [12, 24, 36, 48, 60]
R3 = ["원리금균등분할", "만기일시상환", "원금균등분할"]

# id, type, inst_kind, cat, subtitle, name, max, min, rate_min, rate_max, terms, repay, target
PRODUCTS = [
    ("g1", "GENERAL", None, "CREDIT", "바로 쓰는 직장인 신용대출", "OO 직장인 신용대출", 100_000_000, 1_000_000, "4.3", "7.9", T5, R3, "재직 3개월 이상 급여소득자"),
    ("g2", "GENERAL", None, "JEONSE", "쉽고 빠른 전월세보증금대출", "OO 스마트 전세대출", 222_000_000, 10_000_000, "3.6", "5.2", [24], ["만기일시상환"], "임차보증금 5% 이상 지급한 무주택 세대주"),
    ("g3", "GENERAL", None, "MORTGAGE", "내 집 마련 주택담보대출", "OO 주택담보대출", 1_000_000_000, 10_000_000, "3.9", "5.6", [120, 240, 360], ["원리금균등분할", "원금균등분할"], "주택 구입 예정자·보유자"),
    ("g4", "GENERAL", None, "AUTO", "신차·중고차 구입자금", "OO 오토론", 100_000_000, 3_000_000, "4.9", "8.9", T5, ["원리금균등분할"], "자동차 구입 예정자"),
    ("g5", "GENERAL", None, "DEPOSIT", "예금 해지 없이 급전 마련", "OO 예금담보대출", 300_000_000, 1_000_000, "3.5", "4.5", [12], ["만기일시상환"], "OO은행 예금 보유 고객"),
    ("p1", "POLICY", None, "MORTGAGE", "무주택 서민 내 집 마련", "정책 주택구입자금 (디딤돌형)", 250_000_000, 10_000_000, "2.6", "3.9", [120, 240, 360], ["원리금균등분할", "원금균등분할"], "무주택 세대주, 부부합산 소득·순자산 기준 충족 (공고 기준)"),
    ("p2", "POLICY", None, "JEONSE", "무주택 세대주 전세자금", "정책 전세자금 (버팀목형)", 120_000_000, 10_000_000, "2.3", "3.3", [24], ["만기일시상환"], "무주택 세대주, 소득·자산 기준 충족 (공고 기준)"),
    ("i1", "INST", "A", "JEONSE", "보증기관 보증으로 한도 UP", "OO 보증부 전세대출 (HUG·HF·SGI)", 500_000_000, 10_000_000, "3.4", "4.9", [24], ["만기일시상환"], "보증기관 보증 대상 임차인"),
    ("i2", "INST", "B", "CREDIT", "협약기관 임직원 전용 우대", "OO 협약기관 임직원 신용대출", 150_000_000, 1_000_000, "3.9", "5.5", T5, ["원리금균등분할", "만기일시상환"], "협약기관 정규직 임직원"),
    ("r1", "REFI", None, "CREDIT", "고금리 신용대출 갈아타기", "OO 신용대출 갈아타기", 100_000_000, 1_000_000, "4.5", "7.5", T5, ["원리금균등분할"], "타 금융사 신용대출 보유자"),
    ("r2", "REFI", None, "MORTGAGE", "주담대 이자 줄이기", "OO 주택담보대출 갈아타기", 1_000_000_000, 10_000_000, "3.8", "5.2", [120, 240, 300, 360], ["원리금균등분할"], "타 금융사 주택담보대출 보유자"),
    ("r3", "REFI", None, "JEONSE", "전세대출 갈아타기", "OO 전세대출 갈아타기", 500_000_000, 10_000_000, "3.5", "4.6", [24], ["만기일시상환"], "타 금융사 전세자금대출 보유자"),
    ("r4", "REFI", None, "AUTO", "자동차 할부 갈아타기", "OO 오토 대환", 100_000_000, 3_000_000, "5.2", "8.5", T5, ["원리금균등분할"], "캐피탈 자동차 할부 보유자"),
]


def _e(inst, kind, bal, rate, since, remain, total, monthly, prepay, bullet=False, **flags):
    return {"institution": inst, "kind": kind, "balance": bal, "rate": rate, "since": since, "remain": remain,
            "total": total, "monthly": monthly, "prepay": prepay, "bullet": bullet, "flags": flags}


_KIM = _e("다온캐피탈(가상)", "신용대출", 12_400_000, "12.9", 30, 30, 60, 410_000, "1.5")
_PARK = _e("가나은행(가상)", "전세자금대출", 120_000_000, "4.9", 8, 16, 24, 490_000, "0.7", True)
_NAM = _e("가나은행(가상)", "주택담보대출", 350_000_000, "5.2", 65, 295, 360, 1_920_000, "1.2")
_LIM = _e("다온캐피탈(가상)", "자동차 할부", 28_000_000, "9.9", 21, 39, 60, 590_000, "1.0")

# 체험 고객 (Customer_Submission_Documents/README.md 정답표 기준)
SCENARIOS = {
    "KIM_OK": {"label": "Kim 김민수 · 적합 (신용)", "profile": {"name": "김민수", "job": "급여소득자", "tenure": 80, "income": 62_000_000, "debt_monthly": 410_000, "score": 880, "inquiries": 1}, "loans": [_KIM], "defects": []},
    "KIM_BAD": {"label": "Kim 김민수 · 부적합 (양식 불량 + 신용 부족)", "profile": {"name": "김민수", "job": "급여소득자", "tenure": 80, "income": 62_000_000, "debt_monthly": 1_650_000, "score": 520, "inquiries": 7, "delinq_current": True, "multi_debt": 5}, "loans": [{**_KIM, "flags": {"delinq": True}}], "defects": ["CONSENT-DENIED", "SIGN-MISSING", "FIELD-BLANK", "DOC-EXPIRED", "DOC-OUTDATED", "NAME-MISMATCH"]},
    "PARK_OK": {"label": "Park 박지영 · 적합 (전세)", "profile": {"name": "박지영", "job": "급여소득자", "tenure": 58, "income": 43_000_000, "debt_monthly": 490_000, "score": 820, "inquiries": 1, "deposit": 200_000_000, "value": 320_000_000, "senior": 0}, "loans": [_PARK], "defects": []},
    "PARK_BAD": {"label": "Park 박지영 · 부적합 (담보·소득 부족)", "profile": {"name": "박지영", "job": "급여소득자", "tenure": 4, "income": 18_000_000, "debt_monthly": 490_000, "score": 820, "inquiries": 1, "deposit": 200_000_000, "value": 260_000_000, "senior": 180_000_000}, "loans": [{**_PARK, "since": 22, "remain": 2, "flags": {"doc_expired": True}}], "defects": ["PARTY-MISMATCH", "MISSING-CERT"]},
    "NAM_OK": {"label": "Nam 남준호 · 적합 (주택담보)", "profile": {"name": "남준호", "job": "급여소득자", "tenure": 220, "income": 130_000_000, "debt_monthly": 1_920_000, "score": 910, "inquiries": 1, "value": 710_000_000, "price": 700_000_000, "amount": 400_000_000, "term": 360}, "loans": [_NAM], "defects": []},
    "NAM_BAD": {"label": "Nam 남준호 · 부적합 (LTV·DSR 초과)", "profile": {"name": "남준호", "job": "급여소득자", "tenure": 55, "income": 36_000_000, "debt_monthly": 3_430_000, "score": 760, "inquiries": 3, "value": 520_000_000, "price": 550_000_000, "amount": 450_000_000, "term": 360}, "loans": [{**_NAM, "since": 2, "remain": 358, "monthly": 1_930_000, "flags": {"legal": True}}], "defects": []},
    "LIM_OK": {"label": "Lim 임소라 · 적합 (자동차, 개인사업자)", "profile": {"name": "임소라", "job": "개인사업자", "tenure": 91, "income": 54_000_000, "debt_monthly": 590_000, "score": 840, "inquiries": 1, "price": 42_000_000, "amount": 35_000_000, "term": 60}, "loans": [_LIM], "defects": []},
    "LIM_BAD": {"label": "Lim 임소라 · 부적합 (소득·신용 부족 + 위변조 의심)", "profile": {"name": "임소라", "job": "개인사업자", "tenure": 91, "income": 9_000_000, "debt_monthly": 2_310_000, "score": 610, "inquiries": 9, "multi_debt": 6, "biz_closed": True, "price": 42_000_000, "amount": 45_000_000, "term": 60}, "loans": [{**_LIM, "flags": {"asset_mismatch": True}}], "defects": ["BIZ-MISMATCH", "ALTERED", "SIGN-MISSING"]},
}
DEFAULT_EXISTING = [_KIM, _e("나래카드(가상)", "카드론", 5_000_000, "15.9", 3, 33, 36, 170_000, "1.0")]

# 사유 코드: code → (group, message, fixable)
REASON_CODES = {
    "CONSENT-DENIED": ("CON", "제출한 동의서에서 필수 '신용정보 조회'가 동의하지 않음으로 표시됨", True),
    "CONSENT-MISSING": ("CON", "필요한 동의가 없어 조회할 수 없음", True),
    "SIGN-MISSING": ("DOC", "서명·직인이 없는 서류가 있음", True),
    "FIELD-BLANK": ("DOC", "필수 칸(연 소득, 작성일 등)이 비어 있음", True),
    "DOC-EXPIRED": ("DOC", "발급일로부터 1개월이 지난 서류", True),
    "DOC-OUTDATED": ("DOC", "최신 귀속연도가 아닌 소득 서류", True),
    "NAME-MISMATCH": ("DOC", "서류 명의자가 신청인과 다름", True),
    "PARTY-MISMATCH": ("DOC", "임대인이 등기부 소유자와 다름", True),
    "BIZ-MISMATCH": ("DOC", "서류 간 상호·사업자번호가 다름", True),
    "ASSET-MISMATCH": ("DOC", "담보 차량번호가 서류마다 다름", True),
    "MISSING-CERT": ("DOC", "임대차계약서에 확정일자가 없음", True),
    "ALTERED": ("DOC", "수기 정정·정정인 없음 (위변조 의심)", True),
    "DOC-MISSING": ("DOC", "필수 서류가 제출되지 않음", True),
    "DOC-INVALID": ("DOC", "허용되지 않는 파일 형식 또는 10MB 초과", True),
    "SUIT-BURDEN": ("SUIT", "월 상환 부담이 월 소득의 70%(예시)를 넘음", False),
    "KO-DELINQ-CURRENT": ("KO", "현재 연체 중인 대출·카드대금이 있음", False),
    "KO-BIZ-CLOSED": ("KO", "사업자 상태가 폐업", False),
    "INC-BELOW-MIN": ("INC", "연 소득이 상품 최소 기준(예시 2,000만원)에 못 미침", False),
    "INC-TENURE-SHORT": ("INC", "재직 기간이 12개월(예시) 미만", False),
    "CRD-SCORE-LOW": ("CRD", "신용평점이 상품 기준(예시 600점) 미만", False),
    "CRD-MULTI-DEBT": ("CRD", "대출 5건 이상 다중채무", False),
    "CRD-INQUIRY-MANY": ("CRD", "최근 6개월 신용조회 7건 이상", False),
    "DSR-OVER": ("DSR", "DSR이 규제 한도(예시 40%)를 넘음", False),
    "COL-LTV-OVER": ("COL", "신청 금액이 담보 한도(시세의 70%, 예시)를 넘음", False),
    "COL-SENIOR-LIEN": ("COL", "선순위 근저당이 있음", False),
    "COL-DEPOSIT-OVER-VALUE": ("COL", "선순위 채권 + 보증금이 주택 시세의 90%(예시)를 넘음 (보증 불가)", False),
    "POL-HOME-OWNED": ("POL", "세대원 중 주택 소유자가 있음", False),
    "POL-INCOME-OVER": ("POL", "부부합산 소득이 공고 기준(예시)을 넘음", False),
    "POL-ASSET-OVER": ("POL", "순자산이 공고 기준(예시)을 넘음", False),
    "ORG-EMP-TYPE": ("ORG", "협약 대상 고용 형태(정규직)가 아님", False),
    "GUA-REJECTED": ("GUA", "보증 대상 기준을 충족하지 않음", False),
    "REFI-DELINQ": ("REFI", "대환 대상 대출이 연체 중", False),
    "REFI-TOO-RECENT": ("REFI", "기존 대출 실행 후 6개월(예시)이 지나지 않음", False),
    "REFI-LEGAL-HOLD": ("REFI", "담보에 가압류 등 법적 제한이 있음", False),
    "REFI-SHORT-REMAIN": ("REFI", "남은 기간이 6개월(예시) 미만이라 대환 실익이 없음", False),
    "REFI-NOT-BENEFICIAL": ("REFI", "순 절감액이 0원 이하", False),
}

# 동의 코드: code → (title, required_for, form_no)
CONSENT_CODES = {
    "TERMS_BASIC": ("여신거래기본약관", "ALL", "LN-01"),
    "COLLECT_USE": ("개인(신용)정보 수집·이용", "ALL", "LN-02"),
    "UNIQUE_ID": ("고유식별정보 처리", "ALL", "LN-02"),
    "CREDIT_INQUIRY": ("개인(신용)정보 조회", "ALL", "LN-02"),
    "PROVIDE_3RD": ("개인(신용)정보 제공 (신용정보원·보증기관·법무사)", "ALL", "LN-02"),
    "ADMIN_INFO": ("행정정보 공동이용", "POLICY", "LN-19"),
    "SPOUSE_INQUIRY": ("배우자·세대원 정보 조회 (배우자 본인 동의)", "POLICY_MARRIED", "LN-20"),
    "AGENCY_PROVIDE": ("정책기관 정보 제공", "POLICY", "LN-19"),
    "GUARANTOR_PROVIDE": ("보증기관 개인(신용)정보 제공·보증 신청", "INST_A", "LN-14"),
    "ORG_EMPLOYMENT": ("협약기관 재직정보 조회·신분 변동 통보 수신", "INST_B", "LN-22"),
    "MYDATA_TRANSFER": ("마이데이터 개인신용정보 전송요구", "REFI", "RF-03"),
    "PAYOFF_PROVIDE": ("기존 금융사 상환 처리 정보 제공", "REFI", "RF-17"),
    "PUBLIC_SCRAPING": ("공공기관 소득·재직 자동 연동", "OPTIONAL", "LN-04"),
    "AUTO_DEBIT": ("자동이체 출금 동의", "TERMS", "LN-08"),
    "MARKETING": ("마케팅 목적 활용", "OPTIONAL", "LN-02"),
}

FORMS_LN = ["여신거래기본약관(가계용)", "개인(신용)정보 수집·이용·조회 동의서", "고객정보확인서", "소득·담보 증빙서류 제출 안내서", "대출 심사결과 통지서", "대출 거절사유 통지서", "제휴사 대출 안내용 제3자 정보제공 동의서", "자동이체 출금 동의서", "대출 상환 스케줄표", "대출 상품설명서", "금융소비자 권리 안내서", "대출거래약정서(가계용)", "근저당권 설정계약서", "전세자금 보증신청 및 채권양도 동의서", "자동차 저당권 설정계약서", "예금 질권설정 승낙서", "대출금 지급 의뢰서", "대출 실행 완료 통지서", "행정정보 공동이용 동의서", "배우자·세대원 개인(신용)정보 조회 동의서", "정책자금 대출 의무사항 확인서", "협약기관 재직정보 조회·제공 동의서", "급여공제 상환 동의서", "협약대출 특약서", "중도상환 신청서", "금리인하요구 신청서", "청약철회 신청서", "대출 조건변경(기간연장) 신청서"]
FORMS_RF = ["여신거래기본약관(가계용)", "개인(신용)정보 수집·이용·조회 동의서", "마이데이터 개인신용정보 전송요구 동의서", "대환 대상 대출 확인서", "고객정보확인서", "소득·담보 증빙서류 제출 안내서", "대환대출 심사결과 통지서", "대환대출 거절사유 통지서", "제휴사 대출 안내용 제3자 정보제공 동의서", "대환대출 비교 안내서", "자동이체 출금 동의서", "대환대출 상환 스케줄표", "대환대출 상품설명서", "금융소비자 권리 안내서", "대환대출 거래약정서", "담보 말소·이전·설정 동의서", "기존대출 상환자금 지급 위임장", "기존대출 상환(완제) 확인서", "대환대출 실행 완료 통지서"]

REG_PARAMS = [
    ("DSR_LIMIT", "0.40", "ratio", "DSR 한도"), ("STRESS_ADD", "1.0", "%p", "스트레스 가산금리"),
    ("LTV_LIMIT", "0.70", "ratio", "주택담보 LTV"), ("JEONSE_RATIO", "0.90", "ratio", "(선순위+보증금)/시세 상한"),
    ("JEONSE_LOAN_RATIO", "0.80", "ratio", "보증금 대비 대출 비율"), ("AUTO_LOAN_RATIO", "0.90", "ratio", "차량가 대비 대출 비율"),
    ("DEPOSIT_LOAN_RATIO", "0.95", "ratio", "예금 대비 대출 비율"), ("MIN_INCOME", "20000000", "won", "최소 연 소득"),
    ("MIN_TENURE", "12", "months", "최소 재직"), ("MIN_SCORE", "600", "score", "신용평점 기준"),
    ("SUIT_MAX_BURDEN", "0.70", "ratio", "적합성 상환 부담률"), ("LEGAL_MAX_RATE", "20.0", "%", "법정 최고 금리"),
    ("BASE_RATE", "3.10", "%", "기준금리(예시)"),
]
RULES = ["SUIT-RULE", "REFI-ELIG", "RATE-RULE", "UW-PIPELINE", "REC-WEIGHTS"]

GUARANTEE_RULES = [("HUG", "0.13", 400_000_000), ("HF", "0.05", 222_000_000), ("SGI", "0.18", 500_000_000)]
ORGS = [("ORG01", "(주)가상전자"), ("ORG02", "가상공사"), ("ORG03", "가상대학교병원")]
POLICY_RULES = {"p1": {"income_limit": 70_000_000, "asset_limit": 450_000_000, "married_factor": "1.2"},
                "p2": {"income_limit": 50_000_000, "asset_limit": 450_000_000, "married_factor": "1.2"}}
OBLIGATIONS = ["전입·실거주", "추가 주택 취득 금지", "소득·자산 사실 신고", "임대차 변경 신고", "우대 조건 변동 신고", "용도 내 사용"]

PROMPTS = [("LLM-8", "standard", "추천 사유 생성"), ("LLM-6", "standard", "거절 사유 설명"),
           ("LLM-7", "standard", "핵심 요약"), ("RLLM-3", "standard", "대환 비교 설명")]

PREFS = {"SALARY": (D("0.2"), "급여 이체"), "AUTO_DEBIT": (D("0.1"), "자동이체 3건 이상"), "CARD_USAGE": (D("0.1"), "카드 사용 월 30만원 이상")}
