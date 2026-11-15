/**
 * 견본 — 데이터 표시 부품.
 * 표, 수치, 램프, 무늬, 키워드, 차트, 사진, 빈 상태를 상태별로 한 장에 늘어놓는다.
 * 개발 중에만 /__gallery/data 로 열린다.
 */
import { Copy, DownloadSimple, Prohibit, Swap } from '@phosphor-icons/react'
import clsx from 'clsx'
import { useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'

import { OPERATOR_LAMP, photos, type PhotoKey } from '@/assets/photos'
import { buildSwatchIndex } from '@/lib/ruleSwatch'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { DefinitionItem, DefinitionList } from '@/ui/DefinitionList/DefinitionList'
import { BlankForm, EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { Figure } from '@/ui/Figure/Figure'
import { KeywordText } from '@/ui/KeywordText/KeywordText'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { Pagination } from '@/ui/Pagination/Pagination'
import { RankList } from '@/ui/RankList/RankList'
import { RuleName, RuleSwatch, RuleSwatchFill } from '@/ui/RuleSwatch/RuleSwatch'
import { SectionHead } from '@/ui/SectionHead/SectionHead'
import { SegmentedBar } from '@/ui/SegmentedBar/SegmentedBar'
import {
  Skeleton,
  SkeletonChart,
  SkeletonRows,
  SkeletonStatus,
  SkeletonText,
} from '@/ui/Skeleton/Skeleton'
import { SlotDots, SlotDotsScale } from '@/ui/SlotDots/SlotDots'
import { Ledger, StatHero, StatRow } from '@/ui/Stat/Stat'
import {
  ACCOUNT_STATUS,
  AccountStatusLabel,
  GROUP_STATUS,
  GroupStatusLabel,
  LEAD_STATUS,
  LeadStatusLabel,
  StatusLabel,
  StatusLamp,
  type AccountStatus,
  type GroupStatus,
  type LampKind,
  type LeadStatus,
} from '@/ui/StatusLamp/StatusLamp'
import {
  SelectionAction,
  SelectionBand,
  TBody,
  TD,
  TFoot,
  TH,
  THead,
  TR,
  Table,
  useRowNavigation,
  type SortDirection,
} from '@/ui/Table/Table'
import { Tally } from '@/ui/Tally/Tally'
import { TrendChart, type TrendPoint } from '@/ui/TrendChart/TrendChart'

import g from './DataGallery.module.css'

/* ── 견본 데이터 ───────────────────────────────────── */

const TODAY = '2026-11-15'

interface Rule {
  id: number
  name: string
  keywords: string[]
}

const RULES: Rule[] = [
  { id: 11, name: '견적 문의', keywords: ['견적', '외주'] },
  { id: 14, name: '업체 찾는 사람', keywords: ['업체 추천'] },
  { id: 20, name: '활발한 유저', keywords: [] },
  { id: 31, name: '광고 대행', keywords: ['광고 대행'] },
]
const SWATCH = buildSwatchIndex(RULES.map((rule) => rule.id))
const ruleOf = (id: number) => RULES.find((rule) => rule.id === id) ?? RULES[0]!
const swatchOf = (id: number) => SWATCH.get(id) ?? -1

interface Lead {
  handle: string
  name: string
  rule: number
  said?: string
  messages?: number
  room: string
  hits: number
  last: string
  status: LeadStatus
}

const LEADS: Lead[] = [
  {
    handle: '@jiwoo_kim92',
    name: '김지우',
    rule: 11,
    said: '혹시 상세페이지 외주 맡겨보신 분 계세요? 견적이 어느 정도인지 궁금해요',
    room: '스마트스토어 셀러 모임',
    hits: 4,
    last: '3분 전',
    status: 'new',
  },
  {
    handle: '@storelab_kr',
    name: '스토어랩',
    rule: 14,
    said: '배대지 업체 추천 좀 부탁드려요. 지금 쓰는 곳이 너무 느려서요',
    room: '해외구매대행 정보방',
    hits: 2,
    last: '4분 전',
    status: 'new',
  },
  {
    handle: '@minho_works',
    name: '민호',
    rule: 20,
    messages: 41,
    room: '프리랜서 디자이너 네트워크',
    hits: 1,
    last: '6분 전',
    status: 'new',
  },
  {
    handle: '@dalbit_market',
    name: '달빛마켓',
    rule: 11,
    said: '촬영 스튜디오 견적 받아보신 분 있나요',
    room: '쇼핑몰 창업 스터디',
    hits: 1,
    last: '8분 전',
    status: 'reviewed',
  },
  {
    handle: '@hyun_trade',
    name: '현',
    rule: 14,
    said: '동대문 사입 대행 업체추천 받습니다',
    room: '도매 사입 정보 공유',
    hits: 3,
    last: '11분 전',
    status: 'contacted',
  },
  {
    handle: '@seoyeon_ad',
    name: '서연',
    rule: 31,
    said: '메타 광고 대행 맡기려는데 수수료 보통 몇 프로예요?',
    room: '퍼포먼스 마케터 모임',
    hits: 12,
    last: '15분 전',
    status: 'new',
  },
  {
    handle: '@bongbong_shop',
    name: '봉봉샵',
    rule: 20,
    messages: 36,
    room: '스마트스토어 셀러 모임',
    hits: 1,
    last: '19분 전',
    status: 'reviewed',
  },
  {
    handle: '@taeyang_log',
    name: '태양',
    rule: 11,
    said: '택배 계약 견적 어디서 받으셨어요?',
    room: '위탁판매 초보방',
    hits: 1,
    last: '22분 전',
    status: 'new',
  },
  {
    handle: '@nari_studio',
    name: '나리 스튜디오',
    rule: 11,
    said: '로고 견적 문의는 어디로 드리면 될까요',
    room: '프리랜서 디자이너 네트워크',
    hits: 5,
    last: '41분 전',
    status: 'contacted',
  },
  {
    handle: '@ocean_import',
    name: '오션임포트',
    rule: 14,
    said: '통관 대행 업체 추천 부탁드립니다',
    room: '해외구매대행 정보방',
    hits: 2,
    last: '1시간 전',
    status: 'excluded',
  },
  {
    handle: '@jun_seller',
    name: '준',
    rule: 20,
    messages: 33,
    room: '위탁판매 초보방',
    hits: 1,
    last: '1시간 전',
    status: 'new',
  },
  {
    handle: '@mari_goods',
    name: '마리굿즈',
    rule: 31,
    said: '네이버 광고대행 써보신 분 후기 궁금해요',
    room: '쇼핑몰 창업 스터디',
    hits: 23,
    last: '2시간 전',
    status: 'reviewed',
  },
]

const LEAD_COLUMNS = [41, 196, 128, null, 200, 132, 92, 122] as const
/** 좁은 창에서는 그룹 열을 접는다. 열을 어떻게 줄일지는 화면이 정한다 */
const LEAD_COLUMNS_NARROW = [41, 176, 126, null, 124, 84, 118] as const

const NARROW_QUERY = '(max-width: 1180px)'

function useNarrow(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const media = window.matchMedia(NARROW_QUERY)
      media.addEventListener('change', notify)
      return () => media.removeEventListener('change', notify)
    },
    () => window.matchMedia(NARROW_QUERY).matches,
    () => false,
  )
}

