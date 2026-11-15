import { expect, it } from 'vitest'

import packageJson from '../../package.json?raw'

import { APP_VERSION } from './version'

it('화면에 적는 판 번호가 package.json 과 같다', () => {
  const pkg = JSON.parse(packageJson) as { version: string }
  expect(APP_VERSION).toBe(pkg.version)
})
