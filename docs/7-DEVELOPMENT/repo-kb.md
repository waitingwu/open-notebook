# Repo KB (PoC)

Builds a layered maintenance knowledge base from local git repositories. Design: [ADR-015](decisions/ADR-015-repo-kb-layered-from-git.md).

## Configure

```yaml
# repo_kb.yaml
data_dir: kb-data            # relative to this file
repos:
  - name: av_doc
    path: ~/Documents/Git_Repo/av_doc
    role: doc                # doc | src
    include: ["CSR2_Doc/*"]  # fnmatch; "*" also matches "/"
    exclude: ["*/av-wiki/*", "*.jar"]
  - name: av_src
    path: ~/Documents/Git_Repo/av_src
    role: src
    include: ["CSR2/source/*"]
```

Directories named `usr` (any case) are always excluded; this cannot be configured away.

## Commands

Run from the directory holding `repo_kb.yaml` with `PYTHONPATH=<open-notebook>`:

| Command | What it does |
|---|---|
| `python -m open_notebook.repo_kb import [repo…]` | Full import at the repo's HEAD commit |
| `… update [repo…]` | Re-process only files in `git diff <last>..HEAD` |
| `… build` | Regenerate table / module / system / SOP pages and `discrepancies.md`; writes `manifest.tsv` |
| `… compile-rules Z1 Q0` | LLM-compile business-rule pages for modules (local Claude Code CLI) |
| `… validate` | Check every citation in the wiki |
| `… search "ERR-40417"` | Trigram keyword search over the masked mirror |
| `… ask "問題"` | Sandboxed local agent answers with citations |
| `… publish --table DTAV0011_AA` | Sync pages into the notebook "AV 影像系統維運知識庫" |
| `… verify-usr` | Evidence that `usr` was never read, indexed or sent |

## Data directory

`state.sqlite` (manifest, FTS index, events), `mirror/<repo>/<path>[.txt]` (masked text), `wiki/`, `manifest.tsv`, `access.jsonl` (every blob read: repo, path, blob id — no content). It contains internal content: keep it out of git.

## Audit

Events record counts, durations, hashes and paths only — never prompt text, answers or credentials.
