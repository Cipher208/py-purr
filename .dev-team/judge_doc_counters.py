"""Judge for the doc-counters defect (verdict-021, card .dev-team/card.md).

Runs the real suite itself, parses the measured ``N passed`` out of pytest,
then compares README.md and FUTURE_PLAN.md against that measurement.

No hard-coded test count. No absolute machine paths, no timestamps, no network
access in the printed output: only the measured number and stable check text.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"
PLAN_PATH = ROOT / "FUTURE_PLAN.md"
PYTEST_CMD = ["uv", "run", "--extra", "dev", "python", "-m", "pytest", "-q"]
SNAPSHOT_DATE = "2026-07-24"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
PASSED_RE = re.compile(r"(?<!\d)(\d+)\s+passed\b")
FALSE_RE = re.compile(r"\bFalse\b")
CALLBACK_RE = re.compile(r"\bCallbackError\b")

# "A line stating the size of the suite" is recognised by meaning, through
# lists of accepted wordings, not by one accidental substring.
SIZE_WORDS = (
    r"\bsuite\b",
    r"\btest\s+suite\b",
    r"\btests?\b",
    r"\btest\s+count\b",
    r"\bnumber\s+of\s+tests\b",
    r"\btest\s+cases?\b",
)
SIZE_CLAIMS = (
    r"\b(\d+)\s+tests?\b",
    r"\bsuite\s+(?:is|of|has|contains|comprises|consists\s+of)\s+(\d+)\b",
    r"\btest\s+suite\s+(?:is|of|has|contains|comprises)\s+(\d+)\b",
    r"\b(?:total|number)\s+of\s+(\d+)\s+tests?\b",
    r"\b(\d+)\s+test\s+cases?\b",
)

# Accepted ways to mark Stats as a historical snapshot.
HISTORICAL = (
    r"\bhistorical\b",
    r"\bsnapshot\b",
    r"\bas\s+of\b",
    r"\bat\s+that\s+date\b",
    r"\bon\s+that\s+date\b",
    r"\bat\s+the\s+time\b",
    r"\bno\s+longer\s+current\b",
    r"\bnot\s+current\b",
    r"\barchived?\b",
    r"\bисторическ",
    r"\bснимок\b",
    r"\bна\s+ту\s+дату\b",
    r"\bсостояние\s+на\b",
    r"\bнеактуальн",
)

# Accepted ways to say the figure was accurate on that date only.
AS_OF = (
    r"\bas\s+of\s+2026-07-24\b",
    r"\baccurate\s+(?:as\s+of|for|on)\b",
    r"\bvalid\s+as\s+of\b",
    r"\bcurrent\s+as\s+of\b",
    r"\bapplies\s+only\s+to\b",
    r"\bonly\s+for\s+that\s+date\b",
    r"\breflects?\s+the\s+state\s+at\b",
    r"\btrue\s+(?:at|on)\s+that\s+date\b",
    r"\bdoes\s+not\s+describe\s+the\s+current\b",
    r"\bdo\s+not\s+describe\s+the\s+current\b",
    r"\bактуальн[а-я]*\s+на\b",
    r"\bверн[а-я]*\s+на\b",
    r"\bна\s+ту\s+дату\b",
    r"\bотносится\s+к\b",
    r"\bсостояние\s+на\s+дату\b",
)

STALE_COUNTERS = (r"\b44/44\s+passed\b", r"\bTests:\s*44\b")
STATS_TITLES = (r"\bstats?\b", r"\bstatistics\b", r"\bстатистик")

# Accepted ways to describe a repeated send near the CallbackError example.
REPEAT_SEND = (
    r"\bagain\b",
    r"\bre-?send\b",
    r"\bresend\b",
    r"\bretry\b",
    r"\brepeated\b",
    r"\bsubsequent\b",
    r"\banother\s+send\b",
    r"\bsecond\s+send\b",
    r"\bsend\s*\([^)]*\)\s*again\b",
    r"\bповторн",
    r"\bещё\s+раз\b",
)
CONTEXT_WINDOW = 12

# Required sections, each with a list of accepted heading wordings.
REQUIRED_SECTIONS = {
    "README.md": (
        ("Installation", (r"\binstall(?:ation)?\b", r"\bgetting\s+started\b", r"\bустановка\b")),
        ("Quick Tour", (r"\bquick\s+tour\b", r"\bquick\s*start\b", r"\bбыстрый\s+старт\b")),
        (
            "Replaying the journal",
            (
                r"\breplay(?:ing)?\s+(?:the\s+)?journal\b",
                r"\bjournal\s+replay\b",
                r"\bвоспроизведение\s+журнала\b",
            ),
        ),
    ),
    "FUTURE_PLAN.md": (
        ("Roadmap", (r"\broad\s*map\b", r"\bплан\b")),
        ("Milestones", (r"\bmilestones?\b", r"\bэтапы\b", r"\bвехи\b")),
        ("Open Questions", (r"\bopen\s+questions?\b", r"\bоткрытые\s+вопросы\b")),
    ),
}


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _sections(text: str) -> list[dict]:
    lines = text.splitlines()
    heads: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            heads.append((index, len(match.group(1)), match.group(2)))
    sections: list[dict] = []
    for position, (start, level, title) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        # A section's own scope runs until the next heading of the same or a
        # higher level: `## Quick Tour` is not empty just because `### 1.`
        # follows it on the very next line.
        scope_end = len(lines)
        for next_start, next_level, _ in heads[position + 1 :]:
            if next_level <= level:
                scope_end = next_start
                break
        sections.append(
            {
                "start": start,
                "end": end,
                "level": level,
                "title": title,
                "text": "\n".join(lines[start:end]),
                "body": "\n".join(lines[start + 1 : end]),
                "scope_body": "\n".join(lines[start + 1 : scope_end]),
            }
        )
    return sections


def measure_test_count() -> tuple[int | None, str]:
    """Run the suite and parse the measured number. Never hard-code it."""
    try:
        proc = subprocess.run(
            PYTEST_CMD,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"pytest subprocess did not run: {type(exc).__name__}"
    if proc.returncode != 0:
        return None, f"pytest exited {proc.returncode}"
    found = PASSED_RE.findall(proc.stdout + "\n" + proc.stderr)
    if not found:
        return None, "no 'N passed' line in pytest output"
    return int(found[-1]), ""


def check_readme_count(text: str, measured: int | None) -> tuple[bool, str, str, str]:
    """(1) Exactly one suite-size line in README, naming the measured N."""
    expected = "non-empty README.md, exactly one size claim equal to measured N"
    if not text.strip():
        return False, "README.md пуст", expected, "empty file"
    if measured is None:
        return False, "измерение числа тестов недоступно", expected, "no pytest measurement"

    size_lines: list[tuple[str, list[int]]] = []
    for line in text.splitlines():
        if not re.search(r"\b\d+\b", line) or not _any(SIZE_WORDS, line):
            continue
        claims = [int(value) for pattern in SIZE_CLAIMS for value in re.findall(pattern, line, re.IGNORECASE)]
        if claims:
            size_lines.append((line.strip(), claims))

    if len(size_lines) != 1:
        actual = f"{len(size_lines)} size claims: {[claims for _, claims in size_lines]}"
        return False, f"строк о размере набора: {len(size_lines)}, ожидалась ровно одна", expected, actual

    _, claims = size_lines[0]
    if not all(claim == measured for claim in claims):
        actual = f"claims={claims}, measured={measured}"
        return False, f"строка называет {claims}, измерено {measured}", expected, actual
    return True, f"одна строка о размере набора называет {measured}", "", ""


def check_plan_snapshot(text: str) -> tuple[bool, str, str, str]:
    """(2) Stats is an explicitly dated historical snapshot; stale counters are not current."""
    expected = f"Stats: date {SNAPSHOT_DATE} + historical marker + as-of caveat; stale counters only inside it"
    if not text.strip():
        return False, "FUTURE_PLAN.md пуст", expected, "empty file"

    sections = _sections(text)
    stats = [section for section in sections if _any(STATS_TITLES, section["title"])]
    if not stats:
        return False, "раздел Stats не найден", expected, "no Stats heading"

    section = stats[0]
    missing: list[str] = []
    if SNAPSHOT_DATE not in section["text"]:
        missing.append(f"нет даты {SNAPSHOT_DATE}")
    if not _any(HISTORICAL, section["text"]):
        missing.append("нет маркера исторического снимка")
    if not _any(AS_OF, section["text"]):
        missing.append("нет оговорки «актуально на ту дату»")

    stale_without_context: list[int] = []
    for index, line in enumerate(text.splitlines()):
        if not _any(STALE_COUNTERS, line):
            continue
        owner = next((s for s in reversed(sections) if s["start"] <= index), None)
        marked = (
            owner is not None
            and _any(HISTORICAL, owner["text"])
            and SNAPSHOT_DATE in owner["text"]
        )
        if not marked:
            stale_without_context.append(index + 1)
    if stale_without_context:
        missing.append(f"устаревшие счётчики без исторической пометки (строки {stale_without_context})")

    if missing:
        return False, "; ".join(missing), expected, "; ".join(missing)
    return (
        True,
        f"Stats помечен как исторический снимок на {SNAPSHOT_DATE}, устаревшие числа не выдаются за текущие",
        "",
        "",
    )


def check_false_contract(text: str) -> tuple[bool, str, str, str]:
    """(3) Near the CallbackError example, a repeated send() is named as returning False."""
    expected = "CallbackError example with False and a repeated send in the same context"
    if not text.strip():
        return False, "README.md пуст", expected, "empty file"

    lines = text.splitlines()
    contexts = [
        "\n".join(lines[max(0, index - CONTEXT_WINDOW) : index + CONTEXT_WINDOW + 1])
        for index, line in enumerate(lines)
        if CALLBACK_RE.search(line)
    ]
    if not contexts:
        return False, "пример CallbackError не найден", expected, "no CallbackError in README.md"

    paired = [context for context in contexts if FALSE_RE.search(context) and _any(REPEAT_SEND, context)]
    if not paired:
        with_false = sum(bool(FALSE_RE.search(context)) for context in contexts)
        actual = f"contexts={len(contexts)}, contexts with False={with_false}, contexts with False+repeat=0"
        return False, "рядом с примером CallbackError не назван False для повторного send()", expected, actual
    return True, "повторный send() после CallbackError явно возвращает False", "", ""


def check_completeness(texts: dict[str, str]) -> tuple[bool, str, str, str]:
    """(4) Both documents are non-empty and still carry all required sections."""
    expected = "both docs non-empty, every required section present with a non-empty body"
    missing: list[str] = []
    for name, requirements in REQUIRED_SECTIONS.items():
        text = texts[name]
        if not text.strip():
            missing.append(f"{name}: пуст")
            continue
        sections = _sections(text)
        for label, patterns in requirements:
            found = any(
                _any(patterns, section["title"])
                and any(line.strip() for line in section["scope_body"].splitlines())
                for section in sections
            )
            if not found:
                missing.append(f"{name}: раздел {label}")
    if missing:
        return False, "; ".join(missing), expected, "; ".join(missing)
    return True, "оба документа полные: все обязательные разделы с содержимым", "", ""


def main() -> int:
    texts = {"README.md": _read(README_PATH), "FUTURE_PLAN.md": _read(PLAN_PATH)}
    measured, measure_error = measure_test_count()
    if measured is None:
        print(f"измерено: недоступно ({measure_error})")
    else:
        print(f"измерено: {measured} passed")

    checks = (
        ("README.md: одна строка о размере набора = измеренному N", check_readme_count(texts["README.md"], measured)),
        ("FUTURE_PLAN.md Stats: исторический снимок с датой", check_plan_snapshot(texts["FUTURE_PLAN.md"])),
        ("README.md: повторный send() после CallbackError возвращает False", check_false_contract(texts["README.md"])),
        ("оба документа полные и непустые", check_completeness(texts)),
    )

    failed = 0
    for number, (label, (ok, detail, expected, actual)) in enumerate(checks, start=1):
        if ok:
            print(f"PASS [{number}] {label}: {detail}")
        else:
            failed += 1
            print(f"FAIL [{number}] {label}: {detail}")
            print(f"  AssertionError: check[{number}] expected {expected}; actual {actual}")
    print(f"провалено {failed} из 4")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
