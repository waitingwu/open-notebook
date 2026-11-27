'use client'

import { useRouter } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { SettingsDialog } from '../../repo-kb/components/SettingsDialog'
import { useRepoSettings } from '@/lib/hooks/use-repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function RepoKBSettingsPage() {
  const router = useRouter()
  const { t } = useTranslation()
  const settings = useRepoSettings()
  return <AppShell><main className="flex-1 p-6"><h1 className="text-2xl font-semibold">{t('repoKb.settings')}</h1>{settings.data ? <SettingsDialog initial={settings.data} onClose={() => router.push('/repo-kb')} /> : <p>{t(settings.error ? 'repoKb.failedRequest' : 'repoKb.loading')}</p>}</main></AppShell>
}
