import type { ComponentType } from 'react'
import type { RouteObject } from 'react-router-dom'

import { GuestGate, ProtectedGate } from './AuthGate'
import { NotFoundPage } from './NotFoundPage'
import { MastheadRule } from './shell/MastheadRule'

/** 화면 하나를 필요할 때 내려받는다. */
const page = (load: () => Promise<{ default: ComponentType }>) => async () => ({
  Component: (await load()).default,
})

/** 개발 중에만 있는 견본 화면. 로그인 없이 열린다. */
const galleryRoutes: RouteObject[] = import.meta.env.DEV
  ? [
      { path: '/__gallery/primitives', lazy: page(() => import('@/gallery/PrimitivesGallery')) },
      { path: '/__gallery/data', lazy: page(() => import('@/gallery/DataGallery')) },
    ]
  : []

export const routes: RouteObject[] = [
  {
    hydrateFallbackElement: <MastheadRule />,
    children: [
      {
        path: '/login',
        element: <GuestGate kind="login" />,
        children: [{ index: true, lazy: page(() => import('@/features/auth/LoginPage')) }],
      },
      {
        path: '/setup',
        element: <GuestGate kind="setup" />,
        children: [{ index: true, lazy: page(() => import('@/features/auth/SetupPage')) }],
      },
      ...galleryRoutes,
      {
        element: <ProtectedGate />,
        children: [
          { path: '/', lazy: page(() => import('@/features/overview/OverviewPage')) },
          { path: '/leads', lazy: page(() => import('@/features/leads/LeadsPage')) },
          { path: '/rules', lazy: page(() => import('@/features/rules/RulesPage')) },
          { path: '/groups', lazy: page(() => import('@/features/groups/GroupsPage')) },
          { path: '/accounts', lazy: page(() => import('@/features/accounts/AccountsPage')) },
          { path: '/logs', lazy: page(() => import('@/features/logs/LogsPage')) },
          { path: '/settings', lazy: page(() => import('@/features/settings/SettingsPage')) },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
