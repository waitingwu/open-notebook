"""Local KB state: file manifest, keyword index (FTS5 trigram) and masked mirror.

Layout under ``data_dir``::

    state.sqlite         manifest, repo heads, FTS index, run events
    mirror/<repo>/<path> masked plain text (``.txt`` appended when converted)
    wiki/                generated pages
    access.jsonl         every blob read by ingest: repo, path, blob (no content)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional

CHUNK_LINES = 40

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repo (
  name TEXT PRIMARY KEY, path TEXT, role TEXT, commit_sha TEXT, imported_at TEXT
);
CREATE TABLE IF NOT EXISTS file (
  repo TEXT, path TEXT, blob TEXT, category TEXT, module TEXT, method TEXT,
  last_commit TEXT, last_date TEXT, lines INTEGER, masks TEXT, mirror TEXT,
  PRIMARY KEY (repo, path)
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
  repo UNINDEXED, path UNINDEXED, category UNINDEXED,
  start_line UNINDEXED, end_line UNINDEXED, body, tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS event (
  ts TEXT, action TEXT, repo TEXT, detail TEXT
);
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(data_dir, "state.sqlite"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._access = open(
            os.path.join(data_dir, "access.jsonl"), "a", encoding="utf-8"
        )

    def close(self) -> None:
        self.db.commit()
        self.db.close()
        self._access.close()

    # -- paths ------------------------------------------------------------
    def mirror_rel(self, repo: str, path: str, converted: bool) -> str:
        return f"mirror/{repo}/{path}" + (".txt" if converted else "")

    def abs(self, rel: str) -> str:
        return os.path.join(self.data_dir, rel)

    # -- writes -----------------------------------------------------------
    def log_access(self, repo: str, path: str, blob: str, action: str = "read") -> None:
        self._access.write(
            json.dumps(
                {
                    "ts": now_iso(),
                    "repo": repo,
                    "path": path,
                    "blob": blob,
                    "action": action,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    def event(self, action: str, repo: str, detail: Dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO event VALUES (?,?,?,?)",
            (now_iso(), action, repo, json.dumps(detail, ensure_ascii=False)),
        )

    def set_repo(self, name: str, path: str, role: str, commit: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO repo VALUES (?,?,?,?,?)",
            (name, path, role, commit, now_iso()),
        )

    def repo_commit(self, name: str) -> Optional[str]:
        row = self.db.execute(
            "SELECT commit_sha FROM repo WHERE name=?", (name,)
        ).fetchone()
        return row[0] if row else None

    def put_file(self, row: Dict[str, Any], text: Optional[str]) -> None:
        repo, path = row["repo"], row["path"]
        self.delete_file(repo, path)
        if text is not None:
            rel = row["mirror"]
            dest = self.abs(rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
            lines = text.split("\n")
            for i in range(0, len(lines), CHUNK_LINES):
                body = "\n".join(lines[i : i + CHUNK_LINES])
                if body.strip():
                    self.db.execute(
                        "INSERT INTO fts VALUES (?,?,?,?,?,?)",
                        (
                            repo,
                            path,
                            row["category"],
                            i + 1,
                            min(i + CHUNK_LINES, len(lines)),
                            body,
                        ),
                    )
        self.db.execute(
            "INSERT INTO file VALUES (:repo,:path,:blob,:category,:module,:method,:last_commit,"
            ":last_date,:lines,:masks,:mirror)",
            {**row, "masks": json.dumps(row.get("masks") or {})},
        )

    def delete_file(self, repo: str, path: str) -> None:
        old = self.db.execute(
            "SELECT mirror FROM file WHERE repo=? AND path=?", (repo, path)
        ).fetchone()
        if old and old[0] and os.path.exists(self.abs(old[0])):
            os.unlink(self.abs(old[0]))
        self.db.execute("DELETE FROM file WHERE repo=? AND path=?", (repo, path))
        self.db.execute("DELETE FROM fts WHERE repo=? AND path=?", (repo, path))

    def update_last_commits(self, repo: str, last: Dict[str, Any]) -> None:
        for path, (sha, date) in last.items():
            self.db.execute(
                "UPDATE file SET last_commit=?, last_date=? WHERE repo=? AND path=?",
                (sha, date, repo, path),
            )

    # -- reads ------------------------------------------------------------
    def files(
        self, repo: Optional[str] = None, category: Optional[str] = None
    ) -> List[sqlite3.Row]:
        q, args = "SELECT * FROM file WHERE 1=1", []
        if repo:
            q += " AND repo=?"
            args.append(repo)
        if category:
            q += " AND category=?"
            args.append(category)
        return list(self.db.execute(q + " ORDER BY repo, path", args))

    def search(
        self, query: str, limit: int = 20, categories: Iterable[str] = ()
    ) -> List[sqlite3.Row]:
        phrase = '"' + query.replace('"', '""') + '"'
        q = "SELECT repo, path, category, start_line, end_line, snippet(fts, 5, '【', '】', '…', 16) AS snip FROM fts WHERE fts MATCH ?"
        args: List[Any] = [phrase]
        cats = list(categories)
        if cats:
            q += f" AND category IN ({','.join('?' * len(cats))})"
            args += cats
        q += " ORDER BY rank LIMIT ?"
        args.append(limit)
        return list(self.db.execute(q, args))
