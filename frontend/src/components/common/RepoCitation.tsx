'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { repoKbApi } from '@/lib/api/repo-kb'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RepoCitationDrawer({
  kb,
  notebook,
  reference,
  onClose,
}: {
  kb?: string
  notebook?: string
  reference: string | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data, isPending, error } = useQuery({
    queryKey: ['repo-kb', kb || notebook, 'cite', reference],
    queryFn: () =>
      notebook
        ? repoKbApi.citeNotebook(notebook, reference!)
        : repoKbApi.cite(kb!, reference!),
    enabled: !!reference,
    retry: false,
  })
  return (
    <Dialog
      open={!!reference}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('repoKb.citation')}</DialogTitle>
        </DialogHeader>
        <p className="break-all text-xs text-muted-foreground">{reference}</p>
        {isPending ? (
          <p>{t('repoKb.loading')}</p>
        ) : error || !data?.valid ? (
          <p className="text-muted-foreground">{t('repoKb.invalidCitation')}</p>
        ) : (
          <>
            <code className="text-xs">{data.file_commit}</code>
            {data.stale && (
              <p className="text-destructive">{t('repoKb.stale')}</p>
            )}
            <pre className="overflow-x-auto rounded-lg border p-3 text-xs">
              {data.lines?.map((line) => (
                <div
                  key={line.number}
                  className={
                    line.highlight
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground'
                  }
                >
                  <span className="mr-4 inline-block w-10 select-none text-right">
                    {line.number}
                  </span>
                  {line.text}
                </div>
              ))}
            </pre>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function RepoMarkdown({
  kb,
  notebook,
  slug = 'index',
  children,
  navigate,
  validity,
}: {
  kb?: string
  notebook?: string
  slug?: string
  children: string
  navigate?: (slug: string) => void
  validity?: Record<string, boolean>
}) {
  const { t } = useTranslation()
  const [reference, setReference] = useState<string | null>(null)
  const text = children.replace(
    /〔[^〔〕\n]+#L\d+(?:-L?\d+)?@[^〔〕\s]+〕/g,
    (ref) => `[${ref}](#repo-cite=${encodeURIComponent(ref)})`,
  )
  return (
    <>
      <MarkdownRenderer
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              className={
                href?.startsWith('#repo-cite=') &&
                validity?.[decodeURIComponent(href.slice(11))] === false
                  ? 'text-muted-foreground line-through'
                  : undefined
              }
              title={
                href?.startsWith('#repo-cite=') &&
                validity?.[decodeURIComponent(href.slice(11))] === false
                  ? t('repoKb.invalidCitation')
                  : undefined
              }
              onClick={(event) => {
                if (href?.startsWith('#repo-cite=')) {
                  event.preventDefault()
                  setReference(decodeURIComponent(href.slice(11)))
                  return
                }
                if (href && !/^(https?:|mailto:|#)/.test(href) && navigate) {
                  event.preventDefault()
                  const parts = slug.split('/').slice(0, -1)
                  for (const part of href
                    .replace(/\.md(?:#.*)?$/, '')
                    .split('/')) {
                    if (part === '..') parts.pop()
                    else if (part && part !== '.')
                      parts.push(decodeURIComponent(part))
                  }
                  navigate(parts.join('/'))
                }
              }}
            >
              {children}
            </a>
          ),
        }}
      >
        {text}
      </MarkdownRenderer>
      <RepoCitationDrawer
        kb={kb}
        notebook={notebook}
        reference={reference}
        onClose={() => setReference(null)}
      />
    </>
  )
}
