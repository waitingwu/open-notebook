# ADR-015: Repo KB — layered knowledge base built from git objects, outside SurrealDB

- Status: Accepted (PoC)
- Date: 2026-11-26
- Context issue: CATH-9 (sub-issue of CATH-8)

## Context

Maintenance knowledge for an internal system (architecture/flow diagrams, DDL, program specs, SOPs) already lives in git repositories, next to the code. We want CaBook to read those repos directly, keep every statement traceable to a file, line and commit, update incrementally, and point out where specs and code disagree. One code repository contains a directory (`usr`) that must never be read, indexed or sent to a model.

## Decision

1. **Read from git objects, not the working tree.** A tree walker decodes tree objects through one `git cat-file --batch` process and checks every directory entry against a hard deny list *before* reading the sub-tree, so a denied directory is never listed. Git commands that walk history (`log`, `diff`) carry `:(exclude)` pathspecs, and every path is filtered again in Python.
2. **Layers by document type**, generated deterministically where possible: DDL → table pages; spec documents (fixed UC/UZ templates) → parsed program, mode, related tables with CRUD flags; code → table usage from SQL resources and Java; SOPs kept verbatim with trigram keyword search. Only business-rule pages are LLM-compiled, and only from masked spec text.
3. **Citations are first-class** (`〔repo:path#Lx-Ly@commit〕`), with the commit verified so the blob at that commit equals the indexed blob. A validator checks every citation in the wiki and in agent answers.
4. **State lives in a local data directory** (SQLite FTS5 + masked mirror + Markdown wiki), not in SurrealDB, for the PoC: it keeps the masked mirror inspectable, makes the Q&A agent's sandbox a plain directory, and avoids schema migrations while the shape settles. Pages are pushed into a notebook through the REST API (`publish`) so they appear in the UI.
5. **Q&A uses a sandboxed local agent** (Claude Code, `--tools Read,Grep,Glob`, `dontAsk`, no allow rules, explicit deny rules for the source repos and `**/usr/**`, working directory = data dir). Bare `Read` allow rules were rejected: they permit reads anywhere on disk.

## Consequences

- Line numbers for Word/Visio sources refer to the extracted text in the mirror, not to the binary file.
- Binary `.vsd` (Visio 2003), `.xls` and images are indexed by name only.
- Spec-vs-code comparison is heuristic: dynamic SQL, shared components and code in excluded directories cause false positives; results are a list to confirm, not verdicts.
- Moving state into SurrealDB (and exposing it in the UI natively) is follow-up work once the PoC is accepted.
