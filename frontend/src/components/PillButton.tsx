import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }

export default function PillButton({ active = false, className = '', ...props }: Props) {
  const tone = active
    ? 'border-pill-active-border bg-pill-active font-semibold text-brand-dark'
    : 'border-gray-300 bg-white text-gray-700'
  return (
    <button
      type="button"
      className={`flex h-12 flex-1 items-center justify-center rounded-full border px-2 text-center text-sm leading-tight ${tone} ${className}`}
      {...props}
    />
  )
}
