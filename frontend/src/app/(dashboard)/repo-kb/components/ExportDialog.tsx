'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { ExportConfig, repoKbApi } from '@/lib/api/repo-kb'
import { useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'

function ExportForm({
  kb,
  initial,
  onClose,
}: {
  kb: string
  initial: ExportConfig
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [config, setConfig] = useState(initial)
  const mutation = useRepoMutation((fn: () => Promise<unknown>) => fn())
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t('repoKb.exportHelp')}</p>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
        />
        {t('repoKb.enabled')}
      </label>
      {(['repo_path', 'branch', 'subdir'] as const).map((key, index) => (
        <div key={key} className="space-y-2">
          <Label htmlFor={`export-${key}`}>
            {t(
              [
                'repoKb.exportPath',
                'repoKb.exportBranch',
                'repoKb.exportSubdir',
              ][index],
            )}
          </Label>
          <Input
            id={`export-${key}`}
            value={config[key]}
            onChange={(e) => setConfig({ ...config, [key]: e.target.value })}
          />
        </div>
      ))}
      {initial.last_export_commit && (
        <code className="break-all text-xs">{initial.last_export_commit}</code>
      )}
      {initial.last_error && (
        <p className="text-destructive">{initial.last_error}</p>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button
          variant="outline"
          disabled={!initial.enabled || mutation.isPending}
          onClick={() => mutation.mutate(() => repoKbApi.exportRun(kb))}
        >
          {t('repoKb.export')}
        </Button>
        <Button
          disabled={!config.repo_path || mutation.isPending}
          onClick={() =>
            mutation.mutate(async () => {
              await repoKbApi.saveExport(kb, config)
              onClose()
            })
          }
        >
          {t('common.save')}
        </Button>
      </DialogFooter>
    </div>
  )
}

export function ExportDialog({
  kb,
  onClose,
}: {
  kb: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const config = useQuery({
    queryKey: ['repo-kb', kb, 'export'],
    queryFn: () => repoKbApi.exportConfig(kb),
    retry: false,
  })
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('repoKb.exportGit')}</DialogTitle>
        </DialogHeader>
        {config.data ? (
          <ExportForm kb={kb} initial={config.data} onClose={onClose} />
        ) : (
          <p>{t(config.error ? 'repoKb.failedRequest' : 'repoKb.loading')}</p>
        )}
      </DialogContent>
    </Dialog>
  )
}
