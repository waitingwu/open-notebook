'use client'

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Folder, ArrowUp } from 'lucide-react'
import { toast } from 'sonner'
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
  type RepoSource,
  type SourceInput,
  type ProtectedRule,
} from '@/lib/api/repo-kb'
import { useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'
import { RuleEditor, removedProtection, selectClass } from './RuleEditor'

const lines = (value: string) =>
  value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

export function FolderPicker({
  onChoose,
  onClose,
}: {
  onChoose: (path: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [path, setPath] = useState<string>()
  const listing = useQuery({
    queryKey: ['repo-kb', 'folders', path],
    queryFn: () => repoKbApi.folders(path),
    retry: false,
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('repoKb.folder')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 overflow-auto">
          <p className="break-all font-mono text-sm">{listing.data?.path}</p>
          {listing.data?.parent && (
            <Button
              variant="ghost"
              onClick={() => setPath(listing.data!.parent!)}
            >
              <ArrowUp className="mr-2 size-4" />
              {t('repoKb.parentFolder')}
            </Button>
          )}
          {listing.isError && (
            <p role="alert" className="text-destructive">
              {t('repoKb.failedRequest')}
            </p>
          )}
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {listing.data?.directories.map((directory) => (
              <button
                key={directory.path}
                type="button"
                className="flex w-full items-center gap-2 rounded-md p-2 text-left text-sm hover:bg-accent"
                onClick={() => setPath(directory.path)}
              >
                <Folder className="size-4 text-muted-foreground" />
                <span className="flex-1">{directory.name}</span>
                {directory.is_git_repo && (
                  <span className="rounded bg-muted px-2 text-xs">git</span>
                )}
              </button>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={!listing.data}
            onClick={() => {
              if (listing.data) onChoose(listing.data.path)
              onClose()
            }}
          >
            {t('repoKb.useFolder')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function SourceDialog({
  kb,
  source,
  defaults,
  onClose,
}: {
  kb: string
  source?: RepoSource
  defaults: ProtectedRule[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [data, setData] = useState<SourceInput>(
    source
      ? {
          name: source.name,
          path: source.path,
          role: source.role,
          include: source.include,
          exclude: source.exclude,
          protected: source.protected,
        }
      : {
          name: '',
          path: '',
          role: 'doc',
          include: ['**'],
          exclude: [],
          protected: defaults.map((rule) => ({ ...rule })),
        },
  )
  const [folder, setFolder] = useState(false)
  const payload = () => ({
    ...data,
    include: data.include.map((s) => s.trim()).filter(Boolean),
    exclude: data.exclude.map((s) => s.trim()).filter(Boolean),
  })
  const save = useRepoMutation(async () => {
    const value = payload()
    if (source) {
      await repoKbApi.editSource(source.id, {
        name: value.name,
        path: value.path,
        role: value.role,
        include: value.include,
        exclude: value.exclude,
      })
    } else await repoKbApi.addSource(kb, value)
    onClose()
  })
  const preview = useMutation({
    mutationFn: () => repoKbApi.preview(payload()),
    onError: () => toast.error(t('repoKb.failedRequest')),
  })
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {t(source ? 'repoKb.editSource' : 'repoKb.addSource')}
            </DialogTitle>
          </DialogHeader>
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault()
              save.mutate(undefined)
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="repo-name">{t('repoKb.sourceName')}</Label>
                <Input
                  id="repo-name"
                  required
                  pattern={'[a-z0-9_\\-]{1,32}'}
                  value={data.name}
                  onChange={(e) => setData({ ...data, name: e.target.value })}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="repo-role">{t('repoKb.role')}</Label>
                <select
                  id="repo-role"
                  className={`${selectClass} w-full`}
                  value={data.role}
                  onChange={(e) =>
                    setData({ ...data, role: e.target.value as 'doc' | 'src' })
                  }
                >
                  <option value="doc">{t('repoKb.doc')}</option>
                  <option value="src">{t('repoKb.src')}</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="repo-path">{t('repoKb.path')}</Label>
              <div className="flex gap-2">
                <Input
                  id="repo-path"
                  required
                  value={data.path}
                  onChange={(e) => setData({ ...data, path: e.target.value })}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setFolder(true)}
                >
                  <Folder className="mr-2 size-4" />
                  {t('repoKb.folder')}
                </Button>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="repo-include">{t('repoKb.include')}</Label>
                <Textarea
                  id="repo-include"
                  rows={3}
                  value={data.include.join('\n')}
                  onChange={(e) =>
                    setData({ ...data, include: e.target.value.split('\n') })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="repo-exclude">{t('repoKb.exclude')}</Label>
                <Textarea
                  id="repo-exclude"
                  rows={3}
                  value={data.exclude.join('\n')}
                  onChange={(e) =>
                    setData({ ...data, exclude: e.target.value.split('\n') })
                  }
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {t('repoKb.patternsHelp')}
            </p>
            {!source && (
              <section className="space-y-2">
                <h3 className="font-medium">{t('repoKb.protected')}</h3>
                <RuleEditor
                  rules={data.protected}
                  onChange={(protectedRules) =>
                    setData({ ...data, protected: protectedRules })
                  }
                />
              </section>
            )}
            {preview.data && (
              <div className="rounded-lg bg-muted p-3 text-sm">
                <p className="font-medium">
                  {t('repoKb.previewCount', { count: preview.data.files })}
                </p>
                <p>
                  {Object.entries(preview.data.by_extension)
                    .map(([ext, count]) => `${ext}: ${count}`)
                    .join(' · ')}
                </p>
                <p className="mt-1">
                  {t('repoKb.protectedCounts')}:{' '}
                  {preview.data.protected_directories
                    .map((r) => `${r.pattern}: ${r.count}`)
                    .join(' · ') || t('repoKb.none')}
                </p>
                {preview.data.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={!data.path || preview.isPending}
                onClick={() => preview.mutate()}
              >
                {t('repoKb.preview')}
              </Button>
              <Button type="button" variant="ghost" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button disabled={save.isPending}>{t('common.save')}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {folder && (
        <FolderPicker
          onChoose={(path) => setData({ ...data, path })}
          onClose={() => setFolder(false)}
        />
      )}
    </>
  )
}

export function ProtectionDialog({
  source,
  onClose,
}: {
  source: RepoSource
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [rules, setRules] = useState(source.protected.map((r) => ({ ...r })))
  const [clearChats, setClearChats] = useState(false)
  const audit = useQuery({
    queryKey: ['repo-kb', source.id, 'protection-audit'],
    queryFn: () => repoKbApi.exclusionAudit(source.id),
    retry: false,
  })
  const clear = useRepoMutation(() => repoKbApi.deleteRelatedChats(source.kb))
  const [confirmation, setConfirmation] = useState('')
  const [reason, setReason] = useState('')
  const removed = removedProtection(source.protected, rules)
  const ready =
    !removed.length ||
    (removed.every((pattern) => lines(confirmation).includes(pattern)) &&
      !!reason.trim())
  const save = useRepoMutation(async () => {
    await repoKbApi.protect(source.id, rules, lines(confirmation), reason)
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t('repoKb.protected')} · {source.name}
          </DialogTitle>
        </DialogHeader>
        <RuleEditor rules={rules} onChange={setRules} />
        <p className="text-sm text-muted-foreground">
          {t('repoKb.chatRetention')}
        </p>
        <Button
          variant="outline"
          disabled={clear.isPending}
          onClick={() => {
            if (!clearChats) setClearChats(true)
            else clear.mutate(undefined)
          }}
        >
          {t(
            clearChats
              ? 'repoKb.confirmDeleteChats'
              : 'repoKb.deleteRelatedChats',
          )}
        </Button>
        <details className="rounded border p-3">
          <summary className="cursor-pointer text-sm">
            {t('repoKb.exclusionHistory')}
          </summary>
          {audit.data?.map((entry) => (
            <div key={entry.id} className="mt-3 border-t pt-3 text-xs">
              <p>
                {new Date(entry.ts).toLocaleString()} · {entry.action}
              </p>
              <p>
                {entry.before?.rules?.map((r) => r.pattern).join('、') ||
                  t('repoKb.none')}{' '}
                →{' '}
                {entry.after?.rules?.map((r) => r.pattern).join('、') ||
                  t('repoKb.none')}
              </p>
              <p>{entry.reason}</p>
            </div>
          ))}
        </details>
        {!!removed.length && (
          <div className="space-y-3 rounded-lg border border-destructive/30 p-4">
            <p className="text-sm">{t('repoKb.weakenProtection')}</p>
            <p className="font-mono text-sm">{removed.join('\n')}</p>
            <Textarea
              aria-label={t('repoKb.weakenProtection')}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
            <Label htmlFor="protection-reason">{t('repoKb.reason')}</Label>
            <Input
              id="protection-reason"
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
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