interface Account {
  no: string
  name: string
  tail: string
  joined: number
  pending?: number
  status: AccountStatus
  note?: ReactNode
}

const ACCOUNTS: Account[] = [
  { no: '01', name: '지우', tail: '3421', joined: 20, status: 'active' },
  { no: '02', name: '민호', tail: '8810', joined: 20, status: 'active' },
  { no: '03', name: '서연', tail: '1177', joined: 17, pending: 2, status: 'active' },
  { no: '05', name: '하늘', tail: '2284', joined: 18, status: 'connecting' },
  {
    no: '07',
    name: '예린',
    tail: '9038',
    joined: 20,
    status: 'flood_wait',
    note: '텔레그램이 요청을 잠시 막았어요. 14분 뒤에 다시 시작해요.',
  },
  { no: '08', name: '준서', tail: '4412', joined: 0, status: 'offline' },
  {
    no: '10',
    name: '건우',
    tail: '3359',
    joined: 13,
    status: 'reauth_required',
    note: (
      <>
        텔레그램에서 로그인이 풀렸어요. <a href="#accounts">다시 로그인하기</a>
      </>
    ),
  },
]

const WEEK: TrendPoint[] = [
  { date: '2026-11-09', keyword: 52, activity: 22 },
  { date: '2026-11-10', keyword: 61, activity: 30 },
  { date: '2026-11-11', keyword: 44, activity: 22 },
  { date: '2026-11-12', keyword: 83, activity: 37 },
  { date: '2026-11-13', keyword: 97, activity: 46 },
  { date: '2026-11-14', keyword: 68, activity: 29 },
  { date: '2026-11-15', keyword: 89, activity: 39 },
]

function series(days: number, keyword: number[], activity: number[]): TrendPoint[] {
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(2026, 10, 15 - (days - 1 - index))
    const pad = (value: number) => String(value).padStart(2, '0')
    return {
      date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
      keyword: keyword[index] ?? 0,
      activity: activity[index] ?? 0,
    }
  })
}

const FORTNIGHT = series(
  14,
  [38, 47, 41, 66, 71, 35, 29, 52, 61, 44, 83, 97, 68, 89],
  [17, 21, 19, 28, 33, 16, 12, 22, 30, 22, 37, 46, 29, 39],
)

const MONTH = series(
  30,
  [
    21, 26, 18, 31, 44, 39, 22, 17, 28, 35, 41, 52, 48, 27, 24, 33, 38, 47, 41, 66, 71, 35, 29, 52,
    61, 44, 83, 97, 68, 89,
  ],
  [
    9, 11, 8, 12, 19, 17, 10, 7, 12, 15, 18, 24, 21, 11, 10, 14, 17, 21, 19, 28, 33, 16, 12, 22, 30,
    22, 37, 46, 29, 39,
  ],
)

const QUIET = series(7, [], [])

const RANK = [
  { id: 1, label: '스마트스토어 셀러 모임', value: 612 },
  { id: 2, label: '해외구매대행 정보방', value: 498 },
  { id: 3, label: '쇼핑몰 창업 스터디', value: 431 },
  { id: 4, label: '퍼포먼스 마케터 모임', value: 377 },
  { id: 5, label: '도매 사입 정보 공유', value: 305 },
]

const SHARE = [
  { id: 11, label: '견적 문의', value: 1904, swatch: 0 },
  { id: 14, label: '업체 찾는 사람', value: 1216, swatch: 1 },
  { id: 20, label: '활발한 유저', value: 1004, swatch: 2 },
  { id: 31, label: '광고 대행', value: 688, swatch: 3 },
]

const SHARE_MANY = [
  { label: '견적 문의', value: 1204 },
  { label: '업체 찾는 사람', value: 916 },
  { label: '활발한 유저', value: 704 },
  { label: '광고 대행', value: 588 },
  { label: '촬영·영상', value: 412 },
  { label: '물류·배송', value: 356 },
  { label: '세무·회계', value: 241 },
  { label: '통관', value: 177 },
  { label: '번역', value: 120 },
  { label: '도메인·호스팅', value: 94 },
].map((item, index) => ({ ...item, id: index, swatch: index }))

const LAMP_VOCAB: { kind: LampKind; means: string }[] = [
  { kind: 'lit', means: '켜짐 — 새로 수집됨, 지금 받는 중. 빨강은 여기에만 써요' },
  { kind: 'ok', means: '정상 — 연결됨, 가입됨' },
  { kind: 'wait', means: '잠시 대기 — 기다리면 풀리는 일' },
  { kind: 'pending', means: '하는 중 — 아직 끝나지 않은 일' },
  { kind: 'problem', means: '문제 — 손을 써야 하는 일. 반전과 ×' },
  { kind: 'off', means: '꺼짐 — 확인함, 꺼 둠, 차례를 기다림' },
  { kind: 'done', means: '끝냄 — 연락함' },
  { kind: 'muted', means: '빠짐 — 제외, 나간 그룹' },
]

const FEED_TIMES = ['오후 2:14', '오후 2:13', '오후 2:11', '오후 2:09']

const PATTERN_NAMES = ['채움', '빗금', '빈 상자', '가로줄', '점', '세로줄', '성긴 빗금', '격자']

/* ── 견본 틀 ───────────────────────────────────────── */

