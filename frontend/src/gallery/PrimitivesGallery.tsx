/**
 * 기본 부품 견본. 개발 중에만 /__gallery/primitives 로 열린다.
 * 활자 견본처럼 한 장에 로고·색·글자·부품의 모든 상태를 늘어놓는다.
 *
 * "올려놓음 / 누름 / 포커스" 칸은 forcePseudoStates 로 상태를 붙잡아 둔 것이고,
 * 떠 있는 면(메뉴·대화상자·알림 띠)은 같은 스타일로 멈춰 둔 모습과 직접 열어 보는 버튼을 함께 둔다.
 */
import {
  ArrowRightIcon,
  CaretDownIcon,
  CheckIcon,
  CopyIcon,
  DownloadSimpleIcon,
  PlusIcon,
  ProhibitIcon,
  SlidersHorizontalIcon,
  TrashIcon,
  XIcon,
} from '@phosphor-icons/react'
import { useEffect, useState, type ReactNode } from 'react'

import { formatFullDate } from '@/lib/format'
import { Button, LoadingDots } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import confirmStyles from '@/ui/ConfirmDialog/ConfirmDialog.module.css'
import { Dialog, DialogClose } from '@/ui/Dialog/Dialog'
import dialogStyles from '@/ui/Dialog/Dialog.module.css'
import { Drawer } from '@/ui/Drawer/Drawer'
import { Field } from '@/ui/Field/Field'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { IconButton } from '@/ui/IconButton/IconButton'
import { Kbd } from '@/ui/Kbd/Kbd'
import { Logo } from '@/ui/Logo/Logo'
import {
  Menu,
  MenuCheckItem,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
} from '@/ui/Menu/Menu'
import menuStyles from '@/ui/Menu/Menu.module.css'
import { NumberField } from '@/ui/NumberField/NumberField'
import { Popover, PopoverClose } from '@/ui/Popover/Popover'
import popoverStyles from '@/ui/Popover/Popover.module.css'
import { SearchField } from '@/ui/SearchField/SearchField'
import { Segmented } from '@/ui/Segmented/Segmented'
import { Select } from '@/ui/Select/Select'
import selectStyles from '@/ui/Select/Select.module.css'
import { Stepper } from '@/ui/Stepper/Stepper'
import { Switch } from '@/ui/Switch/Switch'
import { TabPanel, Tabs } from '@/ui/Tabs/Tabs'
import { TextArea } from '@/ui/TextArea/TextArea'
import { TextField } from '@/ui/TextField/TextField'
import toastStyles from '@/ui/Toast/Toast.module.css'
import { useToast } from '@/ui/Toast/useToast'
import { Tooltip } from '@/ui/Tooltip/Tooltip'
import tooltipStyles from '@/ui/Tooltip/Tooltip.module.css'

import { forcePseudoStates } from './forcePseudoStates'
import g from './PrimitivesGallery.module.css'

// ── 견본의 뼈대 ────────────────────────────────────────────────

function Section({
  no,
  title,
  note,
  secondary = false,
  children,
}: {
  no: string
  title: string
  note: ReactNode
  secondary?: boolean
  children: ReactNode
}) {
  return (
    <section
      className={g.section}
      data-secondary={secondary || undefined}
      aria-labelledby={`sec-${no}`}
    >
      <div className={g.sectionHead}>
        <span className={g.sectionNo}>{no}</span>
        <h2 id={`sec-${no}`} className={g.sectionTitle}>
          {title}
        </h2>
        <p className={g.sectionNote}>{note}</p>
      </div>
      <div className={g.sectionBody}>{children}</div>
    </section>
  )
}

function Spec({
  label,
  hint,
  children,
  wide = false,
}: {
  label: string
  hint?: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <div className={g.spec} data-wide={wide || undefined}>
      <div className={g.specLabel}>
        <span>{label}</span>
        {hint && <small>{hint}</small>}
      </div>
      <div className={g.specBody}>{children}</div>
    </div>
  )
}

/** 상태 하나: 위에 견본, 아래에 상태 이름 */
function State({ name, children }: { name: string; children: ReactNode }) {
  return (
    <figure className={g.state}>
      <div className={g.stateBody}>{children}</div>
      <figcaption>{name}</figcaption>
    </figure>
  )
}

// ── 색 ─────────────────────────────────────────────────────────

const PALETTE: {
  group: string
  items: { token: string; hex: string; role: string; dark?: boolean; lined?: boolean }[]
}[] = [
  {
    group: '종이',
    items: [
      { token: '--paper', hex: '#F0EEE8', role: '바탕', lined: true },
      { token: '--paper-2', hex: '#E6E3DA', role: '선택된 행, 눌린 면', lined: true },
      { token: '--paper-3', hex: '#DAD6CB', role: '더 깊은 면', lined: true },
      { token: '--paper-raised', hex: '#F7F6F2', role: '대화상자, 메뉴', lined: true },
    ],
  },
  {
    group: '먹',
    items: [
      { token: '--ink', hex: '#191816', role: '본문, 제목, 주요 버튼', dark: true },
      { token: '--ink-2', hex: '#45433D', role: '보조 글자', dark: true },
      { token: '--ink-3', hex: '#6A675F', role: '캡션, 표 머리글 · 4.8:1', dark: true },
      { token: '--ink-4', hex: '#A09C91', role: '장식 전용. 글자에는 쓰지 않음' },
    ],
  },
  {
    group: '괘선',
    items: [
      { token: '--rule', hex: '#D6D2C6', role: '가는 괘선' },
      { token: '--rule-2', hex: '#B9B4A6', role: '구분자, 못 쓰는 칸의 줄' },
    ],
  },
  {
    group: '램프 — 불이 켜진 것에만',
    items: [
      { token: '--lamp', hex: '#D62B1F', role: '새 유저의 점, 방점, 받는 중', dark: true },
      { token: '--lamp-ink', hex: '#B3221A', role: '종이 위 작은 글자 · 5.7:1', dark: true },
      { token: '--lamp-tint', hex: '#F3DCD6', role: '표 안 키워드의 밑칠' },
    ],
  },
  {
    group: '상태',
    items: [
      { token: '--ok', hex: '#2E6A4A', role: '정상 · 찬 점과 함께', dark: true },
      { token: '--wait', hex: '#86590A', role: '잠시 대기 · 반쪽 점과 함께', dark: true },
    ],
  },
]

