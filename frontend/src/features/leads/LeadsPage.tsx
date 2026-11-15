import { Copy, DownloadSimple, Prohibit, Swap, Trash } from '@phosphor-icons/react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import {
  leadExportUrl,
  useBulkLeads,
  useGroups,
  useLeads,
  useOverview,
  useRules,
  type Lead,
  type LeadSort,
  type LeadStatus,
} from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatCount, formatDateTime, formatNumber, formatRelative } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import { EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { Kbd } from '@/ui/Kbd/Kbd'
import { Menu, MenuItem } from '@/ui/Menu/Menu'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { Pagination } from '@/ui/Pagination/Pagination'
import { SearchField } from '@/ui/SearchField/SearchField'
import { Segmented } from '@/ui/Segmented/Segmented'
import { Select } from '@/ui/Select/Select'
import { SkeletonRows } from '@/ui/Skeleton/Skeleton'
import { LEAD_STATUS, LeadStatusLabel } from '@/ui/StatusLamp/StatusLamp'
import {
  SelectionAction,
  SelectionBand,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  useRowNavigation,
} from '@/ui/Table/Table'
import { Tabs } from '@/ui/Tabs/Tabs'
import { Tally } from '@/ui/Tally/Tally'
import { useToast } from '@/ui/Toast/Toast'
import { Tooltip } from '@/ui/Tooltip/Tooltip'

import {
  HitText,
  RuleName,
  isTyping,
  shared,
  useDebounced,
  useNow,
  useSwatchIndex,
  useUrlState,
} from '../shared/shared'
import { LeadDrawer } from './LeadDrawer'
import styles from './LeadsPage.module.css'
import {
  STATUSES,
  hasFilters,
  previewHandles,
  rangeIds,
  readView,
  sortLabel,
  toFilters,
  type Period,
} from './leadsState'

const DENSITY_KEY = 'chatdb.leads.density'
type Density = 'roomy' | 'compact'
const COLUMNS = [44, 210, 150, null, 200, 118, 110, 128] as const
const ALL = 'all'

function download(url: string) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = ''
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}

