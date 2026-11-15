/**
 * 서버 데이터 훅 모음. 화면은 여기 있는 훅만 써서 서버와 이야기한다.
 *
 * 쿼리 키 규칙 (실시간 연결이 이 접두사로 무효화한다):
 *   ['overview'] ['leads', …] ['rules'] ['groups', …] ['accounts', …] ['logs', …] ['settings'] ['blocklist']
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api, unwrap, type Schemas } from './client'

// ── 타입 별칭 ────────────────────────────────────────────────

export type Account = Schemas['AccountOut']
export type AccountStatus = Schemas['AccountStatus']
export type Dialog = Schemas['DialogOut']
export type Group = Schemas['GroupOut']
export type GroupStatus = Schemas['GroupStatus']
export type GroupKind = Schemas['GroupKind']
export type GroupJoinItem = Schemas['GroupJoinItem']
export type GroupJoinResponse = Schemas['GroupJoinResponse']
export type Rule = Schemas['RuleOut']
export type RuleKind = Schemas['RuleKind']
export type RuleCreate = Schemas['RuleCreate']
export type RuleUpdate = Schemas['RuleUpdate']
export type MatchMode = Schemas['MatchMode']
export type Lead = Schemas['LeadOut']
export type LeadDetail = Schemas['LeadDetail']
export type LeadStatus = Schemas['LeadStatus']
export type LeadList = Schemas['LeadListResponse']
export type LeadBulkRequest = Schemas['LeadBulkRequest']
export type Hit = Schemas['HitOut']
export type FeedItem = Schemas['FeedItem']
export type Overview = Schemas['OverviewOut']
export type DayPoint = Schemas['DayPoint']
export type LogEntry = Schemas['LogOut']
export type LogLevel = Schemas['LogLevel']
export type LogCategory = Schemas['LogCategory']
export type LogList = Schemas['LogListResponse']
export type Settings = Schemas['SettingsOut']
export type SettingsUpdate = Schemas['SettingsUpdate']
export type BlocklistEntry = Schemas['BlocklistOut']
export type LoginStart = Schemas['LoginStartResponse']
export type LoginStep = Schemas['LoginStepResponse']

export type LeadSort = 'last_seen' | 'first_seen' | 'hit_count' | 'username'
export type SortOrder = 'asc' | 'desc'

/** 수집함 목록·내보내기에 쓰는 필터. 비어 있는 값은 보내지 않는다. */
export type LeadFilters = {
  q?: string
  status?: LeadStatus[]
  rule_id?: number
  group_id?: number
  kind?: RuleKind
  /** 마지막 감지 시각 기준. 날짜(YYYY-MM-DD) 또는 ISO 시각 */
  since?: string
  until?: string
  sort?: LeadSort
  order?: SortOrder
}

export type LeadListParams = LeadFilters & { page?: number; page_size?: number }

export type GroupFilters = { account_id?: number; status?: GroupStatus[]; q?: string }

export type LogParams = {
  level?: LogLevel
  category?: LogCategory
  account_id?: number
  page?: number
  page_size?: number
}

// ── 쿼리 키 ──────────────────────────────────────────────────

export const keys = {
  /** 7일(기본)은 머리띠와 같은 키를 써서 한 번만 불러온다. */
  overview: (days = 7) => (days === 7 ? (['overview'] as const) : (['overview', days] as const)),
  leads: ['leads'] as const,
  leadList: (params: LeadListParams) => ['leads', 'list', params] as const,
  lead: (id: number) => ['leads', 'detail', id] as const,
  rules: ['rules'] as const,
  groups: ['groups'] as const,
  groupList: (filters: GroupFilters) => ['groups', 'list', filters] as const,
  accounts: ['accounts'] as const,
  accountList: ['accounts', 'list'] as const,
  dialogs: (accountId: number) => ['accounts', 'dialogs', accountId] as const,
  logs: ['logs'] as const,
  logList: (params: LogParams) => ['logs', 'list', params] as const,
  settings: ['settings'] as const,
  blocklist: ['blocklist'] as const,
}

function invalidate(client: QueryClient, ...prefixes: (readonly unknown[])[]) {
  for (const queryKey of prefixes) void client.invalidateQueries({ queryKey })
}

/** 빈 문자열·빈 배열·undefined 를 뺀다. */
function compact<T extends Record<string, unknown>>(input: T): Partial<T> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value) && value.length === 0) continue
    out[key] = value
  }
  return out as Partial<T>
}

// ── 개요 ─────────────────────────────────────────────────────

