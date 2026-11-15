/**
 * 사진 목록.
 *
 * 모두 미국 의회도서관 소장, 저작권 제한이 없는 사진이다 (출처와 가공 내용은 CREDITS.md).
 * 먹(#191816)에서 종이(#f0eee8)로 가는 듀오톤에 필름 그레인을 얹어 같은 인쇄물처럼 맞췄다.
 * 사진은 로그인, 개요, 빈 상태, 화면 그림에만 쓴다. 표가 있는 작업 화면의 머리에는 넣지 않는다.
 */

import cards2x from './cards-2x.jpg'
import cards from './cards.jpg'
import clocks2x from './clocks-2x.jpg'
import clocks from './clocks.jpg'
import cords2x from './cords-2x.jpg'
import cords from './cords.jpg'
import lineman2x from './lineman-2x.jpg'
import lineman from './lineman.jpg'
import operator2x from './operator-2x.jpg'
import operator from './operator.jpg'
import positions2x from './positions-2x.jpg'
import positions from './positions.jpg'
import row2x from './row-2x.jpg'
import row from './row.jpg'
import shelves2x from './shelves-2x.jpg'
import shelves from './shelves.jpg'
import sorting2x from './sorting-2x.jpg'
import sorting from './sorting.jpg'
import takingNotes2x from './taking-notes-2x.jpg'
import takingNotes from './taking-notes.jpg'

export interface Photo {
  /** 1배율 파일 */
  src: string
  /** 2배율 파일 */
  src2x: string
  /** <img srcSet> 에 그대로 넣는 값 */
  srcSet: string
  /** 1배율 기준 크기 (CSS px) */
  width: number
  height: number
  /** 대체 글 */
  alt: string
  /** 캡션의 굵은 첫 구절 */
  title: string
  /** 캡션: 어디서, 언제 */
  caption: string
  /** 찍은 사람과 소장처 */
  credit: string
  /** 잘라서 보여 줄 때 지켜야 할 자리 (object-position) */
  focus: string
}

function photo(
  src: string,
  src2x: string,
  width: number,
  height: number,
  rest: Pick<Photo, 'alt' | 'title' | 'caption' | 'credit'> & { focus?: string },
): Photo {
  return {
    src,
    src2x,
    srcSet: `${src} 1x, ${src2x} 2x`,
    width,
    height,
    focus: '50% 50%',
    ...rest,
  }
}

const LOC = '미국 의회도서관'

