# 사진 출처

모든 사진은 미국 의회도서관(Library of Congress) 인쇄·사진부 소장품이고, 도서관이 밝힌 권리 안내는
"No known restrictions (on publication)" 이다. FSA/OWI 사진은 미국 연방정부 직원이 업무로 찍은 것이라
퍼블릭 도메인이다.

## 공통 가공

원본 TIFF 에서 다음 순서로 만들었다. 가공 스크립트는 시안의 `_tools/img.js` 를 새 종이색에 맞춰 고친 것이다.

1. 의도한 구도로 자르기 (필름 테두리와 번호는 잘라 냄)
2. 흑백으로 바꾸고 어두운 끝·밝은 끝을 맞춘 뒤 완만한 S 커브
3. 듀오톤: 가장 어두운 곳은 먹 `#191816`, 가장 밝은 곳은 종이 `#f0eee8` 보다 3% 어둡게
4. 필름 그레인 (중간 톤에서 가장 강하게, 재현 가능한 난수)
5. JPEG 내보내기: `이름.jpg` (1배율), `이름-2x.jpg` (2배율)

| 키 | 파일 | 1배율 크기 | 쓰는 곳 |
| --- | --- | --- | --- |
| `operator` | operator.jpg · operator-2x.jpg | 933 × 900 | 로그인 |
| `positions` | positions.jpg · positions-2x.jpg | 640 × 450 | 개요 |
| `takingNotes` | taking-notes.jpg · taking-notes-2x.jpg | 640 × 480 | 수집함이 비었을 때 |
| `sorting` | sorting.jpg · sorting-2x.jpg | 550 × 550 | 수집 규칙 |
| `cords` | cords.jpg · cords-2x.jpg | 640 × 556 | 그룹 |
| `row` | row.jpg · row-2x.jpg | 640 × 427 | 계정 |
| `clocks` | clocks.jpg · clocks-2x.jpg | 640 × 480 | 활동 기록 |
| `lineman` | lineman.jpg · lineman-2x.jpg | 520 × 650 | 설정 |
| `shelves` | shelves.jpg · shelves-2x.jpg | 520 × 650 | 찾는 결과가 없을 때 |
| `cards` | cards.jpg · cards-2x.jpg | 640 × 480 | 규칙·기록이 아직 없을 때 |

## 사진별 출처

### operator — 불 켜진 회선을 찾는 교환원

- 원제: Telephone operators at Aberdeen proving grounds. Aberdeen, Maryland
- 찍은 사람: John Vachon, 1941년 12월
- 소장: Farm Security Administration / Office of War Information Black-and-White Negatives. LC-USF34-064182-D
- 출처: https://www.loc.gov/item/2017813699/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 교환원 손끝의 램프 하나만 램프 빨강 `#d62b1f` 계열로 손채색했다
  (램프 자리는 `OPERATOR_LAMP`).

### positions — 자리마다 번호가 붙은 교환대

- 원제: Telephone operators at Aberdeen proving grounds. Aberdeen, Maryland
- 찍은 사람: John Vachon, 1941년 12월
- 소장: FSA/OWI Black-and-White Negatives. LC-USF34-064183-D
- 출처: https://www.loc.gov/item/2017813700/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공.

### takingNotes — 받아 적는 손

- 원제: C & P Telephone Co. switchboards
- 찍은 사람: Harris & Ewing, 1905–1945년 사이 (정확한 해는 기록에 없음)
- 소장: Harris & Ewing Collection. LC-DIG-hec-20543 (LC-H25-91174-GA)
- 출처: https://www.loc.gov/item/2016861597/
- 권리: No known restrictions on publication (https://www.loc.gov/rr/print/res/140_harr.html)
- 바꾼 것: 공통 가공. 넓은 교환실 사진에서 쪽지에 받아 적는 두 사람만 크게 잘랐다.

### sorting — 칸마다 나눠 넣는 손

- 원제: Washington, D.C. Sorting air mail at the main post office
- 찍은 사람: Arthur Rothstein, 1938년
- 소장: FSA/OWI Black-and-White Negatives. LC-USF34-012959-D
- 출처: https://www.loc.gov/item/2017764853/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 세로 사진을 정사각형으로 잘랐다.

### cords — 회선에 코드를 꽂는 교환원

- 원제: Oakridge, Oregon. Town telephone switchboard. Population of the town is 520
- 찍은 사람: Russell Lee, 1942년 7월
- 소장: FSA/OWI Black-and-White Negatives. LC-USF34-073112-D
- 출처: https://www.loc.gov/item/2017818774/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 세로 사진의 위쪽(교환대와 손)을 가로로 잘랐다.

### row — 한 사람에 한 자리

- 원제: [Women working at a switchboard at the U.S. Capitol, Washington, D.C.]
- 찍은 사람: Marion S. Trikosko, 1959년
- 소장: U.S. News & World Report Magazine Photograph Collection. LC-DIG-ppmsca-71119 (LC-U9-1924-33)
- 출처: https://www.loc.gov/item/2021640241/
- 권리: No known restrictions on publication (https://www.loc.gov/rr/print/res/078_usnw.html)
- 바꾼 것: 공통 가공.

### clocks — 시계 아래에서 받아 치는 전신수

- 원제: Seligman, Arizona. Teletype operator in the telegraph office of the Atchison, Topeka, and
  Santa Fe Railroad. The time here changes from Mountain to Pacific time
- 찍은 사람: Jack Delano, 1943년 3월
- 소장: FSA/OWI Black-and-White Negatives. LC-USW3-021342-E (LC-DIG-fsa-8d27403)
- 출처: https://www.loc.gov/item/2017848967/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 정사각형 사진을 4:3 으로 잘랐다.

### lineman — 선을 손보는 사람

- 원제: [Untitled photo, possibly related to: Lineman on telephone pole at the Casa Grande Valley
  Farms, Pinal County, Arizona]
- 찍은 사람: Russell Lee, 1940년 4월
- 소장: FSA/OWI Black-and-White Negatives. LC-USF33-012683-M3 (LC-DIG-fsa-8a28375)
- 출처: https://www.loc.gov/item/2017742161/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 35mm 필름의 구멍 자리를 잘라 내고 4:5 로 맞췄다.

### shelves — 기록 칸을 더듬어 찾는 사람

- 원제: Kansas City, Missouri. E. A. Schenck, teletype operator, looking up one of the files in the
  record room of the freight depot
- 찍은 사람: Jack Delano, 1943년 3월
- 소장: FSA/OWI Black-and-White Negatives. LC-USW3-019404-D
- 출처: https://www.loc.gov/item/2017847298/
- 권리: No known restrictions (https://www.loc.gov/rr/print/res/071_fsab.html)
- 바꾼 것: 공통 가공. 필름 가장자리의 글자를 잘라 내고 4:5 로 맞췄다.

### cards — 카드를 한 장씩 맞춰 보는 사람들

- 원제: Baltimore, MD. Chances of a mechanical error escaping detection are infinitesimal in the
  Social Security Board Records Office … (review section at work)
- 찍은 사람: Harris & Ewing, 1937년 무렵
- 소장: Harris & Ewing Collection. LC-DIG-hec-22877 (LC-H22-D-1717)
- 출처: https://www.loc.gov/item/2016871853/
- 권리: No known restrictions on publication (https://www.loc.gov/rr/print/res/140_harr.html)
- 바꾼 것: 공통 가공. 유리 건판 가장자리의 번호를 잘라 내고 4:3 으로 맞췄다.
