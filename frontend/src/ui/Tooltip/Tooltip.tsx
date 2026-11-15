import clsx from 'clsx'
import { Tooltip as RadixTooltip } from 'radix-ui'
import { createContext, useContext, type ReactElement, type ReactNode } from 'react'

import styles from './Tooltip.module.css'

const ProviderContext = createContext(false)

/** 앱 맨 위에 한 번 둔다. 풍선 사이를 빠르게 옮겨 다닐 때 기다리는 시간을 함께 쓴다. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <ProviderContext.Provider value={true}>
      <RadixTooltip.Provider delayDuration={450} skipDelayDuration={250}>
        {children}
      </RadixTooltip.Provider>
    </ProviderContext.Provider>
  )
}

export type TooltipProps = {
  /** 풍선에 적을 짧은 말 */
  label: ReactNode
  /** 풍선이 붙을 대상. 포커스를 받을 수 있는 요소 하나 */
  children: ReactElement
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  /** 단축키가 있으면 풍선 끝에 붙인다 */
  shortcut?: string
  className?: string
}

/** 작은 먹색 이름표. 아이콘만 있는 버튼의 이름을 알려 준다. */
export function Tooltip({ label, children, side = 'bottom', align = 'center', shortcut, className }: TooltipProps) {
  const hasProvider = useContext(ProviderContext)
  const tooltip = (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          className={clsx(styles.tooltip, className)}
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
        >
          {label}
          {shortcut && <span className={styles.shortcut}>{shortcut}</span>}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
  // 공급자 없이도(시험, 갤러리) 그대로 쓸 수 있게 한다.
  return hasProvider ? tooltip : <RadixTooltip.Provider delayDuration={450}>{tooltip}</RadixTooltip.Provider>
}