function Specimen({
  no,
  title,
  names,
  children,
}: {
  no: string
  title: string
  names: string
  children: ReactNode
}) {
  return (
    <section className={g.specimen} aria-labelledby={`specimen-${no}`}>
      <SectionHead
        id={`specimen-${no}`}
        title={title}
        note={
          <span className={g.names}>
            {no} · {names}
          </span>
        }
      />
      {children}
    </section>
  )
}

function Case({
  label,
  code,
  span = 'span12',
  className,
  children,
}: {
  label: string
  code?: string
  span?: 'span3' | 'span4' | 'span5' | 'span6' | 'span7' | 'span8' | 'span12'
  className?: string
  children: ReactNode
}) {
  return (
    <div className={clsx(g.case, g[span], className)}>
      <p className={g.caseLabel}>
        {label}
        {code && <i>{code}</i>}
      </p>
      {children}
    </div>
  )
}

/* ── 수집함 표 견본 ────────────────────────────────── */

function LeadRowCells({ lead, showRoom }: { lead: Lead; showRoom: boolean }) {
  const rule = ruleOf(lead.rule)
  const out = lead.status === 'excluded'
  return (
    <>
      <TD>
        <span className={clsx(g.handle, out && g.handleOut)}>{lead.handle}</span>
        <span className={g.dname}>{lead.name}</span>
      </TD>
      <TD>
        <RuleName index={swatchOf(rule.id)} muted={out}>
          {rule.name}
        </RuleName>
      </TD>
      <TD truncate={false}>
        {lead.said ? (
          <KeywordText
            variant="table"
            text={lead.said}
            keywords={rule.keywords}
            quoted
            maxLines={1}
            muted={out}
          />
        ) : (
          <span className={clsx(g.activity, out && g.activityOut)}>
            24시간 동안 메시지 <b>{lead.messages}개</b>
          </span>
        )}
      </TD>
      {showRoom && <TD dim>{lead.room}</TD>}
      <TD align="end" className={g.countCell}>
        <Tally count={lead.hits} muted={out} />
      </TD>
      <TD dim>{lead.last}</TD>
      <TD>
        <LeadStatusLabel status={lead.status} />
      </TD>
    </>
  )
}

function LeadsSpecimen() {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(['@jiwoo_kim92', '@storelab_kr', '@seoyeon_ad']),
  )
  const [sort, setSort] = useState<{ key: 'last' | 'hits'; dir: SortDirection }>({
    key: 'last',
    dir: 'desc',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const narrow = useNarrow()
  const columns = narrow ? LEAD_COLUMNS_NARROW : LEAD_COLUMNS

  const toggle = (handle: string) =>
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(handle)) next.delete(handle)
      else next.add(handle)
      return next
    })
  const clear = () => setSelected(new Set())
  const allChecked =
    selected.size === 0 ? false : selected.size === LEADS.length ? true : 'indeterminate'
  const toggleAll = () =>
    setSelected(selected.size === LEADS.length ? new Set() : new Set(LEADS.map((l) => l.handle)))
  const flip = (key: 'last' | 'hits') =>
    setSort((previous) => ({
      key,
      dir: previous.key === key && previous.dir === 'desc' ? 'asc' : 'desc',
    }))

  const nav = useRowNavigation({
    count: LEADS.length,
    onToggle: (index) => {
      const lead = LEADS[index]
      if (lead) toggle(lead.handle)
    },
  })

  return (
    <>
      <div className={g.toolbar}>
        <span>
          <b>넉넉하게</b> · 선택 띠가 머리 행 위에 겹쳐요. 행을 눌러 고르고, ↑ ↓ 로 옮기고, Space 로
          고르고, Esc 로 풀어요.
        </span>
        <Button variant="quiet" size="sm" onClick={toggleAll}>
          {selected.size === LEADS.length ? '모두 풀기' : '이 쪽 모두 고르기'}
        </Button>
      </div>
      <Table
        density="roomy"
        edge="inset"
        columns={columns}
        minWidth={880}
        aria-label="수집한 유저"
        band={
          <SelectionBand
            count={selected.size}
            onClear={clear}
            label="선택한 유저에게 할 일"
            leading={
              <Checkbox
                onInk
                checked={allChecked}
                onCheckedChange={toggleAll}
                aria-label="이 쪽 전체 선택"
              />
            }
          >
            <SelectionAction icon={<Copy size={15} aria-hidden />}>@아이디 복사</SelectionAction>
            <SelectionAction icon={<DownloadSimple size={15} aria-hidden />}>
              CSV로 내보내기
            </SelectionAction>
            <SelectionAction icon={<Swap size={15} aria-hidden />}>상태 바꾸기</SelectionAction>
            <SelectionAction icon={<Prohibit size={15} aria-hidden />}>제외</SelectionAction>
          </SelectionBand>
        }
      >
        <THead>
          <TR>
            <TH>
              <Checkbox
                checked={allChecked}
                onCheckedChange={toggleAll}
                aria-label="이 쪽 전체 선택"
              />
            </TH>
            <TH>유저</TH>
            <TH colSpan={2}>감지 내용</TH>
            {!narrow && <TH>그룹</TH>}
            <TH
              align="end"
              className={g.countCell}
              sort={sort.key === 'hits' ? sort.dir : 'none'}
              onSort={() => flip('hits')}
            >
              감지 횟수
            </TH>
            <TH sort={sort.key === 'last' ? sort.dir : 'none'} onSort={() => flip('last')}>
              마지막 감지
            </TH>
            <TH>상태</TH>
          </TR>
        </THead>
        <TBody>
          {LEADS.map((lead, index) => (
            <TR
              key={lead.handle}
              interactive
              selected={selected.has(lead.handle)}
              muted={lead.status === 'excluded'}
              focused={index === 4}
              onClick={() => toggle(lead.handle)}
              {...nav.getRowProps(index)}
            >
              <TD onClick={(event) => event.stopPropagation()}>
                <Checkbox
                  checked={selected.has(lead.handle)}
                  onCheckedChange={() => toggle(lead.handle)}
                  aria-label={`${lead.handle} 선택`}
                />
              </TD>
              <LeadRowCells lead={lead} showRoom={!narrow} />
            </TR>
          ))}
        </TBody>
      </Table>
      <Pagination
        page={page}
        pageSize={pageSize}
        total={4812}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size)
          setPage(1)
        }}
        sortLabel={
          sort.key === 'last'
            ? sort.dir === 'desc'
              ? '마지막 감지가 가까운 순서'
              : '마지막 감지가 오래된 순서'
            : sort.dir === 'desc'
              ? '많이 감지된 순서'
              : '적게 감지된 순서'
        }
      />

      <div className={g.tableGap} />

      <div className={g.toolbar}>
        <span>
          <b>촘촘하게</b> · 아무것도 고르지 않았을 때. 머리 행이 그대로 보여요.
        </span>
      </div>
      <Table
        density="compact"
        edge="inset"
        columns={columns}
        minWidth={880}
        aria-label="수집한 유저, 촘촘하게"
      >
        <THead>
          <TR>
            <TH>
              <Checkbox
                checked={false}
                onCheckedChange={() => undefined}
                aria-label="이 쪽 전체 선택"
              />
            </TH>
            <TH>유저</TH>
            <TH colSpan={2}>감지 내용</TH>
            {!narrow && <TH>그룹</TH>}
            <TH align="end" className={g.countCell} sort="none">
              감지 횟수
            </TH>
            <TH sort="desc">마지막 감지</TH>
            <TH>상태</TH>
          </TR>
        </THead>
        <TBody>
          {LEADS.slice(5, 11).map((lead) => (
            <TR key={lead.handle} interactive muted={lead.status === 'excluded'}>
              <TD>
                <Checkbox
                  checked={false}
                  onCheckedChange={() => undefined}
                  aria-label={`${lead.handle} 선택`}
                />
              </TD>
              <LeadRowCells lead={lead} showRoom={!narrow} />
            </TR>
          ))}
        </TBody>
      </Table>
    </>
  )
}

