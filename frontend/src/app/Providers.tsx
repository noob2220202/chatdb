import { IconContext } from '@phosphor-icons/react'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ToastProvider } from '@/ui/Toast/Toast'
import { TooltipProvider } from '@/ui/Tooltip/Tooltip'

/** 아이콘은 한 벌(Phosphor), 한 굵기(Regular), 기본 16px. */
const ICON_DEFAULTS = { size: 16, weight: 'regular', color: 'currentColor' } as const

export function Providers({
  queryClient,
  children,
}: {
  queryClient: QueryClient
  children: ReactNode
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <IconContext.Provider value={ICON_DEFAULTS}>
        <TooltipProvider>
          <ToastProvider>{children}</ToastProvider>
        </TooltipProvider>
      </IconContext.Provider>
    </QueryClientProvider>
  )
}
