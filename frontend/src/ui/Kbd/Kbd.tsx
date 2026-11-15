import clsx from 'clsx'
import type { ReactNode } from 'react'

import styles from './Kbd.module.css'

export type KbdProps = {
  children: ReactNode
  /** 먹색 면 위에 놓일 때 */
  onInk?: boolean
  className?: string
}

/** 키캡. 단축키를 알려 줄 때 쓴다: <Kbd>/</Kbd> */
export function Kbd({ children, onInk = false, className }: KbdProps) {
  return <kbd className={clsx(styles.kbd, onInk && styles.onInk, className)}>{children}</kbd>
}
