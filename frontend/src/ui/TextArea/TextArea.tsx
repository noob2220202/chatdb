import clsx from 'clsx'
import { forwardRef, type ReactNode, type TextareaHTMLAttributes } from 'react'

import { Field } from '@/ui/Field/Field'

import styles from './TextArea.module.css'

export type TextAreaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: ReactNode
  labelAside?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  /** 글자를 모노로(링크 목록, 키워드 목록처럼 한 줄에 하나씩 적는 칸) */
  mono?: boolean
  /** 내용만큼 아래로 늘어난다(지원하는 브라우저에서). 기본 true */
  autoGrow?: boolean
  /** textarea 에 붙일 클래스 (className 은 바깥 틀에 붙는다) */
  inputClassName?: string
}

/** 여러 줄 입력 칸. 가는 괘선 테 안에 쓰고, 아래 줄만 먹색이다. */
export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  {
    label,
    labelAside,
    hint,
    error,
    mono = false,
    autoGrow = true,
    className,
    inputClassName,
    id,
    rows = 4,
    ...rest
  },
  ref,
) {
  return (
    <Field
      label={label}
      labelAside={labelAside}
      hint={hint}
      error={error}
      id={id}
      className={className}
    >
      {(ids) => (
        <div className={styles.shell} data-disabled={rest.disabled || undefined}>
          <textarea
            ref={ref}
            id={ids.id}
            rows={rows}
            aria-invalid={ids.invalid || undefined}
            aria-describedby={ids.describedBy}
            className={clsx(
              styles.input,
              mono && styles.mono,
              autoGrow && styles.grow,
              inputClassName,
            )}
            {...rest}
          />
        </div>
      )}
    </Field>
  )
})
