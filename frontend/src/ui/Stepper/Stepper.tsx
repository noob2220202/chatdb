import { CheckIcon } from '@phosphor-icons/react'
import clsx from 'clsx'

import styles from './Stepper.module.css'

export type StepperProps = {
  /** 단계 이름들. "전화번호", "인증 코드", "2단계 비밀번호" */
  steps: readonly string[]
  /** 지금 단계(0부터) */
  current: number
  'aria-label'?: string
  className?: string
}

/** 마법사의 단계 표시. 인쇄물의 차례처럼 "1 — 전화번호" 로 적고, 지금 단계는 굵은 글자와 굵은 줄. */
export function Stepper({
  steps,
  current,
  'aria-label': ariaLabel = '진행 단계',
  className,
}: StepperProps) {
  return (
    <ol className={clsx(styles.stepper, className)} aria-label={ariaLabel}>
      {steps.map((step, index) => {
        const state = index < current ? 'done' : index === current ? 'current' : 'todo'
        return (
          <li
            key={step}
            className={styles.step}
            data-state={state}
            aria-current={state === 'current' ? 'step' : undefined}
          >
            <span className={styles.no}>{index + 1}</span>
            <span className={styles.dash} aria-hidden="true">
              —
            </span>
            <span className={styles.name}>{step}</span>
            {state === 'done' && (
              <>
                <CheckIcon className={styles.done} size={12} aria-hidden="true" />
                <span className="visually-hidden">마침</span>
              </>
            )}
          </li>
        )
      })}
    </ol>
  )
}
