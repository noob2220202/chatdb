import styles from './AppShell.module.css'

/** 로그인 상태를 확인하는 동안 보이는 것: 머리띠 자리의 겹줄뿐이다. 돌아가는 표시는 두지 않는다. */
export function MastheadRule() {
  return (
    <div className={styles.frame} aria-busy="true">
      <div className={styles.masthead} />
      <span className="visually-hidden">불러오고 있어요</span>
    </div>
  )
}
