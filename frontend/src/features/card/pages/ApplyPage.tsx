import { useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { applyCard, getApplyEligibility, listCardProducts, listPaymentAccounts } from '../api/cardApi'
import { toApiError, type ApiError } from '../api/errors'
import type { CardApplicationRequest, CardApplicationResult, CardType, IncomeRange } from '../api/types'
import { ErrorBox, InfoRow, Loading, PageHeader, Section, btnOutline, btnPrimary, inputClass } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { usePinVerify } from '../hooks/usePinVerify'
import { isSimplePin } from '../lib/pin'

type Draft = {
  type: CardType | null
  paymentAccountId: string
  paymentDay: number
  incomeRange: IncomeRange | ''
  cardPin: string
  cardPinConfirm: string
  recipient: string
  phone: string
  line1: string
  line2: string
  cardTerms: boolean
  privacy: boolean
  creditInquiry: boolean
}

const INITIAL: Draft = {
  type: null, paymentAccountId: '', paymentDay: 25, incomeRange: '', cardPin: '', cardPinConfirm: '',
  recipient: '', phone: '', line1: '', line2: '', cardTerms: false, privacy: false, creditInquiry: false,
}

const INCOME: [IncomeRange, string][] = [
  ['none', '소득 없음'], ['lt_10m', '1,000만 원 미만'], ['10m_20m', '1,000만~2,000만 원 미만'],
  ['20m_40m', '2,000만~4,000만 원 미만'], ['40m_70m', '4,000만~7,000만 원 미만'], ['gte_70m', '7,000만 원 이상'],
]
const TYPE_LABEL: Record<CardType, string> = { credit: '신용카드', debit: '체크카드' }

const formatPhone = (v: string) => {
  const d = v.replace(/\D/g, '').slice(0, 11)
  return d.length < 4 ? d : d.length < 8 ? `${d.slice(0, 3)}-${d.slice(3)}` : `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`
}

const REQUIRED = '필수 입력 항목입니다'
const validateStep = (step: number, d: Draft): Record<string, string> => {
  const e: Record<string, string> = {}
  if (step === 1 && !d.type) e.type = '카드 종류를 선택해 주세요'
  if (step === 2) {
    if (!d.paymentAccountId) e.paymentAccountId = REQUIRED
    if (d.type === 'credit' && !d.incomeRange) e.incomeRange = REQUIRED
    if (!d.cardPin) e.cardPin = REQUIRED
    else if (!/^\d{4}$/.test(d.cardPin)) e.cardPin = '숫자 4자리를 입력해 주세요'
    else if (isSimplePin(d.cardPin)) e.cardPin = '같은 숫자나 연속된 숫자는 사용할 수 없습니다'
    if (!e.cardPin && d.cardPin !== d.cardPinConfirm) e.cardPinConfirm = '비밀번호가 일치하지 않습니다'
    const recipient = d.recipient.trim()
    if (!recipient) e.recipient = REQUIRED
    else if ([...recipient].length > 20) e.recipient = '20자 이하로 입력해 주세요'
    if (!d.phone) e.phone = REQUIRED
    else if (!/^010-\d{4}-\d{4}$/.test(d.phone)) e.phone = '휴대폰 번호 형식(010-0000-0000)을 확인해 주세요'
    if (!d.line1.trim()) e.line1 = REQUIRED
    else if ([...d.line1.trim()].length > 100) e.line1 = '100자 이하로 입력해 주세요'
    if ([...d.line2].length > 100) e.line2 = '100자 이하로 입력해 주세요'
  }
  if (step === 3 && (!d.cardTerms || !d.privacy || (d.type === 'credit' && !d.creditInquiry))) {
    e.agreements = '필수 약관에 동의해 주세요'
  }
  return e
}

/** 서버 오류 필드 → (단계, 화면 필드 키) */
const FIELD_MAP: Record<string, [number, string]> = {
  type: [1, 'type'], productId: [1, 'type'], paymentAccountId: [2, 'paymentAccountId'], paymentDay: [2, 'paymentDay'],
  incomeRange: [2, 'incomeRange'], cardPin: [2, 'cardPin'], recipient: [2, 'recipient'], phone: [2, 'phone'],
  'address.line1': [2, 'line1'], 'address.line2': [2, 'line2'],
  'agreements.cardTerms': [3, 'agreements'], 'agreements.privacy': [3, 'agreements'], 'agreements.creditInquiry': [3, 'agreements'],
}
const REASON_TEXT: Record<string, string> = {
  REQUIRED: REQUIRED, INVALID_FORMAT: '형식을 확인해 주세요', OUT_OF_RANGE: '결제일은 1일부터 28일까지 선택할 수 있습니다',
  TOO_LONG: '입력 길이를 확인해 주세요', PIN_TOO_SIMPLE: '같은 숫자나 연속된 숫자는 사용할 수 없습니다',
  MUST_BE_TRUE: '필수 약관에 동의해 주세요', INVALID_ENUM: '올바른 값을 선택해 주세요',
  PRODUCT_TYPE_MISMATCH: '선택한 상품과 카드 종류가 맞지 않습니다. 처음부터 다시 선택해 주세요',
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <label className="mb-1 block text-sm font-medium text-gray-800">{label}{children}</label>
      {error && <p role="alert" className="mt-1 text-sm text-warning">{error}</p>}
    </div>
  )
}

