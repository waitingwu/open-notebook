# Native repository knowledge bases

CaBook imports committed files from local Git repositories into SurrealDB,
builds a linked wiki, and retrieves masked evidence for ordinary notebook chat.
Repository configuration, content, wiki history, manual notes, and the keyword
index use SurrealDB. The native CLI and UI share the same services. Native KB
operations do not use the PoC YAML configuration, SQLite store, mirror, or
`publish` command. The application's existing chat checkpointer remains a
separate subsystem.

## Run locally

The existing application requires SurrealDB, the API, its command worker, and
the Next.js frontend. Start the worker with:

```sh
uv run surreal-commands-worker --import-modules commands
```

Database migrations 30 and 31 install the native KB schema. Node.js 22.12 or
newer is required by the frontend. On macOS, Word conversion uses `textutil`.
The worker must see the same repository paths as the API; Docker deployments
need read-only bind mounts and an alternative converter for Word documents.

For an isolated local preview, start the `repo-kb` environment in Multica's
environment sidebar. Its declaration is `.multica/environments.toml`. The
daemon assigns a port block, supervises all services, records a log, and stops
them after 24 hours. The URL is the assigned frontend port followed by
`/repo-kb`. The preview stores its database and application files under
`data/repo-kb-preview/`, and uses `.next-repo-kb-preview` so an existing Next.js
development server can keep running.

Outside Multica, `.venv/bin/python scripts/dev_repo_kb.py` runs the same preview
in the foreground at `http://localhost:8502/repo-kb` by default. Stop that
foreground process with Ctrl-C. Its database credentials are local development
credentials and its services bind to loopback.

## Connect repositories

1. Open **Knowledge bases**, create a global or notebook-specific KB, and add
   repositories with documentation/source roles.
2. Choose paths and include/exclude patterns, then preview. Preview traverses
   Git tree metadata without reading file blobs.
3. Configure protected exclusions before the first sync. Factory defaults are
   empty; `usr` is never silently inserted. For the real AV source repository,
   manually add an enabled `dir_name` rule for `usr` before syncing.
4. The first-sync dialog lists the current rules for every selected repository.
   The server checks a configuration hash so changed rules require a new review.
5. Sync one or multiple repositories. Returning to the page preserves job
   progress because job state lives in the database. A successful sync builds
   the deterministic wiki and publishes a complete keyword-index generation.

Only committed content is imported. Git operations are read-only: tree/blob,
log, diff, and revision metadata queries. The source working tree is never
checked out, fetched, or changed. A source is staged independently and its
snapshot pointer changes only after successful completion. Unchanged blobs
reuse masked chunks. Per-file Git commits and dates remain separate from each
repository's snapshot commit.

## Protected exclusions and filesystem boundaries

`.git` is always excluded. A protected directory is pruned before its subtree
is listed; protected globs also become Git log/diff exclusion pathspecs. Every
content read, citation lookup, and retrieval rechecks current policy. Masking
happens before persistence. Converter NUL characters become replacement
characters without changing line numbers.

Adding protection purges matching files/chunks from all snapshots, removes
affected derived content and history, invalidates compressed postings, records
the rule change, and queues a rebuild. Removing, disabling, or editing away a
rule requires its exact text and a reason. Defaults are copied into new sources;
applying defaults changes only explicitly selected sources. Existing chat
history is retained; deleting related chats requires a separate confirmation.

**Settings → Knowledge base settings** exposes optional allowed roots.
`REPO_KB_ALLOWED_ROOTS` overrides the UI list, with entries separated by the
platform path separator. An empty list allows any repository except CaBook's
own data directories and their ancestors. Actual application data, uploads,
and checkpoint folders are protected. Add custom database storage directories
through `REPO_KB_DATA_ROOTS`; these supplement the mandatory roots.
`OPEN_NOTEBOOK_DATA_FOLDER` changes the application data directory.

The exclusion report separates current stored content from historical reads.
After intentionally disabling a synthetic rule and syncing, its historical
read counter remains nonzero even after the content is purged. The report
must not claim that content was never read. OS-level evidence must be collected
separately with tools such as `fs_usage`; macOS requires administrator access.

## Wiki, search, and chat

