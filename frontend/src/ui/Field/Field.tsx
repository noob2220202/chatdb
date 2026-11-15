import clsx from 'clsx'
import { useId, type ReactNode } from 'react'

import styles from './Field.module.css'
import { ProblemMark } from './ProblemMark'

export type FieldIds = {
  /** 입력 요소의 id (label 이 가리킨다) */
  id: string
  /** aria-describedby 에 넣을 값. 도움말·오류가 없으면 undefined */
  describedBy: string | undefined
  /** 오류가 있는지. aria-invalid 에 넣는다 */
  invalid: boolean
}

export type FieldProps = {
  label?: ReactNode
  /** 이름 줄 오른쪽에 놓는 짧은 말 */
  labelAside?: ReactNode
  /** 입력 칸 아래 도움말 */
  hint?: ReactNode
  /** 오류 문장. 있으면 도움말 자리에 × 표식과 함께 먹색으로 적는다 */
  error?: ReactNode
  /** 입력 요소의 id. 주지 않으면 만든다 */
  id?: string
  className?: string
  /** 입력 요소. 함수로 주면 id 와 aria 값을 받는다 */
  children: ReactNode | ((ids: FieldIds) => ReactNode)
}

/** 도움말·오류 한 줄. Field 밖에서 따로 쓸 수도 있다. */
export function FieldMessage({
  error,
  hint,
  id,
  className,
}: {
  error?: ReactNode
  hint?: ReactNode
  id?: string
  className?: string
}) {
  if (!error && !hint) return null
  return error ? (
    <p id={id} className={clsx(styles.message, styles.error, className)} role="alert">
      <ProblemMark className={styles.mark} />
      <span>{error}</span>
    </p>
  ) : (
    <p id={id} className={clsx(styles.message, className)}>
      {hint}
    </p>
  )
}

/** 이름 + 입력 칸 + 도움말·오류의 자리 잡기. 오류는 빨강이 아니라 ×와 먹색 글로 알린다. */
export function Field({ label, labelAside, hint, error, id, className, children }: FieldProps) {
  const autoId = useId()
  const controlId = id ?? autoId
  const messageId = `${controlId}-msg`
  const hasMessage = Boolean(error || hint)
  const ids: FieldIds = {
    id: controlId,
    describedBy: hasMessage ? messageId : undefined,
    invalid: Boolean(error),
  }
  return (
    <div className={clsx(styles.field, className)}>
      {(label || labelAside) && (
        <div className={styles.head}>
          {label && (
            <label className={styles.label} htmlFor={controlId}>
              {label}
            </label>
          )}
          {labelAside && <span className={styles.aside}>{labelAside}</span>}
        </div>
      )}
      {typeof children === 'function' ? children(ids) : children}
      <FieldMessage id={messageId} error={error} hint={hint} />
    </div>
  )
}