export default function LeadsPage() {
  const toast = useToast()
  const now = useNow()
  const url = useUrlState()
  const view = useMemo(() => readView(url.params), [url.params])
  const filters = useMemo(() => toFilters(view), [view])
  const swatches = useSwatchIndex()

  const [search, setSearch] = useState(view.q)
  const debounced = useDebounced(search)
  useEffect(() => {
    if (debounced !== view.q) url.set({ q: debounced, page: null })
    // 주소는 입력이 멈췄을 때만 바꾼다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])

  const [density, setDensity] = useState<Density>(() =>
    localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'roomy',
  )
  useEffect(() => localStorage.setItem(DENSITY_KEY, density), [density])

  const leads = useLeads({ ...filters, page: view.page, page_size: view.pageSize })
  const overview = useOverview()
  const rules = useRules()
  const groups = useGroups({ status: ['joined'] })
  const bulk = useBulkLeads()

  const items = useMemo(() => leads.data?.items ?? [], [leads.data])
  const ids = useMemo(() => items.map((lead) => lead.id), [items])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const anchor = useRef<number | null>(null)
  const [confirm, setConfirm] = useState<'block' | 'delete' | null>(null)

  // 쪽이나 필터가 바뀌면 선택을 푼다
  // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
  useEffect(() => setSelected(new Set()), [view.page, view.pageSize, filters])

  const selectedLeads = items.filter((lead) => selected.has(lead.id))
  const allChecked =
    selected.size === 0 ? false : selected.size === items.length ? true : 'indeterminate'
  const clear = () => setSelected(new Set())
  const toggleAll = () => setSelected(selected.size === items.length ? new Set() : new Set(ids))
  const toggle = (index: number, range = false) => {
    const id = ids[index]
    if (id === undefined) return
    setSelected((previous) => {
      const next = new Set(previous)
      if (range && anchor.current !== null) {
        for (const each of rangeIds(ids, anchor.current, index)) next.add(each)
      } else if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    anchor.current = index
  }

  const openLead = (lead: Lead) => url.set({ lead: lead.id }, false)
  const nav = useRowNavigation({
    count: items.length,
    onToggle: (index) => toggle(index),
    onOpen: (index) => {
      const lead = items[index]
      if (lead) openLead(lead)
    },
  })

  const fail = (error: unknown) => toast.problem(errorMessage(error))
  const targets = (fallback?: Lead) =>
    selectedLeads.length ? selectedLeads : fallback ? [fallback] : []

  const copyHandles = async (list: Lead[]) => {
    if (!list.length) return
    try {
      await navigator.clipboard.writeText(list.map((lead) => `@${lead.username}`).join('\n'))
      toast.show(`${formatCount(list.length, '명')}의 @아이디를 복사했어요`)
    } catch {
      toast.problem('복사하지 못했어요. 브라우저에서 복사 권한을 확인해 주세요.')
    }
  }
  const setStatus = (list: Lead[], status: LeadStatus) =>
    bulk.mutate(
      { ids: list.map((lead) => lead.id), action: 'set_status', status },
      {
        onSuccess: () => {
          toast.show(
            `${formatCount(list.length, '명')}을 ‘${LEAD_STATUS[status].label}’(으)로 바꿨어요`,
          )
          clear()
        },
        onError: fail,
      },
    )
  const runBulk = (action: 'block' | 'delete') =>
    bulk
      .mutateAsync({ ids: selectedLeads.map((lead) => lead.id), action })
      .then((result) => {
        toast.show(
          action === 'block'
            ? `${formatCount(result.affected, '명')}을 제외 목록에 올렸어요`
            : `${formatCount(result.affected, '명')}을 지웠어요`,
        )
        clear()
      })
      .catch(fail)

  const onRowKey = (event: KeyboardEvent<HTMLTableRowElement>, index: number) => {
    if (event.target !== event.currentTarget || event.metaKey || event.ctrlKey) return
    const lead = items[index]
    const key = event.key.toLowerCase()
    if (key === 'x') toggle(index, event.shiftKey)
    else if (key === 'c') void copyHandles(targets(lead))
    else if (key === 'e' && lead) {
      if (!selected.has(lead.id)) setSelected(new Set([lead.id]))
      setConfirm('block')
    } else return
    event.preventDefault()
  }

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape' && selected.size && !isTyping(event.target)) clear()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected.size])

  const flip = (sort: LeadSort) =>
    url.set({
      sort,
      order: view.sort === sort && view.order === 'desc' ? 'asc' : 'desc',
      page: null,
    })
  const sortOf = (sort: LeadSort) => (view.sort === sort ? view.order : 'none')

  const counts = leads.data?.status_counts ?? {}
  const totalAll = STATUSES.reduce((sum, status) => sum + (counts[status] ?? 0), 0)
  const lastHit = overview.data?.recent_hits[0]?.created_at
  const leadParam = url.num('lead') ?? null
  const filtered = hasFilters(view)

  const summary = overview.data ? (
    <>
      오늘 <b>{formatCount(overview.data.today_new, '명')}</b>이 새로 들어왔어요.
      {lastHit && ` 마지막으로 받아 적은 건 ${formatRelative(lastHit, now)}이에요.`}
    </>
  ) : undefined

  return (
    <div className={shared.page}>
      <PageHeader
        title="수집함"
        count={overview.data ? `전체 ${formatCount(overview.data.total_leads, '명')}` : undefined}
        summary={summary}
        aside={
          <div className={styles.asideStats}>
            <Segmented<Density>
              aria-label="행 간격"
              size="sm"
              value={density}
              onValueChange={setDensity}
              options={[
                { value: 'roomy', label: '넉넉하게' },
                { value: 'compact', label: '촘촘하게' },
              ]}
            />
            <Menu
              align="end"
              trigger={
                <Button leadingIcon={<DownloadSimple />}>
                  {filtered ? '걸러 낸 사람 내보내기' : '모두 내보내기'}
                </Button>
              }
            >
              <MenuItem
                onSelect={() => download(leadExportUrl('csv', { filters }))}
                note="엑셀에서 열 수 있어요"
              >
                CSV 파일
              </MenuItem>
              <MenuItem
                onSelect={() => download(leadExportUrl('txt', { filters }))}
                note="한 줄에 하나씩"
              >
                @아이디 목록 (TXT)
              </MenuItem>
            </Menu>
          </div>
        }
      />

      <div className={shared.filters}>
        <SearchField
          className={shared.grow}
          value={search}
          onValueChange={setSearch}
          placeholder="@아이디, 이름, 메모로 찾기"
          aria-label="수집함에서 찾기"
        />
        <Select
          variant="bare"
          prefix="규칙"
          aria-label="규칙"
          value={view.ruleId ? String(view.ruleId) : ALL}
          onValueChange={(value) => url.set({ rule_id: value === ALL ? null : value, page: null })}
          options={[
            { value: ALL, label: '전체' },
            ...(rules.data ?? []).map((rule) => ({ value: String(rule.id), label: rule.name })),
          ]}
        />
        <Select
          variant="bare"
          prefix="그룹"
          aria-label="그룹"
          value={view.groupId ? String(view.groupId) : ALL}
          onValueChange={(value) => url.set({ group_id: value === ALL ? null : value, page: null })}
          options={[
            { value: ALL, label: '전체' },
            ...(groups.data ?? []).map((group) => ({
              value: String(group.id),
              label: group.display_title,
            })),
          ]}
        />
        <Select
          variant="bare"
          prefix="기간"
          aria-label="기간"
          value={view.period || ALL}
          onValueChange={(value) =>
            url.set({ period: value === ALL ? null : (value as Period), page: null })
          }
          options={[
            { value: ALL, label: '전체 기간' },
            { value: 'today', label: '오늘' },
            { value: '7d', label: '최근 7일' },
            { value: '30d', label: '최근 30일' },
          ]}
        />
      </div>

      <Tabs<LeadStatus | typeof ALL>
        aria-label="상태"
        value={view.status || ALL}
        onValueChange={(value) => url.set({ status: value === ALL ? null : value, page: null })}
        items={[
          { value: ALL, label: '전체', count: leads.data ? totalAll : undefined },
          ...STATUSES.map((status) => ({
            value: status,
            label: LEAD_STATUS[status].label,
            count: leads.data ? (counts[status] ?? 0) : undefined,
          })),
        ]}
      />

      {leads.isError ? (
        <ErrorState message={errorMessage(leads.error)} onRetry={() => void leads.refetch()} />
      ) : leads.isLoading ? (
        <SkeletonRows rows={12} density={density} />
      ) : items.length === 0 ? (
        filtered ? (
          <EmptyState
            photo={photos[PHOTO_FOR.noResults]}
            title="조건에 맞는 사람이 없어요"
            description="찾는 말이나 걸러 보기 조건을 바꿔 보세요."
            action={
              <Button
                onClick={() => {
                  setSearch('')
                  url.set({
                    q: null,
                    status: null,
                    rule_id: null,
                    group_id: null,
                    period: null,
                    page: null,
                  })
                }}
              >
                조건 모두 지우기
              </Button>
            }
          />
        ) : (
          <EmptyState
            size="page"
            photo={photos[PHOTO_FOR.leads]}
            title="아직 받아 적은 사람이 없어요"
            description="그룹에 들어가 있고 수집 규칙이 켜져 있으면, 찾는 말이 나오는 대로 여기에 적혀요."
            action={
              <>
                <Button asChild variant="solid">
                  <Link to="/rules">수집 규칙 보기</Link>
                </Button>
                <Button asChild>
                  <Link to="/groups">그룹 넣기</Link>
                </Button>
              </>
            }
          />
        )
      ) : (
        <>
          <Table
            density={density}
            columns={COLUMNS}
            minWidth={1080}
            stickyTop={0}
            pending={leads.isPlaceholderData}
            aria-label="받아 적은 사람"
            band={
              <SelectionBand
                count={selected.size}
                onClear={clear}
                label="고른 사람에게 할 일"
                leading={
                  <Checkbox
                    onInk
                    checked={allChecked}
                    onCheckedChange={toggleAll}
                    aria-label="이 쪽 모두 고르기"
                  />
                }
              >
                <span className={styles.preview}>
                  {previewHandles(selectedLeads.map((lead) => lead.username))}
                </span>
                <SelectionAction
                  icon={<Copy size={15} aria-hidden />}
                  onClick={() => void copyHandles(selectedLeads)}
                >
                  @아이디 복사
                </SelectionAction>
                <Menu
                  trigger={
                    <SelectionAction icon={<DownloadSimple size={15} aria-hidden />}>
                      내보내기
                    </SelectionAction>
                  }
                >
                  <MenuItem onSelect={() => download(leadExportUrl('csv', { ids: [...selected] }))}>
                    CSV 파일
                  </MenuItem>
                  <MenuItem onSelect={() => download(leadExportUrl('txt', { ids: [...selected] }))}>
                    @아이디 목록 (TXT)
                  </MenuItem>
                </Menu>
                <Menu
                  trigger={
                    <SelectionAction icon={<Swap size={15} aria-hidden />}>
                      상태 바꾸기
                    </SelectionAction>
                  }
                >
                  {(['new', 'reviewed', 'contacted'] as const).map((status) => (
                    <MenuItem key={status} onSelect={() => setStatus(selectedLeads, status)}>
                      {LEAD_STATUS[status].label}
                    </MenuItem>
                  ))}
                </Menu>
                <SelectionAction
                  icon={<Prohibit size={15} aria-hidden />}
                  onClick={() => setConfirm('block')}
                >
                  제외
                </SelectionAction>
                <SelectionAction
                  icon={<Trash size={15} aria-hidden />}
                  onClick={() => setConfirm('delete')}
                >
                  지우기
                </SelectionAction>
              </SelectionBand>
            }
          >
            <THead>
              <TR>
                <TH>
                  <Checkbox
                    checked={allChecked}
                    onCheckedChange={toggleAll}
                    aria-label="이 쪽 모두 고르기"
                  />
                </TH>
                <TH sort={sortOf('username')} onSort={() => flip('username')}>
                  유저
                </TH>
                <TH colSpan={2}>감지 내용</TH>
                <TH>그룹</TH>
                <TH align="end" sort={sortOf('hit_count')} onSort={() => flip('hit_count')}>
                  감지 횟수
                </TH>
                <TH sort={sortOf('last_seen')} onSort={() => flip('last_seen')}>
                  마지막 감지
                </TH>
                <TH>상태</TH>
              </TR>
            </THead>
            <TBody>
              {items.map((lead, index) => {
                const rowProps = nav.getRowProps(index)
                const muted = lead.status === 'excluded'
                const hit = lead.last_hit
                return (
                  <TR
                    key={lead.id}
                    interactive
                    selected={selected.has(lead.id)}
                    muted={muted}
                    onClick={() => openLead(lead)}
                    {...rowProps}
                    onKeyDown={(event) => {
                      rowProps.onKeyDown(event)
                      onRowKey(event, index)
                    }}
                  >
                    <TD onClick={(event) => event.stopPropagation()}>
                      <span
                        onClickCapture={(event) => {
                          if (event.shiftKey) {
                            event.preventDefault()
                            event.stopPropagation()
                            toggle(index, true)
                          }
                        }}
                      >
                        <Checkbox
                          checked={selected.has(lead.id)}
                          onCheckedChange={() => toggle(index)}
                          aria-label={`@${lead.username} 고르기`}
                        />
                      </span>
                    </TD>
                    <TD truncate strike={muted}>
                      <span className={shared.handle}>@{lead.username}</span>
                      {lead.display_name !== lead.username && (
                        <span className={shared.sub}>{lead.display_name}</span>
                      )}
                    </TD>
                    <TD truncate>
                      {hit ? <RuleName hit={hit} swatches={swatches} muted={muted} /> : '—'}
                    </TD>
                    <TD>
                      <span className={styles.content}>
                        {hit && <HitText hit={hit} variant="table" muted={muted} maxLines={1} />}
                      </span>
                    </TD>
                    <TD truncate dim>
                      {hit?.group_title ?? '—'}
                    </TD>
                    <TD align="end">
                      <Tally count={lead.hit_count} unit="번" muted={muted} />
                    </TD>
                    <TD dim>
                      <Tooltip label={formatDateTime(lead.last_seen_at, now)}>
                        <span>{formatRelative(lead.last_seen_at, now)}</span>
                      </Tooltip>
                    </TD>
                    <TD>
                      <LeadStatusLabel status={lead.status} />
                    </TD>
                  </TR>
                )
              })}
            </TBody>
          </Table>
          <Pagination
            page={view.page}
            pageSize={view.pageSize}
            total={leads.data?.total ?? 0}
            pending={leads.isFetching}
            onPageChange={(page) => url.set({ page: page === 1 ? null : page }, false)}
            onPageSizeChange={(size) => url.set({ size: size === 50 ? null : size, page: null })}
            sortLabel={sortLabel(view.sort, view.order)}
          />
          <p className={shared.legend}>
            <span>
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> 옮기기
            </span>
            <span>
              <Kbd>X</Kbd> 고르기
            </span>
            <span>
              <Kbd>Enter</Kbd> 자세히 보기
            </span>
            <span>
              <Kbd>C</Kbd> @아이디 복사
            </span>
            <span>
              <Kbd>E</Kbd> 제외
            </span>
            <span>
              <Kbd>Esc</Kbd> 선택 풀기
            </span>
            <span>
              전체 {formatNumber(leads.data?.total ?? 0)}명 가운데 이 쪽에 {items.length}명
            </span>
          </p>
        </>
      )}

      <LeadDrawer
        leadId={leadParam}
        swatches={swatches}
        onClose={() => url.set({ lead: null }, false)}
      />

      <ConfirmDialog
        open={confirm === 'block'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`${formatCount(selected.size, '명')}을 제외할까요?`}
        consequence="제외 목록에 올라가서, 앞으로 키워드를 말하거나 활발해져도 다시 받아 적지 않아요."
        confirmLabel="제외하기"
        onConfirm={() => runBulk('block')}
      />
      <ConfirmDialog
        open={confirm === 'delete'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`${formatCount(selected.size, '명')}을 지울까요?`}
        consequence="감지 기록과 메모가 함께 지워져요. 나중에 다시 감지되면 새로 받아 적어요."
        confirmLabel="지우기"
        onConfirm={() => runBulk('delete')}
      />
    </div>
  )
}