- Deterministic builds produce system, module, table, SOP, and discrepancy pages.
  The directory includes summaries and omits individual table pages; tables use
  exact entity routing and keyword search.
- Citation links open masked database text with original line numbers and the
  file's Git commit. Old snapshots remain resolvable under current protection.
- Stable discrepancy fingerprints preserve review decisions across rebuilding.
- Rule/flow compilation is explicit. Cross-KB batches process one item at a
  time, preserve independent failures, support cancelling queued work, and allow
  retries. Compilers use bounded, representative masked input and report skipped
  material. Flow source text does not establish diagram connector directions.
- `.vsd` contributes no extracted text; `.vsdx` currently supplies shape text.
  Unsupported order/branches must remain **unknown / requires confirmation**.
- Wiki revisions preserve model/source provenance. LLM pages can be restored.
  Manual notes survive rebuilding and become stale when their parent changes.
- Notebook mounts include global KBs and the notebook's own private KBs. Scope
  changes require confirming any notebook detachments. Chat chips can disable
  a mount temporarily without changing the notebook's saved mounts.

Retrieval runs exact entity routing and LLM page selection in parallel, adds
BM25-ranked wiki sections and original evidence, and fits the result into a
24k-token estimated context budget. Selection uses the chosen chat model and
an independent 20-second default timeout. Only a strict JSON page list of at
most eight known slugs is accepted. Empty, invalid, timed-out, or failed
responses use keyword fallback; free prose is never interpreted as page IDs.
Local CLI subprocesses are killed and reaped by their runner on deadline.

Good answers can be saved as QA pages only after citation revalidation. They
enter the directory and search index. All model inputs come from masked DB
content. AI audit records token/timing metadata and selected paths, never
prompts or answers; the requested acceptance Q&A artifact is a separate,
intentional export.

## Storage and keyword-index fallback

Source snapshots, files/chunks, wiki pages/sections, revisions/notes,
discrepancies, events, jobs, batches, locks, and search generations are native
SurrealDB records. Lease tokens fence writes inside their transaction. Only one
writer can own a KB; the API returns 409 with an active job ID where available.
Compilation batches also share a global compilation lease.

The application builds compressed bigram postings in `repo_search_posting`,
ordinal-to-target records in `repo_search_document`, and generation metadata in
`repo_search_generation`. Candidate ranking uses posting document frequencies;
BM25 verifies term frequency and length against authorised current text before
returning snippets. Complete generations are published atomically and tied to
the protection-policy version. No embedding model is downloaded. See
`decisions/ADR-016-repo-kb-native-search.md` for the initial benchmark
and SurrealDB native-index investigation.

The PoC modules remain for historical fixture/benchmark comparison. They are
not native application entry points. PoC data is not automatically migrated
or deleted; an old published notebook can be removed manually after review.

## Optional export

SurrealDB is canonical. ZIP downloads are generated on demand without a server
copy. Git export must target a separate repository outside every source repo.
It writes Markdown/front matter and manual notes to the configured branch and
subfolder, creates a commit, and never pushes. A private Git index preserves
the export repository's existing working tree, staging area, and checked-out
branch. Git history can retain content excluded later.

## Maintenance and verification

```sh
uv run python -m open_notebook.repo_kb list
uv run python -m open_notebook.repo_kb --kb repo_kb:ID review-source repo_source:ID
uv run python -m open_notebook.repo_kb --kb repo_kb:ID sync repo_source:ID --confirm-protection HASH
uv run python -m open_notebook.repo_kb --kb repo_kb:ID search '執行紀錄位置'
uv run python -m open_notebook.repo_kb --kb repo_kb:ID verify
```

Commands enqueue work by default; `--foreground` runs the same job service
synchronously. The old `publish`/`ask` PoC file sandbox and YAML flags are not
native CLI commands. Use ordinary notebook chat for native KB answers.

`scripts/benchmark_repo_kb_retrieval.py` measures both local CLIs with strict
selection, fallback, token counts, and page recall. Its engineering labels need
human confirmation. `scripts/benchmark_repo_kb_chat.py` records ten questions
through the ordinary API. Both require an already imported, masked KB; neither
opens a source repository. Reports belong under the ignored `output/` folder.
