import { describe, expect, it } from 'vitest'

import {
  decideLogin,
  decideProtected,
  decideSetup,
  loginPath,
  safeNext,
  type AuthStatus,
} from './auth'

const fresh: AuthStatus = { setup_required: true, authenticated: false, demo: false }
const loggedOut: AuthStatus = { setup_required: false, authenticated: false, demo: false }
const loggedIn: AuthStatus = { setup_required: false, authenticated: true, demo: false }

describe('safeNext', () => {
  it('사이트 안의 경로는 그대로 둔다', () => {
    expect(safeNext('/leads?status=new#top')).toBe('/leads?status=new#top')
  })

  it('밖으로 나가는 주소와 빈 값은 첫 화면으로 바꾼다', () => {
    for (const bad of [
      null,
      undefined,
      '',
      'https://example.com',
      '//example.com',
      '/\\example.com',
      'leads',
    ]) {
      expect(safeNext(bad)).toBe('/')
    }
  })

  it('로그인·설정 화면으로는 돌려보내지 않는다', () => {
    expect(safeNext('/login')).toBe('/')
    expect(safeNext('/login?next=%2Fleads')).toBe('/')
    expect(safeNext('/setup')).toBe('/')
  })
})

describe('loginPath', () => {
  it('가려던 곳을 next 로 기억한다', () => {
    expect(loginPath({ pathname: '/leads', search: '?status=new' })).toBe(
      '/login?next=%2Fleads%3Fstatus%3Dnew',
    )
  })

  it('첫 화면이면 next 를 붙이지 않는다', () => {
    expect(loginPath({ pathname: '/' })).toBe('/login')
  })
})

describe('decideProtected', () => {
  it('상태를 아직 모르면 기다린다', () => {
    expect(decideProtected(undefined, { pathname: '/' })).toEqual({ kind: 'wait' })
  })

  it('비밀번호가 아직 없으면 설정으로 보낸다', () => {
    expect(decideProtected(fresh, { pathname: '/leads' })).toEqual({
      kind: 'redirect',
      to: '/setup',
    })
  })

  it('로그인하지 않았으면 가려던 곳을 기억하고 로그인으로 보낸다', () => {
    expect(decideProtected(loggedOut, { pathname: '/groups', search: '', hash: '' })).toEqual({
      kind: 'redirect',
      to: '/login?next=%2Fgroups',
    })
  })

  it('로그인했으면 그대로 보여 준다', () => {
    expect(decideProtected(loggedIn, { pathname: '/groups' })).toEqual({ kind: 'allow' })
  })
})

describe('decideLogin', () => {
  it('비밀번호가 아직 없으면 설정으로 보낸다', () => {
    expect(decideLogin(fresh, null)).toEqual({ kind: 'redirect', to: '/setup' })
  })

  it('이미 로그인했으면 가려던 곳으로 보낸다', () => {
    expect(decideLogin(loggedIn, '/leads')).toEqual({ kind: 'redirect', to: '/leads' })
    expect(decideLogin(loggedIn, 'https://example.com')).toEqual({ kind: 'redirect', to: '/' })
  })

  it('로그인하지 않았으면 로그인 화면을 보여 준다', () => {
    expect(decideLogin(loggedOut, null)).toEqual({ kind: 'allow' })
    expect(decideLogin(undefined, null)).toEqual({ kind: 'wait' })
  })
})

describe('decideSetup', () => {
  it('처음일 때만 보여 준다', () => {
    expect(decideSetup(fresh)).toEqual({ kind: 'allow' })
    expect(decideSetup(loggedOut)).toEqual({ kind: 'redirect', to: '/login' })
    expect(decideSetup(loggedIn)).toEqual({ kind: 'redirect', to: '/' })
    expect(decideSetup(undefined)).toEqual({ kind: 'wait' })
  })
})
