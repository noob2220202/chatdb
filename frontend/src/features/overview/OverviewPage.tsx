import { ArrowRight } from '@phosphor-icons/react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import { useJoinGroups, useOverview, useSettings, type FeedItem, type Overview } from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatCount, formatNumber, formatTime, formatUntil } from '@/lib/format'
import { subscribeLive, useLiveState } from '@/lib/live'
import { Button } from '@/ui/Button/Button'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { Figure } from '@/ui/Figure/Figure'
import { RankList } from '@/ui/RankList/RankList'
import { SectionHead } from '@/ui/SectionHead/SectionHead'
import { Segmented } from '@/ui/Segmented/Segmented'
import { SegmentedBar } from '@/ui/SegmentedBar/SegmentedBar'
import { SkeletonChart, SkeletonRows, SkeletonText } from '@/ui/Skeleton/Skeleton'
import { SlotDots, SlotDotsScale } from '@/ui/SlotDots/SlotDots'
import { Ledger, StatHero, StatRow } from '@/ui/Stat/Stat'
import { AccountStatusLabel, StatusLamp } from '@/ui/StatusLamp/StatusLamp'
import { Table, TBody, TD, TFoot, TH, THead, TR } from '@/ui/Table/Table'
import { TextField } from '@/ui/TextField/TextField'
import { useToast } from '@/ui/Toast/Toast'
import { TrendChart } from '@/ui/TrendChart/TrendChart'

import { HitText, RuleName, shared, useNow, useSwatchIndex, useUrlState } from '../shared/shared'
import styles from './OverviewPage.module.css'
import { attentionList, heroDeck, joinSummary, slotTone, splitLinks } from './overviewText'

const FEED_ROWS = 8
type Days = '7' | '14' | '30'

function JoinForm() {
  const toast = useToast()
  const join = useJoinGroups()
  const [text, setText] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const links = splitLinks(text)
    if (!links.length) return
    join.mutate(
      { links },
      {
        onSuccess: (result) => {
          const message = joinSummary(result.items)
          if (result.queued > 0) {
            toast.show(message)
            setText('')
          } else toast.problem(message)
        },
        onError: (error) => toast.problem(errorMessage(error)),
      },
    )
  }
  return (
    <form className={styles.join} onSubmit={submit}>
      <TextField
        label="그룹 넣기"
        labelAside={<Link to="/groups">여러 곳 한꺼번에 넣기</Link>}
        placeholder="t.me 링크나 @아이디를 붙여 넣으세요"
        hint="여유가 많은 계정부터 알아서 들어가요. 승인이 필요한 곳은 입장 요청을 보내요."
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <Button type="submit" variant="solid" loading={join.isPending} disabled={!text.trim()}>
        넣기
      </Button>
    </form>
  )
}

function Feed({ initial, swatches }: { initial: FeedItem[]; swatches: Map<number, number> }) {
  const [items, setItems] = useState(initial)
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
  useEffect(() => setItems(initial), [initial])
  useEffect(
    () =>
      subscribeLive('hit', (payload) => {
        const hit = payload as unknown as FeedItem
        setItems((previous) =>
          previous.some((item) => item.hit_id === hit.hit_id)
            ? previous
            : [hit, ...previous].slice(0, FEED_ROWS),
        )
        setFresh((previous) => new Set(previous).add(hit.hit_id))
        window.setTimeout(
          () =>
            setFresh((previous) => {
              const next = new Set(previous)
              next.delete(hit.hit_id)
              return next
            }),
          6000,
        )
      }),
    [],
  )
  if (!items.length)
    return (
      <p className={styles.calm}>아직 감지된 것이 없어요. 찾는 말이 나오면 여기에 불이 켜져요.</p>
    )
  return (
    <ol className={styles.feed}>
      {items.slice(0, FEED_ROWS).map((hit) => (
        <li key={hit.hit_id} className={fresh.has(hit.hit_id) ? styles.fresh : undefined}>
          <time dateTime={hit.created_at}>{formatTime(hit.created_at)}</time>
          <span className={styles.who}>
            {(fresh.has(hit.hit_id) || hit.is_new_lead) && (
              <StatusLamp
                kind={fresh.has(hit.hit_id) ? 'lit' : 'done'}
                size={6}
                label={hit.is_new_lead ? '처음 수집됨' : '방금'}
              />
            )}
            <Link className={shared.handle} to={`/leads?lead=${hit.lead_id}`}>
              @{hit.username}
            </Link>
            <span className={styles.where}>— {hit.group_title ?? '지워진 그룹'}</span>
          </span>
          <RuleName hit={hit} swatches={swatches} />
          <p className={hit.kind === 'activity' ? `${styles.said} ${styles.plain}` : styles.said}>
            <HitText hit={hit} variant="quote" maxLines={2} />
          </p>
        </li>
      ))}
    </ol>
  )
}

