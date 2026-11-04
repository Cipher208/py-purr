"""Судья направления FUTURE_PLAN.md: документ обязан говорить про концепцию А.

Чистый Python: только re, sys, pathlib. Ни pytest, ни ruff, ни subprocess --
`pytest>=7.0` в pyproject.toml не запинён, а линтер текстовому судье не нужен.
Команда прогона: `uv run python .dev-team/judge_roadmap_direction.py`.

Пять проверок ровно по критерию приёмки карточки:
  1. дословное решение владельца с датой 2026-11-04;
  2. шапка Status/Vision не обещает «full Redis-like database engine» как
     ближайшую цель и фиксирует встроенную библиотеку без инфраструктуры;
  3. семь серверных мест ПОИМЕННО помечены отложенными;
  4. непустой активный план под концепцию А, ссылающийся на 3.11/3.12/
     3.16/3.21/3.36/3.37, и не обещающий сервер следующим шагом;
  5. документ непустой и содержит Roadmap, Milestones, Open Questions.

Семь мест проверки 3 -- сверено с FUTURE_PLAN.md на HEAD 198be7d:
  1. `### Phase 3: Networking` (строка 193, раздел 2) -- заголовок фазы;
  2. таблица приоритетов раздела 2: строки `**TCP Server**` (199, P1) и
     `**Redis Protocol**` (202, P1) -- приоритеты TCP/RESP. В таблицах
     Phase 4 (270-277) и Phase 5 (313-320) строк TCP/RESP НЕТ: там
     Cluster/TLS/Auth/Docker/Client Library. Отдельной таблицы
     «Phase 4/5 приоритеты TCP/RESP» в файле нет и она не выдумана: это место
     -- реальная таблица `Phase 3: Networking`. Проверяется отдельно от
     заголовка, потому что пометка на заголовке не покрывает строки P1;
  3. `### 3.6 Replication (WAL Log Shipping)` (строка 505);
  4. `### 3.7 Sharding (hash-based partitioning)` (строка 529);
  5. `### 3.23 REST API Spec` (строка 926);
  6. `## 7. Milestones` -- три строки v0.4.0 (1618), v0.7.0 (1621), v1.0.0 (1622);
  7. `## 8. Open Questions` -- пункты 1 RESP (1628), 3 Cluster (1630), 4 Auth (1631).

«Отложено», «встроенная библиотека» и «активный план» заданы списками
принятых формулировок, а не одной случайной подстрокой: пустой текст не
проходит ни одну из проверок. Вывод детерминирован: нет времени, сети,
абсолютных путей машины и версии окружения.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "FUTURE_PLAN.md"

# ---------------------------------------------------------------------------
# Списки принятых формулировок. Это и есть смысл проверок: что считается
# пометкой «отложено», что -- встроенной библиотекой, что -- активным планом.
# ---------------------------------------------------------------------------

DECISION_FORMS = (
    "Берем за основу концепцию А, сервер возможно потом",
)
DECISION_DATES = (
    "2026-11-04",
)

HEADER_FORBIDDEN_FORMS = (
    "full redis-like database engine",
    "redis-like database engine",
    "full redis compatibility",
    "redis-compatible server",
    "a redis-like server",
    "полная совместимость с redis как ближайшая цель",
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

DEFERRED_FORMS = (
    "отложено",
    "отложен",
    "отложена",
    "отложены",
    "отложить",
    "deferred",
    "postponed",
    "postpone",
    "on hold",
    "заморожено",
    "не входит в активный план",
    "не в текущем плане",
    "не в ближайшем плане",
    "не планируется",
    "пока не планируется",
    "возможно потом",
    "после ядра",
    "не следующий шаг",
    "не является следующим шагом",
    "за пределами текущего плана",
    "вне текущего плана",
    "не в этом цикле",
    "сервер возможно потом",
)

SECTION_PLACES = (
    ("Phase 3: Networking (раздел 2)", r"^###\s+Phase 3:\s*Networking\b"),
    ("3.6 Replication (WAL Log Shipping)", r"^###\s+3\.6\s+Replication\b"),
    ("3.7 Sharding", r"^###\s+3\.7\s+Sharding\b"),
    ("3.23 REST API Spec", r"^###\s+3\.23\s+REST API Spec\b"),
)
HEADING_WINDOW = 4  # заголовок + 3 строки: вступление и ближайшая пометка

PRIORITY_ROWS = (
    ("таблица приоритетов раздела 2: TCP Server (P1)", r"^\s*\|\s*\*\*TCP Server\*\*"),
    (
        "таблица приоритетов раздела 2: Redis Protocol / RESP (P1)",
        r"^\s*\|\s*\*\*Redis Protocol\*\*",
    ),
)
MILESTONE_VERSIONS = ("v0.4.0", "v0.7.0", "v1.0.0")
OPEN_ITEMS = (
    ("Open Questions: пункт 1 (RESP)", r"\bRESP\b"),
    ("Open Questions: пункт 3 (Cluster)", r"\bCluster\b|\bRaft\b|\bPaxos\b"),
    ("Open Questions: пункт 4 (Auth)", r"\bAuth\b|\bACL\b"),
)
SEVEN_PLACES = (
    "Phase 3: Networking",
    "таблица приоритетов TCP/RESP раздела 2",
    "3.6 Replication (WAL Log Shipping)",
    "3.7 Sharding",
    "3.23 REST API Spec",
    "Milestones (v0.4.0/v0.7.0/v1.0.0)",
    "Open Questions (пункты 1/3/4)",
)

ACTIVE_HEADINGS = (
    r"^##\s+(?:\d+\.\s*)?.*(?:активный план|active plan|план концепции а|план под концепцию а)",
    r"^###\s+.*(?:активный план|active plan)",
)
CORE_REFS = ("3.11", "3.12", "3.16", "3.21", "3.36", "3.37")
ACTIVE_FORMS = (
    "делаем сейчас",
    "в работе сейчас",
    "в активной разработке",
    "ближайший этап",
    "ближайшие шаги",
    "активный план",
    "текущий фокус",
    "приоритет ядра",
    "следующие шаги",
    "следующий этап",
    "active plan",
    "current focus",
    "in scope now",
    "next steps",
    "now in scope",
)
SERVER_NEXT_FORMS = (
    "следующий шаг — сервер",
    "следующий шаг: сервер",
    "следующий шаг - сервер",
    "следующим шагом будет сервер",
    "следующим шагом станет сервер",
    "дальше — сервер",
    "дальше: сервер",
    "дальше сервер",
    "сервер как следующий шаг",
    "сервер в качестве следующего шага",
    "next step: server",
    "next step is the server",
    "server is the next step",
    "server as the next step",
    "next: tcp",
    "next milestone: tcp",
    "v0.4.0 — следующий",
    "v0.4.0 как следующий",
    "поднимаем сервер",
    "запускаем tcp-сервер",
)
SERVER_ACTIVE_PATTERNS = (
    r"\bTCP Server\b",
    r"\bRESP\b",
    r"\bHTTP API\b",
    r"\bREST API\b",
    r"\bCluster\b",
    r"\bReplication\b",
    r"\bSharding\b",
    r"\bWebSocket\b",
)
MIN_PLAN_LINES = 3
MIN_PLAN_CHARS = 120

REQUIRED_SECTIONS = (
    ("Roadmap", r"\bRoadmap\b"),
    ("Milestones", r"\bMilestones\b"),
    ("Open Questions", r"\bOpen\s+Questions\b"),
)
MIN_DOC_LINES = 100
MIN_DOC_CHARS = 2000
MIN_SECTION_BODY_LINES = 2


def load() -> tuple[str, str]:
    """(текст, заметка о чтении). Исключений наружу нет: пустой файл -- провал проверок."""
    if not PLAN.is_file():
        return "", "файл отсутствует"
    data = PLAN.read_bytes()
    if not data.strip():
        return "", "файл пуст (нет содержимого)"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "", "файл не читается как utf-8"
    return text.replace("\r\n", "\n"), f"прочитано {len(data)} байт, {len(text.splitlines())} строк"


def any_of(text: str, forms: tuple[str, ...]) -> str | None:
    """Первая принятая формулировка, встретившаяся в тексте, без регистра."""
    low = text.lower()
    for form in forms:
        if form.lower() in low:
            return form
    return None


def find_line(lines: list[str], pattern: str) -> tuple[int, str] | None:
    for i, line in enumerate(lines):
        if re.search(pattern, line, re.I):
            return i, line
    return None


def section_slice(lines: list[str], title_pattern: str) -> tuple[int, list[str]] | None:
    """Заголовок уровня `##` и его тело до следующего заголовка уровня `##`."""
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.*)$", line)
        if m and re.search(title_pattern, m.group(1), re.I):
            j = i + 1
            while j < len(lines) and not re.match(r"^##\s", lines[j]):
                j += 1
            return i, lines[i + 1 : j]
    return None


def header_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if re.match(r"^##\s", line):
            break
        out.append(line)
    return out


def content_lines(body: list[str]) -> list[str]:
    return [ln.strip() for ln in body if ln.strip() and not ln.lstrip().startswith("#")]


# ---------------------------------------------------------------------------
# Пять проверок
# ---------------------------------------------------------------------------


def check_decision(lines: list[str]) -> tuple[bool, str]:
    spot = find_line(lines, re.escape(DECISION_FORMS[0]))
    if spot is None:
        return False, (
            "assert «дословное решение владельца с датой 2026-11-04» -- нарушено: "
            f"фраза {DECISION_FORMS[0]!r} не найдена ({len(lines)} строк просмотрено)"
        )
    i, _ = spot
    window = "\n".join(lines[max(0, i - 2) : i + 3])
    date = any_of(window, DECISION_DATES)
    if date is None:
        return False, (
            "assert «решение записано с датой 2026-11-04» -- нарушено: "
            f"фраза на строке {i + 1}, даты нет в окне +-2 строки"
        )
    return True, f"решение дословно на строке {i + 1}, дата {date} в том же блоке"


def check_header(lines: list[str]) -> tuple[bool, str]:
    hdr = "\n".join(header_lines(lines))
    what = "шапка Status/Vision фиксирует встроенную библиотеку без инфраструктуры"
    if not hdr.strip():
        return False, f"assert «{what}» -- нарушено: шапки нет (документ пуст или обрезан)"
    if not re.search(r"(?im)^[>\s]*\**status\**\s*:", hdr):
        return False, f"assert «{what}» -- нарушено: в шапке нет поля Status"
    if not re.search(r"(?im)^[>\s]*\**vision\**\s*:", hdr):
        return False, f"assert «{what}» -- нарушено: в шапке нет поля Vision"
    bad = any_of(hdr, HEADER_FORBIDDEN_FORMS)
    if bad is not None:
        return False, (
            f"assert «{what}» -- нарушено: шапка обещает {bad!r} как ближайшую цель"
        )
    embedded = any_of(hdr, EMBEDDED_FORMS)
    infra = any_of(hdr, NO_INFRA_FORMS)
    if embedded is None or infra is None:
        gaps = []
        if embedded is None:
            gaps.append("нет принятой формулировки встроенной библиотеки")
        if infra is None:
            gaps.append("нет принятой формулировки без сервера/без инфраструктуры")
        return False, f"assert «{what}» -- нарушено: " + "; ".join(gaps)
    return True, f"Status/Vision: «{embedded}» + «{infra}», сервер ближайшей целью не объявлен"


def check_deferred(lines: list[str]) -> tuple[bool, str]:
    missing: list[str] = []

    for name, pattern in SECTION_PLACES:
        spot = find_line(lines, pattern)
        if spot is None:
            missing.append(f"{name} -- заголовок не найден")
            continue
        i, _ = spot
        window = "\n".join(lines[i : i + HEADING_WINDOW])
        if any_of(window, DEFERRED_FORMS) is None:
            missing.append(f"{name} -- нет пометки в окне строк {i + 1}-{i + HEADING_WINDOW}")

    for name, pattern in PRIORITY_ROWS:
        rows = [(i, ln) for i, ln in enumerate(lines) if re.search(pattern, ln, re.I)]
        if not rows:
            missing.append(f"{name} -- строка приоритета не найдена")
        elif not any(any_of(ln, DEFERRED_FORMS) for _, ln in rows):
            missing.append(f"{name} -- строка {rows[0][0] + 1} без пометки отложено")

    milestones = section_slice(lines, r"\bMilestones\b")
    if milestones is None:
        missing.append("Milestones -- раздел не найден")
    else:
        _, body = milestones
        for version in MILESTONE_VERSIONS:
            rows = [ln for ln in body if version in ln and ln.lstrip().startswith("|")]
            if not rows:
                missing.append(f"Milestones: строка {version} не найдена")
            elif not any(any_of(ln, DEFERRED_FORMS) for ln in rows):
                missing.append(f"Milestones: строка {version} без пометки отложено")

    questions = section_slice(lines, r"\bOpen\s+Questions\b")
    if questions is None:
        missing.append("Open Questions -- раздел не найден")
    else:
        _, body = questions
        numbered = [ln for ln in body if re.match(r"^\s*\d+\.\s", ln)]
        if len(numbered) < 3:
            missing.append(f"Open Questions: пронумерованных пунктов {len(numbered)} < 3")
        for name, pattern in OPEN_ITEMS:
            rows = [ln for ln in numbered if re.search(pattern, ln, re.I)]
            if not rows:
                missing.append(f"{name} -- пункт не найден")
            elif not any(any_of(ln, DEFERRED_FORMS) for ln in rows):
                missing.append(f"{name} -- без пометки отложено")

    if missing:
        return False, (
            "assert «все семь серверных мест поименно помечены отложенными» -- нарушено: "
            + "; ".join(missing)
        )
    return True, "все 7 мест помечены: " + ", ".join(SEVEN_PLACES)


def check_active_plan(lines: list[str]) -> tuple[bool, str]:
    what = "непустой активный план под концепцию А с разделами ядра и без сервера следующим шагом"
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
    body = content_lines(lines[idx + 1 : j])
    body_text = "\n".join(body)
    if len(body) < MIN_PLAN_LINES or len(body_text) < MIN_PLAN_CHARS:
        return False, (
            f"assert «{what}» -- нарушено: активный план пуст или обрезан: "
            f"{len(body)} строк, {len(body_text)} символов"
        )
    no_refs = [ref for ref in CORE_REFS if ref not in body_text]
    if no_refs:
        return False, (
            f"assert «{what}» -- нарушено: нет ссылок на разделы ядра: {', '.join(no_refs)}"
        )
    active = any_of(body_text, ACTIVE_FORMS)
    if active is None:
        return False, (
            f"assert «{what}» -- нарушено: нет ни одной принятой формулировки активного плана "
            f"(список из {len(ACTIVE_FORMS)} формулировок)"
        )
    promise = any_of(body_text, SERVER_NEXT_FORMS)
    if promise is not None:
        return False, (
            f"assert «{what}» -- нарушено: план обещает сервер следующим шагом: {promise!r}"
        )
    for line in body:
        server = any(re.search(p, line, re.I) for p in SERVER_ACTIVE_PATTERNS)
        if server and any_of(line, ACTIVE_FORMS) and any_of(line, DEFERRED_FORMS) is None:
            return False, (
                f"assert «{what}» -- нарушено: серверная работа заявлена активной: {line[:90]!r}"
            )
    return True, (
        f"{len(body)} строк, ссылки на все 6 разделов ядра, маркер «{active}», "
        "сервер следующим шагом не обещан"
    )


def check_document(lines: list[str], text: str) -> tuple[bool, str]:
    what = "документ непустой и содержит Roadmap, Milestones, Open Questions"
    if not text.strip():
        return False, f"assert «{what}» -- нарушено: файл пуст"
    if len(text) < MIN_DOC_CHARS:
        return False, (
            f"assert «{what}» -- нарушено: {len(text)} символов < {MIN_DOC_CHARS}, файл обрезан"
        )
    if len(lines) < MIN_DOC_LINES:
        return False, (
            f"assert «{what}» -- нарушено: {len(lines)} строк < {MIN_DOC_LINES}, файл обрезан"
        )
    for name, pattern in REQUIRED_SECTIONS:
        found = section_slice(lines, pattern)
        if found is None:
            return False, f"assert «{what}» -- нарушено: нет раздела {name}"
        _, body = found
        body_lines = content_lines(body)
        if len(body_lines) < MIN_SECTION_BODY_LINES:
            return False, (
                f"assert «{what}» -- нарушено: раздел {name} без содержимого "
                f"({len(body_lines)} строк)"
            )
    return True, f"{len(lines)} строк, {len(text)} символов; Roadmap/Milestones/Open Questions с телом"


def main() -> int:
    text, note = load()
    lines = text.splitlines()
    print(f"FUTURE_PLAN.md: {note}")
    results = (
        ("решение владельца", check_decision(lines)),
        ("шапка Status/Vision", check_header(lines)),
        ("семь серверных мест отложены", check_deferred(lines)),
        ("активный план концепции А", check_active_plan(lines)),
        ("документ непустой и полный", check_document(lines, text)),
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
