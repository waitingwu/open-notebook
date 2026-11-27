'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  repoKbApi,
  type RepoSettings,
  type RepoSource,
} from '@/lib/api/repo-kb'
import { useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'
import { RuleEditor, removedProtection } from './RuleEditor'

export function SettingsDialog({
  initial,
  onClose,
}: {
  initial: RepoSettings
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [data, setData] = useState(initial)
  const [rootText, setRootText] = useState(initial.allowed_roots.join('\n'))
  const [confirmation, setConfirmation] = useState('')
  const [reason, setReason] = useState('')
  const removed = removedProtection(
    initial.default_protected,
    data.default_protected,
  )
  const patterns = confirmation
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const ready =
    !removed.length ||
    (!!reason.trim() && removed.every((pattern) => patterns.includes(pattern)))
  const save = useRepoMutation(async () => {
    await repoKbApi.saveSettings({
      default_protected: data.default_protected,
      confirm_patterns: patterns,
      reason,
      selector_timeout: data.selector_timeout,
      allowed_roots: rootText
        .split('\n')
        .map((r) => r.trim())
        .filter(Boolean),
    })
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('repoKb.settings')}</DialogTitle>
        </DialogHeader>
        <section className="space-y-3">
          <h3 className="font-medium">{t('repoKb.defaults')}</h3>
          <p className="text-sm text-muted-foreground">
            {t('repoKb.defaultsHelp')}
          </p>
          <RuleEditor
            rules={data.default_protected}
            onChange={(rules) => setData({ ...data, default_protected: rules })}
          />
        </section>
        {!!removed.length && (
          <div className="space-y-2 rounded border p-3">
            <p>{t('repoKb.weakenProtection')}</p>
            <p>{removed.join('、')}</p>
            <Textarea
              aria-label={t('repoKb.weakenProtection')}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
            <Label htmlFor="default-reason">{t('repoKb.reason')}</Label>
            <Input
              id="default-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="repo-roots">{t('repoKb.allowedRoots')}</Label>
          <Textarea
            id="repo-roots"
            value={rootText}
            onChange={(e) => setRootText(e.target.value)}
            rows={3}
          />
          <p className="text-sm text-muted-foreground">
            {t('repoKb.allowedRootsHelp')}
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="repo-timeout">{t('repoKb.selectorTimeout')}</Label>
          <Input
            id="repo-timeout"
            type="number"
            min={1}
            max={120}
            value={data.selector_timeout}
            onChange={(e) =>
              setData({ ...data, selector_timeout: Number(e.target.value) })
            }
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={save.isPending || !ready}
            onClick={() => save.mutate(undefined)}
          >
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ApplyDefaultsDialog({
  sources,
  settings,
  onClose,
}: {
  sources: RepoSource[]
  settings: RepoSettings
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [confirmation, setConfirmation] = useState('')
  const [reason, setReason] = useState('')
  const removed = [
    ...new Set(
      sources.flatMap((source) =>
        removedProtection(source.protected, settings.default_protected),
      ),
    ),
  ]
  const patterns = confirmation
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
  const ready =
    !removed.length ||
    (removed.every((pattern) => patterns.includes(pattern)) && !!reason.trim())
  const save = useRepoMutation(async () => {
    await repoKbApi.applyDefaults(
      sources.map((s) => s.id),
      patterns,
      reason,
    )
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('repoKb.applyDefaults')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          {t('repoKb.applyDefaultsHelp')}
        </p>
        <ul className="list-inside list-disc text-sm">
          {sources.map((source) => (
            <li key={source.id}>{source.name}</li>
          ))}
        </ul>
        <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
          {settings.default_protected.map((r) => r.pattern).join('\n') ||
            t('repoKb.none')}
        </pre>
        {!!removed.length && (
          <div className="space-y-2">
            <p>{t('repoKb.weakenProtection')}</p>
            <pre>{removed.join('\n')}</pre>
            <Textarea
              aria-label={t('repoKb.weakenProtection')}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
            <Label htmlFor="apply-reason">{t('repoKb.reason')}</Label>
            <Input
              id="apply-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={!ready || save.isPending}
            onClick={() => save.mutate(undefined)}
          >
            {t('common.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
