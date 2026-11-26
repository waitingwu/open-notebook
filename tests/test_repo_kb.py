"""Repo KB: deny policy, git walking/diff, masking and parsers."""

import os
import subprocess

import pytest

from open_notebook.repo_kb.config import RepoConfig
from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.ingest import import_repo, update_repo
from open_notebook.repo_kb.mask import mask_text
from open_notebook.repo_kb.parsers import (
    normalize_program,
    parse_ddl,
    parse_spec,
    sql_usage,
)
from open_notebook.repo_kb.policy import PathRules, has_denied_component
from open_notebook.repo_kb.store import Store


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "src"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _write(
        r, "app/DB/T1.sql", 'CREATE TABLE "S"."DTAV9001" ("ID" VARCHAR(10) NOT NULL);\n'
    )
    _write(r, "app/usr/Secret.java", "CANARY_USR_ROOT")
    _write(r, "app/x/USR/Deep.java", "CANARY_USR_UPPER")
    _write(r, "usr/top.txt", "CANARY_USR_TOP")
    _write(r, "app/user/ok.txt", "host 10.20.30.40")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "init")
    return r


def test_policy_hard_deny():
    assert has_denied_component("CSR2/source/AV_SRC/usr/a/B.java")
    assert has_denied_component("usr/a.txt")
    assert has_denied_component("a/USR/b.txt")
    assert not has_denied_component("a/user/b.txt")
    assert not has_denied_component("a/usr.txt")  # a file, not a directory
    assert not PathRules(include=["*"]).allows_file("x/usr/y.sql")


def test_walk_never_descends_into_usr(repo, monkeypatch):
    g = GitRepo(str(repo))
    seen_specs = []
    orig = g._cat_full

    def spy(spec):
        seen_specs.append(spec)
        return orig(spec)

    monkeypatch.setattr(g, "_cat_full", spy)
    rules = PathRules()
    paths = [e.path for e in g.walk(g.head(), rules.allows_dir, rules.allows_file)]
    g.close()
    assert sorted(paths) == ["app/DB/T1.sql", "app/user/ok.txt"]
    # only root tree + allowed sub-trees were read: app, app/DB, app/user, app/x
    assert len(seen_specs) == 5


def test_import_update_and_mask(repo, tmp_path):
    store = Store(str(tmp_path / "kb"))
    cfg = RepoConfig(name="src", path=str(repo), role="src")
    first = import_repo(store, cfg, progress=lambda m: None)
    assert first["files"] == 2
    text = open(store.abs("mirror/src/app/user/ok.txt"), encoding="utf-8").read()
    assert text == "host <IP>"
    _write(repo, "app/user/ok.txt", "changed")
    _write(repo, "app/usr/Secret.java", "CANARY_CHANGED")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "c2")
    upd = update_repo(store, cfg, progress=lambda m: None)
    assert [c["path"] for c in upd["changed"]] == ["app/user/ok.txt"]
    log = open(store.abs("access.jsonl"), encoding="utf-8").read()
    assert "usr/" not in log.lower().replace("/user/", "/")
    for (body,) in store.db.execute("SELECT body FROM fts"):
        assert "CANARY" not in body
    store.close()


def test_mask_rules():
    assert mask_text("jdbc:db2://h:5/X")[0] == "<CONN>"
    assert mask_text('GRANT SELECT ON T TO USER "DB2USR"')[0].endswith('"<ACCOUNT>"')
    assert mask_text("password=abc123")[0] == "password=<SECRET>"
    assert mask_text("1.2.3.4\t章節")[0] == "1.2.3.4\t章節"
    assert mask_text("getGuid:abc")[0] == "getGuid:abc"
    assert mask_text("帳號: avbatch，查看 log")[0] == "帳號: <ACCOUNT>，查看 log"
    code, _ = mask_text('String userId = req.getParameter("x");', is_code=True)
    assert code == 'String userId = req.getParameter("x");'


def test_parse_ddl_and_sql_usage():
    ddl = """CREATE TABLE "DBAV    "."DTAV0011_AA"  (
      "BUSINESSNO" VARCHAR(2) NOT NULL,
      "CASENO" VARCHAR(15) NOT NULL,
      "UNBPM" VARCHAR(1)   DEFAULT 'N')
     IN "DBAVDATA";
ALTER TABLE "DBAV"."DTAV0011_AA" ADD CONSTRAINT "PK" PRIMARY KEY ("BUSINESSNO","CASENO");
CREATE INDEX "DBAV"."IDX1" ON "DBAV"."DTAV0011_AA" ("CASENO" ASC);
COMMENT ON TABLE DBAV.DTAV0011_AA IS '掃瞄明細狀態記錄檔';
"""
    (t,) = parse_ddl(ddl, "x.sql")
    assert t.name == "DTAV0011_AA" and t.comment == "掃瞄明細狀態記錄檔"
    assert [c.name for c in t.columns] == ["BUSINESSNO", "CASENO", "UNBPM"]
    assert t.pk == ["BUSINESSNO", "CASENO"] and t.indexes[0][0] == "IDX1"
    use = sql_usage(
        "UPDATE DBAV.DTAV0011_AA SET X=1 WHERE Y IN (SELECT Y FROM DTAV0003)",
        {"DTAV0011_AA", "DTAV0003"},
    )
    assert use == {"DTAV0011_AA": {"U"}, "DTAV0003": {"R"}}


def test_parse_spec():
    text = "\n".join(
        [
            "程式名稱",
            "AVZ1_2000.java",
            "作業方式",
            "ONLINE",
            "•\t相關檔案",
            "項次",
            "刪除",
            "•\t",
            "DTAVZ100",
            "影像版本比對檔",
            "■",
            "■",
            "□",
            "□",
            "•\t相關模組",
            "項次",
            "中文說明",
            "程式名稱",
            "•\t",
            "審批序號模組",
            "ZZ_B3Z001",
            "•\t畫面",
        ]
    )
    s = parse_spec(text, "x.doc")
    assert s.program == "AVZ1_2000" and s.mode == "ONLINE"
    assert [(t.name, t.crud) for t in s.tables] == [("DTAVZ100", "RC")]
    assert [m[0] for m in s.modules] == ["ZZ_B3Z001"]
    assert normalize_program("UZAV_Z1Z001") == "AV_Z1Z001"
    assert normalize_program("UCAVZ1_B100") == "AVZ1_B100"


def test_store_is_outside_repo(repo, tmp_path):
    # ingest never writes into the source repository
    store = Store(str(tmp_path / "kb2"))
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
    ).stdout
    import_repo(
        store,
        RepoConfig(name="src", path=str(repo), role="src"),
        progress=lambda m: None,
    )
    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
    ).stdout
    store.close()
    assert before == after == ""
    assert not os.path.exists(repo / "kb2")
