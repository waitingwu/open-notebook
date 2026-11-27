# ADR-016: Native repo KB keyword search with versioned posting lists

- Status: Proposed (implementation in progress)
- Date: 2026-11-27
- Context: CATH-10, specification v1.4

## Context

The PoC uses SQLite FTS5 and masked files. The native integration needs keyword
search in SurrealDB without retaining a separate SQLite index. Queries include
Chinese phrases, identifiers with underscores, and error codes. Source content
is masked before indexing, and protected exclusions apply before source reads
and again at retrieval time.

The initially specified SurrealDB 2.7.0 `class` / `lowercase, ngram(2,3)`
analyzer did not match strings of four or more characters using a single
`@1@` query, even when the exact text was indexed. In a small control, querying
the analyzer's two-character tokens separately and intersecting the results
did match the expected strings. This identifies a query behavior; it does not
establish an upstream defect.

In an isolated in-memory instance, 31,583 masked chunks loaded before indexing.
At approximately 4,000 chunks indexed, the database process's macOS physical
footprint had reached 2,096 MB; the index was still building and the experiment
was stopped. The full index memory and timing were therefore not measured.
RSS was lower and varied substantially as the OS compressed memory. This crosses
the CATH-10 resource threshold and motivates the specified fallback.

## Decision

Create a compact application-built inverted index stored in SurrealDB:

- `repo_search_generation` identifies a KB-local snapshot, its document count,
  and whether it finished building; `repo_kb.search_generation` points to the
  published version.
- `repo_search_document` maps a generation-local unsigned 32-bit ordinal to a
  `repo_chunk` or `repo_wiki_section` record.
- `repo_search_posting` maps a case-folded two-character gram to compressed,
  little-endian sorted ordinals. Posting and document record IDs are derived
  from the generation and gram or ordinal. Index construction uses already
  masked and policy-filtered text; it does not store full raw source files.
- Intersect postings to find candidates, then enforce current KB scope,
  protected exclusions, and active source snapshots before fetching text.
  Verify the case-folded substring against the authorised text; postings can
  return false positives. One-character queries require a bounded scan.
- Build a new generation off to the side, publish it only after all rows are
  written, and invalidate the pointer before exposing changed source data.
  Writers must use the KB lease and fence stale workers. Purge, access checks,
  cleanup of superseded generations, and wiring these operations into every
  source/exclusion/wiki mutation remain required before the feature is usable.

## Measurement

On the local machine, an isolated SurrealDB 2.7.0 in-memory instance and the
native implementation were exercised using 31,583 previously masked PoC chunks
(the SQLite input was read-only, and `usr` paths were excluded). The benchmark
script is `scripts/benchmark_native_repo_search.py`.

| Measure | Result |
| --- | ---: |
| Load chunks | 9.27 s |
| Build and publish full index | 58.84 s |
| Database peak RSS | 507.5 MiB |
| Python process peak RSS | 546.7 MiB |
| `執行紀錄位置` | 3 exact matches, 0.008 s |
| `DTAV0011_AA` | 155 candidates, 134 exact matches, 0.041 s |
| `SQLCODE=-803` | 1 exact match, 0.016 s |

These are single local runs, not p95 or production capacity results. The two
peak RSS figures are measured independently and should not be added as a
simultaneous peak. The benchmark verifies stored chunks and exact phrase
matching, not the complete UI, permissions, incremental update, or answer
quality. It does not use the original source repositories.

## Consequences

Full rebuilds temporarily retain an old generation until a new one is ready;
the product needs explicit cleanup and storage monitoring. Incremental updates,
publication, protection changes, and reads must coordinate through the same
KB-level policy and write fencing; a stale generation must never be used to
reveal excluded content. The index supplies exact keyword candidates, not BM25
ranking or semantic similarity. Ranking and LLM page selection remain separate.