export default function ApplyPage() {
  const navigate = useNavigate()
  const elig = useAsync(getApplyEligibility, [])
  const products = useAsync(listCardProducts, [])
  const accounts = useAsync(listPaymentAccounts, [])
  const pin = usePinVerify()
  const [step, setStep] = useState(1)
  const [d, setD] = useState<Draft>(INITIAL)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [banner, setBanner] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false) // 응답을 못 받아 같은 키로 다시 확인해야 하는 상태
  const keyRef = useRef<string | null>(null)
  const resultRef = useRef<CardApplicationResult | null>(null)

  // 입력을 하나라도 고치면 Idempotency-Key를 새로 만든다 (같은 키에 다른 본문이면 422가 되기 때문)
  const update = (patch: Partial<Draft>) => {
    keyRef.current = null
    setD((prev) => ({ ...prev, ...patch }))
  }

  if (elig.loading || products.loading) return <Loading />
  if (elig.error || products.error || !elig.data || !products.data) {
    return <ErrorBox message="상품 정보를 불러오지 못했습니다" onRetry={() => { elig.reload(); products.reload() }} />
  }

  const product = products.data.items.find((p) => p.type === d.type)
  const credit = d.type === 'credit'
  const reasonText = (type: CardType) => {
    const t = elig.data!.types[type]
    return t.reason === 'AGE_UNDER_19' ? '만 19세 이상부터 신청할 수 있습니다'
      : t.reason === 'COUNT_EXCEEDED' ? `${TYPE_LABEL[type]}는 최대 ${t.maxCount}장까지 보유할 수 있습니다` : ''
  }

  const next = () => {
    const found = validateStep(step, d)
    setErrors(found)
    if (Object.keys(found).length === 0) setStep(step + 1)
  }

  const body = (): CardApplicationRequest => ({
    type: d.type!, productId: product!.id, paymentAccountId: d.paymentAccountId,
    ...(credit ? { paymentDay: d.paymentDay, incomeRange: d.incomeRange as IncomeRange } : {}),
    cardPin: d.cardPin, recipient: d.recipient.trim(), phone: d.phone,
    address: { line1: d.line1.trim(), ...(d.line2.trim() ? { line2: d.line2.trim() } : {}) },
    agreements: { cardTerms: d.cardTerms, privacy: d.privacy, ...(credit ? { creditInquiry: d.creditInquiry } : {}) },
  })

  const submit = async () => {
    if (!keyRef.current) keyRef.current = crypto.randomUUID()
    try {
      resultRef.current = await applyCard(body(), keyRef.current)
      keyRef.current = null
    } catch (e) {
      const err = toApiError(e)
      if (err.status > 0 && err.status < 500) keyRef.current = null // 확정된 응답이면 키를 버린다
      throw err
    }
  }

  const apply = async () => {
    setBanner(null)
    try {
      const res = await pin.runVerified({ description: '카드 신청을 확정하려면 간편비밀번호를 입력해 주세요.' }, submit)
      if (res.ok) navigate('/cards/apply/result', { replace: true, state: { result: resultRef.current } })
    } catch (e) {
      handleError(toApiError(e))
    }
  }

  const handleError = (err: ApiError) => {
    setBanner(null)
    setRetrying(err.status === 0)
    if (err.code === 'VALIDATION_FAILED') {
      const fields = (err.details?.fields ?? []) as { field: string; reason: string }[]
      const found: Record<string, string> = {}
      let first = 4
      for (const f of fields) {
        const [s, key] = FIELD_MAP[f.field] ?? [4, 'submit']
        found[key] = REASON_TEXT[f.reason] ?? '입력값을 확인해 주세요'
        first = Math.min(first, s)
      }
      setErrors(found)
      setStep(first)
    } else if (err.code === 'ACCOUNT_NOT_FOUND') {
      accounts.reload()
      setErrors({ paymentAccountId: '선택한 계좌를 사용할 수 없습니다' })
      setStep(2)
    } else if (err.code === 'APPLICANT_NOT_ELIGIBLE' || err.code === 'CARD_COUNT_LIMIT_EXCEEDED') {
      elig.reload()
      setD((prev) => ({ ...prev, type: null }))
      setStep(1)
      setBanner(err.code === 'APPLICANT_NOT_ELIGIBLE' ? '만 19세 이상부터 신청할 수 있습니다' : '보유할 수 있는 카드 수를 넘었습니다')
    } else if (err.code === 'IDEMPOTENCY_KEY_REUSED') {
      keyRef.current = null
      setBanner('다시 한 번 신청하기를 눌러 주세요')
    } else if (err.code === 'ACCOUNT_SERVICE_UNAVAILABLE') {
      setBanner('계좌 정보를 확인할 수 없어 신청하지 못했습니다. 잠시 후 다시 시도해 주세요')
    } else if (err.code === 'MEMBER_SERVICE_UNAVAILABLE') {
      setBanner('회원 정보를 확인할 수 없어 신청하지 못했습니다. 잠시 후 다시 시도해 주세요')
    } else if (err.status === 0) {
      setBanner('신청 결과를 확인하지 못했습니다. 결과 다시 확인을 눌러 주세요')
    } else {
      setBanner('신청하지 못했습니다. 잠시 후 다시 시도해 주세요')
    }
  }

  return (
    <main>
      <PageHeader title="카드 신청" backTo="/cards" />
      <p className="px-4 pt-3 text-xs text-gray-500">{step}/5 단계</p>
      {banner && <p role="alert" className="mx-4 mt-2 rounded bg-gray-100 p-3 text-sm text-warning">{banner}</p>}

      {step === 1 && (
        <Section title="카드 종류와 상품을 선택해 주세요">
          <fieldset className="space-y-2">
            {(['debit', 'credit'] as const).map((type) => {
              const t = elig.data!.types[type]
              const p = products.data!.items.find((x) => x.type === type)
              return (
                <label key={type} className={`block rounded-lg border p-4 ${d.type === type ? 'border-brand' : 'border-gray-300'} ${t.available ? '' : 'opacity-50'}`}>
                  <input
                    type="radio" name="type" className="mr-2" disabled={!t.available}
                    checked={d.type === type} onChange={() => update({ type })}
                  />
                  <span className="text-sm font-semibold">{p?.name ?? TYPE_LABEL[type]}</span>
                  <span className="mt-1 block text-xs text-gray-600">{p?.description}</span>
                  {!t.available && <span className="mt-1 block text-xs text-warning">{reasonText(type)}</span>}
                </label>
              )
            })}
          </fieldset>
          {errors.type && <p role="alert" className="mt-2 text-sm text-warning">{errors.type}</p>}
        </Section>
      )}

      {step === 2 && (
        <Section title="신청 정보를 입력해 주세요">
          <fieldset className="mb-4">
            <legend className="mb-1 text-sm font-medium text-gray-800">결제 계좌</legend>
            {accounts.loading ? <Loading /> : accounts.error ? (
              <ErrorBox message="계좌 정보를 불러오지 못했습니다" onRetry={accounts.reload} />
            ) : accounts.data!.items.length === 0 ? (
              <p role="alert" className="text-sm text-warning">결제 계좌로 쓸 수 있는 계좌가 없습니다. 먼저 계좌를 개설해 주세요</p>
            ) : accounts.data!.items.map((a) => (
              <label key={a.accountId} className="mb-1 flex items-center gap-2 rounded border border-gray-300 p-3 text-sm">
                <input type="radio" name="account" checked={d.paymentAccountId === a.accountId} onChange={() => update({ paymentAccountId: a.accountId })} />
                {a.bankName} {a.accountMasked}
              </label>
            ))}
            {errors.paymentAccountId && <p role="alert" className="mt-1 text-sm text-warning">{errors.paymentAccountId}</p>}
          </fieldset>
          {credit && (
            <>
              <Field label="결제일">
                <select value={d.paymentDay} onChange={(e) => update({ paymentDay: Number(e.target.value) })} className={`${inputClass} mt-1`}>
                  {Array.from({ length: 28 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}일</option>)}
                </select>
              </Field>
              <fieldset className="mb-4">
                <legend className="mb-1 text-sm font-medium text-gray-800">연소득 구간</legend>
                {INCOME.map(([v, label]) => (
                  <label key={v} className="flex items-center gap-2 py-1 text-sm">
                    <input type="radio" name="income" checked={d.incomeRange === v} onChange={() => update({ incomeRange: v })} /> {label}
                  </label>
                ))}
                {errors.incomeRange && <p role="alert" className="mt-1 text-sm text-warning">{errors.incomeRange}</p>}
              </fieldset>
            </>
          )}
          <Field label="카드 비밀번호 (숫자 4자리)" error={errors.cardPin}>
            <input type="password" inputMode="numeric" maxLength={4} autoComplete="off" value={d.cardPin} onChange={(e) => update({ cardPin: e.target.value.replace(/\D/g, '') })} className={`${inputClass} mt-1`} />
          </Field>
          <Field label="카드 비밀번호 확인" error={errors.cardPinConfirm}>
            <input type="password" inputMode="numeric" maxLength={4} autoComplete="off" value={d.cardPinConfirm} onChange={(e) => update({ cardPinConfirm: e.target.value.replace(/\D/g, '') })} className={`${inputClass} mt-1`} />
          </Field>
          <Field label="수령인" error={errors.recipient}>
            <input maxLength={20} value={d.recipient} onChange={(e) => update({ recipient: e.target.value })} className={`${inputClass} mt-1`} />
          </Field>
          <Field label="연락처" error={errors.phone}>
            <input inputMode="numeric" placeholder="010-0000-0000" value={d.phone} onChange={(e) => update({ phone: formatPhone(e.target.value) })} className={`${inputClass} mt-1`} />
          </Field>
          <Field label="배송 주소" error={errors.line1}>
            <input maxLength={100} value={d.line1} onChange={(e) => update({ line1: e.target.value })} className={`${inputClass} mt-1`} />
          </Field>
          <Field label="상세 주소 (선택)" error={errors.line2}>
            <input maxLength={100} value={d.line2} onChange={(e) => update({ line2: e.target.value })} className={`${inputClass} mt-1`} />
          </Field>
        </Section>
      )}

      {step === 3 && (
        <Section title="약관에 동의해 주세요">
          <label className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <input
              type="checkbox"
              checked={d.cardTerms && d.privacy && (!credit || d.creditInquiry)}
              onChange={(e) => update({ cardTerms: e.target.checked, privacy: e.target.checked, creditInquiry: e.target.checked })}
            />
            전체 동의
          </label>
          {([['cardTerms', '카드 이용 약관 (필수)'], ['privacy', '개인정보 수집·이용 동의 (필수)'], ...(credit ? [['creditInquiry', '신용정보 조회 동의 (필수)']] : [])] as [keyof Draft, string][]).map(([k, label]) => (
            <details key={k} className="border-b border-gray-100 py-2">
              <summary className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="checkbox" checked={d[k] as boolean} onChange={(e) => update({ [k]: e.target.checked } as Partial<Draft>)} onClick={(e) => e.stopPropagation()} />
                {label}
              </summary>
              <p className="mt-2 text-xs text-gray-500">데모용 약관 본문입니다.</p>
            </details>
          ))}
          {errors.agreements && <p role="alert" className="mt-2 text-sm text-warning">{errors.agreements}</p>}
        </Section>
      )}

      {step === 4 && product && (
        <Section title="신청 내용을 확인해 주세요">
          <dl className="divide-y divide-gray-100">
            <InfoRow label="카드">{product.name}</InfoRow>
            <InfoRow label="결제 계좌">
              {accounts.data!.items.find((a) => a.accountId === d.paymentAccountId)?.accountMasked}
            </InfoRow>
            {credit && <InfoRow label="결제일">매월 {d.paymentDay}일</InfoRow>}
            <InfoRow label="수령인">{d.recipient}</InfoRow>
            <InfoRow label="연락처">{d.phone}</InfoRow>
            <InfoRow label="배송 주소">{d.line1} {d.line2}</InfoRow>
          </dl>
          {errors.submit && <p role="alert" className="mt-2 text-sm text-warning">{errors.submit}</p>}
        </Section>
      )}

      <div className="flex gap-2 px-4 pb-6">
        {step > 1 && <button type="button" onClick={() => { setErrors({}); setStep(step - 1) }} className={`${btnOutline} flex-1`}>이전</button>}
        {step < 4 ? (
          <button
            type="button" onClick={next} className={`${btnPrimary} flex-1`}
            disabled={step === 1 && !elig.data.types.credit.available && !elig.data.types.debit.available}
          >
            다음
          </button>
        ) : (
          <button type="button" onClick={() => void apply()} className={`${btnPrimary} flex-1`}>
            {retrying ? '결과 다시 확인' : '신청하기'}
          </button>
        )}
      </div>

    </main>
  )
}
