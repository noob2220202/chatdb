import { ArrowRightIcon } from '@phosphor-icons/react'
import { Link, useLocation } from 'react-router-dom'

import { Button } from '@/ui/Button/Button'

import styles from './NotFoundPage.module.css'

/** 없는 주소로 들어왔을 때. 머리띠는 그대로 있으니 차례에서 다시 고를 수 있다. */
export function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <section className={styles.page} aria-labelledby="not-found-title">
      <p className={styles.number} aria-hidden="true">
        404
      </p>
      <div className={styles.text}>
        <h1 id="not-found-title" className={styles.title}>
          없는 쪽이에요.
        </h1>
        <p className={styles.body}>
          주소가 바뀌었거나 잘못 적힌 것 같아요. 찾던 화면은 위쪽 차례에서 다시 고를 수 있어요.
        </p>
        <p className={styles.path}>
          <span className={styles.pathLabel}>들어온 주소</span>
          <span className="mono">{pathname}</span>
        </p>
        <div className={styles.actions}>
          <Button asChild variant="solid" trailingIcon={<ArrowRightIcon aria-hidden="true" />}>
            <Link to="/">개요로 가기</Link>
          </Button>
          <Button asChild variant="quiet">
            <Link to="/leads">수집함 보기</Link>
          </Button>
        </div>
      </div>
    </section>
  )
}
