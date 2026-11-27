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
import { RepoKB, repoKbApi } from '@/lib/api/repo-kb'
import { useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { useNotebooks } from '@/lib/hooks/use-notebooks'
import { useTranslation } from '@/lib/hooks/use-translation'
import { selectClass } from './RuleEditor'

export function ManageKBDialog({
  kb,
  onClose,
}: {
  kb: RepoKB
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(kb.name)
  const [scope, setScope] = useState(kb.scope)
  const [owner, setOwner] = useState(kb.owner_notebook || '')
  const [confirmed, setConfirmed] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const notebooks = useNotebooks()
  const mounted = useQuery({
    queryKey: ['repo-kb', kb.id, 'mounted-notebooks'],
    queryFn: () => repoKbApi.mountedNotebooks(kb.id),
    retry: false,
  })
  const affected = (mounted.data || []).filter(
    (n) => scope === 'notebook' && n.id !== owner,
  )
  const mutate = useRepoMutation((fn: () => Promise<unknown>) => fn())
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t('common.edit')} · {kb.name}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="kb-edit-name">{t('repoKb.name')}</Label>
          <Input
            id="kb-edit-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <Label htmlFor="kb-edit-scope">{t('repoKb.scope')}</Label>
        <select
          id="kb-edit-scope"
          className={selectClass}
          value={scope}
          onChange={(e) => {
            setScope(e.target.value as RepoKB['scope'])
            setConfirmed(false)
          }}
        >
          <option value="global">{t('repoKb.global')}</option>
          <option value="notebook">{t('repoKb.private')}</option>
        </select>
        {scope === 'notebook' && (
          <select
            aria-label={t('repoKb.chooseNotebook')}
            className={selectClass}
            value={owner}
            onChange={(e) => {
              setOwner(e.target.value)
              setConfirmed(false)
            }}
          >
            <option value="">{t('repoKb.chooseNotebook')}</option>
            {notebooks.data?.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
          </select>
        )}
        {affected.length > 0 && (
          <div className="space-y-2 rounded border p-3">
            <p>{t('repoKb.detachHelp')}</p>
            <ul className="list-inside list-disc">
              {affected.map((n) => (
                <li key={n.id}>{n.name}</li>
              ))}
            </ul>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              {t('common.confirm')}
            </label>
          </div>
        )}
        {deleting && (
          <p className="text-destructive">{t('repoKb.deleteKBHelp')}</p>
        )}
        <DialogFooter>
          <Button
            variant="destructive"
            disabled={mutate.isPending}
            onClick={() => {
              if (!deleting) setDeleting(true)
              else
                mutate.mutate(async () => {
                  await repoKbApi.deleteKB(kb.id)
                  onClose()
                })
            }}
          >
            {t('common.delete')}
          </Button>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={
              !name.trim() ||
              (scope === 'notebook' && !owner) ||
              (!!affected.length && !confirmed) ||
              mounted.isPending ||
              mounted.isError ||
              mutate.isPending
            }
            onClick={() =>
              mutate.mutate(async () => {
                await repoKbApi.editKB(kb.id, {
                  name,
                  scope,
                  owner_notebook: owner || undefined,
                  detach_confirmed: confirmed ? affected.map((n) => n.id) : [],
                })
                onClose()
              })
            }
          >
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
