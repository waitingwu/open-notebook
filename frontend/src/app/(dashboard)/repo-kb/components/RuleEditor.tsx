'use client'

import { useId } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { ProtectedRule } from '@/lib/api/repo-kb'

export const selectClass =
  'h-9 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

export function RuleEditor({
  rules,
  onChange,
}: {
  rules: ProtectedRule[]
  onChange: (rules: ProtectedRule[]) => void
}) {
  const { t } = useTranslation()
  const uid = useId()
  const edit = (index: number, value: Partial<ProtectedRule>) =>
    onChange(
      rules.map((rule, i) => (i === index ? { ...rule, ...value } : rule)),
    )
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t('repoKb.protectionHelp')}
      </p>
      {!rules.length && (
        <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
          {t('repoKb.noProtection')}
        </p>
      )}
      {rules.map((rule, index) => (
        <div key={index} className="space-y-2 rounded-lg border p-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor={`${uid}-kind-${index}`}>{t('repoKb.kind')}</Label>
              <select
                id={`${uid}-kind-${index}`}
                value={rule.kind}
                onChange={(e) =>
                  edit(index, { kind: e.target.value as ProtectedRule['kind'] })
                }
                className={selectClass}
              >
                <option value="dir_name">{t('repoKb.dirName')}</option>
                <option value="glob">{t('repoKb.glob')}</option>
              </select>
            </div>
            <div className="min-w-40 flex-1 space-y-1">
              <Label htmlFor={`${uid}-pattern-${index}`}>
                {t('repoKb.pattern')}
              </Label>
              <Input
                id={`${uid}-pattern-${index}`}
                value={rule.pattern}
                onChange={(e) => edit(index, { pattern: e.target.value })}
              />
            </div>
            <label className="flex h-9 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={rule.enabled}
                onChange={(e) => edit(index, { enabled: e.target.checked })}
              />
              {t('repoKb.enabled')}
            </label>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t('common.remove')}
              onClick={() => onChange(rules.filter((_, i) => i !== index))}
            >
              <Trash2 className="size-4 text-destructive" />
            </Button>
          </div>
          <Input
            aria-label={t('repoKb.ruleNote')}
            placeholder={t('repoKb.ruleNote')}
            value={rule.note ?? ''}
            onChange={(e) => edit(index, { note: e.target.value })}
          />
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() =>
          onChange([...rules, { kind: 'dir_name', pattern: '', enabled: true }])
        }
      >
        <Plus className="mr-2 size-4" />
        {t('repoKb.addRule')}
      </Button>
      <p className="text-xs text-muted-foreground">{t('repoKb.gitExcluded')}</p>
    </div>
  )
}

export function removedProtection(
  previous: ProtectedRule[],
  next: ProtectedRule[],
) {
  return previous
    .filter(
      (old) =>
        !next.some(
          (rule) =>
            (!old.enabled || rule.enabled) &&
            rule.kind === old.kind &&
            rule.pattern.toLowerCase() === old.pattern.toLowerCase(),
        ),
    )
    .map((rule) => rule.pattern)
}