function AccountsSpecimen() {
  const total = ACCOUNTS.reduce((sum, account) => sum + account.joined, 0)
  return (
    <Table density="compact" columns={[30, 50, 138, 158, 54, null]} aria-label="계정 상태">
      <THead>
        <TR>
          <TH colSpan={2}>계정</TH>
          <TH>번호</TH>
          <TH colSpan={2}>
            <SlotDotsScale />
          </TH>
          <TH>상태</TH>
        </TR>
      </THead>
      <TBody>
        {ACCOUNTS.flatMap((account) => {
          const tone =
            account.status === 'flood_wait'
              ? 'wait'
              : ACCOUNT_STATUS[account.status].kind === 'problem'
                ? 'problem'
                : 'normal'
          const row = (
            <TR key={account.no} joined={Boolean(account.note)}>
              <TD className={g.no}>{account.no}</TD>
              <TD className={g.accountName}>{account.name}</TD>
              <TD className={g.phone}>
                +82 10-<i>••••</i>-{account.tail}
              </TD>
              <TD>
                <SlotDots joined={account.joined} pending={account.pending} tone={tone} />
              </TD>
              <TD className={g.cnt}>
                {account.joined}
                <i>/20</i>
              </TD>
              <TD>
                <AccountStatusLabel status={account.status} />
              </TD>
            </TR>
          )
          return account.note
            ? [
                row,
                <TR key={`${account.no}-note`}>
                  <TD colSpan={6} truncate={false} className={g.noteCell}>
                    {account.note}
                  </TD>
                </TR>,
              ]
            : [row]
        })}
      </TBody>
      <TFoot>
        <TR>
          <TD colSpan={3}>모두 합쳐</TD>
          <TD />
          <TD colSpan={2} className={g.sum}>
            {total}
            <i> / 140곳</i>
          </TD>
        </TR>
      </TFoot>
    </Table>
  )
}

/* ── 견본 한 장 ────────────────────────────────────── */

