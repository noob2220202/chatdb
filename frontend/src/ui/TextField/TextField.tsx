import clsx from 'clsx'
import { forwardRef, useState, type InputHTMLAttributes, type ReactNode } from 'react'

import { Field } from '@/ui/Field/Field'

import styles from './TextField.module.css'

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> & {
  label?: ReactNode
  /** 이름 줄 오른쪽의 짧은 말 */
  labelAside?: ReactNode
  hint?: ReactNode
  /** 오류 문장. 있으면 aria-invalid 가 붙고 도움말 자리에 나온다 */
  error?: ReactNode
  /** md: 36px / lg: 52px(로그인처럼 한 칸이 주인공일 때) */
  size?: 'md' | 'lg'
  /** 입력 글자를 모노로(@아이디, 전화번호, 코드, 비밀번호) */
  mono?: boolean
  /** 입력 칸 앞에 붙는 것(아이콘, "@" 같은 머리 글자) */
  leading?: ReactNode
  /** 입력 칸 뒤에 붙는 것(단위, 버튼) */
  trailing?: ReactNode
  /** type="password" 일 때 "보기 / 숨기기" 를 붙인다 */
  revealable?: boolean
  /** 입력 요소에 붙일 클래스 (className 은 바깥 틀에 붙는다) */
  inputClassName?: string
}

/** 한 줄 입력 칸. 시안의 밑줄 방식: 쉬고 있을 때는 먹색 줄 하나, 쓰는 동안은 줄이 굵어진다. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  {
    label,
    labelAside,
    hint,
    error,
    size = 'md',
    mono = false,
    leading,
    trailing,
    revealable = false,
    className,
    inputClassName,
    id,
    type = 'text',
    disabled,
    ...rest
  },
  ref,
) {
  const [revealed, setRevealed] = useState(false)
  const canReveal = revealable && type === 'password'
  const inputType = canReveal && revealed ? 'text' : type

  return (
    <Field label={label} labelAside={labelAside} hint={hint} error={error} id={id} className={className}>
      {(ids) => (
        <div
          className={clsx(styles.shell, styles[size])}
          data-invalid={ids.invalid || undefined}
          data-disabled={disabled || undefined}
        >
          {leading && <span className={styles.adornment}>{leading}</span>}
          <input
            ref={ref}
            id={ids.id}
            type={inputType}
            disabled={disabled}
            aria-invalid={ids.invalid || undefined}
            aria-describedby={ids.describedBy}
            className={clsx(styles.input, mono && styles.mono, inputClassName)}
            {...rest}
          />
          {trailing && <span className={styles.adornment}>{trailing}</span>}
          {canReveal && (
            <button
              type="button"
              className={styles.reveal}
              onClick={() => setRevealed((value) => !value)}
              aria-pressed={revealed}
              aria-label={revealed ? '비밀번호 숨기기' : '비밀번호 보기'}
              disabled={disabled}
            >
              {revealed ? '숨기기' : '보기'}
            </button>
          )}
        </div>
      )}
    </Field>
  )
})
