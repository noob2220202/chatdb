import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

/** 앱 전체가 함께 쓰는 쿼리 설정. 10초 동안은 새로 묻지 않고, 실패하면 한 번만 다시 묻는다. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: true,
        // 로그인이 풀렸거나(401) 없는 것을 물었을 때(404)는 다시 물어도 같다.
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          return failureCount < 1
        },
      },
      mutations: { retry: false },
    },
  })
}
