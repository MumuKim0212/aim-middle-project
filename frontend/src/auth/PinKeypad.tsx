import { useEffect, useState } from 'react'

type Props = {
  length?: number
  /** 6자리가 다 눌리면 부른다(자동 제출). 입력값은 URL 이 아니라 요청 본문으로만 보낸다. */
  onComplete: (pin: string) => void
  disabled?: boolean
  /** 값이 바뀌면 입력을 비운다(틀렸을 때 다시 입력하게) */
  resetKey?: number
}

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫']

/** 숫자 6자리 입력용 키패드(●●●○○○ 표시). */
export default function PinKeypad({ length = 6, onComplete, disabled, resetKey }: Props) {
  const [pin, setPin] = useState('')

  useEffect(() => setPin(''), [resetKey])

  function press(k: string) {
    if (disabled || !k) return
    if (k === '⌫') return setPin((p) => p.slice(0, -1))
    setPin((p) => {
      if (p.length >= length) return p
      const next = p + k
      if (next.length === length) window.setTimeout(() => onComplete(next), 120)
      return next
    })
  }

  return (
    <div className="pin">
      <div className="pin-dots" aria-label={`${pin.length}자리 입력됨`} role="status">
        {Array.from({ length }, (_, i) => <i key={i} className={i < pin.length ? 'on' : ''} />)}
      </div>
      <div className="pin-pad" role="group" aria-label="숫자 키패드">
        {KEYS.map((k, i) => (
          <button key={i} type="button" disabled={disabled || !k} aria-label={k === '⌫' ? '지우기' : k || undefined} onClick={() => press(k)}>{k}</button>
        ))}
      </div>
    </div>
  )
}
