"""Судья свежести раздела «0. Активный план» (карточка .dev-team/card.md).

Пять детерминированных проверок по `## Критерий приёмки`:

  1. В разделе 0 нет трёх устаревших оборотов. Запрещённые формулировки
     заданы СПИСКОМ дословных строк, а не одной подстрокой; документ и сам
     раздел обязаны быть непустыми.
  2. Пункт про состояние помечен ЗАКРЫТЫМ и называет verdict-020,
     verdict-023, db_path, снимок, CallbackError.
  3. Пункт про replay помечен ЗАКРЫТЫМ; судья САМ запускает
     .dev-team/judge_journal_replay.py подпроцессом через sys.executable
     и требует «провалено 0 из 7» при exit=0, иначе «закрыто» голословно.
  4. Счётчики тестов не выданы за открытую задачу; E501 назван оставшимся
     хвостом, его число сверено с «Found N errors» от подпроцесса
     sys.executable -m ruff check tools/crash_harness.py --select E501;
     пин ruff==0.17.2 проверяется в pyproject.toml.
  5. Оба документа полные: Roadmap, Milestones, Open Questions с телами,
     раздел 0 >=3 непустых строк и >=120 символов, FUTURE_PLAN_SERVER.md
     непуст. Пустой или обрезанный файл не проходит как «нет запрещённых фраз».

ЯВНО НЕ ПРОВЕРЯЕТСЯ:
  - парафразы и переформулировки устаревших утверждений;
  - новые формулировки тех же устаревших утверждений;
  - Unicode-гомоглифы и визуально похожие символы;
  - семантическая корректность прочих разделов FUTURE_PLAN.md;
  - содержимое FUTURE_PLAN_SERVER.md сверх непустоты;
  - даты и числа вне раздела «0. Активный план».

Судья — сторож свежести трёх конкретных пунктов, а не детектор намерений.
Регулярок про намерения, списков форм обещаний/отрицаний и понимания
естественного языка здесь нет (урок verdict-019): только дословные токены,
структура заголовков и нумерованных пунктов, вывод двух подпроцессов.
Корень репозитория берётся из Path(__file__).resolve().parents[1],
подпроцессы запускаются с cwd=ROOT через sys.executable, без uv run внутри
uv run и без абсолютных путей машины в исходнике.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "FUTURE_PLAN.md"
SERVER_PATH = ROOT / "FUTURE_PLAN_SERVER.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"

REPLAY_CMD = [sys.executable, ".dev-team/judge_journal_replay.py"]
RUFF_CMD = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "tools/crash_harness.py",
    "--select",
    "E501",
]

SECTION_ZERO = "0. Активный план"
REQUIRED_SECTIONS = ("Roadmap", "Milestones", "Open Questions")

# Ровно три устаревших оборота из FUTURE_PLAN.md:14-20, заданные списком
# дословных формулировок. Никаких регулярок и никакого «понимания смысла».
FORBIDDEN_PHRASES = (
    "состояние только в памяти",
    "исправить рассогласование FSM в памяти и БД при откате записи",
    "спроектировать персистенцию саги",
    "счётчики тестов и E501 в `tools/` ведутся отдельными задачами",
    "счётчики тестов ведутся отдельными задачами",
)
OPEN_COUNTER_PHRASES = (
    "счётчики тестов и E501 в `tools/` ведутся отдельными задачами",
    "счётчики тестов ведутся отдельными задачами",
    "счётчики тестов отдельными задачами",
    "счётчики тестов отдельной задачей",
)
CLOSED = "ЗАКРЫТО"
STATE_TOKENS = ("verdict-020", "verdict-023", "db_path", "снимок", "CallbackError")
TAIL_TOKENS = ("хвост", "осталось", "оставшийся", "вне CI")
RUFF_PIN = "ruff==0.17.2"
REPLAY_OK_LINE = "провалено 0 из 7"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _section_zero(lines: list[str]) -> list[str] | None:
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and SECTION_ZERO in line:
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def _item_start(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped or not stripped[0].isdigit():
        return False
    head = stripped.split(".", 1)
    return len(head) == 2 and head[0].isdigit() and head[1].startswith(" ")


def _items(section: list[str] | None) -> list[str]:
    if section is None:
        return []
    items: list[str] = []
    current: list[str] | None = None
    for line in section[1:]:
        if _item_start(line):
            if current is not None:
                items.append("\n".join(current))
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        items.append("\n".join(current))
    return items


def _missing_sections(lines: list[str]) -> list[str]:
    missing: list[str] = []
    for label in REQUIRED_SECTIONS:
        found = False
        for index, line in enumerate(lines):
            if not (line.startswith("## ") and label in line):
                continue
            body = []
            for following in lines[index + 1 :]:
                if following.startswith("## "):
                    break
                if following.strip():
                    body.append(following)
            if body:
                found = True
                break
        if not found:
            missing.append(label)
    return missing


def _digit_runs(text: str) -> list[int]:
    runs: list[int] = []
    current = ""
    for char in text:
        if char.isdigit():
            current += char
        elif current:
            runs.append(int(current))
            current = ""
    if current:
        runs.append(int(current))
    return runs


def _e501_numbers(line: str) -> list[int]:
    text = line
    stripped = text.lstrip()
    if stripped and stripped[0].isdigit():
        head = stripped.split(".", 1)
        if len(head) == 2 and head[0].isdigit():
            text = head[1]
    return _digit_runs(text.replace("E501", "E"))


def _run_replay() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            REPLAY_CMD,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"подпроцесс replay-судьи не запустился: {type(exc).__name__}"
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        return False, f"replay-судья вернул exit={proc.returncode}, а не 0"
    if REPLAY_OK_LINE not in out:
        return False, "replay-судья не напечатал «провалено 0 из 7»"
    return True, "провалено 0 из 7, exit=0"


def _measure_e501() -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            RUFF_CMD,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"подпроцесс ruff не запустился: {type(exc).__name__}"
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if "No module named ruff" in out:
        return None, "ruff как модуль недоступен для sys.executable -m ruff (No module named ruff)"
    if "Found " in out:
        tail = out.split("Found ", 1)[1].lstrip()
        first = tail.split(None, 1)[0] if tail else ""
        digits = "".join(char for char in first if char.isdigit())
        if digits:
            return int(digits), f"Found {digits} errors"
    if proc.returncode == 0:
        return 0, "Found 0 errors (All checks passed)"
    return None, f"вывод ruff не содержит «Found N errors» (exit={proc.returncode})"


def _check1(plan: str, section: list[str] | None) -> tuple[bool, str, str, str]:
    expected = "непустые FUTURE_PLAN.md и раздел 0; ни одной из 5 запрещённых формулировок"
    if not plan.strip():
        return (
            False,
            "FUTURE_PLAN.md пуст — пустой файл не проходит как «нет запрещённых фраз»",
            expected,
            "пустой документ",
        )
    if section is None:
        return False, "раздел «0. Активный план» не найден", expected, "заголовок раздела 0 отсутствует"
    if not any(line.strip() for line in section[1:]):
        return False, "раздел «0. Активный план» пуст", expected, "0 непустых строк в разделе 0"
    text = "\n".join(section)
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in text]
    if found:
        return (
            False,
            "в разделе 0 остались устаревшие обороты: " + "; ".join(repr(p) for p in found),
            expected,
            f"найдено {len(found)} из 5: {found}",
        )
    return True, f"документ и раздел непустые, {len(FORBIDDEN_PHRASES)} запрещённых формулировок не найдено", "", ""


def _check2(items: list[str]) -> tuple[bool, str, str, str]:
    expected = "ровно один пункт с verdict-020, в нём ЗАКРЫТО, verdict-023, db_path, снимок, CallbackError"
    candidates = [item for item in items if "verdict-020" in item]
    if len(candidates) != 1:
        return (
            False,
            f"пункт состояния не определяется по verdict-020: найдено {len(candidates)}",
            expected,
            f"пунктов с verdict-020: {len(candidates)}",
        )
    missing = [token for token in (CLOSED, *STATE_TOKENS) if token not in candidates[0]]
    if missing:
        return (
            False,
            "в пункте состояния не хватает: " + ", ".join(missing),
            expected,
            f"отсутствуют: {missing}",
        )
    return True, "пункт состояния ЗАКРЫТО: verdict-020/023, db_path, снимок, CallbackError", "", ""


def _check3(items: list[str], replay_ok: bool, replay_detail: str) -> tuple[bool, str, str, str]:
    expected = "пункт с replay помечен ЗАКРЫТЫМ; judge_journal_replay.py: провалено 0 из 7, exit=0"
    problems: list[str] = []
    candidates = [item for item in items if "replay" in item.lower()]
    if not candidates:
        problems.append("в разделе 0 нет пункта с replay")
    elif not any(CLOSED in item for item in candidates):
        problems.append("ни один пункт с replay не помечен ЗАКРЫТЫМ")
    if not replay_ok:
        problems.append(replay_detail)
    if problems:
        return False, "; ".join(problems), expected, "; ".join(problems)
    return True, "пункт replay ЗАКРЫТ; подпроцесс судьи: провалено 0 из 7, exit=0", "", ""


def _check4(
    section: list[str] | None,
    pyproject: str,
    measured: int | None,
    measured_detail: str,
) -> tuple[bool, str, str, str]:
    expected = "счётчики не открытая задача; E501 = Found N errors; пин ruff==0.17.2 в pyproject.toml"
    if section is None:
        return False, "раздел 0 не найден — проверять E501 негде", expected, "раздел 0 отсутствует"
    text = "\n".join(section)
    problems: list[str] = []
    open_phrases = [phrase for phrase in OPEN_COUNTER_PHRASES if phrase in text]
    if open_phrases:
        problems.append(
            "счётчики тестов выданы за открытую задачу: " + "; ".join(repr(p) for p in open_phrases)
        )
    e501_lines = [line for line in section[1:] if "E501" in line]
    if not e501_lines:
        problems.append("в разделе 0 нет строки с E501")
    else:
        tail_lines = [line for line in e501_lines if any(token in line for token in TAIL_TOKENS)]
        if not tail_lines:
            problems.append(
                "E501 не назван оставшимся хвостом (нет токена из " + ", ".join(TAIL_TOKENS) + ")"
            )
        numbers = sorted({number for line in e501_lines for number in _e501_numbers(line)})
        if measured is None:
            problems.append(measured_detail)
        elif measured not in numbers:
            problems.append(
                f"число E501 в плане {numbers} не совпало с измеренным {measured} ({measured_detail})"
            )
    if RUFF_PIN not in pyproject:
        problems.append("пин ruff==0.17.2 отсутствует в pyproject.toml")
    if problems:
        return False, "; ".join(problems), expected, "; ".join(problems)
    return (
        True,
        f"счётчики не открытая задача; E501={measured} совпал с {measured_detail}; пин {RUFF_PIN} на месте",
        "",
        "",
    )


def _check5(
    plan: str,
    server: str,
    section: list[str] | None,
    lines: list[str],
) -> tuple[bool, str, str, str]:
    expected = "оба документа непустые; Roadmap/Milestones/Open Questions с телами; раздел 0 >=3 строк и >=120 символов"
    problems: list[str] = []
    if not plan.strip():
        problems.append("FUTURE_PLAN.md пуст")
    missing = _missing_sections(lines)
    if missing:
        problems.append("нет разделов с телами: " + ", ".join(missing))
    nonblank = 0
    size = 0
    if section is None:
        problems.append("раздел «0. Активный план» не найден")
    else:
        nonblank = sum(1 for line in section[1:] if line.strip())
        size = len("\n".join(section))
        if nonblank < 3 or size < 120:
            problems.append(
                f"раздел 0 обрезан: {nonblank} непустых строк, {size} символов (нужно >=3 / >=120)"
            )
    if not server.strip():
        problems.append("FUTURE_PLAN_SERVER.md пуст")
    if problems:
        return False, "; ".join(problems), expected, "; ".join(problems)
    return (
        True,
        f"документы полные; раздел 0: {nonblank} непустых строк, {size} символов; FUTURE_PLAN_SERVER.md непуст",
        "",
        "",
    )


def main() -> int:
    plan = _read(PLAN_PATH)
    server = _read(SERVER_PATH)
    pyproject = _read(PYPROJECT_PATH)
    lines = plan.splitlines()
    section = _section_zero(lines)
    items = _items(section)
    replay_ok, replay_detail = _run_replay()
    measured, measured_detail = _measure_e501()

    checks = (
        ("1", "раздел 0 без устаревших оборотов", _check1(plan, section)),
        ("2", "пункт состояния ЗАКРЫТ и актуален", _check2(items)),
        ("3", "пункт replay ЗАКРЫТ и подтверждён прогоном", _check3(items, replay_ok, replay_detail)),
        (
            "4",
            "счётчики и E501 сверены с фактом",
            _check4(section, pyproject, measured, measured_detail),
        ),
        ("5", "оба документа полные", _check5(plan, server, section, lines)),
    )

    failed = 0
    for number, label, (ok, detail, expected, actual) in checks:
        if ok:
            print(f"PASS [{number}] {label}: {detail}")
        else:
            failed += 1
            print(f"FAIL [{number}] {label}: {detail}")
            print(f"  AssertionError: check[{number}] expected {expected}; actual {actual}")
    print(f"провалено {failed} из 5")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
