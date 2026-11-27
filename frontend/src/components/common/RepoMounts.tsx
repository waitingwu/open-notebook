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
} from '@/components/ui/dialog'
import { repoKbApi } from '@/lib/api/repo-kb'
import { useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RepoMounts({
  notebook,
  disabled,
  onDisable,
}: {
  notebook: string
  disabled: string[]
  onDisable: (value: string[]) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const mounts = useQuery({
    queryKey: ['repo-kb', 'mounts', notebook],
    queryFn: () => repoKbApi.mounts(notebook),
    retry: false,
  })
  const available = useQuery({
    queryKey: ['repo-kb', 'available', notebook],
    queryFn: () => repoKbApi.list(notebook),
    enabled: open,
    retry: false,
  })
  const save = useRepoMutation((ids: string[]) =>
    repoKbApi.setMounts(notebook, ids),
  )
  return (
    <div className="space-y-2 border-b p-3">
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {t('repoKb.mounts')}
      </Button>
      <div className="flex flex-wrap gap-2">
        {mounts.data?.map((kb) => (
          <label
            key={kb.id}
            className="flex items-center gap-1 rounded-full border bg-muted/30 px-3 py-1 text-xs"
          >
            <input
              type="checkbox"
              checked={!disabled.includes(kb.id)}
              onChange={(e) =>
                onDisable(
                  e.target.checked
                    ? disabled.filter((id) => id !== kb.id)
                    : [...disabled, kb.id],
                )
              }
            />
            {kb.name}
          </label>
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('repoKb.mounts')}</DialogTitle>
          </DialogHeader>
          {available.data?.map((kb) => (
            <label
              className="flex items-center gap-3 rounded border p-3"
              key={kb.id}
            >
              <input
                type="checkbox"
                disabled={save.isPending}
                checked={mounts.data?.some((m) => m.id === kb.id) || false}
                onChange={(e) =>
                  save.mutate(
                    e.target.checked
                      ? [...(mounts.data || []).map((m) => m.id), kb.id]
                      : (mounts.data || [])
                          .filter((m) => m.id !== kb.id)
                          .map((m) => m.id),
                  )
                }
              />
              {kb.name}
            </label>
          ))}
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function SaveRepoAnswer({
  notebook,
  session,
  message,
}: {
  notebook: string
  session: string
  message: string
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [kb, setKB] = useState('')
  const [title, setTitle] = useState('')
  const mounts = useQuery({
    queryKey: ['repo-kb', 'mounts', notebook],
    queryFn: () => repoKbApi.mounts(notebook),
    enabled: open,
    retry: false,
  })
  const save = useRepoMutation(async () => {
    await repoKbApi.saveAnswer(kb, session, message, title)
    setOpen(false)
  })
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        {t('repoKb.saveAnswer')}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('repoKb.saveAnswer')}</DialogTitle>
          </DialogHeader>
          <Label htmlFor="qa-kb">{t('repoKb.selectKb')}</Label>
          <select
            id="qa-kb"
            className="rounded border bg-background p-2"
            value={kb}
            onChange={(e) => setKB(e.target.value)}
          >
            <option value="">{t('repoKb.selectKb')}</option>
            {mounts.data?.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
          <Label htmlFor="qa-title">{t('repoKb.name')}</Label>
          <Input
            id="qa-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <Button
            disabled={!kb || !title.trim() || save.isPending}
            onClick={() => save.mutate(undefined)}
          >
            {t('common.save')}
          </Button>
        </DialogContent>
      </Dialog>
    </>
  )
}
