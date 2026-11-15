import clsx from 'clsx'
import { Tabs as RadixTabs } from 'radix-ui'
import type { ReactNode } from 'react'

import { formatNumber } from '@/lib/format'

import styles from './Tabs.module.css'

export type TabItem<T extends string = string> = {
  value: T
  label: string
  /** 이름 뒤에 모노로 붙는 개수 */
  count?: number
  /** 이름 앞의 표식(상태 점 등) */
  leading?: ReactNode
  disabled?: boolean
}

export type TabsProps<T extends string = string> = {
  value: T
  onValueChange: (value: T) => void
  items: readonly TabItem<T>[]
  /** 탭 묶음의 이름(읽어 주는 이름) */
  'aria-label': string
  /** 탭 줄 아래에 가는 괘선을 긋는다. 기본 true. 이미 괘선 안(필터 줄)이면 false */
  ruled?: boolean
  /** <TabPanel value="…"> 들. 목록을 걸러 보여 주기만 할 때는 비워 둔다 */
  children?: ReactNode
  className?: string
  listClassName?: string
}

/** 시안의 밑줄 탭. 고른 탭은 굵은 글자와 3px 먹색 줄. 좌우 화살표로 옮긴다. */
export function Tabs<T extends string = string>({
  value,
  onValueChange,
  items,
  'aria-label': ariaLabel,
  ruled = true,
  children,
  className,
  listClassName,
}: TabsProps<T>) {
  return (
    <RadixTabs.Root
      className={className}
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      activationMode="automatic"
    >
      <RadixTabs.List
        className={clsx(styles.list, ruled && styles.ruled, listClassName)}
        aria-label={ariaLabel}
      >
        {items.map((item) => (
          <RadixTabs.Trigger
            key={item.value}
            value={item.value}
            disabled={item.disabled}
            className={styles.tab}
          >
            {item.leading && <span className={styles.leading}>{item.leading}</span>}
            {/* 굵기가 바뀌어도 폭이 흔들리지 않게, 굵은 글자의 폭을 미리 잡아 둔다 */}
            <span className={styles.label} data-label={item.label}>
              {item.label}
            </span>
            {item.count !== undefined && (
              <span className={styles.count}>{formatNumber(item.count)}</span>
            )}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {children}
    </RadixTabs.Root>
  )
}

export type TabPanelProps = {
  value: string
  children: ReactNode
  className?: string
}

export function TabPanel({ value, children, className }: TabPanelProps) {
  return (
    <RadixTabs.Content value={value} className={clsx(styles.panel, className)}>
      {children}
    </RadixTabs.Content>
  )
}
