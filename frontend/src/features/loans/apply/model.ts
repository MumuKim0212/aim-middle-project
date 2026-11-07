// 대출 신청 API 응답 타입과 화면 문구(backend/app/loan/router.py·application.py, 프로토타입_구현명세.md 4·5·12장과 맞춘다).
// 금액은 원 단위 정수. 서버가 snake_case 키도 camelCase 로 바꿔 보낸다.

export type Terms = { amount: number; term: number; repay: string; paymentDay: number; debitAccountId: number | null }

/** POST/GET /applications 응답. terms·finalRate 는 GET 에만 있다. */
export type AppState = {
  applicationId: string
  status: string
  flow: string[]
  productId: string
  contractNo: string | null
  terms?: Terms | null
  finalRate?: number | null
}

export type ExistingLoan = {
  id: string
  institution: string
  kind: string
  balance: number
  rate: string
  since: number
  remain: number
  total: number
  monthly: number
  prepay: string
  bullet: boolean
  codes: string[]
}

export type Stage = { name: string; mark: 'ok' | 'wa' | 'ng'; text: string }
export type ReviewResult = {
  result: 'APPROVED' | 'COND_APPROVED' | 'DOCS_REQUIRED' | 'REJECTED'
  limit: number
  rate: number
  dsr: number
  hardCodes: string[]
  conditionCodes: string[]
  docCodes: string[]
  stages: Stage[]
}

export type Candidate = { variant: string; rate: number; rateType: string; totalInterest: number; monthly: number; score: number; reasons: string[]; cautions: string[] }

export type GuaranteeOption = { agency: string; ok: boolean; amount: number; feeRate: number; cost: number; interest: number; fee: number }

export type Compare = {
  verdict: 'BENEFICIAL' | 'TRADE_OFF' | 'NOT_BENEFICIAL'
  oldInterest: number; newInterest: number; cost: number; fee: number; stamp: number; net: number; breakEven: number | null
  oldMonthly: number; newMonthly: number; oldRate: number; newRate: number; term: number; remain: number; principal: number
  message: { reasons: string[]; cautions: string[] }
}

export type ProfileResult = {
  suitability: 'SUITABLE' | 'WARNING' | 'UNSUITABLE'
  burdenRatio: number
  adjustPlan: { budget: number; maxAmount: number | null; minTerm: number | null; exactTerm: number | null } | null
  status: string
}

/** 서버가 단계 사이에 돌려주지 않아 화면에서 이어 쓰는 값. 탭 안(sessionStorage)에만 두며, 없어도 각 단계가 서버 기본값으로 동작한다. */
export type Stash = {
  productId?: string // 신청이 끝난 뒤(payoff·done)에는 서버에서 못 읽어서 틀이 기억해 둔다
  flow?: string[]
  scenario?: string
  agreed?: string[]
  existing?: ExistingLoan[]
  targets?: ExistingLoan[]
  profile?: { amount?: number; term?: number; repay?: string }
  review?: ReviewResult
  monthly?: number
  contractNo?: string
}

const key = (id: string) => `loan.apply.${id}`
export function readStash(id: string): Stash {
  try { return JSON.parse(sessionStorage.getItem(key(id)) ?? '{}') as Stash } catch { return {} }
}
export function writeStash(id: string, s: Stash) {
  try { sessionStorage.setItem(key(id), JSON.stringify(s)) } catch { /* 저장소를 못 써도 신청은 계속된다 */ }
}

/** 마지막으로 시작한 신청(이어서 하기용). 탭을 닫은 뒤에도 남아야 해서 localStorage 를 쓴다. */
const LAST = 'loan.apply.last'
export type LastApp = { id: string; name: string }
export function readLast(): LastApp | null {
  try { return JSON.parse(localStorage.getItem(LAST) ?? 'null') as LastApp | null } catch { return null }
}
export function writeLast(v: LastApp | null) {
  try { if (v) localStorage.setItem(LAST, JSON.stringify(v)); else localStorage.removeItem(LAST) } catch { /* 이어서 하기만 안 보인다 */ }
}

/** 신청 상태로 지금 해야 할 단계를 정한다(서버가 단계 이름을 따로 주지 않는다). */
export function stepFor(status: string, flow: string[]): string {
  const after = (s: string) => flow[flow.indexOf(s) + 1]
  switch (status) {
    case 'DRAFT': return flow[0]
    case 'POLICY_CHECKING': return 'consent'
    case 'CONSENTED': return flow.includes('fetch') ? 'fetch' : 'profile'
    case 'LOANS_FETCHED': return 'targets'
    case 'TARGET_SELECTED': case 'UNSUITABLE': return 'profile'
    case 'PROFILED': return after('profile')
    case 'DOCS_SUBMITTED': case 'UNDER_REVIEW': return 'review'
    case 'DOCS_REQUIRED': return 'docs'
    case 'APPROVED': case 'COND_APPROVED': return flow.includes('compare') ? 'compare' : 'result'
    case 'REJECTED': return flow.includes('compare') ? 'compare' : 'result'
    case 'TERMS_SET': return 'pricing'
    case 'PRICED': return 'explain'
    case 'EXPLAINED': return 'contract'
    case 'CONTRACTED': return after('contract')
    case 'COLLATERAL_SET': return 'execute'
    default: return 'done'
  }
}

