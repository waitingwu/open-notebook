"""Pure deterministic wiki rendering from masked, authorised database content."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from open_notebook.repo_kb.classify import DIAGRAM, SOP
from open_notebook.repo_kb.wiki import (
    KB,
    _error_codes,
    _ops,
    _slug,
    _table_page,
    cite,
    compare,
)


@dataclass
class Page:
    slug: str
    kind: str
    title: str
    summary: str
    body: str
    module: str | None = None


class FileView:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def files(
        self, repo: str | None = None, category: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            r
            for r in self.rows
            if (repo is None or r["repo"] == repo)
            and (category is None or r["category"] == category)
        ]


def render(
    name: str, files: list[dict[str, Any]], texts: dict[str, str]
) -> tuple[list[Page], list[dict[str, Any]]]:
    view = FileView(files)
    model = KB(view, lambda row: texts[str(row["id"])])
    pages: list[Page] = []
    users: dict[str, list[Any]] = defaultdict(list)
    specs: dict[str, list[Any]] = defaultdict(list)
    for cls in model.classes:
        for used_table, usage in model.effective_usage(cls, depth=0).items():
            ref = usage.get("cite")
            reference = (
                cite(ref[0]["repo"], ref[0]["path"], ref[1], ref[0]["last_commit"])
                if ref
                else ""
            )
            users[used_table].append((cls, _ops(usage["ops"]), reference))
    for spec, row in model.specs:
        for spec_table in spec.tables:
            specs[spec_table.name].append((spec, row, spec_table.crud))
    for table_name, (table, row) in sorted(model.tables.items()):
        pages.append(
            Page(
                f"tables/{_slug(table_name)}",
                "table",
                table_name,
                table.comment or f"{table_name}：欄位、主鍵、索引及存取程式。",
                _table_page(model, table, row, users[table_name], specs[table_name]),
            )
        )
    table_index = ["# 資料表索引", "", "| 資料表 | 說明 |", "|---|---|"]
    table_index += [
        f"| [{p.title}]({p.slug.split('/')[-1]}.md) | {p.summary} |"
        for p in pages
        if p.kind == "table"
    ]
    pages.append(
        Page(
            "tables/index",
            "index",
            "資料表索引",
            f"共 {len(model.tables)} 張資料表與檢視表。",
            "\n".join(table_index),
        )
    )
    modules = sorted({r["module"] for r in files if r.get("module")})
    system_slug = "systems/AV" if modules else "systems/main"
    for module in modules:
        members = [r for r in files if r.get("module") == module]
        title = f"模組 {module} {model.module_names.get(module, '')}".strip()
        lines = [
            f"# {title}",
            "",
            f"系統：[{name}](../{system_slug}.md)",
            "",
            "## 程式規格",
        ]
        for spec, row in model.specs:
            if row.get("module") == module:
                lines.append(
                    f"- {spec.program or ''} {spec.title}：{spec.summary[:240]} {cite(row['repo'], row['path'], spec.summary_line or spec.program_line or 1, row['last_commit'])}"
                )
        lines += ["", "## 程式、SQL、圖檔與其他來源"]
        for row in members:
            suffix = (
                cite(row["repo"], row["path"], 1, row["last_commit"])
                if row["lines"]
                else f"（{row['method']}；僅檔名，沒有文字證據）"
            )
            lines.append(f"- {row['path'].rsplit('/', 1)[-1]} {suffix}")
        tables = sorted(
            {
                table
                for cls, info in model.classes.items()
                if info.get("module") == module
                for table in model.effective_usage(cls, depth=0)
            }
        )
        lines += ["", "## 資料表"] + [
            f"- [{table}](../tables/{_slug(table)}.md)"
            for table in tables
            if table in model.tables
        ]
        pages.append(
            Page(
                f"modules/{module}",
                "module",
                title,
                f"{len(members)} 份來源；{len(tables)} 張相關資料表。",
                "\n".join(lines),
                module,
            )
        )
    sop = ["# SOP 與維運手冊", "", "以下為來源索引；處理步驟應回查原文。"]
    for row in view.files(category=SOP):
        codes = ", ".join(sorted(_error_codes(texts[str(row["id"])]))[:8])
        reference = (
            cite(row["repo"], row["path"], 1, row["last_commit"])
            if row["lines"]
            else "（沒有可讀文字）"
        )
        sop.append(f"- {row['path'].rsplit('/', 1)[-1]} {codes} {reference}")
    pages.append(
        Page(
            "sop/index",
            "sop_index",
            "SOP 與維運手冊",
            "操作、排查文件與錯誤碼索引；原文不改寫。",
            "\n".join(sop),
        )
    )
    differences = compare(model)
    lines = [
        "# 規格與程式不一致",
        "",
        "以下為啟發式比對的待確認事項；動態 SQL、共用元件及被排除的來源可能造成誤判。",
    ]
    for item in differences:
        lines.append(
            f"- {item['program']}：{item['detail']} {' '.join(item['evidence'])}"
        )
    pages.append(
        Page(
            "discrepancies",
            "discrepancies",
            "規格與程式不一致",
            f"{len(differences)} 個待確認事項。",
            "\n".join(lines),
        )
    )
    system = [f"# {name}", "", "## 模組"] + [
        f"- [{module}](../modules/{module}.md)" for module in modules
    ]
    system += ["", "## 架構與流程圖"]
    for row in view.files(category=DIAGRAM):
        system.append(
            f"- {row['path'].rsplit('/', 1)[-1]} "
            + (
                cite(row["repo"], row["path"], 1, row["last_commit"])
                if row["lines"]
                else "（僅檔名，無法由此推定流程方向或分支）"
            )
        )
    pages.append(
        Page(
            system_slug,
            "system",
            name,
            f"{len(modules)} 個模組、{len(files)} 份來源的系統導覽。",
            "\n".join(system),
        )
    )
    return pages, differences
