'use client'

import { useState } from 'react'
import { CheckCircle2, CircleAlert, Loader2, Terminal } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useLocalCliStatus, useRegisterLocalModel, useTestLocalModel } from '@/lib/hooks/use-audit'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { LocalCliStatus } from '@/lib/api/audit'

function CliRow({ cli }: { cli: LocalCliStatus }) {
  const { t } = useTranslation()
  const register = useRegisterLocalModel()
  const test = useTestLocalModel()
  const [name, setName] = useState(cli.suggested_models[0] ?? 'default')
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({})
  const ready = cli.installed && cli.logged_in

  return (
    <div className="rounded-md border p-4 space-y-3" data-testid={`local-cli-${cli.provider}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Terminal className="size-4 text-teal" aria-hidden="true" />
        <span className="font-medium">{cli.display_name}</span>
        {cli.version && <Badge variant="secondary">v{cli.version}</Badge>}
        {!cli.installed ? (
          <Badge variant="destructive">{t('aiAudit.cli.notInstalled')}</Badge>
        ) : cli.logged_in ? (
          <Badge>
            <CheckCircle2 aria-hidden="true" />
            {t('aiAudit.cli.loggedIn')}
            {cli.auth_method ? ` · ${cli.auth_method}` : ''}
            {cli.plan ? ` · ${cli.plan}` : ''}
          </Badge>
        ) : (
          <Badge variant="destructive">
            <CircleAlert aria-hidden="true" />
            {t('aiAudit.cli.notLoggedIn')}
          </Badge>
        )}
      </div>
      {cli.path && <p className="text-xs text-muted-foreground font-mono break-all">{cli.path}</p>}
      {cli.installed && !cli.logged_in && (
        <p className="text-sm text-warn">
          {t('aiAudit.cli.loginHint', {
            command: cli.provider === 'codex_cli' ? 'codex login' : 'claude auth login',
          })}
        </p>
      )}
      {cli.registered_models.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">{t('aiAudit.cli.registeredModels')}</p>
          <ul className="space-y-1">
            {cli.registered_models.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono">{m.name}</span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!ready || test.isPending}
                  onClick={async () => {
                    const r = await test.mutateAsync(m.id)
                    setTestResult((prev) => ({ ...prev, [m.id]: r }))
                  }}
                >
                  {test.isPending && test.variables === m.id ? (
                    <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                  ) : null}
                  {t('aiAudit.cli.test')}
                </Button>
                {testResult[m.id] && (
                  <span className={testResult[m.id].success ? 'text-teal text-xs' : 'text-destructive text-xs'}>
                    {testResult[m.id].message}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {cli.installed && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label={t('aiAudit.cli.modelName')}
            className="w-48"
            value={name}
            list={`models-${cli.provider}`}
            onChange={(e) => setName(e.target.value)}
          />
          <datalist id={`models-${cli.provider}`}>
            {cli.suggested_models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <Button
            size="sm"
            disabled={!name.trim() || register.isPending}
            onClick={() => register.mutate({ provider: cli.provider, name: name.trim() })}
          >
            {t('aiAudit.cli.addModel')}
          </Button>
        </div>
      )}
    </div>
  )
}

export function LocalCliCard() {
  const { t } = useTranslation()
  const { data, isLoading, refetch, isFetching } = useLocalCliStatus()
  return (
    <Card className="p-6 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-xl font-semibold tracking-tight">{t('aiAudit.cli.title')}</h2>
          <p className="text-sm text-muted-foreground mt-1">{t('aiAudit.cli.desc')}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}
          {t('aiAudit.cli.recheck')}
        </Button>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {(data ?? []).map((cli) => (
            <CliRow key={cli.provider} cli={cli} />
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">{t('aiAudit.cli.privacyNote')}</p>
    </Card>
  )
}