export function useOverview(days = 7) {
  return useQuery({
    queryKey: keys.overview(days),
    queryFn: () => unwrap(api.GET('/api/overview', { params: { query: { days } } })),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
}

// ── 수집함 ───────────────────────────────────────────────────

export function useLeads(params: LeadListParams) {
  const query = compact(params)
  return useQuery({
    queryKey: keys.leadList(query),
    queryFn: () => unwrap(api.GET('/api/leads', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

export function useLead(id: number | null) {
  return useQuery({
    queryKey: keys.lead(id ?? 0),
    queryFn: () =>
      unwrap(api.GET('/api/leads/{lead_id}', { params: { path: { lead_id: id as number } } })),
    enabled: id !== null,
  })
}

export function useUpdateLead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas['LeadUpdate']) =>
      unwrap(api.PATCH('/api/leads/{lead_id}', { params: { path: { lead_id: id } }, body })),
    onSuccess: () => invalidate(client, keys.leads, keys.overview(), keys.blocklist),
  })
}

export function useBulkLeads() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: LeadBulkRequest) => unwrap(api.POST('/api/leads/bulk', { body })),
    onSuccess: () => invalidate(client, keys.leads, keys.overview(), keys.blocklist),
  })
}

export function useDeleteLead() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/leads/{lead_id}', { params: { path: { lead_id: id } } })),
    onSuccess: () => invalidate(client, keys.leads, keys.overview()),
  })
}

/**
 * 내보내기 파일 주소. <a href={…} download> 로 쓴다.
 * ids 를 주면 그 유저들만, 아니면 필터에 맞는 전체를 내보낸다.
 */
export function leadExportUrl(
  format: 'csv' | 'txt',
  options: { ids?: number[]; filters?: LeadFilters } = {},
): string {
  const search = new URLSearchParams({ format })
  if (options.ids && options.ids.length > 0) {
    search.set('ids', options.ids.join(','))
  } else {
    for (const [key, value] of Object.entries(compact(options.filters ?? {}))) {
      if (Array.isArray(value)) for (const item of value) search.append(key, String(item))
      else search.set(key, String(value))
    }
  }
  return `/api/leads/export?${search.toString()}`
}

// ── 수집 규칙 ────────────────────────────────────────────────

export function useRules() {
  return useQuery({ queryKey: keys.rules, queryFn: () => unwrap(api.GET('/api/rules')) })
}

export function useCreateRule() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: RuleCreate) => unwrap(api.POST('/api/rules', { body })),
    onSuccess: () => invalidate(client, keys.rules, keys.overview()),
  })
}

export function useUpdateRule() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & RuleUpdate) =>
      unwrap(api.PATCH('/api/rules/{rule_id}', { params: { path: { rule_id: id } }, body })),
    onSuccess: () => invalidate(client, keys.rules, keys.overview()),
  })
}

export function useDeleteRule() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/rules/{rule_id}', { params: { path: { rule_id: id } } })),
    onSuccess: () => invalidate(client, keys.rules, keys.overview(), keys.leads),
  })
}

// ── 그룹 ─────────────────────────────────────────────────────

export function useGroups(filters: GroupFilters = {}) {
  const query = compact(filters)
  return useQuery({
    queryKey: keys.groupList(query),
    queryFn: () => unwrap(api.GET('/api/groups', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

export function useJoinGroups() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['GroupJoinRequest']) => unwrap(api.POST('/api/groups/join', { body })),
    onSuccess: () => invalidate(client, keys.groups, keys.accounts, keys.overview()),
  })
}

export function useUpdateGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas['GroupUpdate']) =>
      unwrap(api.PATCH('/api/groups/{group_id}', { params: { path: { group_id: id } }, body })),
    onSuccess: () => invalidate(client, keys.groups, keys.overview()),
  })
}

export function useRetryGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST('/api/groups/{group_id}/retry', { params: { path: { group_id: id } } })),
    onSuccess: () => invalidate(client, keys.groups, keys.accounts, keys.overview()),
  })
}

export function useDeleteGroup() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, leave = false }: { id: number; leave?: boolean }) =>
      unwrap(
        api.DELETE('/api/groups/{group_id}', {
          params: { path: { group_id: id }, query: { leave } },
        }),
      ),
    onSuccess: () => invalidate(client, keys.groups, keys.accounts, keys.overview(), keys.rules),
  })
}

// ── 계정 ─────────────────────────────────────────────────────

export function useAccounts() {
  return useQuery({
    queryKey: keys.accountList,
    queryFn: () => unwrap(api.GET('/api/accounts')),
    refetchInterval: 30_000,
  })
}

export function useUpdateAccount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas['AccountUpdate']) =>
      unwrap(api.PATCH('/api/accounts/{account_id}', { params: { path: { account_id: id } }, body })),
    onSuccess: () => invalidate(client, keys.accounts, keys.overview(), keys.groups),
  })
}

export function useReconnectAccount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.POST('/api/accounts/{account_id}/reconnect', { params: { path: { account_id: id } } }),
      ),
    onSuccess: () => invalidate(client, keys.accounts, keys.overview()),
  })
}

