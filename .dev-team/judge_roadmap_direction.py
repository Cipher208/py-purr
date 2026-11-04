"""Судья направления FUTURE_PLAN.md: документ обязан говорить про концепцию А.

Чистый Python: только re, sys, pathlib. Ни pytest, ни ruff, ни subprocess --
`pytest>=7.0` в pyproject.toml не запинён, а линтер текстовому судье не нужен.
Команда прогона: `uv run python .dev-team/judge_roadmap_direction.py`.

Пять проверок ровно по критерию приёмки карточки:
  1. дословное решение владельца с датой 2026-11-04;
  2. шапка Status/Vision не обещает «full Redis-like database engine» как
     ближайшую цель и фиксирует встроенную библиотеку без инфраструктуры;
  3. инвариант «ни одного серверного обещания без пометки отложено» по всему
     документу: по смысловым маркерам собираются ВСЕ строки, где серверное
     направление заявлено как план, приоритет, этап или пример будущего API,
     и каждая обязана либо нести пометку сама, либо лежать в разделе,
     помеченном отложенным. Непокрытые места печатаются ВСЕ поименно;
  4. непустой активный план под концепцию А, ссылающийся на 3.11/3.12/
     3.16/3.21/3.36/3.37, и не обещающий сервер следующим шагом;
  5. документ непустой и содержит Roadmap, Milestones, Open Questions.

Проверка 3 не знает номеров строк: разделы определяются заголовками
Markdown вне блоков кода, места -- содержимым строк. Пометка «отложено»
ищется списком DEFERRED_FORMS на самой строке либо на заголовке раздела
(в окне HEADING_WINDOW строк от заголовка) -- тогда она покрывает весь
подраздел, включая примеры кода. Заголовок уровня `#` (имя документа)
покрытием не считается: одна пометка в начале файла не должна закрывать
весь документ. Если маркеры почти ничего не нашли, проверка падает как
вакуумная: вырезать серверные разделы нельзя, их надо пометить.

Вывод детерминирован: нет времени, сети, абсолютных путей машины и версии
окружения.
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

# ---------------------------------------------------------------------------
# Проверка 3. Смысловые маркеры серверного направления: план, приоритет,
# этап, пример будущего API. Порядок не важен -- у строки собираются ВСЕ
# сработавшие маркеры, и каждое непокрытое место печатается поименно.
# Номера строк не используются вообще: только заголовки и содержимое.
# ---------------------------------------------------------------------------

SERVER_MARKERS = (
    ("purr serve / --port", r"\bpurr serve\b|--port\s+\d+"),
    (
        "TCP Server / TCP-сервер",
        r"\bTCP server\b|\btcp\.py\b|\bPurrServer\b|\bstart_server\b|\bserve_forever\b",
    ),
    (
        "HTTP API / REST API",
        r"\bHTTP API\b|\bREST API\b|\bhttp_api\.py\b|\bhttp\.py\b|\baiohttp\b",
    ),
    ("WebSocket", r"\bWebSocket\b|\bwebsocket\.py\b"),
    (
        "RESP / Redis Protocol",
        r"\bRESP\b|\bRESP2\b|\bRedis Protocol\b|\bRedis-compatible protocol\b"
        r"|\bRedis Serialization Protocol\b",
    ),
    ("дерево server/ / purr/server.py", r"server/|purr/server\.py"),
    (
        "server side / remote access / client library",
        r"\bserver side\b|\bremote access\b|\bClient Library\b|client/"
        r"|connection\.py\b|\bconnection pool\b",
    ),
    ("Cluster / Clustering / консенсус", r"\bCluster\b|\bClustering\b|\bRaft\b|\bPaxos\b"),
    (
        "Replication / replicas / master-slave",
        r"\bReplication\b|\breplication\.py\b|\breplica\b|\breplicas\b|\bMaster-slave\b",
    ),
    ("Sharding", r"\bSharding\b|\bShardedStore\b|\bsharded_store\.py\b"),
    ("RDB / AOF", r"\bRDB\b|\bAOF\b"),
    (
        "TLS / Auth / ACL",
        r"\bTLS\b|\bAuth\b|\bAuthentication\b|\bACL\b|\bauth\.py\b|\bPassword\b",
    ),
    ("Docker", r"\bDocker\b"),
    ("Planned / in the future / ETA", r"\bPlanned\b|\bin the future\b|\bETA\b"),
    ("Milestones v0.4/v0.5/v0.7/v1.0", r"\bv0\.[457]\.0\b|\bv1\.0\.0\b"),
    ("Full Redis compatibility", r"\bFull Redis compatibility\b"),
    # Заголовок сетевого этапа и строка примера клиентского дерева: это тоже
    # «этап» и «пример будущего API», а не просто соседи найденных строк.
    ("этап Networking / Python client", r"\bNetworking\b|\bPython client\b"),
)
HEADING_WINDOW = 3  # пометка на заголовке или в первых строках раздела
DEFERRED_HEADING_MIN_LEVEL = 2  # `#` -- имя документа, покрытием не считается
MIN_SERVER_PLACES = 12  # защита от вакуума: вырезать разделы нельзя
MIN_SERVER_MARKERS = 6
MAX_SNIPPET = 76

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
# Проверка 3: разметка документа по заголовкам и сбор серверных мест
# ---------------------------------------------------------------------------


def heading_level(line: str) -> tuple[int, str] | None:
    m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
    if m is None:
        return None
    return len(m.group(1)), m.group(2).strip()


def heading_stacks(lines: list[str]) -> list[tuple[tuple[int, int, str], ...]]:
    """Для каждой строки -- стек активных заголовков (уровень, индекс, имя).

    Содержимое fenced-блоков кода заголовками не считается: `# purr/server.py`
    и `# Server` внутри примеров не должны ломать границы разделов.
    """
    stack: list[tuple[int, int, str]] = []
    out: list[tuple[tuple[int, int, str], ...]] = []
    in_fence = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(tuple(stack))
            continue
        if not in_fence:
            heading = heading_level(line)
            if heading is not None:
                level, title = heading
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, i, title))
        out.append(tuple(stack))
    return out


def deferred_headings(
    lines: list[str], stacks: list[tuple[tuple[int, int, str], ...]]
) -> set[int]:
    """Индексы заголовков разделов, помеченных отложенными.

    Пометка ищется в окне HEADING_WINDOW строк от заголовка: она может быть
    прямо в заголовке или в ближайшем вступлении раздела.
    """
    marked: set[int] = set()
    for i, stack in enumerate(stacks):
        if not stack or stack[-1][1] != i:
            continue
        if stack[-1][0] < DEFERRED_HEADING_MIN_LEVEL:
            continue
        window = "\n".join(lines[i : i + HEADING_WINDOW])
        if any_of(window, DEFERRED_FORMS) is not None:
            marked.add(i)
    return marked


def section_label(stack: tuple[tuple[int, int, str], ...]) -> str:
    if not stack:
        return "шапка документа"
    title = re.sub(r"\((?:отложено|deferred|postponed)[^)]*\)", "", stack[-1][2], flags=re.I)
    title = title.strip()
    return title[:70] or "раздел без имени"


def collect_server_lines(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """(индекс строки, фрагмент, все сработавшие маркеры)."""
    found: list[tuple[int, str, list[str]]] = []
    for i, line in enumerate(lines):
        hits = [name for name, pattern in SERVER_MARKERS if re.search(pattern, line, re.I)]
        if hits:
            found.append((i, line.strip()[:MAX_SNIPPET], hits))
    return found


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
    what = "ни одного серверного обещания без пометки «отложено»"
    stacks = heading_stacks(lines)
    marked = deferred_headings(lines, stacks)
    found = collect_server_lines(lines)
    markers_seen = {name for _, _, hits in found for name in hits}

    # Нулевой случай: документ, из которого вырезали все серверные разделы,
    # не должен проходить как «нет запрещённых фраз» -- пометить надо, а не стереть.
    if len(found) < MIN_SERVER_PLACES or len(markers_seen) < MIN_SERVER_MARKERS:
        return False, (
            f"assert «{what}» -- нарушено: проверка вакуумна -- "
            f"найдено {len(found)} строк с серверными маркерами и "
            f"{len(markers_seen)} смысловых маркеров из {len(SERVER_MARKERS)}; "
            "документ обрезан или серверные разделы вырезаны вместо пометки"
        )

    # Одно место -- одна строка: у неё могут сработать несколько маркеров,
    # но печатается она один раз, со своим номером и своим дословным текстом.
    uncovered: list[tuple[int, str, str, tuple[str, ...]]] = []
    for i, snippet, hits in found:
        if any_of(lines[i], DEFERRED_FORMS) is not None:
            continue  # пометка на самой строке
        if any(idx in marked for _, idx, _ in stacks[i]):
            continue  # пометка на заголовке раздела покрывает подраздел целиком
        uncovered.append((i + 1, section_label(stacks[i]), snippet, tuple(hits)))

    if uncovered:
        detail = [
            f"assert «{what}» -- нарушено: непокрытых мест {len(uncovered)} "
            f"из {len(found)} найденных строк с серверными маркерами, все поименно:"
        ]
        for number, (lineno, label, snippet, hits) in enumerate(uncovered, 1):
            detail.append(
                f"    - [{number}] «{label}» строка {lineno} "
                f"[{'; '.join(hits)}] -> {snippet!r}"
            )
        return False, "\n".join(detail)

    labels = {section_label(stacks[i]) for i, _, _ in found}
    return True, (
        f"найдено {len(found)} строк с серверными маркерами в {len(labels)} разделах; "
        f"все покрыты пометкой: сами строки или {len(marked)} помеченных разделов"
    )


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
        ("серверные обещания отложены по всему документу", check_deferred(lines)),
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