/** 더 진행할 수 없는 상태. REJECTED 는 결과 화면이 거절 사유를 보여 주므로 그 단계에서는 예외로 둔다. */
export const ENDED: Record<string, string> = {
  REJECTED: '승인되지 않았어요.',
  POLICY_INELIGIBLE: '정책 자격 요건을 충족하지 못했어요.',
  AFFILIATION_FAILED: '협약 대상이 아니에요.',
  GUARANTEE_REJECTED: '보증 대상 기준을 충족하지 못했어요.',
  REFI_INELIGIBLE: '대환할 수 있는 대출이 없어요.',
  REFI_FAILED: '대환 실행 중 문제가 생겨 거래를 원래대로 되돌렸어요.',
  CANCELLED: '취소된 신청이에요.',
  EXPIRED: '기간이 지난 신청이에요.',
}

/** 단계 제목과 안내문(구현명세 4.2·12.2). */
export const STEP: Record<string, [string, string?]> = {
  precheck: ['정책 자격 사전 확인', '조회 동의 전이라 입력값으로만 간단히 확인해요. 실제 자격은 행정정보로 확정해요.'],
  consent: ['약관·동의', '동의가 기록된 뒤에만 조회가 실행돼요.'],
  fetch: ['기존 대출 조회', '마이데이터로 다른 금융사의 대출을 가져와요.'],
  targets: ['대환 대상 선택', '갈아탈 대출을 고르세요. 대환 가능 조건(예시 기준)을 바로 확인해요.'],
  profile: ['고객정보 확인·적합성', '금소법 적합성 원칙에 따른 고객정보확인서예요.'],
  policycheck: ['정책 자격 검증', '고객 진술이 아니라 조회 결과로 판단해요. 신청일 기준 공고를 적용해요.'],
  guarantee: ['보증기관 선택', '보증료까지 포함한 실질 비용으로 보증기관을 비교해요. 보증료율은 예시예요. 선택한 한 곳에만 신청해요.'],
  affiliation: ['협약기관 소속·재직 확인', '협약 금리의 근거라서 고객 진술만으로 확정하지 않아요.'],
  docs: ['소득·담보 증빙 제출', '공공기관 자동 연동을 먼저 시도하고, 나머지는 직접 파일을 올려요 (PDF·JPG·PNG, 10MB 이하).'],
  review: ['심사', '네 업무가 같은 심사 파이프라인을 써요. 기준값은 예시예요.'],
  result: ['심사 결과·권장 상품'],
  compare: ['심사 결과·대환 유불리 비교'],
  terms: ['대출 조건 설정', '승인 범위 안에서 조건을 골라요.'],
  pricing: ['금액·금리 확정', '최종 금리 = 기준금리 + 가산금리 − 우대금리 (정부는 정책 금리표 기준, 상품 상·하한 안)'],
  explain: ['상품설명서 확인', '금소법 설명의무: 설명서를 끝까지 읽고 이해 확인 문제를 풀어야 진행돼요.'],
  contract: ['약정·전자서명', '약정 직전에 내용을 다시 확인해요.'],
  collateral: ['담보·보증 설정', '담보·보증 설정이 끝나야 실행할 수 있어요.'],
  execute: ['대출 실행·지급', '실행 직전 확인을 마치면 대출이 실행돼요.'],
  payoff: ['기존 대출 완제 확인', '기존 금융사의 완제 확인을 받아야 대환이 끝나요.'],
  done: ['결과 통보'],
}

