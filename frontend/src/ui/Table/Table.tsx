import { ArrowDown, ArrowUp, ArrowsDownUp, X } from '@phosphor-icons/react'
import clsx from 'clsx'
import {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from 'react'

import { formatNumber } from '@/lib/format'

import styles from './Table.module.css'

/* ── 표 ───────────────────────────────────────────── */

export type ColumnWidth = number | string | null

export interface TableProps extends Omit<HTMLAttributes<HTMLTableElement>, 'children'> {
  children: ReactNode
  /** 행 높이: roomy(넉넉하게, --row) / compact(촘촘하게, --row-compact) */
  density?: 'roomy' | 'compact'
  /**
   * 열 폭. 화면(페이지)이 정해서 넘긴다. 숫자는 px, 문자열은 그대로, null 은 남는 폭.
   * 예: [41, 192, 122, null, 208, 86, 100, 116]
   */
  columns?: readonly ColumnWidth[]
  /** 머리 행이 달라붙는 위치. 숫자는 px. 예: 0, 'var(--masthead-h)' */
  stickyTop?: number | string
  /** 선택 띠(SelectionBand). 머리 행 위에 같은 높이로 겹쳐 놓여서 표가 밀리지 않는다 */
  band?: ReactNode
  /**
   * 행의 양 끝.
   *   flush 첫 칸과 끝 칸의 글자가 판면의 선에 맞는다 (기본)
   *   inset 양 끝을 13px 들인다 (선택·호버로 행에 면이 깔리는 표)
   */
  edge?: 'flush' | 'inset'
  /** 이 폭(px)보다 좁아지면 표 안에서 가로로 스크롤한다 (이때는 머리 행이 달라붙지 않는다) */
  minWidth?: number
  /** 다시 불러오는 중: 이전 내용을 흐리게 둔다 (자리 표시로 바꾸지 않는다) */
  pending?: boolean
  /** 표 바깥 상자의 className */
  frameClassName?: string
}

/** 차분하고 촘촘한 표. 열 폭은 columns 로, 높이는 density 로 정한다. */
export function Table({
  children,
  density = 'roomy',
  columns,
  stickyTop = 0,
  band,
  edge = 'flush',
  minWidth,
  pending = false,
  className,
  frameClassName,
  style,
  ...rest
}: TableProps) {
  const frameRef = useRef<HTMLDivElement>(null)
  const [narrow, setNarrow] = useState(false)

  useEffect(() => {
    const frame = frameRef.current
    if (!frame || minWidth === undefined || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setNarrow(entry.contentRect.width < minWidth)
    })
    observer.observe(frame)
    return () => observer.disconnect()
  }, [minWidth])

  const scrolling = minWidth !== undefined && narrow
  const frameStyle = {
    '--table-top': typeof stickyTop === 'number' ? `${stickyTop}px` : stickyTop,
  } as CSSProperties

  return (
    <div
      ref={frameRef}
      className={clsx(styles.frame, scrolling && styles.scroll, frameClassName)}
      style={frameStyle}
    >
      <div className={styles.inner} style={scrolling ? { minWidth } : undefined}>
        {band ? <div className={styles.bandSlot}>{band}</div> : null}
        <table
          className={clsx(
            styles.table,
            styles[density],
            styles[edge],
            pending && styles.pending,
            className,
          )}
          style={style}
          aria-busy={pending || undefined}
          {...rest}
        >
          {columns && (
            <colgroup>
              {columns.map((width, index) => (
                <col
                  key={index}
                  style={
                    width === null
                      ? undefined
                      : { width: typeof width === 'number' ? `${width}px` : width }
                  }
                />
              ))}
            </colgroup>
          )}
          {children}
        </table>
      </div>
    </div>
  )
}