export default function DataGallery() {
  const [retrying, setRetrying] = useState(false)
  const photoKeys = useMemo(() => Object.keys(photos) as PhotoKey[], [])

  return (
    <div className={g.sheet}>
      <header className={g.mast}>
        <p className={g.mastTitle}>
          견본 <small>02 / 데이터 표시</small>
        </p>
        <p className={g.mastMeta}>표 · 수치 · 램프 · 무늬 · 차트 · 사진</p>
      </header>

      <div className={g.intro}>
        <h1 className={g.introTitle}>
          찾는 말이 나오면,
          <br />
          불이 켜져요.
        </h1>
        <p className={g.introLede}>
          이 장에는 받아 적은 것을 <b>보여 주는</b> 부품이 모여 있어요. 먹 한 가지와 괘선으로 짜고,
          빨강은 불이 켜진 자리에만 써요. 상태는 언제나 모양과 글자를 함께 적어요.
        </p>
      </div>

      <Specimen no="01" title="화면 머리와 꼭지 머리" names="PageHeader · SectionHead">
        <div className={g.grid}>
          <Case label="화면 머리" code="PageHeader" span="span12">
            <PageHeader
              title="수집함"
              count={
                <>
                  전체 <b>4,812</b>명
                </>
              }
              summary={
                <>
                  <StatusLamp kind="lit" />
                  <span>
                    오늘 <b>128명</b>이 새로 들어왔어요. 마지막으로 받아 적은 건 3분 전이에요.
                  </span>
                </>
              }
              aside={
                <>
                  <Button variant="outline">CSV로 내보내기</Button>
                  <Button variant="solid">규칙 만들기</Button>
                </>
              }
            />
          </Case>
          <Case label="주요 꼭지: 2px 굵은 괘선, 명조 18px" code="level 1" span="span6">
            <SectionHead
              title="최근 7일 수집 추이"
              note="11월 9일 – 15일 · 하루에 수집한 사람 수"
            />
          </Case>
          <Case label="주요 꼭지에 램프와 동작" code="level 1" span="span6">
            <SectionHead
              title="실시간 감지"
              note={
                <>
                  <StatusLamp kind="lit" live />
                  <b>받는 중</b> · 최근 8건
                </>
              }
              action={
                <Button variant="quiet" size="sm">
                  수집함에서 모두 보기
                </Button>
              }
            />
          </Case>
          <Case label="딸린 꼭지: 1px 괘선, 명조 16px" code="level 2" span="span6">
            <SectionHead level={2} title="이 규칙으로 찾은 사람" note="최근 30일" />
          </Case>
          <Case label="딸린 꼭지, 설명 없이" code="level 2" span="span6">
            <SectionHead level={2} title="걸러 낼 말" />
          </Case>
        </div>
      </Specimen>

      <Specimen no="02" title="수치" names="StatHero · Ledger · StatRow · Figure">
        <div className={g.lead}>
          <StatHero
            className={g.leadHero}
            height={300}
            label="오늘 수집"
            value={128}
            unit="명"
            deck={
              <>
                어제는 105명이었어요.{' '}
                <span>오늘은 키워드로 89명, 활발한 유저로 39명을 찾았어요.</span>
              </>
            }
          />
          <Ledger className={g.leadLedger} label="지금 상태">
            <StatRow
              label="누적 수집"
              note="처음부터 지금까지 받아 적은 사람"
              value={4812}
              unit="명"
            />
            <StatRow
              label="연결된 계정"
              note={
                <>
                  <StatusLamp kind="problem" />
                  건우 계정은 다시 로그인해야 해요
                </>
              }
              value={9}
              of={10}
            />
            <StatRow
              label="감시 중인 그룹"
              note="아직 13곳을 더 넣을 수 있어요"
              value={187}
              of={200}
            />
            <StatRow
              label="승인 대기 중인 입장 요청"
              note="승인되면 바로 듣기 시작해요"
              value={6}
              unit="건"
            />
          </Ledger>
          <Figure className={g.leadPlate} photo={photos.positions} height={300} priority />
        </div>
        <div className={g.heroRow}>
          <div className={g.heroCell}>
            <StatHero height={280} label="네 자리가 되면 칸에 맞게 줄어요" value={1284} unit="명" />
          </div>
          <div className={g.heroCell}>
            <StatHero height={280} label="아직 한 명도 없을 때" value={0} unit="명" />
          </div>
          <div className={g.heroCell}>
            <StatHero height={280} label="아직 모르는 값" value={null} unit="명" />
          </div>
        </div>
      </Specimen>

      <Specimen no="03" title="추이 차트" names="TrendChart">
        <div className={g.grid}>
          <Case label="7일" span="span6" className={g.wide}>
            <TrendChart data={WEEK} today={TODAY} title="최근 7일 수집 추이" />
          </Case>
          <Case label="14일: 날짜를 하루 걸러 적어요" span="span6" className={g.wide}>
            <TrendChart data={FORTNIGHT} today={TODAY} title="최근 14일 수집 추이" />
          </Case>
          <Case label="30일: 점은 끝과 꼭대기에만 찍어요" span="span8" className={g.wide}>
            <TrendChart data={MONTH} today={TODAY} title="최근 30일 수집 추이" />
          </Case>
          <Case label="좁은 칸" span="span4">
            <TrendChart
              data={WEEK}
              today={TODAY}
              title="최근 7일 수집 추이, 좁은 칸"
              footnote={false}
            />
          </Case>
          <Case label="받아 적은 사람이 없던 기간" span="span4">
            <TrendChart data={QUIET} today={TODAY} title="받아 적은 사람이 없던 7일" />
          </Case>
          <Case label="아직 데이터가 없을 때" span="span4">
            <TrendChart data={[]} today={TODAY} title="비어 있는 추이" />
          </Case>
          <Case label="다시 불러오는 중: 이전 그림을 흐리게 둬요" span="span4">
            <TrendChart
              data={WEEK}
              today={TODAY}
              title="다시 불러오는 추이"
              pending
              footnote={false}
            />
          </Case>
        </div>
      </Specimen>

      <Specimen no="04" title="순위와 비중" names="RankList · SegmentedBar">
        <div className={g.grid}>
          <Case label="순위" span="span3">
            <RankList items={RANK} />
          </Case>
          <Case label="순위: 밑 괘선으로 비율" code="proportion" span="span3">
            <RankList items={RANK} proportion />
          </Case>
          <Case label="규칙별 누적" span="span3">
            <SegmentedBar items={SHARE} />
            <p className={g.caseNote}>조각이나 범례를 가리키면 나머지가 물러나요.</p>
          </Case>
          <Case label="규칙이 열 개일 때" span="span3">
            <SegmentedBar items={SHARE_MANY} />
          </Case>
          <Case label="순위가 비었을 때" span="span3">
            <RankList items={[]} />
          </Case>
          <Case label="비중이 비었을 때" span="span3">
            <SegmentedBar items={SHARE.map((item) => ({ ...item, value: 0 }))} />
          </Case>
        </div>
      </Specimen>

      <Specimen no="05" title="램프" names="StatusLamp · StatusLabel">
        <div className={g.grid}>
          <Case label="램프 낱말" span="span6">
            <ul className={g.vocab}>
              {LAMP_VOCAB.map(({ kind, means }) => (
                <li key={kind}>
                  <StatusLamp kind={kind} />
                  <code>{kind}</code>
                  <span>{means}</span>
                </li>
              ))}
            </ul>
          </Case>
          <Case label="수집한 유저" code="LeadStatusLabel" span="span3">
            <ul className={g.enumList}>
              {(Object.keys(LEAD_STATUS) as LeadStatus[]).map((status) => (
                <li key={status}>
                  <LeadStatusLabel status={status} />
                  <code className={g.code}>{status}</code>
                </li>
              ))}
            </ul>
            <p className={g.caseLabel} style={{ marginTop: 28 }}>
              그룹 <i>GroupStatusLabel</i>
            </p>
            <ul className={g.enumList}>
              {(Object.keys(GROUP_STATUS) as GroupStatus[]).map((status) => (
                <li key={status}>
                  <GroupStatusLabel status={status} />
                  <code className={g.code}>{status}</code>
                </li>
              ))}
            </ul>
          </Case>
          <Case label="계정" code="AccountStatusLabel" span="span3">
            <ul className={g.enumList}>
              {(Object.keys(ACCOUNT_STATUS) as AccountStatus[]).map((status) => (
                <li key={status}>
                  <AccountStatusLabel status={status} />
                  <code className={g.code}>{status}</code>
                </li>
              ))}
            </ul>
            <p className={g.caseLabel} style={{ marginTop: 28 }}>
              지금 받는 중 <i>live</i>
            </p>
            <p className={g.live}>
              <StatusLamp kind="lit" live />
              <b>받는 중</b> · 오후 2:14에 마지막으로 받아 적었어요
            </p>
            <p className={g.caseLabel} style={{ marginTop: 28 }}>
              먹색 면 위 <i>onInk</i>
            </p>
            <div className={g.inkPanel}>
              <span>
                <StatusLamp kind="lit" onInk /> 새로 3명
              </span>
              <span>
                <StatusLamp kind="done" onInk /> 연락함
              </span>
              <span>
                <StatusLamp kind="off" onInk /> 확인함
              </span>
            </div>
          </Case>
          <Case label="문구를 바꿔 쓸 때" span="span6">
            <div className={g.swatchRow}>
              <AccountStatusLabel status="flood_wait">14분 뒤 다시 시작</AccountStatusLabel>
              <GroupStatusLabel status="failed">링크가 만료됨</GroupStatusLabel>
              <StatusLabel kind="lit" live>
                지금 받는 중
              </StatusLabel>
              <StatusLabel kind="ok">9개 연결됨</StatusLabel>
            </div>
          </Case>
        </div>
      </Specimen>

      <Specimen no="06" title="규칙의 무늬" names="RuleSwatch · RuleSwatchFill · RuleName">
        <div className={g.grid}>
          <Case label="여덟 가지 무늬: 12px 표식과 28px 막대" span="span8" className={g.wide}>
            <ul className={g.swatches}>
              {PATTERN_NAMES.map((name, index) => (
                <li key={name}>
                  <RuleSwatch index={index} />
                  <span>
                    {index + 1}. {name}
                  </span>
                  <i>
                    <RuleSwatchFill index={index} />
                  </i>
                </li>
              ))}
            </ul>
          </Case>
          <Case label="아홉 번째부터는 번호 상자" span="span4">
            <div className={g.swatchRow}>
              {[8, 9, 10, 11, 23, 99].map((index) => (
                <RuleSwatch key={index} index={index} />
              ))}
              <RuleSwatch index={-1} label="지워진 규칙" />
            </div>
            <div className={g.swatchBig} style={{ marginTop: 16, height: 28 }}>
              <RuleSwatchFill index={8} style={{ width: 96 }} />
              <RuleSwatchFill index={11} style={{ width: 48 }} />
              <RuleSwatchFill index={12} style={{ width: 16 }} />
            </div>
            <p className={g.caseNote}>
              좁은 조각에는 번호를 찍지 않아요. 마지막 표식은 목록에 없는 규칙이에요.
            </p>
          </Case>
          <Case
            label="무늬 + 이름: 실시간 감지와 표에서"
            code="RuleName"
            span="span8"
            className={g.wide}
          >
            <div className={g.swatchRow}>
              {RULES.map((rule) => (
                <RuleName key={rule.id} index={swatchOf(rule.id)}>
                  {rule.name}
                </RuleName>
              ))}
              <RuleName index={9}>도메인·호스팅</RuleName>
              <RuleName index={1} muted>
                업체 찾는 사람 (제외된 행)
              </RuleName>
            </div>
          </Case>
          <Case label="크기를 달리해도" span="span4">
            <div className={g.swatchRow}>
              {[10, 12, 16, 24].map((size) => (
                <span key={size} className={g.swatchRow} style={{ gap: 6 }}>
                  {[1, 3, 4, 6, 7].map((index) => (
                    <RuleSwatch key={index} index={index} size={size} />
                  ))}
                </span>
              ))}
            </div>
          </Case>
        </div>
      </Specimen>

      <Specimen no="07" title="걸린 말" names="KeywordText">
        <div className={g.grid}>
          <Case label="인용문: 굵게 + 방점" code="quote" span="span7" className={g.wide}>
            <ol className={g.feed}>
              {LEADS.slice(0, 4).map((lead, index) => {
                const rule = ruleOf(lead.rule)
                return (
                  <li key={lead.handle} className={index === 0 ? g.feedNew : undefined}>
                    <time className={g.feedTime}>{FEED_TIMES[index]}</time>
                    <p className={g.feedWho}>
                      <span className={g.feedHandle}>{lead.handle}</span>
                      <span className={g.feedRoom}>{lead.room}</span>
                    </p>
                    <span className={g.feedRule}>
                      <RuleName index={swatchOf(rule.id)}>{rule.name}</RuleName>
                    </span>
                    {lead.said ? (
                      <p className={g.feedSaid}>
                        <KeywordText text={lead.said} keywords={rule.keywords} quoted />
                      </p>
                    ) : (
                      <p className={g.feedActivity}>
                        최근 24시간 동안 메시지 <b>{lead.messages}개</b>
                      </p>
                    )}
                  </li>
                )
              })}
            </ol>
          </Case>
          <Case label="줄이 바뀌어도 낱말은 끊기지 않아요" code="quote" span="span5">
            <div className={g.narrow}>
              <KeywordText
                text="안녕하세요, 이번에 스마트스토어 상세페이지 외주 견적을 여러 군데서 받아 보려고 하는데 업체추천 부탁드려도 될까요"
                keywords={['견적', '외주', '업체 추천']}
                quoted
              />
            </div>
            <p className={g.caseLabel} style={{ marginTop: 28 }}>
              두 줄까지만 <i>maxLines=2</i>
            </p>
            <div className={clsx(g.narrow, g.clampBox)}>
              <KeywordText
                text="안녕하세요, 이번에 스마트스토어 상세페이지 외주 견적을 여러 군데서 받아 보려고 하는데 업체추천 부탁드려도 될까요"
                keywords={['견적', '외주', '업체 추천']}
                quoted
                maxLines={2}
              />
            </div>
          </Case>
          <Case label="표 안: 굵게 + 방점 + 옅은 밑칠" code="table" span="span7" className={g.wide}>
            <div className={g.stack} style={{ gap: 10 }}>
              <KeywordText
                variant="table"
                text="배대지 업체 추천 좀 부탁드려요. 지금 쓰는 곳이 너무 느려서요"
                keywords={['업체 추천']}
                quoted
              />
              <KeywordText
                variant="table"
                text="CSV 견적서 양식 있으신 분? ＣＳＶ로 받고 싶어요"
                keywords={['csv', '견적']}
                quoted
              />
              <KeywordText
                variant="table"
                text="통관 대행 업체 추천 부탁드립니다"
                keywords={['업체 추천']}
                quoted
                muted
              />
            </div>
          </Case>
          <Case
            label="한 줄로 줄일 때: 가려진 글자는 방점도 사라져요"
            code="maxLines=1"
            span="span5"
          >
            <div className={g.stack} style={{ gap: 6 }}>
              {[340, 250, 188, 120].map((width) => (
                <div key={width} style={{ width }}>
                  <KeywordText
                    variant="table"
                    text="메타 광고 대행 맡기려는데 수수료 보통 몇 프로예요?"
                    keywords={['광고 대행', '수수료']}
                    quoted
                    maxLines={1}
                  />
                </div>
              ))}
            </div>
          </Case>
        </div>
      </Specimen>

      <Specimen no="08" title="횟수와 자리" names="Tally · SlotDots">
        <div className={g.grid}>
          <Case label="감지 횟수: 다섯 번에 正 한 글자, 15회를 넘으면 숫자만" span="span4">
            <ul className={g.tallies}>
              {[1, 2, 3, 4, 5, 6, 9, 10, 13, 15, 16, 1280].map((count) => (
                <li key={count}>
                  <Tally count={count} />
                </li>
              ))}
            </ul>
          </Case>
          <Case label="계정의 그룹 자리: 점 하나가 그룹 한 곳" span="span8" className={g.wide}>
            <ul className={g.slots}>
              <li className={g.slotsHead}>
                <span>계정의 상태</span>
                <SlotDotsScale />
                <span />
                <span>뜻</span>
              </li>
              <li>
                <span>정상, 가득 참</span>
                <SlotDots joined={20} />
                <span className={g.cnt}>
                  20<i>/20</i>
                </span>
                <span>찬 점은 들어가 있는 그룹</span>
              </li>
              <li>
                <span>정상, 기다리는 곳 있음</span>
                <SlotDots joined={13} pending={4} />
                <span className={g.cnt}>
                  13<i>/20</i>
                </span>
                <span>반쪽 점은 승인이나 차례를 기다리는 곳, 테는 빈 자리</span>
              </li>
              <li>
                <span>잠시 대기</span>
                <SlotDots joined={18} pending={1} tone="wait" />
                <span className={g.cnt}>
                  18<i>/20</i>
                </span>
                <span>황토: 텔레그램이 잠시 막은 계정</span>
              </li>
              <li>
                <span>다시 로그인 필요</span>
                <SlotDots joined={13} tone="problem" />
                <span className={g.cnt}>
                  13<i>/20</i>
                </span>
                <span>먹색 테만 남아요. 지금은 듣지 못하는 자리</span>
              </li>
              <li>
                <span>자리가 서른 개일 때</span>
                <SlotDots joined={24} pending={2} capacity={30} />
                <span className={g.cnt}>
                  24<i>/30</i>
                </span>
                <span>열 개씩 묶고, 스무 개마다 줄을 바꿔요</span>
              </li>
              <li>
                <span>자리가 여덟 개일 때</span>
                <SlotDots joined={5} capacity={8} />
                <span className={g.cnt}>
                  5<i>/8</i>
                </span>
                <span />
              </li>
            </ul>
          </Case>
        </div>
      </Specimen>

      <Specimen no="09" title="표" names="Table · SelectionBand · Pagination">
        <div style={{ paddingTop: 20 }}>
          <LeadsSpecimen />
        </div>
        <div className={g.grid} style={{ paddingTop: 56 }}>
          <Case
            label="판면에 맞춘 표: 딸린 설명 행과 합계"
            code="edge=flush"
            span="span6"
            className={g.wide}
          >
            <AccountsSpecimen />
          </Case>
          <Case label="쪽 넘기기의 여러 경우" code="Pagination" span="span6" className={g.wide}>
            <div className={g.stack} style={{ gap: 0 }}>
              <Pagination
                page={1}
                pageSize={50}
                total={4812}
                onPageChange={() => undefined}
                sortLabel="마지막 감지가 가까운 순서"
              />
              <Pagination
                page={37}
                pageSize={100}
                total={4812}
                onPageChange={() => undefined}
                onPageSizeChange={() => undefined}
              />
              <Pagination
                page={97}
                pageSize={50}
                total={4812}
                onPageChange={() => undefined}
                onPageSizeChange={() => undefined}
              />
              <Pagination
                page={1}
                pageSize={50}
                total={12}
                onPageChange={() => undefined}
                unit="곳"
              />
              <Pagination
                page={2}
                pageSize={50}
                total={4812}
                onPageChange={() => undefined}
                onPageSizeChange={() => undefined}
                pending
              />
              <Pagination page={1} pageSize={50} total={0} onPageChange={() => undefined} />
            </div>
            <p className={g.caseLabel} style={{ marginTop: 28 }}>
              표를 불러오는 중 <i>SkeletonRows</i>
            </p>
            <SkeletonStatus label="수집함을 불러오는 중이에요">
              <SkeletonRows rows={4} density="compact" />
            </SkeletonStatus>
          </Case>
        </div>
      </Specimen>

      <Specimen no="10" title="사진" names="Figure · assets/photos">
        <div className={g.photos}>
          <div className={clsx(g.case, g.span5)}>
            <div className={g.loginPlate}>
              <Figure photo={photos.operator} ratio="933 / 900" caption="none" />
              <svg
                viewBox="0 0 933 900"
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
                aria-hidden="true"
              >
                <circle
                  cx={OPERATOR_LAMP.x * 933}
                  cy={OPERATOR_LAMP.y * 900}
                  r="22"
                  fill="none"
                  stroke="var(--lamp)"
                  strokeWidth="2.5"
                />
              </svg>
            </div>
            <p className={g.photoKey}>
              operator · 로그인 · 불 켜진 램프 하나만 덧칠 (OPERATOR_LAMP)
            </p>
          </div>
          <div className={clsx(g.case, g.span7)}>
            <div className={g.grid} style={{ paddingTop: 0, rowGap: 28 }}>
              {(['positions', 'takingNotes', 'sorting', 'cords'] as PhotoKey[]).map((key) => (
                <div key={key} className={clsx(g.case, g.span6)} style={{ gridColumn: 'span 6' }}>
                  <Figure photo={photos[key]} height={236} />
                  <p className={g.photoKey}>{key}</p>
                </div>
              ))}
            </div>
          </div>
          {(['row', 'clocks', 'cards'] as PhotoKey[]).map((key) => (
            <div key={key} className={clsx(g.case, g.span4)}>
              <Figure photo={photos[key]} ratio="3 / 2" />
              <p className={g.photoKey}>{key}</p>
            </div>
          ))}
          {(['lineman', 'shelves'] as PhotoKey[]).map((key) => (
            <div key={key} className={clsx(g.case, g.span3)}>
              <Figure photo={photos[key]} />
              <p className={g.photoKey}>{key}</p>
            </div>
          ))}
          <div className={clsx(g.case, g.span6)}>
            <p className={g.caseLabel}>
              캡션을 줄이거나 없앨 때 <i>caption</i>
            </p>
            <div className={g.grid} style={{ paddingTop: 0 }}>
              <div style={{ gridColumn: 'span 6' }}>
                <Figure photo={photos.lineman} height={150} caption="credit" />
              </div>
              <div style={{ gridColumn: 'span 6' }}>
                <Figure photo={photos.shelves} height={150} caption="none" />
              </div>
            </div>
            <p className={g.caseNote}>
              사진은 모두 {photoKeys.length}장이에요. 잘라서 보여 줄 때는 목록에 적어 둔
              자리(focus)를 지켜요.
            </p>
          </div>
        </div>
      </Specimen>

      <Specimen
        no="11"
        title="비었을 때, 불러올 때, 안 될 때"
        names="EmptyState · Skeleton · ErrorState"
      >
        <div className={g.grid}>
          <Case label="화면 한 장이 비었을 때" code="size=page" span="span12">
            <EmptyState
              size="page"
              photo={photos.takingNotes}
              title="아직 받아 적은 사람이 없어요"
              description="그룹에서 찾는 말이 나오면 그 사람의 @아이디가 여기에 한 줄씩 쌓여요. 먼저 무엇을 찾을지 정해 주세요."
              action={<Button variant="solid">수집 규칙 만들기</Button>}
            />
          </Case>
          <Case label="찾는 결과가 없을 때" code="size=page" span="span12">
            <EmptyState
              size="page"
              photo={photos.shelves}
              title="‘도매 견적’으로는 찾지 못했어요"
              description="@아이디, 이름, 문장 어디에도 없었어요. 띄어쓰기를 바꾸거나 기간을 넓혀 보세요."
              action={<Button variant="outline">조건 모두 지우기</Button>}
            />
          </Case>
          <Case
            label="꼭지 안: 사진이 어울리지 않으면 빈 양식"
            code="size=section"
            span="span6"
            className={g.wide}
          >
            <EmptyState
              title="아직 들어간 그룹이 없어요"
              description="초대 링크나 @공개주소를 붙여 넣으면 계정이 차례로 가입해요."
              action={
                <Button variant="outline" size="sm">
                  링크 붙여 넣기
                </Button>
              }
            />
          </Case>
          <Case label="꼭지 안: 작은 사진" code="size=section" span="span6" className={g.wide}>
            <EmptyState
              photo={photos.sorting}
              title="아직 만든 규칙이 없어요"
              description="찾을 말을 적어 두면 그 말이 나올 때마다 받아 적어요."
              action={
                <Button variant="outline" size="sm">
                  규칙 만들기
                </Button>
              }
            />
          </Case>
          <Case label="표·목록 안" code="size=inline" span="span4">
            <EmptyState
              size="inline"
              title="오늘은 아직 조용해요"
              description="새로 받아 적으면 맨 위에 나타나요."
            />
          </Case>
          <Case label="빈 양식 그림" code="BlankForm" span="span4">
            <BlankForm />
          </Case>
          <Case label="오류: 표·목록 안의 한 줄" code="size=inline" span="span4">
            <ErrorState
              size="inline"
              title="순위를 불러오지 못했어요"
              message="잠시 뒤에 다시 시도해 주세요."
              onRetry={() => undefined}
            />
          </Case>
          <Case label="오류: 꼭지 안" code="ErrorState" span="span6" className={g.wide}>
            <ErrorState
              title="수집함을 불러오지 못했어요"
              message="서버에 연결할 수 없어요. 잠시 뒤에 다시 시도해 주세요."
              retrying={retrying}
              onRetry={() => {
                setRetrying(true)
                window.setTimeout(() => setRetrying(false), 1400)
              }}
            />
          </Case>
          <Case
            label="불러오는 중: 가는 괘선과 조용한 면"
            code="Skeleton"
            span="span6"
            className={g.wide}
          >
            <SkeletonStatus>
              <div className={g.grid} style={{ paddingTop: 0, rowGap: 20 }}>
                <div style={{ gridColumn: 'span 5' }}>
                  <Skeleton width={72} height={12} />
                  <Skeleton width="78%" height={96} style={{ marginTop: 18 }} />
                  <div style={{ marginTop: 14 }}>
                    <SkeletonText lines={2} />
                  </div>
                </div>
                <div style={{ gridColumn: 'span 7' }}>
                  <SkeletonChart height={170} />
                </div>
                <div style={{ gridColumn: '1 / -1' }}>
                  <SkeletonRows rows={3} />
                </div>
              </div>
            </SkeletonStatus>
          </Case>
        </div>
      </Specimen>

      <Specimen no="12" title="설정 항목" names="DefinitionList">
        <div className={g.grid}>
          <Case label="이름 — 값과 설명 — 동작" span="span8" className={g.wide}>
            <DefinitionList>
              <DefinitionItem
                term="계정마다 넣을 그룹 수"
                value="20곳"
                help="텔레그램이 계정을 막지 않도록 스무 곳을 넘기지 않는 편이 좋아요."
                action={
                  <Button variant="outline" size="sm">
                    바꾸기
                  </Button>
                }
              />
              <DefinitionItem
                term="가입 사이 간격"
                value="90초"
                mono
                help="그룹 하나에 들어간 뒤 다음 그룹에 들어가기까지 쉬는 시간이에요."
                action={
                  <Button variant="outline" size="sm">
                    바꾸기
                  </Button>
                }
              />
              <DefinitionItem
                term="텔레그램 API 키"
                help="my.telegram.org 에서 받은 api_id 와 api_hash 를 넣어 주세요."
                action={
                  <Button variant="solid" size="sm">
                    넣기
                  </Button>
                }
              />
              <DefinitionItem
                term="시간대"
                value="Asia/Seoul"
                mono
                help="표와 차트의 날짜는 이 시간대로 나눠요."
              />
              <DefinitionItem term="버전" value="1.0.0" mono />
            </DefinitionList>
          </Case>
          <Case label="사진과 함께" span="span4">
            <Figure photo={photos.lineman} height={280} />
          </Case>
        </div>
      </Specimen>
    </div>
  )
}
