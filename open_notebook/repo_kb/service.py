"""Native repo-KB entry points; shared by the API, commands, and maintenance CLI.

Legacy PoC SQLite modules remain for historical fixture comparison only.
Native application paths do not use YAML configuration, mirror, or publish.
"""

from open_notebook.repo_kb.native_catalog import create_kb, create_source
from open_notebook.repo_kb.native_cite import resolve, validate
from open_notebook.repo_kb.native_jobs import cancel_job, execute_job, submit_job
from open_notebook.repo_kb.native_lookup import search
from open_notebook.repo_kb.native_mutations import update_protected
from open_notebook.repo_kb.native_sync import sync_source
from open_notebook.repo_kb.native_wiki import build_wiki

__all__ = [
    "create_kb",
    "create_source",
    "resolve",
    "validate",
    "cancel_job",
    "execute_job",
    "submit_job",
    "search",
    "update_protected",
    "sync_source",
    "build_wiki",
]