/** 사유 코드 문구(구현명세 5장). 서버는 코드만 준다. */
export const REASON: Record<string, string> = {
  'CONSENT-DENIED': "제출한 동의서에서 필수 '신용정보 조회'가 동의하지 않음으로 표시됨",
  'SIGN-MISSING': '서명·직인이 없는 서류가 있음',
  'FIELD-BLANK': '필수 칸(연 소득, 작성일 등)이 비어 있음',
  'DOC-EXPIRED': '발급일로부터 1개월이 지난 서류',
  'DOC-OUTDATED': '최신 귀속연도가 아닌 소득 서류',
  'NAME-MISMATCH': '서류 명의자가 신청인과 다름',
  'PARTY-MISMATCH': '임대인이 등기부 소유자와 다름',
  'BIZ-MISMATCH': '서류 간 상호·사업자번호가 다름',
  'ASSET-MISMATCH': '담보 차량번호가 서류마다 다름',
  'MISSING-CERT': '임대차계약서에 확정일자가 없음',
  'ALTERED': '수기 정정·정정인 없음 (위변조 의심)',
  'DOC-MISSING': '필수 서류가 제출되지 않음',
  'DOC-INVALID': '허용되지 않는 파일 형식 또는 10MB 초과',
  'KO-DELINQ-CURRENT': '현재 연체 중인 대출·카드대금이 있음',
  'KO-BIZ-CLOSED': '사업자 상태가 폐업',
  'INC-BELOW-MIN': '연 소득이 상품 최소 기준(예시 2,000만원)에 못 미침',
  'INC-TENURE-SHORT': '재직 기간이 12개월(예시) 미만',
  'CRD-SCORE-LOW': '신용평점이 상품 기준(예시 600점) 미만',
  'CRD-MULTI-DEBT': '대출 5건 이상 다중채무',
  'CRD-INQUIRY-MANY': '최근 6개월 신용조회 7건 이상',
  'DSR-OVER': 'DSR이 규제 한도(예시 40%)를 넘음',
  'COL-LTV-OVER': '신청 금액이 담보 한도(시세의 70%, 예시)를 넘음',
  'COL-SENIOR-LIEN': '선순위 근저당이 있음',
  'COL-DEPOSIT-OVER-VALUE': '선순위 채권 + 보증금이 주택 시세의 90%(예시)를 넘음 (보증 불가)',
  'SUIT-BURDEN': '월 상환 부담이 월 소득의 70%(예시)를 넘음',
  'POL-HOME-OWNED': '세대원 중 주택 소유자가 있음',
  'POL-INCOME-OVER': '부부합산 소득이 공고 기준(예시)을 넘음',
  'POL-ASSET-OVER': '순자산이 공고 기준(예시)을 넘음',
  'ORG-EMP-TYPE': '협약 대상 고용 형태(정규직)가 아님',
  'REFI-DELINQ': '대환 대상 대출이 연체 중',
  'REFI-TOO-RECENT': '기존 대출 실행 후 6개월(예시)이 지나지 않음',
  'REFI-LEGAL-HOLD': '담보에 가압류 등 법적 제한이 있음',
  'REFI-SHORT-REMAIN': '남은 기간이 6개월(예시) 미만이라 대환 실익이 없음',
  'REFI-NOT-BENEFICIAL': '순 절감액이 0원 이하',
}

/** 체험 고객(서버 catalog.SCENARIOS). 목록 API 가 없어 키와 이름을 옮겨 둔다. */
export const SCENARIOS: [string, string][] = [
  ['KIM_OK', 'Kim 김민수 · 적합 (신용)'], ['KIM_BAD', 'Kim 김민수 · 부적합 (양식 불량 + 신용 부족)'],
  ['PARK_OK', 'Park 박지영 · 적합 (전세)'], ['PARK_BAD', 'Park 박지영 · 부적합 (담보·소득 부족)'],
  ['NAM_OK', 'Nam 남준호 · 적합 (주택담보)'], ['NAM_BAD', 'Nam 남준호 · 부적합 (LTV·DSR 초과)'],
  ['LIM_OK', 'Lim 임소라 · 적합 (자동차, 개인사업자)'], ['LIM_BAD', 'Lim 임소라 · 부적합 (소득·신용 부족 + 위변조 의심)'],
]

export const JOBS = ['급여소득자', '개인사업자', '프리랜서', '연금소득자']
export const RATE_PREFS = ['고정금리', '변동금리', '혼합형', '상관없음']
/** 선택 동의(서버의 필수 목록에는 없다). 자동 연동 동의는 동의 단계에서만 받을 수 있다. */
export const OPTIONAL_CONSENTS: [string, string][] = [['PUBLIC_SCRAPING', '공공기관 소득·재직 자동 연동'], ['MARKETING', '마케팅 목적 활용']]
export const PREFS: [string, string][] = [['SALARY', '급여 이체 −0.2%p'], ['AUTO_DEBIT', '자동이체 3건 이상 −0.1%p'], ['CARD_USAGE', '카드 사용 월 30만원 이상 −0.1%p']]

export const FIELD_LABEL: Record<string, string> = {
  homeless: '무주택 여부', married: '혼인 여부', householdIncome: '연 소득', netAssets: '순자산', job: '직업', income: '연 소득', tenure: '재직 기간',
  debtMonthly: '기존 월 상환액', amount: '희망 금액', term: '기간', repay: '상환 방법', ratePref: '금리 선호', orgId: '협약기관', empNo: '사번', empType: '고용 형태',
  paymentDay: '납입일', debitAccountId: '자동이체 계좌', accountId: '입금 계좌', docKey: '서류', file: '파일', answers: '답변', confirmations: '확인 항목',
}
/** 협약기관(서버 catalog.ORGS). 목록 API 가 없어 옮겨 둔다. */
export const ORGS: [string, string][] = [['ORG01', '(주)가상전자'], ['ORG02', '가상공사'], ['ORG03', '가상대학교병원']]
export const VERDICT_TEXT: Record<string, string> = { APPROVED: '승인', COND_APPROVED: '조건부 승인 (감액)', DOCS_REQUIRED: '서류 보완 요청', REJECTED: '거절' }
