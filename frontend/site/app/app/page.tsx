import type { Metadata } from 'next'
import { Dashboard } from '@/components/Dashboard'

export const metadata: Metadata = {
  title: 'YourBrand Workspace',
  description: 'A sample view of your automation workflows and activity.',
}

export default function DashboardPage() {
  return <Dashboard />
}