function Accounts({ overview, now }: { overview: Overview; now: Date }) {
  const joined = overview.accounts.reduce((sum, account) => sum + account.joined_count, 0)
  return (
    <>
      <Table
        density="compact"
        columns={[34, 72, null, 76, 150]}
        minWidth={520}
        aria-label="계정 상태"
      >
        <THead>
          <TR>
            <TH>번호</TH>
            <TH>계정</TH>
            <TH>
              <SlotDotsScale capacity={overview.accounts[0]?.max_groups ?? 20} />
            </TH>
            <TH align="end">그룹</TH>
            <TH>상태</TH>
          </TR>
        </THead>
        <TBody>
          {overview.accounts.map((account, index) => {
            const until = account.flood_until ? formatUntil(account.flood_until, now) : null
            const reason =
              account.status === 'flood_wait'
                ? `텔레그램이 요청을 잠시 막았어요.${until ? ` ${until}에 다시 시작해요.` : ''}`
                : account.status !== 'active' && account.status !== 'connecting'
                  ? account.status_detail
                  : null
            return (
              <TR key={account.id}>
                <TD mono dim>
                  {String(index + 1).padStart(2, '0')}
                </TD>
                <TD truncate>
                  <b>{account.display_name}</b>
                </TD>
                <TD>
                  <SlotDots
                    joined={account.joined_count}
                    pending={account.pending_count}
                    capacity={account.max_groups}
                    tone={slotTone(account)}
                  />
                  {reason && <span className={styles.reason}>{reason}</span>}
                </TD>
                <TD align="end" mono>
                  {account.joined_count}/{account.max_groups}
                </TD>
                <TD>
                  <AccountStatusLabel status={account.status} />
                </TD>
              </TR>
            )
          })}
        </TBody>
        <TFoot>
          <TR>
            <TD colSpan={3}>모두 합쳐</TD>
            <TD align="end" mono>
              {joined}/{overview.groups_capacity}
            </TD>
            <TD>
              <Link className={shared.link} to="/accounts">
                계정에서 보기
              </Link>
            </TD>
          </TR>
        </TFoot>
      </Table>
      <p className={shared.note}>
        ＊ 점 하나가 그룹 한 곳이에요. 반쯤 찬 점은 가입이나 승인을 기다리는 자리예요.
      </p>
    </>
  )
}

function StartGuide({ overview, apiReady }: { overview: Overview; apiReady: boolean }) {
  const steps = [
    {
      title: '텔레그램 API 키 넣기',
      note: 'my.telegram.org 에서 받은 api_id 와 api_hash 를 넣어요.',
      to: '/settings',
      done: apiReady,
    },
    {
      title: '계정 연결하기',
      note: '내 텔레그램 계정으로 로그인하거나 세션을 불러와요.',
      to: '/accounts',
      done: overview.accounts_total > 0,
    },
    {
      title: '그룹 넣기',
      note: '링크를 붙여 넣으면 계정이 차례로 들어가요.',
      to: '/groups',
      done: overview.groups_monitoring > 0,
    },
    {
      title: '수집 규칙 만들기',
      note: '어떤 말을 한 사람을 받아 적을지 정해요.',
      to: '/rules',
      done: overview.rule_totals.length > 0,
    },
  ]
  return (
    <div className={styles.start}>
      <div>
        <h1>
          아직 비어 있어요.
          <br />네 가지만 하면 듣기 시작해요.
        </h1>
        <ol className={styles.steps}>
          {steps.map((step, index) => (
            <li key={step.to} className={step.done ? styles.done : undefined}>
              <span className={styles.no}>{index + 1}</span>
              <span>
                <b>{step.title}</b>
                <span className={shared.note}>{step.note}</span>
              </span>
              {step.done ? (
                <span className={shared.note}>했어요</span>
              ) : (
                <Button asChild trailingIcon={<ArrowRight />}>
                  <Link to={step.to}>하러 가기</Link>
                </Button>
              )}
            </li>
          ))}
        </ol>
      </div>
      <Figure photo={photos[PHOTO_FOR.overview]} ratio="4 / 3" />
    </div>
  )
}