export const photos = {
  /** 로그인. 불 켜진 램프 하나만 --lamp 빨강으로 덧칠했다. 램프 자리는 OPERATOR_LAMP */
  operator: photo(operator, operator2x, 933, 900, {
    alt: '교환대 앞에 앉은 교환원이 수많은 램프 가운데 불이 켜진 하나를 손끝으로 가리키고 있는 흑백 사진',
    title: '불 켜진 회선을 찾는 교환원',
    caption: '메릴랜드 애버딘, 1941년',
    credit: `사진 존 바숀 · ${LOC}`,
    focus: '0% 0%',
  }),
  /** 개요 */
  positions: photo(positions, positions2x, 640, 450, {
    alt: '번호가 붙은 교환대 자리마다 앉아 코드를 꽂고 있는 교환원들의 흑백 사진',
    title: '자리마다 번호가 붙은 교환대',
    caption: '메릴랜드 애버딘, 1941년',
    credit: `사진 존 바숀 · ${LOC}`,
  }),
  /** 수집함이 비었을 때 */
  takingNotes: photo(takingNotes, takingNotes2x, 640, 480, {
    alt: '헤드셋을 쓴 교환원 두 사람이 교환대 앞에서 연필로 쪽지에 받아 적고 있는 흑백 사진',
    title: '받아 적는 손',
    caption: '워싱턴 D.C.의 전화 교환실',
    credit: `사진 해리스 앤드 유잉 · ${LOC}`,
    focus: '55% 70%',
  }),
  /** 수집 규칙 */
  sorting: photo(sorting, sorting2x, 550, 550, {
    alt: '갓등 아래에서 우체국 직원이 편지 다발을 들고 칸칸이 나뉜 분류함 앞에 서 있는 흑백 사진',
    title: '칸마다 나눠 넣는 손',
    caption: '워싱턴 D.C. 중앙우체국, 1938년',
    credit: `사진 아서 로스타인 · ${LOC}`,
    focus: '60% 35%',
  }),
  /** 그룹 */
  cords: photo(cords, cords2x, 640, 556, {
    alt: '수화기를 귀에 댄 교환원이 종이 줄지어 달린 작은 교환대에 코드를 꽂고 있는 흑백 사진',
    title: '회선에 코드를 꽂는 교환원',
    caption: '오리건 오크리지, 1942년',
    credit: `사진 러셀 리 · ${LOC}`,
    focus: '60% 60%',
  }),
  /** 계정 */
  row: photo(row, row2x, 640, 427, {
    alt: '긴 교환대를 따라 교환원들이 한 자리씩 줄지어 앉아 있고 뒤에서 감독이 지켜보는 흑백 사진',
    title: '한 사람에 한 자리',
    caption: '워싱턴 D.C. 국회의사당 교환실, 1959년',
    credit: `사진 매리언 트리코스코 · ${LOC}`,
    focus: '60% 55%',
  }),
  /** 활동 기록 */
  clocks: photo(clocks, clocks2x, 640, 480, {
    alt: '표준 시계 두 대가 걸린 전신실에서 전신수가 전신 타자기를 치고 있는 흑백 사진',
    title: '시계 아래에서 받아 치는 전신수',
    caption: '애리조나 셀리그먼, 1943년',
    credit: `사진 잭 델라노 · ${LOC}`,
    focus: '30% 40%',
  }),
  /** 설정 */
  lineman: photo(lineman, lineman2x, 520, 650, {
    alt: '빈 하늘을 배경으로 전봇대에 올라 전화선을 손보고 있는 사람의 흑백 사진',
    title: '선을 손보는 사람',
    caption: '애리조나 피널 카운티, 1940년',
    credit: `사진 러셀 리 · ${LOC}`,
    focus: '60% 45%',
  }),
  /** 찾는 결과가 없을 때 */
  shelves: photo(shelves, shelves2x, 520, 650, {
    alt: '서류 뭉치가 천장까지 쌓인 좁은 통로에서 발판에 올라 높은 칸에 손을 뻗고 있는 사람의 흑백 사진',
    title: '기록 칸을 더듬어 찾는 사람',
    caption: '미주리 캔자스시티, 1943년',
    credit: `사진 잭 델라노 · ${LOC}`,
    focus: '55% 22%',
  }),
  /** 규칙·기록이 아직 없을 때 */
  cards: photo(cards, cards2x, 640, 480, {
    alt: '네 사람이 책상에 마주 앉아 카드를 한 장씩 맞춰 보고 있는 모습을 위에서 내려다본 흑백 사진',
    title: '카드를 한 장씩 맞춰 보는 사람들',
    caption: '메릴랜드 볼티모어, 1937년 무렵',
    credit: `사진 해리스 앤드 유잉 · ${LOC}`,
  }),
} as const satisfies Record<string, Photo>

export type PhotoKey = keyof typeof photos

/** 화면마다 쓰는 사진. 같은 화면은 늘 같은 사진을 쓴다. */
export const PHOTO_FOR = {
  login: 'operator',
  overview: 'positions',
  leads: 'takingNotes',
  rules: 'sorting',
  groups: 'cords',
  accounts: 'row',
  logs: 'clocks',
  settings: 'lineman',
  noResults: 'shelves',
  blank: 'cards',
} as const satisfies Record<string, PhotoKey>

/**
 * 로그인 사진 속 불 켜진 램프의 자리.
 *   x, y    램프의 중심. 사진의 왼쪽 위를 (0, 0), 오른쪽 아래를 (1, 1)로 본 비율
 *   rx, ry  램프의 반지름. 사진 폭에 대한 비율 (가로, 세로)
 * 머리글에서 램프까지 선을 잇거나 램프 둘레에 테를 두를 때 쓴다.
 */
export const OPERATOR_LAMP = { x: 213.4 / 933, y: 377 / 900, rx: 0.0054, ry: 0.0062 } as const
