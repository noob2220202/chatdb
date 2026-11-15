import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { Providers } from './Providers'
import { createQueryClient } from './queryClient'
import { routes } from './router'

const queryClient = createQueryClient()
const router = createBrowserRouter(routes)

export function App() {
  return (
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  )
}
