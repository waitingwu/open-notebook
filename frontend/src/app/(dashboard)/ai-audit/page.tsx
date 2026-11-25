'use client'

import { AppShell } from '@/components/layout/AppShell'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/hooks/use-translation'
import { LocalCliCard } from './components/LocalCliCard'
import { RunsTab } from './components/RunsTab'
import { UsageTab } from './components/UsageTab'
import { RateLimitsTab } from './components/RateLimitsTab'
import { AuditSettingsTab } from './components/AuditSettingsTab'

export default function AiAuditPage() {
  const { t } = useTranslation()
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6">
          <div className="max-w-6xl mx-auto space-y-6">
            <div>
              <h1 className="font-display text-2xl font-bold tracking-tight">{t('aiAudit.title')}</h1>
              <p className="text-muted-foreground mt-2">{t('aiAudit.desc')}</p>
            </div>
            <LocalCliCard />
            <Tabs defaultValue="runs">
              <TabsList>
                <TabsTrigger value="runs" className="whitespace-nowrap px-4">{t('aiAudit.tabs.runs')}</TabsTrigger>
                <TabsTrigger value="usage" className="whitespace-nowrap px-4">{t('aiAudit.tabs.usage')}</TabsTrigger>
                <TabsTrigger value="limits" className="whitespace-nowrap px-4">{t('aiAudit.tabs.limits')}</TabsTrigger>
                <TabsTrigger value="settings" className="whitespace-nowrap px-4">{t('aiAudit.tabs.settings')}</TabsTrigger>
              </TabsList>
              <TabsContent value="runs"><RunsTab /></TabsContent>
              <TabsContent value="usage"><UsageTab /></TabsContent>
              <TabsContent value="limits"><RateLimitsTab /></TabsContent>
              <TabsContent value="settings"><AuditSettingsTab /></TabsContent>
            </Tabs>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