// ── 글자 ───────────────────────────────────────────────────────

const TYPE_SCALE: {
  token: string
  meta: string
  family: 'serif' | 'sans' | 'mono'
  size: string
  weight: number
  sample: string
  tight?: boolean
}[] = [
  {
    token: '--head-xl',
    meta: '명조 800 · 52',
    family: 'serif',
    size: 'var(--head-xl)',
    weight: 800,
    sample: '찾는 말이 나오면, 불이 켜져요.',
    tight: true,
  },
  {
    token: '--head-lg',
    meta: '명조 700 · 34',
    family: 'serif',
    size: 'var(--head-lg)',
    weight: 700,
    sample: '수집함',
    tight: true,
  },
  {
    token: '--head-md',
    meta: '명조 700 · 24',
    family: 'serif',
    size: 'var(--head-md)',
    weight: 700,
    sample: '이 그룹에서 나갈까요?',
  },
  {
    token: '--head-sm',
    meta: '명조 700 · 18',
    family: 'serif',
    size: 'var(--head-sm)',
    weight: 700,
    sample: '최근 7일 수집 추이',
  },
  {
    token: '인용문',
    meta: '명조 400 · 16',
    family: 'serif',
    size: 'var(--text-lg)',
    weight: 400,
    sample: '“혹시 상세페이지 외주 맡겨보신 분 계세요? 견적이 어느 정도인지 궁금해요”',
  },
  {
    token: '--text-lg',
    meta: '고딕 500 · 16',
    family: 'sans',
    size: 'var(--text-lg)',
    weight: 500,
    sample: '텔레그램 그룹 이백 곳의 대화를 지켜봐요.',
  },
  {
    token: '--text-md',
    meta: '고딕 400 · 14',
    family: 'sans',
    size: 'var(--text-md)',
    weight: 400,
    sample: '오늘은 키워드로 89명, 활발한 유저로 39명을 찾았어요.',
  },
  {
    token: '--text-sm',
    meta: '고딕 600 · 13',
    family: 'sans',
    size: 'var(--text-sm)',
    weight: 600,
    sample: '링크 붙여 넣고 들어가기',
  },
  {
    token: '--text-xs',
    meta: '고딕 400 · 12.5',
    family: 'sans',
    size: 'var(--text-xs)',
    weight: 400,
    sample: '점 하나가 그룹 한 곳이에요. 계정마다 스무 곳까지 넣을 수 있어요.',
  },
  {
    token: '--text-2xs',
    meta: '고딕 600 · 11.5',
    family: 'sans',
    size: 'var(--text-2xs)',
    weight: 600,
    sample: '계정 · 번호 · 들어가 있는 그룹 · 상태',
  },
  {
    token: '모노',
    meta: '플렉스 모노 500 · 14',
    family: 'mono',
    size: 'var(--text-md)',
    weight: 500,
    sample: '@jiwoo_kim92   오후 2:14   +82 10-····-3421   4,812',
  },
]

const RULE_OPTIONS = [
  { value: 'all', label: '전체', note: '4,812' },
  { value: 'quote', label: '견적 문의', note: '1,904' },
  { value: 'vendor', label: '업체 찾는 사람', note: '1,216' },
  { value: 'active', label: '활발한 유저', note: '1,004' },
  { value: 'ads', label: '광고 대행', note: '688', disabled: true },
]

const STATUS_TABS = [
  { value: 'all', label: '전체', count: 4812 },
  { value: 'new', label: '새로 수집됨', count: 128 },
  { value: 'seen', label: '확인함', count: 3920 },
  { value: 'done', label: '연락함', count: 702 },
  { value: 'out', label: '제외', count: 62, disabled: true },
] as const

