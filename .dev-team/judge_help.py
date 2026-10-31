"""Судья задачи «справка стенда перечисляет все режимы, подпись P1-9 нейтральна».

Проверок столько, сколько режимов, плюс одна:
  1. справка   каждый режим, который `main()` распознаёт (`mode == "<имя>"`),
               встречается в выводе запуска без аргументов;
  2. подпись   подпись пробы P1-9 не содержит слова «мутирует»;
  3. итог      неупомянутые режимы названы поимённо, `ИТОГ: провалено N из M`.

Справка читается прогоном, а не разбором docstring: `main()` печатает
`__doc__`, но проверять надо напечатанное, а не то, что лежит в исходнике.
Запуск без аргументов завершается кодом 2 — это штатное поведение справки, а
не признак поломки, поэтому код возврата здесь не оценивается: оценивается
текст. Пустой текст валит все проверки режимов, а не проходит молча.

Режим ищется целым токеном (`(?<![\\w-])имя(?![\\w-])`), а не подстрокой: иначе
`write-journal` «нашёлся» бы в `write-journal-txn`, и добавление одного режима
в справку закрывало бы сразу два — судья зеленел бы на неполной справке.

Нулевой случай: если из кода не извлечено ни одного режима, проверка падает
отдельной строкой. Пустой список неупомянутых означает «ничего не проверено»,
а не «всё упомянуто», и зелёным он быть не может.

Подпись P1-9 берётся из таблицы PROBES по имени пробы `probe_p1_9`, а не по
префиксу: `P1-9b` — сторож обратной стороны, его подпись к дефекту отношения
не имеет.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "crash_harness.py"
PROBES = ROOT / ".dev-team" / "audit_probes.py"

MODE_RE = re.compile(r'mode\s*==\s*"([^"]+)"')
P1_9_RE = re.compile(r'\(\s*"([^"]+)"\s*,\s*probe_p1_9\s*\)')
PRINT_RE = re.compile(r'print\(f"\{status[^"]*\{name\}[^"]*\{detail\}')
BANNED = "мутирует"


def help_text() -> tuple[str, str]:
    """Вывод запуска стенда без аргументов: ровно то, что видит человек.

    PYTHONIOENCODING=utf-8 обязателен: без него дочерний процесс пишет в
    пайп в локальной кодировке, и русский текст приходит битым.
    """
    if not HARNESS.exists():
        return "", f"нет файла {HARNESS}"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(
            [sys.executable, str(HARNESS)],
            cwd=ROOT, capture_output=True, env=env, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"{type(exc).__name__}: {exc}"
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def modes() -> list[str]:
    return MODE_RE.findall(HARNESS.read_text(encoding="utf-8"))


def mentioned(mode: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(mode)}(?![\w-])", text) is not None


def check_label() -> tuple[bool, str]:
    src = PROBES.read_text(encoding="utf-8")
    m = P1_9_RE.search(src)
    if not m:
        return False, (
            'assert подпись P1-9 найдена: в .dev-team/audit_probes.py нет записи '
            '("<подпись>", probe_p1_9)'
        )
    label = m.group(1)
    if not PRINT_RE.search(src):
        return False, (
            "assert подпись печатается: в audit_probes.py не найдено место печати "
            "`{status}  {name}: {detail}` — проверять нечего"
        )
    if BANNED in label.lower():
        return False, (
            f'assert "{BANNED}" нет в подписи: подпись "{label}" печатается и при '
            "HOLDS, то есть зелёный вердикт читается как утверждение о дефекте"
        )
    return True, f'подпись "{label}" без слова «{BANNED}»'


def main() -> int:
    text, stderr = help_text()
    found = modes()
    checks: list[tuple[bool, str]] = []

    if not found:
        checks.append((
            False,
            'assert режимы извлечены: ни одного `mode == "<имя>"` в tools/crash_harness.py',
        ))
        missing: list[str] = []
    else:
        if not text.strip():
            print(f"справка пуста: запуск без аргументов не дал вывода (stderr: {stderr[-200:]})")
        missing = [mode for mode in found if not mentioned(mode, text)]
        for mode in found:
            if mode in missing:
                checks.append((
                    False,
                    f'assert "{mode}" в справке: не найден в выводе запуска без аргументов',
                ))
            else:
                checks.append((True, f'режим {mode}: найден в справке'))

    checks.append(check_label())

    failed = 0
    for ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {detail}")
        failed += 0 if ok else 1

    if missing:
        print(f"НЕ УПОМЯНУТЫ: {', '.join(sorted(missing))} ({len(missing)} из {len(found)})")
    else:
        print(f"НЕ УПОМЯНУТЫ: нет (0 из {len(found)})")
    print(f"ИТОГ: провалено {failed} из {len(checks)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
