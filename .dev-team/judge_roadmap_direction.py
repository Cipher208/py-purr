"""Судья целостности переноса серверного направления роадмапа PURR.

Чистый Python: только re, sys, pathlib. Ни pytest, ни ruff, ни subprocess,
ни абсолютных путей машины -- документы ищутся от Path(__file__), поэтому
команда исполняется и в свежем клоне.
Команда прогона: `uv run python .dev-team/judge_roadmap_direction.py`.

Пять детерминированных проверок ровно по критерию приёмки карточки:
  1. дословное решение владельца «Берем за основу концепцию А, сервер
     возможно потом» и дата 2026-11-04 в шапках ОБОИХ документов;
  2. шапка активного документа: поля Status и Vision, принятая формулировка
     встроенной библиотеки, формулировка без сервера/без инфраструктуры,
     запрещённая строка «full redis-like database engine» отсутствует;
  3. FUTURE_PLAN_SERVER.md существует, >=150 строк, шапка с решением, датой
     и пометкой отложенности; все 19 фрагментов MOVED_FRAGMENTS найдены
     ЦЕЛЫМИ строками (strip-совпадение) вне HTML-комментариев;
  4. раздел «Активный план» непустой (>=3 строк / 120 символов) и ссылается
     на разделы ядра 3.11/3.12/3.16/3.21/3.36/3.37;
  5. активный >=100 строк и Roadmap/Milestones/Open Questions с телами;
     вынесенный >=2000 символов.

Чего этот судья НЕ проверяет (решение владельца «вариант А», 2026-11-04):
парафразы и переформулировки, Unicode-гомоглифы, новые серверные обещания,
семантику строк-указателей, отсутствие серверных обещаний в активном
документе, намерения автора вообще. Он сторож целостности переноса, а не
детектор намерений: проверяется только то, что можно сосчитать и сравнить
дословно. Требовать от него ловить парафразы запрещено решением владельца.

Вывод детерминирован: нет времени, сети, версии окружения. Каждая проверка
печатает PASS/FAIL с названной причиной, итог -- «провалено N из 5»,
exit=0 при N=0, exit=1 при N>0.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "FUTURE_PLAN.md"
SERVER = ROOT / "FUTURE_PLAN_SERVER.md"

DECISION_FORMS = (
    "Берем за основу концепцию А, сервер возможно потом",
)
DECISION_DATES = (
    "2026-11-04",
)
EMBEDDED_FORMS = (
    "встроенная библиотека",
    "встроенной библиотек",
    "embedded library",
    "embedded sqlite library",
    "in-process library",
    "библиотека в одном процессе",
)
NO_INFRA_FORMS = (
    "без сервера",
    "без инфраструктуры",
    "без сетевого доступа",
    "без демонов",
    "no server",
    "no infrastructure",
    "zero-infrastructure",
    "no daemons",
    "в одном процессе",
    "in-process",
)
HEADER_FORBIDDEN_FORMS = (
    "full redis-like database engine",
    "redis-like database engine",
    "full redis compatibility",
    "redis-compatible server",
    "a redis-like server",
    "полная совместимость с redis как ближайшая цель",
)
ACTIVE_HEADINGS = (
    r"^##\s+(?:\d+\.\s*)?.*(?:активный план|active plan|план концепции а|план под концепцию а)",
    r"^###\s+.*(?:активный план|active plan)",
)
CORE_REFS = ("3.11", "3.12", "3.16", "3.21", "3.36", "3.37")
REQUIRED_SECTIONS = (
    ("Roadmap", r"\bRoadmap\b"),
    ("Milestones", r"\bMilestones\b"),
    ("Open Questions", r"\bOpen\s+Questions\b"),
)

# Дословные строки, перенесённые из FUTURE_PLAN.md в FUTURE_PLAN_SERVER.md.
# Каждая -- целая строка обоих документов; проверяется strip-совпадением.
MOVED_FRAGMENTS = (
    "### Phase 3: Networking",
    "Add the server side for remote access.",
    "| **TCP Server** | Redis-compatible protocol | P1 |",
    "| **Redis Protocol** | RESP (Redis Serialization Protocol) | P1 |",
    "#### TCP Server",
    "# purr/server.py",
    "class PurrServer:",
    '"""Start TCP server."""',
    "server = await asyncio.start_server(",
    "await server.serve_forever()",
    '"""Handle client connection (RESP protocol)."""',
    "#### HTTP API",
    "from aiohttp import web",
    "| **Cluster** | Multi-node replication | P2 |",
    "purr serve --port 6379          # Redis-compatible protocol (RESP)",
    "### 3.6 Replication (WAL Log Shipping)",
    "The master ships WAL logs; the replicas apply the diffs.",
    "class ShardedStore:",
    "| **v1.0.0** | Full Redis compatibility | 3 months |",
)

MIN_PLAN_LINES = 3
MIN_PLAN_CHARS = 120
MIN_DOC_LINES = 100
MIN_SERVER_LINES = 150
MIN_SERVER_CHARS = 2000
MIN_SECTION_BODY_LINES = 2


def load(path: Path) -> tuple[str, str]:
    """(текст, заметка). Исключений наружу нет: нет файла -- провал проверки."""
    if not path.is_file():
        return "", f"{path.name}: файл отсутствует"
    data = path.read_bytes()
    if not data.strip():
        return "", f"{path.name}: файл пуст"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "", f"{path.name}: не читается как utf-8"
    return text.replace("\r\n", "\n"), (
        f"{path.name}: прочитано {len(data)} байт, {len(text.splitlines())} строк"
    )


def any_of(text: str, forms: tuple[str, ...]) -> str | None:
    """Первая принятая формулировка в тексте, без регистра."""
    low = text.lower()
    for form in forms:
        if form.lower() in low:
            return form
    return None


def header(lines: list[str]) -> list[str]:
    """Шапка: всё до первого заголовка уровня `##`."""
    out: list[str] = []
    for line in lines:
        if re.match(r"^##\s", line):
            break
        out.append(line)
    return out


def section_body(lines: list[str], pattern: str) -> tuple[int, list[str]] | None:
    """(номер заголовка `##`, тело до следующего `##`) либо None."""
    for i, line in enumerate(lines):
        match = re.match(r"^##\s+(.*)$", line)
        if match and re.search(pattern, match.group(1), re.I):
            j = i + 1
            while j < len(lines) and not re.match(r"^##\s", lines[j]):
                j += 1
            return i + 1, lines[i + 1 : j]
    return None


def content(body: list[str]) -> list[str]:
    return [ln.strip() for ln in body if ln.strip() and not ln.lstrip().startswith("#")]


def visible_lines(text: str) -> set[str]:
    """Целые strip-строки документа вне HTML-комментариев."""
    without_comments = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return {ln.strip() for ln in without_comments.splitlines() if ln.strip()}


def check_decision(active: list[str], server: list[str]) -> tuple[bool, str]:
    what = "дословное решение владельца с датой 2026-11-04 в шапках обоих документов"
    for label, lines in (("активного", active), ("вынесенного", server)):
        hdr = "\n".join(header(lines))
        if not hdr.strip():
            return False, (
                f"assert «{what}» -- нарушено: шапка {label} документа пуста "
                "(документ отсутствует или обрезан)"
            )
        decision = any_of(hdr, DECISION_FORMS)
        if decision is None:
            return False, (
                f"assert «{what}» -- нарушено: в шапке {label} документа "
                f"нет фразы {DECISION_FORMS[0]!r}"
            )
        date = any_of(hdr, DECISION_DATES)
        if date is None:
            return False, (
                f"assert «{what}» -- нарушено: в шапке {label} документа "
                f"есть решение, но нет даты {DECISION_DATES[0]!r}"
            )
    return True, "решение и дата 2026-11-04 в шапках активного и вынесенного документов"


def check_header(active: list[str]) -> tuple[bool, str]:
    what = "шапка Status/Vision фиксирует встроенную библиотеку без инфраструктуры"
    hdr = "\n".join(header(active))
    if not hdr.strip():
        return False, f"assert «{what}» -- нарушено: шапки нет (документ пуст или обрезан)"
    if not re.search(r"(?im)^[>\s]*\**status\**\s*:", hdr):
        return False, f"assert «{what}» -- нарушено: в шапке нет поля Status"
    if not re.search(r"(?im)^[>\s]*\**vision\**\s*:", hdr):
        return False, f"assert «{what}» -- нарушено: в шапке нет поля Vision"
    bad = any_of(hdr, HEADER_FORBIDDEN_FORMS)
    if bad is not None:
        return False, f"assert «{what}» -- нарушено: шапка обещает {bad!r} как ближайшую цель"
    embedded = any_of(hdr, EMBEDDED_FORMS)
    infra = any_of(hdr, NO_INFRA_FORMS)
    if embedded is None or infra is None:
        gaps = []
        if embedded is None:
            gaps.append("нет принятой формулировки встроенной библиотеки")
        if infra is None:
            gaps.append("нет принятой формулировки без сервера/без инфраструктуры")
        return False, f"assert «{what}» -- нарушено: " + "; ".join(gaps)
    return True, f"Status/Vision: «{embedded}» + «{infra}», запрещённой строки нет"


def check_server(lines: list[str], text: str) -> tuple[bool, str]:
    what = (
        "вынесенный документ >=150 строк, шапка с решением/датой/пометкой, "
        "19 фрагментов целыми строками вне HTML-комментариев"
    )
    if not text.strip():
        return False, (
            f"assert «{what}» -- нарушено: FUTURE_PLAN_SERVER.md отсутствует или пуст"
        )
    if len(lines) < MIN_SERVER_LINES:
        return False, (
            f"assert «{what}» -- нарушено: {len(lines)} строк < {MIN_SERVER_LINES}, "
            "вынесенный документ обрезан"
        )
    hdr = "\n".join(header(lines))
    if any_of(hdr, DECISION_FORMS) is None:
        return False, (
            f"assert «{what}» -- нарушено: в шапке вынесенного документа "
            f"нет решения {DECISION_FORMS[0]!r}"
        )
    if any_of(hdr, DECISION_DATES) is None:
        return False, (
            f"assert «{what}» -- нарушено: в шапке вынесенного документа нет даты 2026-11-04"
        )
    if "отложено" not in hdr.lower() and "deferred" not in hdr.lower():
        return False, (
            f"assert «{what}» -- нарушено: в шапке вынесенного документа "
            "нет пометки отложенности"
        )
    visible = visible_lines(text)
    missing = [frag for frag in MOVED_FRAGMENTS if frag.strip() not in visible]
    if missing:
        detail = [
            f"assert «{what}» -- нарушено: не найдено фрагментов "
            f"{len(missing)} из {len(MOVED_FRAGMENTS)}, все поименно:"
        ]
        detail += [f"    - {frag!r}" for frag in missing]
        return False, "\n".join(detail)
    return True, (
        f"{len(lines)} строк, шапка с решением/датой/пометкой, "
        f"все {len(MOVED_FRAGMENTS)} фрагментов целыми строками вне комментариев"
    )


def check_active_plan(lines: list[str]) -> tuple[bool, str]:
    what = "непустой активный план концепции А со ссылками на 6 разделов ядра"
    idx = None
    for i, line in enumerate(lines):
        if any(re.search(pattern, line, re.I) for pattern in ACTIVE_HEADINGS):
            idx = i
            break
    if idx is None:
        return False, (
            f"assert «{what}» -- нарушено: раздел активного плана не найден "
            "(принятые заголовки: «Активный план» / «Active Plan»)"
        )
    j = idx + 1
    while j < len(lines) and not re.match(r"^##\s", lines[j]):
        j += 1
    body = content(lines[idx + 1 : j])
    body_text = "\n".join(body)
    if len(body) < MIN_PLAN_LINES or len(body_text) < MIN_PLAN_CHARS:
        return False, (
            f"assert «{what}» -- нарушено: активный план пуст или обрезан: "
            f"{len(body)} строк, {len(body_text)} символов "
            f"(нужно >= {MIN_PLAN_LINES} строк / {MIN_PLAN_CHARS} символов)"
        )
    no_refs = [ref for ref in CORE_REFS if ref not in body_text]
    if no_refs:
        return False, (
            f"assert «{what}» -- нарушено: нет ссылок на разделы ядра: {', '.join(no_refs)}"
        )
    return True, (
        f"{len(body)} строк, {len(body_text)} символов, ссылки на все 6 разделов ядра"
    )


def check_completeness(
    active_lines: list[str], active_text: str, server_text: str
) -> tuple[bool, str]:
    what = (
        "активный >=100 строк с Roadmap/Milestones/Open Questions, "
        "вынесенный >=2000 символов"
    )
    if not active_text.strip():
        return False, f"assert «{what}» -- нарушено: активный документ пуст или отсутствует"
    if len(active_lines) < MIN_DOC_LINES:
        return False, (
            f"assert «{what}» -- нарушено: активный документ обрезан: "
            f"{len(active_lines)} строк < {MIN_DOC_LINES}"
        )
    for name, pattern in REQUIRED_SECTIONS:
        found = section_body(active_lines, pattern)
        if found is None:
            return False, f"assert «{what}» -- нарушено: нет раздела {name}"
        _, body = found
        if len(content(body)) < MIN_SECTION_BODY_LINES:
            return False, (
                f"assert «{what}» -- нарушено: раздел {name} без содержимого "
                f"({len(content(body))} строк)"
            )
    if len(server_text) < MIN_SERVER_CHARS:
        return False, (
            f"assert «{what}» -- нарушено: вынесенный документ обрезан: "
            f"{len(server_text)} символов < {MIN_SERVER_CHARS}"
        )
    return True, (
        f"{len(active_lines)} строк активного, Roadmap/Milestones/Open Questions с телом, "
        f"{len(server_text)} символов вынесенного"
    )


def main() -> int:
    active_text, note_active = load(ACTIVE)
    server_text, note_server = load(SERVER)
    active_lines = active_text.splitlines()
    server_lines = server_text.splitlines()
    print(note_active)
    print(note_server)
    results = (
        ("решение владельца в обеих шапках", check_decision(active_lines, server_lines)),
        ("шапка активного документа", check_header(active_lines)),
        ("вынесенный документ и 19 фрагментов", check_server(server_lines, server_text)),
        ("активный план концепции А", check_active_plan(active_lines)),
        (
            "полнота обоих документов",
            check_completeness(active_lines, active_text, server_text),
        ),
    )
    failed = 0
    for number, (name, (ok, detail)) in enumerate(results, 1):
        print(f"{'PASS' if ok else 'FAIL'}  {number} {name}: {detail}")
        if not ok:
            failed += 1
    print(f"провалено {failed} из 5")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