export default function OverviewPage() {
  const url = useUrlState()
  const days = (['14', '30'].includes(url.get('days')) ? url.get('days') : '7') as Days
  const overview = useOverview(Number(days))
  const base = useOverview()
  const settings = useSettings()
  const swatches = useSwatchIndex()
  const live = useLiveState()
  const now = useNow(15_000)
  const data = base.data
  const attention = useMemo(
    () => (data ? attentionList(data, settings.data, now) : []),
    [data, settings.data, now],
  )

  if (base.isError)
    return <ErrorState message={errorMessage(base.error)} onRetry={() => void base.refetch()} />
  if (!data) {
    return (
      <div className={shared.page}>
        <SkeletonText lines={6} />
        <SkeletonChart />
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (data.accounts_total === 0) {
    return (
      <StartGuide
        overview={data}
        apiReady={Boolean(
          settings.data && (settings.data.tg_api_source !== 'none' || settings.data.demo),
        )}
      />
    )
  }

  const needAttention = data.accounts.filter((account) =>
    ['reauth_required', 'banned', 'error'].includes(account.status),
  )
  const free =
    data.groups_capacity -
    data.accounts.reduce((sum, account) => sum + account.joined_count + account.pending_count, 0)

  return (
    <div className={shared.page}>
      <section className={styles.hero}>
        <StatHero
          className={styles.heroFigure}
          label="오늘 수집"
          value={data.today_new}
          unit="명"
          height={250}
          deck={heroDeck(data)}
        />
        <Ledger className={styles.heroLedger} label="지금 상태">
          <StatRow
            label="누적 수집"
            note="처음부터 지금까지 받아 적은 사람"
            value={data.total_leads}
            unit="명"
          />
          <StatRow
            label="연결된 계정"
            value={data.accounts_connected}
            of={data.accounts_total}
            note={
              needAttention.length ? (
                <Link className={shared.link} to="/accounts">
                  {needAttention.map((account) => account.display_name).join(', ')} 계정을 확인해
                  주세요
                </Link>
              ) : (
                '모두 잘 연결돼 있어요'
              )
            }
          />
          <StatRow
            label="감시 중인 그룹"
            value={data.groups_monitoring}
            of={data.groups_capacity}
            note={
              free > 0 ? `아직 ${formatNumber(free)}곳을 더 넣을 수 있어요` : '자리가 모두 찼어요'
            }
          />
          <StatRow
            label="승인 기다리는 입장 요청"
            value={data.join_requests_pending}
            unit="건"
            note={
              <Link className={shared.link} to="/groups?status=requested">
                그룹에서 보기
              </Link>
            }
          />
        </Ledger>
        <div className={styles.heroSide}>
          <Figure photo={photos[PHOTO_FOR.overview]} height={150} caption="credit" />
          <JoinForm />
        </div>
      </section>

      <div className={styles.row}>
        <section className={styles.c7}>
          <SectionHead
            title="실시간 감지"
            note={
              <span className={styles.feedHead}>
                <StatusLamp
                  kind={live === 'open' ? 'lit' : 'off'}
                  live={live === 'open'}
                  size={7}
                />
                {live === 'open' ? '받는 중' : '다시 연결하는 중'}
              </span>
            }
            action={
              <Link className={shared.link} to="/leads">
                수집함에서 모두 보기
              </Link>
            }
          />
          <Feed initial={data.recent_hits} swatches={swatches} />
        </section>
        <div className={styles.c5}>
          <section>
            <SectionHead
              title="살펴볼 일"
              note={attention.length ? `${attention.length}건` : undefined}
            />
            {attention.length ? (
              <ul className={styles.attention}>
                {attention.map((item) => (
                  <li key={item.key}>
                    <StatusLamp kind={item.kind} />
                    <span>{item.text}</span>
                    <Link className={shared.link} to={item.to}>
                      {item.action}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.calm}>지금은 살펴볼 일이 없어요.</p>
            )}
          </section>
          <section style={{ marginTop: 'var(--s-8)' }}>
            <SectionHead
              title="계정 상태"
              note={`${data.accounts_total}개 가운데 ${data.accounts_connected}개 연결됨`}
            />
            <Accounts overview={data} now={now} />
          </section>
        </div>
      </div>

      <div className={styles.row}>
        <section className={styles.c6}>
          <SectionHead title={`최근 ${days}일 수집 추이`} note="하루에 새로 받아 적은 사람 수" />
          <div className={styles.chartHead}>
            <Segmented<Days>
              aria-label="기간"
              size="sm"
              value={days}
              onValueChange={(value) => url.set({ days: value === '7' ? null : value })}
              options={[
                { value: '7', label: '7일' },
                { value: '14', label: '14일' },
                { value: '30', label: '30일' },
              ]}
            />
          </div>
          <TrendChart data={(overview.data ?? data).series} pending={overview.isPlaceholderData} />
        </section>
        <section className={styles.c3}>
          <SectionHead level={2} title="수집이 많은 그룹" note="누적" />
          <RankList
            items={data.top_groups.map((group) => ({
              id: group.group_id,
              value: group.leads,
              label: <Link to={`/leads?group_id=${group.group_id}`}>{group.title}</Link>,
            }))}
          />
        </section>
        <section className={styles.c3}>
          <SectionHead
            level={2}
            title="규칙별 누적"
            note={`전체 ${formatCount(data.total_leads, '명')}`}
          />
          <SegmentedBar
            label="규칙별 누적"
            items={data.rule_totals.map((rule) => ({
              id: rule.rule_id,
              label: rule.name,
              value: rule.leads,
              swatch: swatches.get(rule.rule_id) ?? -1,
            }))}
          />
        </section>
      </div>
    </div>
  )
}
