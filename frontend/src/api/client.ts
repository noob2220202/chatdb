import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

export type Schemas = components['schemas']

/** API 오류. detail 은 화면에 그대로 보여 줄 수 있는 한국어 문장이다. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null
  readonly retryAfter: number | null

  constructor(status: number, detail: string, code: string | null = null, retryAfter: number | null = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

/** 로그인이 풀렸을 때(401) window 에 쏘는 이벤트 이름. */
export const UNAUTHORIZED_EVENT = 'chatdb:unauthorized'

export const api = createClient<paths>({ baseUrl: '/', credentials: 'same-origin' })

type FetchResult<T> = { data?: T; error?: unknown; response: Response }

function readErrorBody(body: unknown): { detail?: string; code?: string | null; retry_after?: number | null } {
  return typeof body === 'object' && body !== null ? (body as Record<string, never>) : {}
}

/**
 * openapi-fetch 호출 결과에서 data 를 꺼낸다. 실패하면 ApiError 를 던진다.
 *
 *   const accounts = await unwrap(api.GET('/api/accounts'))
 */
export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>
  try {
    result = await request
  } catch {
    throw new ApiError(0, '서버에 연결할 수 없어요. 잠시 뒤에 다시 시도해 주세요.', 'network')
  }
  const { data, error, response } = result
  if (response.ok) return data as T

  const body = readErrorBody(error)
  const apiError = new ApiError(
    response.status,
    body.detail ?? '요청을 처리하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
    body.code ?? null,
    body.retry_after ?? null,
  )
  if (response.status === 401 && apiError.code === 'unauthorized') {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }
  throw apiError
}

/** 오류를 화면에 보여 줄 한 문장으로 바꾼다. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return '문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.'
}
