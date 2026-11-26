"""Generate the deterministic wiki layer and the spec↔code comparison.

Pages (under ``data_dir/wiki``)::

    index.md                 entry point for people and the Q&A agent
    systems/AV.md            system page: modules, architecture/flow diagrams
    modules/<code>.md        module page: specs, programs, tables, diagrams, SOPs
    tables/<name>.md         one page per table / view
    sop/index.md             troubleshooting docs + error-code keyword index
    rules/<code>.md          business-rule pages (LLM-compiled, see rules.py)
    discrepancies.md         spec vs. code mismatches (to confirm)

Citations use ``〔repo:path#Lx[-Ly]@commit7〕``; line numbers are lines of the
masked mirror text (identical to the source for text files; for Word/Visio
files they are lines of the extracted text).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from open_notebook.repo_kb.classify import APP_SQL, CODE, DDL, DIAGRAM, SOP, SPEC
from open_notebook.repo_kb.config import KBConfig
from open_notebook.repo_kb.parsers import (
    Spec,
    Table,
    java_calls,
    java_refs,
    parse_ddl,
    parse_spec,
    program_from_filename,
    sql_usage,
)
from open_notebook.repo_kb.store import Store

OP_ZH = {"R": "查詢", "C": "新增", "U": "修改", "D": "刪除"}


def cite(
    repo: str, path: str, line: int, commit: Optional[str], end: Optional[int] = None
) -> str:
    rng = f"L{line}" + (f"-L{end}" if end and end != line else "")
    return f"〔{repo}:{path}#{rng}@{(commit or 'HEAD')[:10]}〕"


def _read(store: Store, row) -> str:
    with open(store.abs(row["mirror"]), encoding="utf-8") as f:
        return f.read()


def _slug(name: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", name)


def _ops(s: Set[str]) -> str:
    return "".join(op for op in "RCUD" if op in s)


def _ops_zh(s: str) -> str:
    return "、".join(OP_ZH[o] for o in "RCUD" if o in s) or "（未勾選）"


class KB:
    """In-memory model built from the store (cheap to rebuild)."""

    def __init__(self, store: Store):
        self.store = store
        self.tables: Dict[str, Tuple[Table, Any]] = {}
        self.specs: List[Tuple[Spec, Any]] = []
        self.classes: Dict[str, Dict[str, Any]] = {}
        self.module_names: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        st = self.store
        for row in st.files(category=DDL):
            for tb in parse_ddl(_read(st, row), row["path"]):
                prev = self.tables.get(tb.name)
                if (
                    prev is None
                    or (not prev[0].columns and tb.columns)
                    or "/TableScript/" in row["path"]
                ):
                    self.tables[tb.name] = (tb, row)
        known = set(self.tables)
        # code: classes from Java files and their SQL resources
        for row in st.files(category=CODE):
            if not row["path"].endswith(".java") or not row["mirror"]:
                continue
            name = row["path"].rsplit("/", 1)[-1][:-5]
            src = _read(st, row)
            refs = java_refs(src, known)
            self.classes[name] = {
                "row": row,
                "module": row["module"],
                "usage": {t: {"?"} for t in refs},
                "lines": {t: (row, ln) for t, ln in refs.items()},
                "calls": java_calls(src, name),
            }
        for row in st.files(category=APP_SQL):
            if not row["mirror"] or row["repo"] == "av_doc":
                continue
            fname = row["path"].rsplit("/", 1)[-1]
            parts = fname.split(".")
            cls = None
            if fname.startswith("com.") and len(parts) >= 7:
                cls = parts[5]
            if not cls:
                continue
            sql = _read(st, row)
            c = self.classes.setdefault(
                cls,
                {
                    "row": None,
                    "module": row["module"],
                    "usage": {},
                    "lines": {},
                    "calls": set(),
                },
            )
            found = sql_usage(sql, known)
            hint = re.match(
                r"SQL_(INSERT|UPDATE|DELETE|QUERY|SELECT|GET|FIND|COUNT|DEL|UPD|INS)_([A-Z0-9_]+)",
                parts[6].upper(),
            )
            if hint:
                op = {
                    "INSERT": "C",
                    "INS": "C",
                    "UPDATE": "U",
                    "UPD": "U",
                    "DELETE": "D",
                    "DEL": "D",
                }.get(hint.group(1), "R")
                for t in known:
                    if hint.group(2) == t or hint.group(2).startswith(t + "_"):
                        found.setdefault(t, set()).add(op)
            lines = sql.split("\n")
            for t, ops in found.items():
                c["usage"].setdefault(t, set()).update(ops)
                c["usage"][t].discard("?")
                ln = next(
                    (i for i, line in enumerate(lines, 1) if t in line.upper()), 1
                )
                if (
                    ops & {"C", "U", "D"}
                    or t not in c["lines"]
                    or c["lines"][t][0]["path"].endswith(".java")
                ):
                    c["lines"][t] = (row, ln)
        for row in st.files(repo=None, category=SPEC):
            if row["mirror"]:
                self.specs.append((parse_spec(_read(st, row), row["path"]), row))
        for row in st.files():
            m = re.search(r"/AV影像系統/([A-Z][0-9A-Z])_([^/]+)/", row["path"])
            if m:
                self.module_names.setdefault(m.group(1), m.group(2).strip())

    def effective_usage(self, cls: str, depth: int = 2) -> Dict[str, Dict[str, Any]]:
        """Tables touched by ``cls`` directly or via called AV classes."""
        seen: Set[str] = set()
        out: Dict[str, Dict[str, Any]] = {}

        def visit(name: str, d: int, via: Optional[str]) -> None:
            if name in seen or name not in self.classes:
                return
            seen.add(name)
            c = self.classes[name]
            for t, ops in c["usage"].items():
                e = out.setdefault(
                    t, {"ops": set(), "via": set(), "cite": c["lines"].get(t)}
                )
                e["ops"].update(o for o in ops if o != "?")
                e["via"].add(via or name)
            if d > 0:
                for callee in c["calls"]:
                    visit(callee, d - 1, callee)

        visit(cls, depth, None)
        return out


# --------------------------------------------------------------------------
# spec ↔ code comparison
# --------------------------------------------------------------------------


def _base_prog(p: Optional[str]) -> str:
    return re.sub(r"_MOD$", "", p or "")


def compare(kb: KB) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for spec, row in kb.specs:
        fn_prog = program_from_filename(row["path"])
        c_spec = cite(
            row["repo"], row["path"], spec.program_line or 1, row["last_commit"]
        )
        if spec.program and fn_prog and _base_prog(fn_prog) != _base_prog(spec.program):
            items.append(
                {
                    "kind": "文件標示不一致",
                    "severity": "中",
                    "program": spec.program,
                    "detail": f"檔名標示為 `{fn_prog}`，但規格內「程式名稱」為 `{spec.program}`",
                    "evidence": [c_spec],
                    "module": row["module"],
                }
            )
        prog = spec.program or fn_prog
        if not prog or not spec.tables:
            continue
        candidates = [prog, prog + "_mod", prog.replace("AV_", "AV_", 1)]
        cls = next((c for c in candidates if c in kb.classes), None)
        if cls is None:
            items.append(
                {
                    "kind": "規格有、程式找不到",
                    "severity": "低（待確認）",
                    "program": prog,
                    "detail": f"規格描述的程式 `{prog}` 在已匯入的程式碼中找不到對應類別（可能已下線、改名，或位於不可存取的 usr 目錄，無法判定）",
                    "evidence": [c_spec],
                    "module": row["module"],
                }
            )
            continue
        usage = kb.effective_usage(
            cls
        )  # lenient: program + called AV classes (2 levels)
        direct = kb.effective_usage(cls, depth=0)  # strict: program + its own _mod
        if cls + "_mod" in kb.classes:
            for mt, mu in kb.effective_usage(cls + "_mod", depth=0).items():
                d = direct.setdefault(
                    mt, {"ops": set(), "via": set(), "cite": mu["cite"]}
                )
                d["ops"] |= mu["ops"]
                d["via"] |= mu["via"]
        spec_tables = {x.name: x for x in spec.tables}
        for t in spec.tables:
            if t.name not in kb.tables:
                continue  # not a table we know (file name, etc.)
            u: Optional[Dict[str, Any]] = usage.get(t.name)
            tc = cite(row["repo"], row["path"], t.line, row["last_commit"])
            if not u:
                items.append(
                    {
                        "kind": "規格列出、程式未存取",
                        "severity": "中",
                        "program": prog,
                        "detail": f"規格「相關檔案」列出 `{t.name}`（{t.desc}，{_ops_zh(t.crud)}），但 `{cls}` 及其呼叫的 AV 模組皆未存取此表",
                        "evidence": [tc, _code_cite(kb, cls)],
                        "module": row["module"],
                    }
                )
                continue
            du: Optional[Dict[str, Any]] = direct.get(t.name)
            extra = (du["ops"] if du else set()) - set(t.crud)
            if extra and du:
                u = du
                items.append(
                    {
                        "kind": "存取方式不一致",
                        "severity": "高" if extra & {"C", "U", "D"} else "低",
                        "program": prog,
                        "detail": f"`{t.name}`：規格勾選「{_ops_zh(t.crud)}」，程式實際有「{_ops_zh(''.join(sorted(extra)))}」（經由 {', '.join(sorted(u['via']))}）",
                        "evidence": [tc, _usage_cite(kb, u)],
                        "module": row["module"],
                    }
                )
        for tname, du2 in direct.items():
            if tname in spec_tables or tname not in kb.tables:
                continue
            if not (du2["ops"] & {"C", "U", "D"}):
                continue  # read-only extras are common (lookup tables); only flag writes
            items.append(
                {
                    "kind": "程式寫入、規格未列",
                    "severity": "高",
                    "program": prog,
                    "detail": f"`{cls}` 會{_ops_zh(_ops(du2['ops']))} `{tname}`（經由 {', '.join(sorted(du2['via']))}），但規格「相關檔案」未列出此表",
                    "evidence": [c_spec, _usage_cite(kb, du2)],
                    "module": row["module"],
                }
            )
    order = {"高": 0, "中": 1, "低": 2, "低（待確認）": 3}
    items.sort(
        key=lambda x: (
            order.get(x["severity"], 9),
            x["module"] or "",
            x["program"] or "",
        )
    )
    return items


def _code_cite(kb: KB, cls: str) -> str:
    row = kb.classes[cls]["row"]
    if row is None:
        return f"（`{cls}` 僅有 SQL 檔）"
    return cite(row["repo"], row["path"], 1, row["last_commit"])


def _usage_cite(kb: KB, u: Dict[str, Any]) -> str:
    if not u.get("cite"):
        return ""
    row, ln = u["cite"]
    return cite(row["repo"], row["path"], ln, row["last_commit"])


# --------------------------------------------------------------------------
# page writers
# --------------------------------------------------------------------------


class Writer:
    def __init__(self, root: str):
        self.root = root
        self.written: Dict[str, str] = {}

    def write(self, rel: str, content: str) -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.rstrip() + "\n")
        self.written[rel] = hashlib.sha1(content.encode()).hexdigest()


def _table_page(
    kb: KB,
    t: Table,
    row,
    users: List[Tuple[str, str, Any]],
    specs: List[Tuple[Spec, Any, str]],
) -> str:
    c0 = cite(row["repo"], row["path"], t.line, row["last_commit"])
    out = [
        "---",
        f"type: table\nname: {t.name}\nkind: {t.kind}\nschema: {t.schema}",
        f"source: {row['repo']}:{row['path']}\nlast_commit: {row['last_commit']}\nlast_date: {row['last_date']}",
        "---",
        f"# {t.name}" + (f"　{t.comment}" if t.comment else ""),
        "",
        f"- 類型：{'資料表' if t.kind == 'TABLE' else '檢視表'}（schema `{t.schema or '-'}`）",
        f"- 定義來源：{c0}",
        f"- 最後修改：{(row['last_date'] or '')[:10]}（commit `{(row['last_commit'] or '')[:7]}`）",
    ]
    if t.comment:
        out.append(
            f"- 表說明：{t.comment} {cite(row['repo'], row['path'], t.comment_line, row['last_commit'])}"
        )
    if t.pk:
        out.append(f"- 主鍵：{', '.join(t.pk)}")
    if t.columns:
        out += [
            "",
            "## 欄位",
            "",
            "| # | 欄位 | 型別 | 可為空 | 預設 | 說明 | 行 |",
            "|---|---|---|---|---|---|---|",
        ]
        for i, c in enumerate(t.columns, 1):
            out.append(
                f"| {i} | {c.name}{' 🔑' if c.name in t.pk else ''} | {c.type} | {'Y' if c.nullable else 'N'} | {c.default or ''} | {c.comment} | L{c.line} |"
            )
    if t.indexes:
        out += ["", "## 索引", ""]
        for name, uniq, cols in t.indexes:
            out.append(f"- `{name}`{'（唯一）' if uniq else ''}：{', '.join(cols)}")
    rel_lines = []
    for cols, ref, refcols in t.fks:
        rel_lines.append(
            f"- 外鍵 {', '.join(cols)} → [{ref}]({_slug(ref)}.md)（{', '.join(refcols)}）"
        )
    co: Dict[str, int] = defaultdict(int)
    for cls, ops, _ in users:
        for other in kb.effective_usage(cls, depth=0):
            if other != t.name and other in kb.tables:
                co[other] += 1
    for other, n in sorted(co.items(), key=lambda x: -x[1])[:12]:
        rel_lines.append(
            f"- 共同使用：[{other}]({_slug(other)}.md)（{n} 支程式同時存取）"
        )
    if t.pk:
        shared = []
        for other, (ot, _) in kb.tables.items():
            if (
                other != t.name
                and ot.pk
                and set(t.pk) <= {c.name for c in ot.columns}
                and len(t.pk) >= 1
                and set(t.pk) != {"BUSINESSNO"}
            ):
                shared.append(other)
        if 0 < len(shared) <= 15:
            rel_lines.append(
                "- 含本表主鍵欄位（推測關聯）："
                + "、".join(f"[{s}]({_slug(s)}.md)" for s in sorted(shared))
            )
    if rel_lines:
        out += [
            "",
            "## 關聯",
            "",
            "> 資料庫未定義外鍵時，關聯由「共同存取的程式」與「主鍵欄位重疊」推測，需人工確認。",
            "",
        ] + rel_lines
    if users:
        out += [
            "",
            "## 存取此表的程式",
            "",
            "| 程式 | 模組 | 存取 | 出處 |",
            "|---|---|---|---|",
        ]
        for cls, ops, c in sorted(users):
            mod = kb.classes[cls]["module"] or ""
            out.append(
                f"| {cls} | {f'[{mod}](../modules/{mod}.md)' if mod else ''} | {_ops_zh(ops) if ops else '引用'} | {c} |"
            )
    if specs:
        out += ["", "## 規格文件提及", ""]
        for s, srow, ops in specs:
            out.append(
                f"- {s.program or program_from_filename(srow['path']) or ''} {s.title}：{_ops_zh(ops)} {cite(srow['repo'], srow['path'], next((x.line for x in s.tables if x.name == t.name), 1), srow['last_commit'])}"
            )
    return "\n".join(out)


def _error_codes(text: str) -> Set[str]:
    codes = set(
        re.findall(
            r"\b(?:SQLCODE\s*[=:]?\s*-?\d{3,5}|SQL\d{4,5}[A-Z]?|[A-Z]{2,5}-\d{3,6}|ERR[_-]?\d{2,6}|E\d{4}|ORA-\d{5}|HTTP\s?[45]\d\d)\b",
            text,
        )
    )
    codes |= {m for m in re.findall(r"\b([A-Za-z]+(?:Exception|Error))\b", text)}
    return codes


def build_wiki(store: Store, cfg: KBConfig) -> Dict[str, Any]:
    kb = KB(store)
    root = store.abs("wiki")
    before = _hash_tree(root)
    w = Writer(root)

    # --- usage indexes ---
    table_users: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for cls in kb.classes:
        for t, u in kb.effective_usage(cls, depth=0).items():
            row_ln = kb.classes[cls]["lines"].get(t)
            c = (
                cite(
                    row_ln[0]["repo"],
                    row_ln[0]["path"],
                    row_ln[1],
                    row_ln[0]["last_commit"],
                )
                if row_ln
                else ""
            )
            table_users[t].append((cls, _ops(u["ops"]), c))
    table_specs: Dict[str, List[Tuple[Spec, Any, str]]] = defaultdict(list)
    for s, row in kb.specs:
        for stt in s.tables:
            table_specs[stt.name].append((s, row, stt.crud))

    # --- tables ---
    for name, (tbl, row) in kb.tables.items():
        w.write(
            f"tables/{_slug(name)}.md",
            _table_page(
                kb, tbl, row, table_users.get(name, []), table_specs.get(name, [])
            ),
        )
    tindex = [
        "# 資料表索引",
        "",
        f"共 {len(kb.tables)} 張表／檢視表（來源：`av_src` DDL）。",
        "",
        "| 表 | 說明 | 欄位數 | 存取程式數 |",
        "|---|---|---|---|",
    ]
    for name in sorted(kb.tables):
        tbl, _ = kb.tables[name]
        tindex.append(
            f"| [{name}]({_slug(name)}.md) | {tbl.comment} | {len(tbl.columns)} | {len(table_users.get(name, []))} |"
        )
    w.write("tables/index.md", "\n".join(tindex))

    # --- discrepancies ---
    disc = compare(kb)
    store.db.execute("DROP TABLE IF EXISTS discrepancy")
    store.db.execute(
        "CREATE TABLE discrepancy (kind TEXT, severity TEXT, module TEXT, program TEXT, detail TEXT, evidence TEXT)"
    )
    for d in disc:
        store.db.execute(
            "INSERT INTO discrepancy VALUES (?,?,?,?,?,?)",
            (
                d["kind"],
                d["severity"],
                d["module"],
                d["program"],
                d["detail"],
                json.dumps(d["evidence"], ensure_ascii=False),
            ),
        )
    by_kind: Dict[str, int] = defaultdict(int)
    for d in disc:
        by_kind[d["kind"]] += 1
    dl = (
        [
            "# Spec 與程式不一致：待確認清單",
            "",
            "由規格書「相關檔案」（查詢／新增／修改／刪除勾選）與程式實際 SQL 比對產生；程式端包含該程式直接與間接（兩層內）呼叫的 AV 模組。",
            "結果是**待確認的疑點**，不是定論：程式可能透過共用元件、動態 SQL 或 usr 目錄（不可存取）中的程式存取資料表。",
            "",
            "| 類型 | 筆數 |",
            "|---|---|",
        ]
        + [f"| {k} | {v} |" for k, v in sorted(by_kind.items(), key=lambda x: -x[1])]
        + [""]
    )
    for d in disc:
        mod = d["module"] or "-"
        dl.append(
            f"- **[{d['severity']}] {d['kind']}**｜{mod}｜`{d['program']}`：{d['detail']}  "
        )
        dl.append("  證據：" + " ".join(e for e in d["evidence"] if e))
    w.write("discrepancies.md", "\n".join(dl))

    # --- SOP ---
    sop_rows = store.files(category=SOP)
    sl = [
        "# 排查 SOP 與維運手冊",
        "",
        "SOP 原文**不改寫**：完整內容保存在原文層（`mirror/`），以關鍵字搜尋（含錯誤碼、log 訊息、中文片語）查找，回答時直接引用原文步驟。",
        "",
        "| 文件 | 最後修改 | 錯誤碼／例外關鍵字 |",
        "|---|---|---|",
    ]
    code_index: Dict[str, List[str]] = defaultdict(list)
    for r in sop_rows:
        if not r["mirror"]:
            sl.append(
                f"| {r['path'].rsplit('/', 1)[-1]}（{r['method']}，未轉文字） | {(r['last_date'] or '')[:10]} | |"
            )
            continue
        codes = sorted(_error_codes(_read(store, r)))[:8]
        for c in codes:
            code_index[c].append(r["path"])
        sl.append(
            f"| [{r['path'].rsplit('/', 1)[-1]}](../{r['mirror']}) | {(r['last_date'] or '')[:10]} | {', '.join(codes)} |"
        )
    w.write("sop/index.md", "\n".join(sl))

    # --- diagrams & modules ---
    diagrams = store.files(category=DIAGRAM)
    modules: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"specs": [], "classes": [], "diagrams": [], "sops": []}
    )
    for s, row in kb.specs:
        modules[row["module"] or "其他"]["specs"].append((s, row))
    for cls, cinfo in kb.classes.items():
        if cinfo["module"]:
            modules[cinfo["module"]]["classes"].append(cls)
    for dg in diagrams:
        mm = dg["module"] or re.search(r"AV([A-Z][0-9])", dg["path"].rsplit("/", 1)[-1])
        key = mm if isinstance(mm, str) else (mm.group(1) if mm else None)
        if key:
            modules[key]["diagrams"].append(dg)
    for r in sop_rows:
        for code in re.findall(r"AV([A-Z][0-9])", r["path"].rsplit("/", 1)[-1]):
            modules[code]["sops"].append(r)
    disc_by_mod: Dict[str, int] = defaultdict(int)
    for d in disc:
        disc_by_mod[d["module"] or "其他"] += 1
    rules_dir = os.path.join(root, "rules")
    for code, m in sorted(modules.items()):
        name = kb.module_names.get(code, "")
        tables_used: Dict[str, Set[str]] = defaultdict(set)
        for cls in m["classes"]:
            for t, u in kb.effective_usage(cls, depth=0).items():
                tables_used[t].update(u["ops"])
        L = [
            "---",
            f"type: module\ncode: {code}\nname: {name}",
            "---",
            f"# 模組 {code}　{name}",
            "",
            f"- 系統：[AV 影像系統](../systems/AV.md)",
            f"- 規格文件 {len(m['specs'])} 份、程式類別 {len(m['classes'])} 支、存取資料表 {len(tables_used)} 張、流程圖 {len(m['diagrams'])} 份",
        ]
        if os.path.exists(os.path.join(rules_dir, f"{code}.md")):
            L.append(f"- 業務規則頁：[rules/{code}.md](../rules/{code}.md)")
        if disc_by_mod.get(code):
            L.append(
                f"- Spec 與程式不一致疑點：{disc_by_mod[code]} 筆（見 [discrepancies.md](../discrepancies.md)）"
            )
        if m["specs"]:
            L += [
                "",
                "## 程式規格",
                "",
                "| 程式 | 功能 | 方式 | 概要 | 出處 |",
                "|---|---|---|---|---|",
            ]
            for s, row in sorted(m["specs"], key=lambda x: x[1]["path"]):
                prog = (
                    s.program
                    or program_from_filename(row["path"])
                    or row["path"].rsplit("/", 1)[-1]
                )
                summ = (s.summary[:120] + "…") if len(s.summary) > 120 else s.summary
                L.append(
                    f"| {prog} | {s.title} | {s.mode} | {summ.replace('|', '／')} | {cite(row['repo'], row['path'], s.summary_line or s.program_line or 1, row['last_commit'])} |"
                )
        if m["classes"]:
            L += ["", "## 程式類別", ""]
            for cls in sorted(m["classes"]):
                r = kb.classes[cls]["row"]
                L.append(
                    f"- `{cls}`"
                    + (
                        f" {cite(r['repo'], r['path'], 1, r['last_commit'])}"
                        if r
                        else "（SQL）"
                    )
                )
        if tables_used:
            L += ["", "## 存取的資料表", ""]
            for t in sorted(tables_used):
                desc = kb.tables[t][0].comment if t in kb.tables else ""
                L.append(
                    f"- [{t}](../tables/{_slug(t)}.md) {desc}：{_ops_zh(_ops(tables_used[t]))}"
                )
        if m["diagrams"]:
            L += ["", "## 架構／流程圖", ""]
            for d in m["diagrams"]:
                L.append(
                    f"- {d['path'].rsplit('/', 1)[-1]}"
                    + (
                        f"（文字：[{d['mirror']}](../{d['mirror']})）"
                        if d["mirror"]
                        else f"（{d['method']}，僅存檔名）"
                    )
                )
        if m["sops"]:
            L += ["", "## 相關 SOP", ""] + [
                f"- {r['path'].rsplit('/', 1)[-1]}" for r in m["sops"]
            ]
        w.write(f"modules/{code}.md", "\n".join(L))

    # --- system page ---
    S = [
        "---\ntype: system\ncode: AV\nname: AV 影像系統\n---",
        "# AV 影像系統",
        "",
        "## 模組",
        "",
        "| 模組 | 名稱 | 規格 | 程式 | 不一致疑點 |",
        "|---|---|---|---|---|",
    ]
    for code, m in sorted(modules.items()):
        S.append(
            f"| [{code}](../modules/{code}.md) | {kb.module_names.get(code, '')} | {len(m['specs'])} | {len(m['classes'])} | {disc_by_mod.get(code, 0)} |"
        )
    S += [
        "",
        "## 架構圖、系統關係圖、業務／作業流程圖",
        "",
        "| 圖 | 分類 | 可讀文字 |",
        "|---|---|---|",
    ]
    for dg in diagrams:
        folder = re.search(r"/_docs/(0\d_[^/]+)/", dg["path"])
        S.append(
            f"| {dg['path'].rsplit('/', 1)[-1]} | {folder.group(1) if folder else ''} | "
            + (
                f"[文字]({'../' + dg['mirror']})"
                if dg["mirror"]
                else f"否（{dg['method']}）"
            )
            + " |"
        )
    w.write("systems/AV.md", "\n".join(S))

    # --- index ---
    counts = {
        r[0]: r[1]
        for r in store.db.execute(
            "SELECT category, COUNT(*) FROM file GROUP BY category"
        )
    }
    repos = list(store.db.execute("SELECT name, commit_sha, imported_at FROM repo"))
    idx = (
        [
            "# CaBook 維運知識庫：AV 影像系統",
            "",
            "## 怎麼用（給人與 agent）",
            "",
            "1. 先看本頁與 [系統頁](systems/AV.md) 找到模組；模組頁連到規格、程式、資料表、流程圖與 SOP。",
            "2. 資料表問題看 [tables/](tables/index.md)；業務規則看 `rules/`；排查問題看 [sop/](sop/index.md)。",
            "3. 需要證據時，依引文 `〔repo:路徑#L行@commit〕` 開啟 `mirror/<repo>/<路徑>`（Word／Visio 檔為 `<路徑>.txt`）核對原文。",
            "4. Spec 與程式不一致的疑點見 [discrepancies.md](discrepancies.md)。",
            "",
            "## 來源",
            "",
            "| repo | commit | 匯入時間 |",
            "|---|---|---|",
        ]
        + [
            f"| {r['name']} | `{r['commit_sha'][:10]}` | {r['imported_at']} |"
            for r in repos
        ]
        + [
            "",
            "## 分層統計",
            "",
            "| 類別 | 檔案數 |",
            "|---|---|",
        ]
        + [f"| {k} | {v} |" for k, v in sorted(counts.items())]
        + [
            "",
            f"資料表頁 {len(kb.tables)}；模組頁 {len(modules)}；規格 {len(kb.specs)} 份；程式類別 {len(kb.classes)}；不一致疑點 {len(disc)} 筆。",
            "",
            "> 硬性規則：程式 repo 中名為 `usr` 的目錄不讀取、不索引、不送進 AI，本知識庫不含其內容。",
        ]
    )
    w.write("index.md", "\n".join(idx))
    with open(store.abs("manifest.tsv"), "w", encoding="utf-8") as f:
        f.write("repo\tpath\tmirror\tcategory\tlast_commit\tlast_date\n")
        for r in store.files():
            f.write(
                f"{r['repo']}\t{r['path']}\t{r['mirror'] or ''}\t{r['category']}\t{(r['last_commit'] or '')[:10]}\t{(r['last_date'] or '')[:10]}\n"
            )
    after = _hash_tree(root)
    changed = sorted(p for p in after if before.get(p) != after[p])
    store.event("build", "*", {"pages": len(after), "changed": len(changed)})
    store.db.commit()
    return {
        "pages": len(after),
        "changed_pages": changed
        if len(changed) <= 40
        else changed[:40] + [f"... +{len(changed) - 40}"],
        "tables": len(kb.tables),
        "specs": len(kb.specs),
        "classes": len(kb.classes),
        "discrepancies": len(disc),
        "discrepancies_by_kind": dict(by_kind),
    }


def _hash_tree(root: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isdir(root):
        return out
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.sha1(f.read()).hexdigest()
    return out
