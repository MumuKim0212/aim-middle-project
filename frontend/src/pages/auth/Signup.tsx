import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { ApiFail, callJson, firstFieldError } from '../../lib/http'

type Form = {
  termsService: boolean; termsPrivacy: boolean; marketing: boolean
  loginId: string; password: string; passwordConfirm: string
  name: string; birthDate: string; phone: string
}
const EMPTY: Form = {
  termsService: false, termsPrivacy: false, marketing: false,
  loginId: '', password: '', passwordConfirm: '', name: '', birthDate: '', phone: '',
}
const TOTAL = 5
const TITLES = ['약관에 동의해 주세요', '사용할 아이디를 입력해 주세요', '비밀번호를 만들어 주세요', '기본 정보를 입력해 주세요', '입력한 내용을 확인해 주세요']

/** 회원가입 5단계(/signup/1 ~ /signup/5). 입력값은 이 화면에만 있고, 마지막 "가입하기"에서야 서버에 저장된다(F-08). */
/** 최종 검증에서 걸린 필드가 속한 가입 단계. */
function signupStepOf(field: string): number {
  if (field === 'terms') return 1
  if (field === 'loginId') return 2
  if (field === 'password' || field === 'passwordConfirm') return 3
  return 4
}

export default function Signup() {
  const { step: raw } = useParams()
  const step = Number(raw)
  const nav = useNavigate()
  const { refresh } = useAuth()
  const [f, setF] = useState<Form>(EMPTY)
  const [err, setErr] = useState<{ field?: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)

  if (!Number.isInteger(step) || step < 1 || step > TOTAL) return <Navigate to="/signup/1" replace />
  // 주소로 바로 3단계 등에 들어오면(새로고침 포함) 입력값이 없으니 1단계부터 다시 시작한다
  if (step > 1 && !f.termsService) return <Navigate to="/signup/1" replace />

  const set = <K extends keyof Form>(k: K, v: Form[K]) => { setF((p) => ({ ...p, [k]: v })); setErr(null) }
  const fieldErr = (k: string) => (err?.field === k ? <p className="auth-err" role="alert">{err.message}</p> : null)
  const allTerms = f.termsService && f.termsPrivacy && f.marketing

  async function next(e?: FormEvent) {
    e?.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      if (step < TOTAL) {
        await callJson('POST', '/api/auth/signup/validate', { step, data: f })
        nav(`/signup/${step + 1}`)
      } else {
        await callJson('POST', '/api/auth/signup', f)
        await refresh()
        nav('/auth/pin/setup', { replace: true }) // 가입 직후 자동 로그인 → 간편비밀번호 설정(건너뛸 수 없음)
      }
    } catch (x) {
      const b = x instanceof ApiFail ? x.body : {}
      const fe0 = firstFieldError(b)
      setErr({ field: fe0?.field, message: fe0?.message ?? b.message ?? '처리하지 못했어요. 잠시 후 다시 해 주세요.' })
      if (step === TOTAL && fe0) nav(`/signup/${signupStepOf(fe0.field)}`) // 최종 검증에서 걸리면 해당 단계로
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-page">
      <div className="auth-progress" aria-label={`${step}단계 중 ${TOTAL}단계`}>
        <span>{step}/{TOTAL}</span>
        <i style={{ width: `${(step / TOTAL) * 100}%` }} />
      </div>
      <h2 className="auth-title">{TITLES[step - 1]}</h2>

      <form className="auth-form" onSubmit={(e) => void next(e)} noValidate>
        {step === 1 && (
          <div className="auth-terms">
            <label className="all"><input type="checkbox" checked={allTerms} onChange={(e) => setF((p) => ({ ...p, termsService: e.target.checked, termsPrivacy: e.target.checked, marketing: e.target.checked }))} /> 전체 동의</label>
            <label><input type="checkbox" checked={f.termsService} onChange={(e) => set('termsService', e.target.checked)} /> <b>[필수]</b> 서비스 이용약관</label>
            <label><input type="checkbox" checked={f.termsPrivacy} onChange={(e) => set('termsPrivacy', e.target.checked)} /> <b>[필수]</b> 개인정보 수집·이용</label>
            <label><input type="checkbox" checked={f.marketing} onChange={(e) => set('marketing', e.target.checked)} /> [선택] 마케팅 정보 수신</label>
            {fieldErr('terms')}
          </div>
        )}

        {step === 2 && (
          <label className="auth-field">아이디
            <input value={f.loginId} autoFocus autoCapitalize="none" autoComplete="username" placeholder="영문 소문자·숫자 5~20자" onChange={(e) => set('loginId', e.target.value)} />
            {fieldErr('loginId')}
          </label>
        )}

        {step === 3 && (
          <>
            <label className="auth-field">비밀번호
              <input type="password" value={f.password} autoFocus autoComplete="new-password" placeholder="8~20자, 영문·숫자·특수문자 중 2종류 이상" onChange={(e) => set('password', e.target.value)} />
              {fieldErr('password')}
            </label>
            <label className="auth-field">비밀번호 확인
              <input type="password" value={f.passwordConfirm} autoComplete="new-password" onChange={(e) => set('passwordConfirm', e.target.value)} />
              {fieldErr('passwordConfirm')}
            </label>
          </>
        )}

        {step === 4 && (
          <>
            <label className="auth-field">이름
              <input value={f.name} autoFocus autoComplete="name" placeholder="한글 2~10자 또는 영문 2~30자" onChange={(e) => set('name', e.target.value)} />
              {fieldErr('name')}
            </label>
            <label className="auth-field">생년월일
              <input type="date" value={f.birthDate} max={new Date().toISOString().slice(0, 10)} onChange={(e) => set('birthDate', e.target.value)} />
              {fieldErr('birthDate')}
            </label>
            <label className="auth-field">휴대폰 번호
              <input inputMode="tel" value={f.phone} autoComplete="tel" placeholder="010-0000-0000" onChange={(e) => set('phone', e.target.value)} />
              {fieldErr('phone')}
            </label>
          </>
        )}

        {step === 5 && (
          <dl className="auth-summary">
            <div><dt>아이디</dt><dd>{f.loginId.trim().toLowerCase()}</dd></div>
            <div><dt>이름</dt><dd>{f.name}</dd></div>
            <div><dt>생년월일</dt><dd>{f.birthDate}</dd></div>
            <div><dt>휴대폰 번호</dt><dd>{f.phone}</dd></div>
            <div><dt>마케팅 수신</dt><dd>{f.marketing ? '동의' : '동의 안 함'}</dd></div>
          </dl>
        )}

        {err && !err.field && <p className="auth-err" role="alert">{err.message}</p>}
        {step === TOTAL && err?.field && <p className="auth-err" role="alert">{err.message}</p>}

        <div className="auth-actions">
          {step > 1 && <button type="button" className="ghost" onClick={() => nav(`/signup/${step - 1}`)}>이전</button>}
          <button type="submit" className="primary" disabled={busy}>{step === TOTAL ? '가입하기' : '다음'}</button>
        </div>
      </form>
      <p className="auth-foot">이미 계정이 있나요? <Link to="/login">로그인</Link></p>
    </section>
  )
}