export function useDeleteAccount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, logOut = false }: { id: number; logOut?: boolean }) =>
      unwrap(
        api.DELETE('/api/accounts/{account_id}', {
          params: { path: { account_id: id }, query: { log_out: logOut } },
        }),
      ),
    onSuccess: () => invalidate(client, keys.accounts, keys.groups, keys.overview()),
  })
}

/** 전화번호로 인증 코드를 보낸다. */
export function useStartLogin() {
  return useMutation({
    mutationFn: (phone: string) =>
      unwrap(api.POST('/api/accounts/login/start', { body: { phone } })),
  })
}

/** 인증 코드를 넣는다. status 가 password_required 면 2단계 비밀번호가 더 필요하다. */
export function useSubmitLoginCode() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['LoginCodeRequest']) =>
      unwrap(api.POST('/api/accounts/login/code', { body })),
    onSuccess: (step) => {
      if (step.status === 'done') invalidate(client, keys.accounts, keys.overview())
    },
  })
}

export function useSubmitLoginPassword() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['LoginPasswordRequest']) =>
      unwrap(api.POST('/api/accounts/login/password', { body })),
    onSuccess: (step) => {
      if (step.status === 'done') invalidate(client, keys.accounts, keys.overview())
    },
  })
}

export function useCancelLogin() {
  return useMutation({
    mutationFn: (loginId: string) =>
      unwrap(
        api.DELETE('/api/accounts/login/{login_id}', { params: { path: { login_id: loginId } } }),
      ),
  })
}

/** 세션 문자열로 계정을 불러온다. */
export function useImportSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['SessionImportRequest']) =>
      unwrap(api.POST('/api/accounts/import', { body })),
    onSuccess: () => invalidate(client, keys.accounts, keys.overview()),
  })
}

/** .session 파일로 계정을 불러온다. */
export function useImportSessionFile() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, label }: { file: File; label?: string }) =>
      unwrap(
        api.POST('/api/accounts/import-file', {
          // 실제 전송은 아래 bodySerializer 가 만든 FormData 로 한다.
          body: { file: file.name, label },
          bodySerializer: () => {
            const form = new FormData()
            form.append('file', file)
            if (label) form.append('label', label)
            return form
          },
        }),
      ),
    onSuccess: () => invalidate(client, keys.accounts, keys.overview()),
  })
}

/** 계정이 이미 들어가 있는 그룹 목록. 계정이 연결돼 있어야 한다. */
export function useDialogs(accountId: number | null) {
  return useQuery({
    queryKey: keys.dialogs(accountId ?? 0),
    queryFn: () =>
      unwrap(
        api.GET('/api/accounts/{account_id}/dialogs', {
          params: { path: { account_id: accountId as number } },
        }),
      ),
    enabled: accountId !== null,
    staleTime: 0,
  })
}

export function useImportDialogs() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ accountId, tgChatIds }: { accountId: number; tgChatIds: number[] }) =>
      unwrap(
        api.POST('/api/accounts/{account_id}/dialogs/import', {
          params: { path: { account_id: accountId } },
          body: { tg_chat_ids: tgChatIds },
        }),
      ),
    onSuccess: () => invalidate(client, keys.groups, keys.accounts, keys.overview()),
  })
}

// ── 활동 기록 ────────────────────────────────────────────────

export function useLogs(params: LogParams = {}) {
  const query = compact(params)
  return useQuery({
    queryKey: keys.logList(query),
    queryFn: () => unwrap(api.GET('/api/logs', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

export function useClearLogs() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/logs')),
    onSuccess: () => invalidate(client, keys.logs),
  })
}

// ── 설정 ─────────────────────────────────────────────────────

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: () => unwrap(api.GET('/api/settings')) })
}

export function useUpdateSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SettingsUpdate) => unwrap(api.PATCH('/api/settings', { body })),
    onSuccess: (settings) => {
      client.setQueryData(keys.settings, settings)
      invalidate(client, keys.accounts, keys.overview())
    },
  })
}

/** 저장해 둔 텔레그램 API 키를 지운다. */
export function useClearTelegramApi() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/settings/telegram-api')),
    onSuccess: (settings) => {
      client.setQueryData(keys.settings, settings)
      invalidate(client, keys.accounts)
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: Schemas['PasswordChangeRequest']) =>
      unwrap(api.POST('/api/auth/password', { body })),
  })
}

// ── 제외 목록 ────────────────────────────────────────────────

export function useBlocklist() {
  return useQuery({ queryKey: keys.blocklist, queryFn: () => unwrap(api.GET('/api/blocklist')) })
}

export function useAddBlocklist() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Schemas['BlocklistCreate']) => unwrap(api.POST('/api/blocklist', { body })),
    onSuccess: () => invalidate(client, keys.blocklist, keys.leads, keys.overview()),
  })
}

export function useRemoveBlocklist() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/blocklist/{entry_id}', { params: { path: { entry_id: id } } })),
    onSuccess: () => invalidate(client, keys.blocklist),
  })
}