export default function PrimitivesGallery() {
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [rule, setRule] = useState('quote')
  const [limit, setLimit] = useState<number | null>(20)
  const [checks, setChecks] = useState({ a: true, b: false })
  const [lever, setLever] = useState(true)
  const [density, setDensity] = useState<'roomy' | 'compact'>('roomy')
  const [tab, setTab] = useState<(typeof STATUS_TABS)[number]['value']>('new')
  const [panel, setPanel] = useState('keyword')
  const [sort, setSort] = useState('recent')
  const [showName, setShowName] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [links, setLinks] = useState('https://t.me/smartstore_sellers\nhttps://t.me/+AbCdEfGh1234')

  useEffect(() => {
    document.title = '기본 부품 견본 — ChatDB'
    // 글꼴·스타일이 다 실린 뒤에 상태 견본을 붙잡아 둔다.
    forcePseudoStates()
    const timer = window.setTimeout(forcePseudoStates, 300)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className={g.sheet}>
      <header className={g.mast}>
        <Logo lit height={28} />
        <p className={g.mastTitle}>기본 부품 견본</p>
        <p className={g.mastMeta}>
          <b>디렉션 “인쇄물”</b>
          {formatFullDate(new Date())}
        </p>
      </header>
      <p className={g.deck}>
        신문지 위에 먹 한 가지, 램프 빨강 한 가지. 빨강은 <b>불이 켜진 것</b>에만 쓰고, 문제는
        뒤집힌 면과 ×로, 나머지는 모두 먹과 종이와 괘선으로 그려요.
      </p>

      {/* ── 01 로고 ─────────────────────────────────────────── */}
      <Section
        no="01"
        title="로고"
        note="교환대의 램프와 잭. 받는 중일 때만 램프가 켜져요. 글자는 본명조 Black 의 윤곽을 손본 것이고, 살아 있는 글꼴이 아니에요."
      >
        <div className={g.logoHero}>
          <Logo lit height={112} />
        </div>
        <div className={g.logoRow}>
          <State name="켜짐 · 48">
            <Logo lit height={48} />
          </State>
          <State name="꺼짐 · 48">
            <Logo height={48} />
          </State>
          <State name="머리띠 · 28">
            <Logo lit height={28} />
          </State>
          <State name="꺼짐 · 28">
            <Logo height={28} />
          </State>
          <State name="20">
            <Logo lit height={20} />
          </State>
        </div>
        <div className={g.logoRow}>
          <State name="심벌 · 48">
            <Logo lit variant="mark" height={48} />
          </State>
          <State name="꺼짐 · 48">
            <Logo variant="mark" height={48} />
          </State>
          <State name="32">
            <Logo lit variant="mark" height={32} />
          </State>
          <State name="16 켜짐">
            <Logo lit variant="mark" height={16} />
          </State>
          <State name="16 꺼짐">
            <Logo variant="mark" height={16} />
          </State>
          <State name="파비콘">
            <img src="/favicon.svg" width={32} height={32} alt="" />
            <img src="/favicon.svg" width={16} height={16} alt="" />
          </State>
          <div className={g.logoInk}>
            <Logo lit height={28} className={g.onInk} />
            <Logo height={28} className={g.onInk} />
          </div>
        </div>
      </Section>

      {/* ── 02 색 ───────────────────────────────────────────── */}
      <Section
        no="02"
        title="색"
        note="종이 넷, 먹 넷, 괘선 둘, 램프 셋, 상태 둘. 이 밖의 색은 없어요. 그림자·그라데이션·둥근 모서리도 쓰지 않아요."
      >
        {PALETTE.map((group) => (
          <Spec key={group.group} label={group.group} wide>
            <ul className={g.swatches}>
              {group.items.map((item) => (
                <li key={item.token} className={g.swatch}>
                  <i
                    className={g.chip}
                    style={{ background: `var(${item.token})` }}
                    data-lined={item.lined || undefined}
                  />
                  <span className={g.swatchToken}>{item.token}</span>
                  <span className={g.swatchHex}>{item.hex}</span>
                  <span className={g.swatchRole}>{item.role}</span>
                </li>
              ))}
            </ul>
          </Spec>
        ))}
      </Section>

      {/* ── 03 글자 ─────────────────────────────────────────── */}
      <Section
        no="03"
        title="글자"
        note="제목·큰 수치·인용문은 명조, 화면 글자는 고딕, @아이디·시각·표 안 숫자는 모노. 고딕 문장 안에 명조 숫자를 섞지 않아요."
      >
        <ul className={g.typeScale}>
          {TYPE_SCALE.map((row) => (
            <li key={row.token} className={g.typeRow}>
              <span className={g.typeMeta}>
                <b>{row.token}</b>
                {row.meta}
              </span>
              <span
                className={g.typeSample}
                style={{
                  fontFamily: `var(--${row.family})`,
                  fontSize: row.size,
                  fontWeight: row.weight,
                  letterSpacing:
                    row.family === 'serif'
                      ? row.tight
                        ? '-0.035em'
                        : 'var(--tracking-head)'
                      : undefined,
                  lineHeight: row.family === 'serif' ? 1.3 : 1.55,
                  whiteSpace: row.family === 'mono' ? 'pre' : undefined,
                }}
              >
                {row.sample}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {/* ── 04 버튼 ─────────────────────────────────────────── */}
      <Section
        no="04"
        title="버튼"
        note="면(주요 동작) · 테(기본) · 글자(조용한 동작). 올려놓으면 면이 뒤집히고, 처리 중에는 폭을 지킨 채 점 세 개가 차례로 켜져요. 지우는 일도 빨강이 아니라 먹이에요."
      >
        {(
          [
            ['solid', '면', '수집 시작'],
            ['outline', '테', 'CSV로 내보내기'],
            ['quiet', '글자', '수집함에서 모두 보기'],
          ] as const
        ).map(([variant, name, text]) => (
          <Spec key={variant} label={name} hint={`variant="${variant}"`}>
            <State name="기본">
              <Button variant={variant}>{text}</Button>
            </State>
            <State name="올려놓음">
              <Button variant={variant} data-force="hover">
                {text}
              </Button>
            </State>
            <State name="누름">
              <Button variant={variant} data-force="active">
                {text}
              </Button>
            </State>
            <State name="포커스">
              <Button variant={variant} data-force="focus-visible">
                {text}
              </Button>
            </State>
            <State name="처리 중">
              <Button variant={variant} loading>
                {text}
              </Button>
            </State>
            <State name="못 씀">
              <Button variant={variant} disabled>
                {text}
              </Button>
            </State>
          </Spec>
        ))}
        <Spec label="크기와 아이콘" hint="sm 28 · md 36 · lg 48">
          <State name="sm">
            <Button size="sm" leadingIcon={<PlusIcon size={13} />}>
              규칙 추가
            </Button>
          </State>
          <State name="md · 앞 아이콘">
            <Button leadingIcon={<DownloadSimpleIcon />}>CSV로 내보내기</Button>
          </State>
          <State name="md · 뒤 아이콘">
            <Button variant="solid" trailingIcon={<ArrowRightIcon />}>
              다음
            </Button>
          </State>
          <State name="글자 · 뒤 아이콘">
            <Button variant="quiet" trailingIcon={<ArrowRightIcon size={12} />}>
              그룹에서 보기
            </Button>
          </State>
          <State name="lg">
            <Button variant="solid" size="lg">
              그룹에 들어가기
            </Button>
          </State>
        </Spec>
        <Spec label="가로로 꽉" hint='size="lg" block'>
          <div className={g.blockDemo}>
            <Button variant="solid" size="lg" block trailingIcon={<ArrowRightIcon size={20} />}>
              로그인
            </Button>
          </div>
          <div className={g.blockDemo}>
            <Button
              variant="solid"
              size="lg"
              block
              loading
              trailingIcon={<ArrowRightIcon size={20} />}
            >
              로그인
            </Button>
          </div>
        </Spec>
        <Spec label="아이콘 버튼" hint="이름표(aria-label)는 꼭">
          <State name="기본">
            <IconButton label="@아이디 복사">
              <CopyIcon />
            </IconButton>
          </State>
          <State name="올려놓음">
            <IconButton label="@아이디 복사" data-force="hover" hideTooltip>
              <CopyIcon />
            </IconButton>
          </State>
          <State name="누름">
            <IconButton label="@아이디 복사" data-force="active" hideTooltip>
              <CopyIcon />
            </IconButton>
          </State>
          <State name="포커스">
            <IconButton label="@아이디 복사" data-force="focus-visible" hideTooltip>
              <CopyIcon />
            </IconButton>
          </State>
          <State name="못 씀">
            <IconButton label="@아이디 복사" disabled>
              <CopyIcon />
            </IconButton>
          </State>
          <State name="테">
            <IconButton label="조건 더 보기" variant="outline">
              <SlidersHorizontalIcon />
            </IconButton>
          </State>
          <State name="sm">
            <IconButton label="닫기" size="sm">
              <XIcon />
            </IconButton>
          </State>
          <State name="이름표">
            <span
              className={tooltipStyles.tooltip}
              style={{ position: 'static', animation: 'none' }}
            >
              @아이디 복사
            </span>
          </State>
          <div className={g.inkStrip}>
            <IconButton label="제외" onInk hideTooltip>
              <ProhibitIcon />
            </IconButton>
            <IconButton label="제외" onInk hideTooltip data-force="hover">
              <ProhibitIcon />
            </IconButton>
            <Button variant="outline" size="sm" onInk>
              선택 해제
            </Button>
            <Button variant="quiet" size="sm" onInk>
              되돌리기
            </Button>
          </div>
        </Spec>
      </Section>

      {/* ── 05 입력 칸 ──────────────────────────────────────── */}
      <Section
        no="05"
        title="입력 칸"
        note="밑줄 하나로 그려요. 쉬고 있을 때는 먹색 1px, 쓰는 동안은 줄이 왼쪽에서 굵게 그어져요. 오류는 빨강이 아니라 ×와 먹색 글로 알려요."
      >
        <Spec label="한 줄" hint="TextField">
          <div className={g.fieldGrid}>
            <TextField
              label="그룹 이름"
              placeholder="스마트스토어 셀러 모임"
              hint="수집함과 개요에 이 이름으로 나와요."
            />
            <div data-force-within="focus-within">
              <TextField label="쓰는 중" defaultValue="해외구매대행 정보방" hint="줄이 굵어져요." />
            </div>
            <TextField
              label="전화번호"
              mono
              defaultValue="+82 10 2345 678"
              error="번호가 한 자리 모자라요. 나라 번호까지 넣어 주세요."
            />
            <TextField
              label="못 쓰는 칸"
              defaultValue="텔레그램이 정한 이름"
              disabled
              hint="텔레그램에서만 바꿀 수 있어요."
            />
            <TextField
              label="@아이디"
              mono
              leading="@"
              placeholder="jiwoo_kim92"
              labelAside="골뱅이 없이"
            />
            <TextField
              label="비밀번호"
              type="password"
              mono
              revealable
              defaultValue="correct horse"
              labelAside="8자 이상"
            />
          </div>
        </Spec>
        <Spec label="큰 칸" hint='size="lg" — 로그인'>
          <div className={g.fieldWide}>
            <TextField
              label="비밀번호"
              labelAside="관리자 한 명만 들어올 수 있어요"
              type="password"
              size="lg"
              mono
              revealable
              placeholder="비밀번호를 입력해 주세요"
            />
          </div>
          <div className={g.fieldWide}>
            <TextField
              label="비밀번호"
              type="password"
              size="lg"
              mono
              revealable
              defaultValue="wrongpass"
              error="비밀번호가 맞지 않아요."
            />
          </div>
        </Spec>
        <Spec label="여러 줄" hint="TextArea">
          <div className={g.fieldWide}>
            <TextArea
              label="그룹 링크"
              labelAside="한 줄에 하나씩"
              mono
              value={links}
              onChange={(event) => setLinks(event.target.value)}
              hint="공개 링크와 초대 링크를 섞어 넣어도 돼요."
            />
          </div>
          <div className={g.fieldWide}>
            <TextArea
              label="찾는 말"
              labelAside="쉼표나 줄바꿈으로 나눠요"
              defaultValue="견적, 외주, 상세페이지"
              error="‘견적’은 이미 ‘견적 문의’ 규칙에 있어요."
              rows={3}
            />
          </div>
        </Spec>
        <Spec label="찾기" hint="SearchField — “/” 로 바로">
          <div className={g.fieldWide}>
            <SearchField
              value={query}
              onValueChange={setQuery}
              placeholder="@아이디, 이름, 문장으로 찾기"
            />
          </div>
          <div className={g.fieldWide}>
            <SearchField
              value="견적"
              onValueChange={() => {}}
              shortcut={false}
              placeholder="@아이디, 이름, 문장으로 찾기"
              aria-label="찾기(값이 있을 때)"
            />
          </div>
        </Spec>
        <Spec label="숫자" hint="NumberField — ↑↓ 로 바꿈">
          <NumberField
            label="계정마다 들어갈 그룹"
            value={limit}
            onValueChange={setLimit}
            min={1}
            max={20}
            unit="곳"
            hint="1곳에서 20곳까지."
          />
          <NumberField
            label="활발한 유저의 기준"
            value={30}
            onValueChange={() => {}}
            unit="개"
            error="24시간에 1개 이상이어야 해요."
          />
          <NumberField
            label="못 쓰는 칸"
            value={24}
            onValueChange={() => {}}
            unit="시간"
            disabled
          />
        </Spec>
        <Spec label="자리 잡기" hint="Field — 직접 만든 입력에">
          <div className={g.fieldWide}>
            <Field
              label="수집을 쉬는 시간"
              labelAside="하루에 한 번"
              hint="이 시간에는 받아 적지 않아요."
            >
              {(ids) => (
                <div
                  className={g.customControl}
                  id={ids.id}
                  aria-describedby={ids.describedBy}
                  role="group"
                >
                  <span className="mono">오전 2:00</span>
                  <span aria-hidden="true">—</span>
                  <span className="mono">오전 6:00</span>
                </div>
              )}
            </Field>
          </div>
        </Spec>
      </Section>

      {/* ── 06 고르기 ───────────────────────────────────────── */}
      <Section
        no="06"
        title="고르기"
        note="네모난 체크 칸, 두 자리 레버, 붙어 있는 칸, 밑줄 탭. 켜진 것은 먹색 면, 꺼진 것은 빈 테. 상태는 모양과 글자를 함께 써요."
      >
        <Spec label="체크 칸" hint="Checkbox">
          <State name="빔">
            <Checkbox checked={false} onCheckedChange={() => {}} aria-label="빈 체크 칸" />
          </State>
          <State name="올려놓음">
            <Checkbox
              checked={false}
              onCheckedChange={() => {}}
              aria-label="올려놓은 체크 칸"
              data-force="hover"
            />
          </State>
          <State name="고름">
            <Checkbox checked onCheckedChange={() => {}} aria-label="고른 체크 칸" />
          </State>
          <State name="일부만">
            <Checkbox
              checked="indeterminate"
              onCheckedChange={() => {}}
              aria-label="일부만 고른 체크 칸"
            />
          </State>
          <State name="포커스">
            <Checkbox
              checked
              onCheckedChange={() => {}}
              aria-label="포커스 받은 체크 칸"
              data-force="focus-visible"
            />
          </State>
          <State name="못 씀">
            <Checkbox
              checked={false}
              onCheckedChange={() => {}}
              disabled
              aria-label="못 쓰는 체크 칸"
            />
            <Checkbox
              checked
              onCheckedChange={() => {}}
              disabled
              aria-label="못 쓰는 고른 체크 칸"
            />
          </State>
          <div className={g.inkStrip}>
            <Checkbox
              checked="indeterminate"
              onCheckedChange={() => {}}
              onInk
              aria-label="선택 띠의 체크 칸"
            />
            <span>3명 선택됨</span>
          </div>
        </Spec>
        <Spec label="이름이 붙은 체크 칸">
          <Checkbox
            checked={checks.a}
            onCheckedChange={(a) => setChecks((current) => ({ ...current, a }))}
            label="대소문자를 가리지 않기"
            hint="‘Naver’와 ‘naver’를 같은 말로 봐요."
          />
          <Checkbox
            checked={checks.b}
            onCheckedChange={(b) => setChecks((current) => ({ ...current, b }))}
            label="봇이 쓴 글은 넘기기"
          />
          <Checkbox
            checked={false}
            onCheckedChange={() => {}}
            label="관리자가 쓴 글도 받기"
            disabled
          />
        </Spec>
        <Spec label="레버" hint="Switch">
          <State name="꺼짐">
            <Switch checked={false} onCheckedChange={() => {}} aria-label="꺼진 레버" />
          </State>
          <State name="켜짐">
            <Switch checked onCheckedChange={() => {}} aria-label="켜진 레버" />
          </State>
          <State name="올려놓음">
            <Switch
              checked
              onCheckedChange={() => {}}
              aria-label="올려놓은 레버"
              data-force="hover"
            />
          </State>
          <State name="포커스">
            <Switch
              checked={false}
              onCheckedChange={() => {}}
              aria-label="포커스 받은 레버"
              data-force="focus-visible"
            />
          </State>
          <State name="못 씀">
            <Switch
              checked={false}
              onCheckedChange={() => {}}
              disabled
              aria-label="못 쓰는 꺼진 레버"
            />
            <Switch checked onCheckedChange={() => {}} disabled aria-label="못 쓰는 켜진 레버" />
          </State>
          <div className={g.leverDemo}>
            <Switch
              checked={lever}
              onCheckedChange={setLever}
              label="이 규칙으로 받아 적기"
              hint="끄면 지금까지 받아 적은 유저는 그대로 남아요."
              stateLabels={['켜짐', '꺼짐']}
            />
          </div>
        </Spec>
        <Spec label="붙은 칸" hint="Segmented">
          <State name="고르기">
            <Segmented
              aria-label="표의 줄 간격"
              value={density}
              onValueChange={setDensity}
              options={[
                { value: 'roomy', label: '넉넉하게' },
                { value: 'compact', label: '촘촘하게' },
              ]}
            />
          </State>
          <State name="셋 · sm">
            <Segmented
              aria-label="기간"
              size="sm"
              value="7"
              onValueChange={() => {}}
              options={[
                { value: '1', label: '오늘' },
                { value: '7', label: '7일' },
                { value: '30', label: '30일' },
              ]}
            />
          </State>
          <State name="못 씀">
            <Segmented
              aria-label="못 쓰는 묶음"
              value="keyword"
              onValueChange={() => {}}
              disabled
              options={[
                { value: 'keyword', label: '키워드' },
                { value: 'activity', label: '활동량' },
              ]}
            />
          </State>
        </Spec>
        <Spec label="탭" hint="Tabs — 이름 뒤에 모노 개수" wide>
          <Tabs aria-label="수집 상태" value={tab} onValueChange={setTab} items={STATUS_TABS} />
          <Tabs
            aria-label="규칙의 종류"
            value={panel}
            onValueChange={setPanel}
            items={[
              { value: 'keyword', label: '키워드 규칙' },
              { value: 'activity', label: '활동량 규칙' },
            ]}
            className={g.tabsWithPanel}
          >
            <TabPanel value="keyword" className={g.tabPanel}>
              찾는 말이 대화에 나오면 그 사람의 @아이디를 받아 적어요.
            </TabPanel>
            <TabPanel value="activity" className={g.tabPanel}>
              정한 시간 안에 말을 많이 한 사람의 @아이디를 받아 적어요.
            </TabPanel>
          </Tabs>
        </Spec>
        <Spec label="하나 고르기" hint="Select">
          <div className={g.fieldNarrow}>
            <Select
              label="규칙"
              value={rule}
              onValueChange={setRule}
              options={RULE_OPTIONS}
              hint="수집함을 이 규칙으로 걸러요."
            />
          </div>
          <div className={g.fieldNarrow}>
            <Select
              label="비어 있을 때"
              value={undefined}
              onValueChange={() => {}}
              options={RULE_OPTIONS}
              placeholder="규칙 고르기"
            />
          </div>
          <div className={g.fieldNarrow}>
            <Select
              label="못 쓰는 칸"
              value="all"
              onValueChange={() => {}}
              options={RULE_OPTIONS}
              disabled
            />
          </div>
          <div className={g.filterBar}>
            <Select
              variant="bare"
              prefix="규칙"
              value={rule}
              onValueChange={setRule}
              options={RULE_OPTIONS}
              aria-label="규칙"
            />
            <Select
              variant="bare"
              prefix="기간"
              value="all"
              onValueChange={() => {}}
              options={[
                { value: 'all', label: '전체 기간' },
                { value: '7', label: '최근 7일' },
              ]}
              aria-label="기간"
            />
          </div>
        </Spec>
      </Section>

      {/* ── 07 떠 있는 면 ───────────────────────────────────── */}
      <Section
        no="07"
        title="떠 있는 면"
        note="메뉴·목록·작은 창은 조금 밝은 종이 면에 먹색 테를 둘러요. 항목 사이는 가는 괘선, 가리킨 항목은 먹으로 뒤집혀요. 그림자와 둥근 모서리는 없어요."
      >
        <Spec label="메뉴" hint="Menu — 멈춰 둔 모습">
          <div className={g.frozen}>
            <div className={menuStyles.content}>
              <div className={menuStyles.item}>
                <span className={menuStyles.icon}>
                  <CopyIcon />
                </span>
                <span className={menuStyles.text}>@아이디 복사</span>
                <span className={menuStyles.shortcut}>C</span>
              </div>
              <div className={menuStyles.item} data-highlighted="">
                <span className={menuStyles.icon}>
                  <DownloadSimpleIcon />
                </span>
                <span className={menuStyles.text}>CSV로 내보내기</span>
                <span className={menuStyles.note}>3명</span>
              </div>
              <div className={menuStyles.item} data-disabled="">
                <span className={menuStyles.icon}>
                  <CheckIcon />
                </span>
                <span className={menuStyles.text}>연락함으로 바꾸기</span>
              </div>
              <div className={menuStyles.separator} />
              <div className={menuStyles.item}>
                <span className={menuStyles.icon}>
                  <ProhibitIcon />
                </span>
                <span className={menuStyles.text}>수집에서 제외</span>
              </div>
            </div>
          </div>
          <div className={g.frozen}>
            <div className={menuStyles.content}>
              <div className={menuStyles.label}>정렬</div>
              <div className={`${menuStyles.item} ${menuStyles.checkable}`} data-state="checked">
                <span className={menuStyles.check}>
                  <CheckIcon size={12} />
                </span>
                <span className={menuStyles.text}>마지막 감지가 가까운 순서</span>
              </div>
              <div className={`${menuStyles.item} ${menuStyles.checkable}`}>
                <span className={menuStyles.text}>감지 횟수가 많은 순서</span>
              </div>
              <div className={menuStyles.separator} />
              <div className={`${menuStyles.item} ${menuStyles.checkable}`} data-state="checked">
                <span className={menuStyles.check}>
                  <CheckIcon size={12} />
                </span>
                <span className={menuStyles.text}>이름도 함께 보기</span>
              </div>
            </div>
          </div>
          <div className={g.live}>
            <Menu
              trigger={
                <Button trailingIcon={<CaretDownIcon size={11} />} leadingIcon={<CheckIcon />}>
                  상태 변경
                </Button>
              }
            >
              <MenuItem
                icon={<CopyIcon />}
                shortcut="C"
                onSelect={() => toast.show('3명의 @아이디를 복사했어요')}
              >
                @아이디 복사
              </MenuItem>
              <MenuItem icon={<DownloadSimpleIcon />} note="3명">
                CSV로 내보내기
              </MenuItem>
              <MenuItem icon={<CheckIcon />} disabled>
                연락함으로 바꾸기
              </MenuItem>
              <MenuSeparator />
              <MenuLabel>정렬</MenuLabel>
              <MenuRadioGroup value={sort} onValueChange={setSort}>
                <MenuRadioItem value="recent">마지막 감지가 가까운 순서</MenuRadioItem>
                <MenuRadioItem value="count">감지 횟수가 많은 순서</MenuRadioItem>
              </MenuRadioGroup>
              <MenuSeparator />
              <MenuCheckItem checked={showName} onCheckedChange={setShowName}>
                이름도 함께 보기
              </MenuCheckItem>
            </Menu>
            <small>눌러서 열어 보기</small>
          </div>
        </Spec>
        <Spec label="고르는 목록" hint="Select 의 펼친 모습">
          <div className={g.frozen}>
            <div className={selectStyles.content} style={{ minWidth: 220 }}>
              <div className={selectStyles.item}>
                전체<span className={selectStyles.note}>4,812</span>
              </div>
              <div className={selectStyles.item} data-state="checked">
                <span className={selectStyles.check}>
                  <CheckIcon size={12} />
                </span>
                견적 문의<span className={selectStyles.note}>1,904</span>
              </div>
              <div className={selectStyles.item} data-highlighted="">
                업체 찾는 사람<span className={selectStyles.note}>1,216</span>
              </div>
              <div className={selectStyles.item}>
                활발한 유저<span className={selectStyles.note}>1,004</span>
              </div>
              <div className={selectStyles.item} data-disabled="">
                광고 대행<span className={selectStyles.note}>688</span>
              </div>
            </div>
          </div>
        </Spec>
        <Spec label="작은 창" hint="Popover">
          <div className={g.frozen}>
            <div className={popoverStyles.content} style={{ width: 280 }}>
              <p className={popoverStyles.title}>감지 횟수로 거르기</p>
              <NumberField
                label="이 횟수 이상만"
                value={2}
                onValueChange={() => {}}
                min={1}
                unit="회"
              />
              <div className={g.popoverFoot}>
                <Button size="sm" variant="quiet">
                  지우기
                </Button>
                <Button size="sm" variant="solid">
                  적용
                </Button>
              </div>
            </div>
          </div>
          <div className={g.live}>
            <Popover
              trigger={<Button leadingIcon={<SlidersHorizontalIcon />}>조건 더 보기</Button>}
              title="감지 횟수로 거르기"
            >
              <p className={g.popoverText}>
                두 번 이상 감지된 사람만 보면 관심이 뚜렷한 사람을 먼저 볼 수 있어요.
              </p>
              <div className={g.popoverFoot}>
                <PopoverClose asChild>
                  <Button size="sm" variant="solid">
                    알겠어요
                  </Button>
                </PopoverClose>
              </div>
            </Popover>
            <small>눌러서 열어 보기</small>
          </div>
        </Spec>
        <Spec label="이름표" hint="Tooltip">
          <span className={tooltipStyles.tooltip} style={{ position: 'static', animation: 'none' }}>
            CSV로 내보내기
          </span>
          <span className={tooltipStyles.tooltip} style={{ position: 'static', animation: 'none' }}>
            찾기<span className={tooltipStyles.shortcut}>/</span>
          </span>
          <div className={g.live}>
            <Tooltip label="CSV로 내보내기" side="top">
              <Button leadingIcon={<DownloadSimpleIcon />}>올려놓아 보기</Button>
            </Tooltip>
          </div>
        </Spec>
      </Section>

      {/* ── 08 대화상자 ─────────────────────────────────────── */}
      <Section
        no="08"
        title="대화상자"
        note="떠 있는 종이 한 장. 위에 2px 먹색 줄, 명조 제목, 동작은 오른쪽 아래. 확인을 구할 때는 결과를 한 문장으로 적고, 버튼은 빨강이 아니라 먹색 면이에요."
      >
        <Spec label="대화상자" hint="Dialog — 멈춰 둔 모습" wide>
          <div className={g.frozenSheets}>
            <div className={g.frozenSheet}>
              <div className={`${dialogStyles.sheet} ${dialogStyles.sm}`}>
                <header className={dialogStyles.head}>
                  <div className={dialogStyles.heading}>
                    <h3 className={dialogStyles.title}>그룹에 들어가기</h3>
                    <p className={dialogStyles.description}>
                      링크를 붙여 넣으면 자리가 남은 계정이 차례로 들어가요.
                    </p>
                  </div>
                  <IconButton label="닫기" size="sm" className={dialogStyles.close} hideTooltip>
                    <XIcon />
                  </IconButton>
                </header>
                <div className={dialogStyles.body}>
                  <TextArea
                    label="그룹 링크"
                    labelAside="한 줄에 하나씩"
                    mono
                    rows={3}
                    defaultValue={'https://t.me/smartstore_sellers'}
                  />
                </div>
                <footer className={dialogStyles.foot}>
                  <Button>취소</Button>
                  <Button variant="solid">1곳에 들어가기</Button>
                </footer>
              </div>
            </div>
            <div className={g.frozenSheet}>
              <div className={confirmStyles.sheet}>
                <h3 className={confirmStyles.title}>이 그룹에서 나갈까요?</h3>
                <p className={confirmStyles.consequence}>
                  ‘쇼핑몰 창업 스터디’의 대화를 더는 받아 적지 않아요. 지금까지 수집한 431명은
                  그대로 남아요.
                </p>
                <div className={confirmStyles.foot}>
                  <Button>취소</Button>
                  <Button variant="solid">나가기</Button>
                </div>
              </div>
            </div>
          </div>
        </Spec>
        <Spec label="직접 열어 보기">
          <Button onClick={() => setDialogOpen(true)}>대화상자</Button>
          <Button onClick={() => setConfirmOpen(true)} leadingIcon={<TrashIcon />}>
            확인 구하기
          </Button>
          <Button onClick={() => setDrawerOpen(true)}>오른쪽 서랍</Button>
        </Spec>
      </Section>

      {/* ── 09 알림 띠 ──────────────────────────────────────── */}
      <Section
        no="09"
        title="알림 띠"
        note="화면 아래 가장자리에 먹색 띠가 올라와요. 보통 알림은 4초, 문제 알림은 × 표식과 함께 8초 머물러요."
      >
        <Spec label="알림 띠" hint="Toast — 멈춰 둔 모습" wide>
          <div className={g.frozenBand}>
            <div className={toastStyles.band}>
              <div className={toastStyles.message}>3명의 @아이디를 복사했어요</div>
              <button type="button" className={toastStyles.close} aria-label="알림 닫기">
                <XIcon size={14} />
              </button>
            </div>
            <div className={toastStyles.band}>
              <div className={toastStyles.message}>@ocean_import 를 수집에서 제외했어요</div>
              <button type="button" className={toastStyles.action}>
                되돌리기
              </button>
              <button type="button" className={toastStyles.close} aria-label="알림 닫기">
                <XIcon size={14} />
              </button>
            </div>
            <div className={`${toastStyles.band} ${toastStyles.problem}`}>
              <ProblemMark onInk className={toastStyles.mark} />
              <div className={toastStyles.message}>
                내보내지 못했어요. 잠시 뒤에 다시 시도해 주세요.
              </div>
              <button type="button" className={toastStyles.action} data-force="hover">
                다시 시도
              </button>
              <button type="button" className={toastStyles.close} aria-label="알림 닫기">
                <XIcon size={14} />
              </button>
            </div>
          </div>
        </Spec>
        <Spec label="직접 띄워 보기">
          <Button onClick={() => toast.show('3명의 @아이디를 복사했어요')}>보통 알림</Button>
          <Button
            onClick={() =>
              toast.show('@ocean_import 를 수집에서 제외했어요', {
                action: { label: '되돌리기', onClick: () => toast.show('다시 수집함에 넣었어요') },
              })
            }
          >
            되돌릴 수 있는 알림
          </Button>
          <Button onClick={() => toast.problem('내보내지 못했어요. 잠시 뒤에 다시 시도해 주세요.')}>
            문제 알림
          </Button>
        </Spec>
      </Section>

      {/* ── 10 그 밖의 것 ───────────────────────────────────── */}
      <Section no="10" title="작은 부품" note="키캡, 단계 표시, 문제 표식, 처리 중 표시." secondary>
        <Spec label="키캡" hint="Kbd">
          <span className={g.inline}>
            <Kbd>/</Kbd> 찾기
          </span>
          <span className={g.inline}>
            <Kbd>Esc</Kbd> 닫기
          </span>
          <span className={g.inline}>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> 행 옮기기
          </span>
          <span className={g.inline}>
            <Kbd>Shift</Kbd>
            <Kbd>X</Kbd> 여기까지 고르기
          </span>
        </Spec>
        <Spec label="단계" hint="Stepper" wide>
          <Stepper
            steps={['전화번호', '인증 코드', '2단계 비밀번호', '마침']}
            current={1}
            aria-label="계정 추가 단계"
          />
        </Spec>
        <Spec label="문제 표식" hint="빨강 대신 뒤집힌 면과 ×">
          <span className={g.inline}>
            <ProblemMark /> <b>다시 로그인 필요</b>
          </span>
          <div className={g.inkStrip}>
            <ProblemMark onInk /> <span>들어가지 못했어요</span>
          </div>
        </Spec>
        <Spec label="처리 중" hint="LoadingDots">
          <LoadingDots />
          <div className={g.inkStrip}>
            <LoadingDots />
          </div>
        </Spec>
      </Section>

      <footer className={g.colophon}>
        <span>ChatDB 기본 부품 견본 · 개발 중에만 열리는 화면이에요</span>
        <span className="mono">/__gallery/primitives</span>
      </footer>

      {/* ── 직접 열어 보는 것들 ─────────────────────────────── */}
      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="그룹에 들어가기"
        description="링크를 붙여 넣으면 자리가 남은 계정이 차례로 들어가요."
        footer={
          <>
            <DialogClose asChild>
              <Button>취소</Button>
            </DialogClose>
            <Button
              variant="solid"
              onClick={() => {
                setDialogOpen(false)
                toast.show('2곳에 들어가기 시작했어요')
              }}
            >
              2곳에 들어가기
            </Button>
          </>
        }
      >
        <TextArea
          label="그룹 링크"
          labelAside="한 줄에 하나씩"
          mono
          value={links}
          onChange={(event) => setLinks(event.target.value)}
          hint="공개 링크와 초대 링크를 섞어 넣어도 돼요."
        />
      </Dialog>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="이 그룹에서 나갈까요?"
        consequence="‘쇼핑몰 창업 스터디’의 대화를 더는 받아 적지 않아요. 지금까지 수집한 431명은 그대로 남아요."
        confirmLabel="나가기"
        onConfirm={() =>
          new Promise((resolve) => window.setTimeout(resolve, 900)).then(() =>
            toast.show('그룹에서 나갔어요'),
          )
        }
      />

      <Drawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        eyebrow="수집된 유저"
        title={<span className="mono">@jiwoo_kim92</span>}
        description="김지우 · 스마트스토어 셀러 모임에서 4번 감지됐어요."
        footer={
          <>
            <Button leadingIcon={<ProhibitIcon />}>제외</Button>
            <Button variant="solid" leadingIcon={<CopyIcon />}>
              @아이디 복사
            </Button>
          </>
        }
      >
        <p className={g.quote}>
          “혹시 상세페이지 외주 맡겨보신 분 계세요? 견적이 어느 정도인지 궁금해요”
        </p>
        <p className={g.quoteMeta}>
          <span className="mono">오후 2:14</span> · 견적 문의
        </p>
      </Drawer>
    </div>
  )
}
