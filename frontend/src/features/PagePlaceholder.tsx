import styles from './PagePlaceholder.module.css'

/** 화면이 만들어지기 전까지 자리를 지키는 제목. 각 화면을 만들 때 이 컴포넌트는 걷어 낸다. */
export function PagePlaceholder({ title }: { title: string }) {
  return (
    <header className={styles.head}>
      <h1 className={styles.title}>{title}</h1>
    </header>
  )
}
