import { formatTime } from '@/lib/format'
import type { LiveState } from '@/lib/live'

import { APP_VERSION } from '../version'
import styles from './AppShell.module.css'

type ShellFooterProps = {
  /** 개요를 마지막으로 불러온 시각(ms). 아직 없으면 null */
  loadedAt: number | null
  /** 불러오지 못했고 보여 줄 예전 값도 없을 때 */
  failed: boolean
  live: LiveState
}

/** 맨 아래 한 줄: 언제 불러왔는지, 새 감지가 바로 들어오는지. */
export function ShellFooter({ loadedAt, failed, live }: ShellFooterProps) {
  return (
    <footer className={styles.footer}>
      <p>
        {loadedAt
          ? `${formatTime(loadedAt)}에 불러왔어요`
          : failed
            ? '아직 불러오지 못했어요'
            : '불러오는 중이에요'}
        <span className={styles.footerSep} aria-hidden="true">
          ·
        </span>
        {live === 'open' ? '새 감지는 바로 반영돼요' : '연결이 다시 이어지면 새 감지를 반영해요'}
      </p>
      <p className={styles.version}>ChatDB {APP_VERSION}</p>
    </footer>
  )
}