/** 머리 행 묶음. 위에 달라붙고, 아래에 1px 먹색 괘선이 있다. */
export function THead({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={clsx(styles.thead, className)} {...rest} />
}

export function TBody({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={clsx(styles.tbody, className)} {...rest} />
}

/** 합계 행 묶음. 위는 1px, 아래는 2px 괘선. */
export function TFoot({ className, ...rest }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tfoot className={clsx(styles.tfoot, className)} {...rest} />
}

export interface TRProps extends HTMLAttributes<HTMLTableRowElement> {
  /** 선택된 행: --paper-2 면 + 왼쪽 끝 3px 먹색 막대. boolean 을 주면 aria-selected 도 붙는다 */
  selected?: boolean
  /** 제외된 행: 글자를 흐리게 하고, strike 칸에는 줄을 긋는다 */
  muted?: boolean
  /** 키보드로 옮겨 다닐 때의 포커스 표시를 강제로 켠다 (보통은 :focus-visible 로 충분하다) */
  focused?: boolean
  /** 행 전체가 눌리는 표 (호버 면, 손 모양 커서) */
  interactive?: boolean
  /** 아래 괘선을 없앤다 (바로 아래에 딸린 설명 행이 올 때) */
  joined?: boolean
}

export const TR = forwardRef<HTMLTableRowElement, TRProps>(function TR(
  {
    selected,
    muted = false,
    focused = false,
    interactive = false,
    joined = false,
    className,
    ...rest
  },
  ref,
) {
  return (
    <tr
      ref={ref}
      className={clsx(
        styles.tr,
        selected && styles.selected,
        muted && styles.muted,
        focused && styles.focused,
        interactive && styles.interactive,
        joined && styles.joined,
        className,
      )}
      aria-selected={selected === undefined ? undefined : selected}
      {...rest}
    />
  )
})

export type SortDirection = 'asc' | 'desc' | 'none'

export interface THProps extends Omit<ThHTMLAttributes<HTMLTableCellElement>, 'align'> {
  align?: 'start' | 'end'
  /**
   * 정렬할 수 있는 열이면 지금 방향을 준다. 'none' 은 "정렬할 수 있지만 지금은 이 열 기준이 아님".
   * 주지 않으면 정렬 버튼이 없다.
   */
  sort?: SortDirection
  /** 정렬 버튼을 눌렀을 때 */
  onSort?: () => void
}

/** 머리 칸. sort 를 주면 방향 화살표가 달린 버튼이 되고 aria-sort 가 붙는다. */
export function TH({
  align = 'start',
  sort,
  onSort,
  className,
  children,
  scope = 'col',
  ...rest
}: THProps) {
  const sortable = sort !== undefined
  const ariaSort =
    sort === 'asc' ? 'ascending' : sort === 'desc' ? 'descending' : sortable ? 'none' : undefined
  const Arrow = sort === 'asc' ? ArrowUp : sort === 'desc' ? ArrowDown : ArrowsDownUp
  return (
    <th
      scope={scope}
      className={clsx(
        styles.th,
        align === 'end' && styles.end,
        sortable && sort !== 'none' && styles.sorted,
        className,
      )}
      aria-sort={ariaSort}
      {...rest}
    >
      {sortable ? (
        <button type="button" className={styles.sort} onClick={onSort}>
          <span>{children}</span>
          <Arrow
            className={clsx(styles.sortIcon, sort === 'none' && styles.sortIdle)}
            size={11}
            aria-hidden
          />
          <span className="sr">
            {sort === 'asc'
              ? ', 오름차순으로 정렬됨'
              : sort === 'desc'
                ? ', 내림차순으로 정렬됨'
                : ', 눌러서 정렬'}
          </span>
        </button>
      ) : (
        children
      )}
    </th>
  )
}

export interface TDProps extends Omit<TdHTMLAttributes<HTMLTableCellElement>, 'align'> {
  align?: 'start' | 'end'
  /** @아이디, 시각, 숫자: 모노 + 폭이 같은 숫자 */
  mono?: boolean
  /** 보조 정보: 한 단계 옅은 글자 */
  dim?: boolean
  /** 한 줄로 두고 넘치면 … 로 줄인다. 기본 true */
  truncate?: boolean
  /** 행이 제외(muted)되면 이 칸의 글자에 줄을 긋는다 */
  strike?: boolean
}

export function TD({
  align = 'start',
  mono = false,
  dim = false,
  truncate = true,
  strike = false,
  className,
  ...rest
}: TDProps) {
  return (
    <td
      className={clsx(
        styles.td,
        align === 'end' && styles.end,
        mono && styles.mono,
        dim && styles.dim,
        truncate && styles.truncate,
        strike && styles.strike,
        className,
      )}
      {...rest}
    />
  )
}

/* ── 선택 띠 ───────────────────────────────────────── */

export interface SelectionBandProps {
  /** 선택한 수. 0 이면 띠가 없다 */
  count: number
  /** 세는 단위. 기본 "명" */
  unit?: string
  /** 선택 해제 (버튼과 Esc) */
  onClear: () => void
  /** 맨 앞 자리: 이 쪽 전체 선택 체크박스 */
  leading?: ReactNode
  /** 동작들 (SelectionAction) */
  children?: ReactNode
  /** 띠의 이름 (읽어 주는 프로그램용) */
  label?: string
  className?: string
}

/**
 * 선택 띠: 먹색 띠에 "N명 선택됨", 동작, "선택 해제 (Esc)".
 * Table 의 band 자리에 넣으면 머리 행 위에 같은 높이로 겹쳐서, 선택을 시작하거나 끝내도 표가 움직이지 않는다.
 */
export function SelectionBand({
  count,
  unit = '명',
  onClear,
  leading,
  children,
  label = '선택한 항목에 할 일',
  className,
}: SelectionBandProps) {
  const active = count > 0

  useEffect(() => {
    if (!active) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      const target = event.target
      // 대화상자·메뉴·입력 칸이 Esc 를 쓰고 있으면 건드리지 않는다
      if (
        target instanceof Element &&
        target.closest('[role="dialog"], [role="menu"], [role="listbox"], input, textarea, select')
      ) {
        return
      }
      onClear()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [active, onClear])

  if (!active) return null

  return (
    <div className={clsx(styles.band, className)} role="toolbar" aria-label={label}>
      {leading && <span className={styles.bandLeading}>{leading}</span>}
      <span className={styles.bandCount} role="status">
        {formatNumber(count)}
        {unit} 선택됨
      </span>
      <div className={styles.bandActions}>{children}</div>
      <button type="button" className={styles.bandClear} onClick={onClear}>
        선택 해제
        <kbd className={styles.bandKey}>Esc</kbd>
        <X size={14} aria-hidden />
      </button>
    </div>
  )
}

export interface SelectionActionProps extends Omit<HTMLAttributes<HTMLButtonElement>, 'children'> {
  /** 16px 아이콘 (Phosphor Regular) */
  icon?: ReactNode
  children: ReactNode
  disabled?: boolean
}

/** 선택 띠 안의 동작 하나 */
export const SelectionAction = forwardRef<HTMLButtonElement, SelectionActionProps>(
  function SelectionAction({ icon, children, className, disabled, ...rest }, ref) {
    return (
      <button
        ref={ref}
        type="button"
        className={clsx(styles.bandAction, className)}
        disabled={disabled}
        {...rest}
      >
        {icon}
        <span>{children}</span>
      </button>
    )
  },
)

/* ── 키보드로 행 옮겨 다니기 ───────────────────────── */

export interface RowNavigationOptions {
  /** 행 수 */
  count: number
  /** Space: 선택 바꾸기 */
  onToggle?: (index: number) => void
  /** Enter: 열기 */
  onOpen?: (index: number) => void
}

/**
 * 표의 행을 키보드로 옮겨 다닌다.
 * Tab 으로 표에 들어오면 한 행에만 멈추고, ↑ ↓ (또는 k j), Home, End 로 옮긴다.
 * Space 는 선택, Enter 는 열기.
 *
 *   const nav = useRowNavigation({ count: rows.length, onToggle, onOpen })
 *   <TR {...nav.getRowProps(index)} />
 */
export function useRowNavigation({ count, onToggle, onOpen }: RowNavigationOptions) {
  const [current, setCurrent] = useState(0)
  const rows = useRef(new Map<number, HTMLTableRowElement>())
  const active = Math.min(current, Math.max(0, count - 1))

  const focusRow = useCallback(
    (index: number) => {
      const next = Math.max(0, Math.min(count - 1, index))
      setCurrent(next)
      rows.current.get(next)?.focus()
    },
    [count],
  )

  const getRowProps = useCallback(
    (index: number) => ({
      ref: (element: HTMLTableRowElement | null) => {
        if (element) rows.current.set(index, element)
        else rows.current.delete(index)
      },
      tabIndex: index === active ? 0 : -1,
      onFocus: () => setCurrent(index),
      onKeyDown: (event: KeyboardEvent<HTMLTableRowElement>) => {
        // 행 안의 체크박스·링크에서 온 키는 그쪽에 맡긴다
        if (event.target !== event.currentTarget) return
        switch (event.key) {
          case 'ArrowDown':
          case 'j':
            event.preventDefault()
            focusRow(index + 1)
            break
          case 'ArrowUp':
          case 'k':
            event.preventDefault()
            focusRow(index - 1)
            break
          case 'Home':
            event.preventDefault()
            focusRow(0)
            break
          case 'End':
            event.preventDefault()
            focusRow(count - 1)
            break
          case ' ':
            if (onToggle) {
              event.preventDefault()
              onToggle(index)
            }
            break
          case 'Enter':
            if (onOpen) {
              event.preventDefault()
              onOpen(index)
            }
            break
        }
      },
    }),
    [active, count, focusRow, onOpen, onToggle],
  )

  return { activeIndex: active, focusRow, getRowProps }
}
