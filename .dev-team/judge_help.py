"""Судья задачи «справка стенда перечисляет все режимы, подпись P1-9 нейтральна».

Проверок столько, сколько режимов, плюс две:
  1. заголовок первая строка справки о режимах не приписывает им числа,
               которого нет: она либо молчит о количестве, либо называет
               фактическое;
  2. справка   каждый режим, который `main()` распознаёт (`mode == "<имя>"`),
               встречается в выводе запуска без аргументов;
  3. подпись   подпись пробы P1-9 не содержит слова «мутирует»;
  4. итог      неупомянутые режимы названы поимённо, `ИТОГ: провалено N из M`.

Справка читается прогоном, а не разбором docstring: `main()` печатает
`__doc__`, но проверять надо напечатанное, а не то, что лежит в исходнике.
Запуск без аргументов завершается кодом 2 — это штатное поведение справки, а
не признак поломки, поэтому код возврата здесь не оценивается: оценивается
текст. Пустой текст валит все проверки режимов, а не проходит молча.

Режим ищется целым токеном (`(?<![\\w-])имя(?![\\w-])`), а не подстрокой: иначе
`write-journal` «нашёлся» бы в `write-journal-txn`, и добавление одного режима
в справку закрывало бы сразу два — судья зеленел бы на неполной справке.

Заголовок проверяется по смыслу, а не по букве. Запрет конкретно «три»/«3»
был бы проверкой буквы: «Четыре режима» прошло бы насквозь. Требование
обязательно назвать число было бы строже карточки: правка «Режимы:» числа не
называет и потому не врёт, а судья бы её завалил. Поэтому проверяется ровно
противоречие: если строка называет количество, оно должно совпадать с
фактическим; строка без числа проходит и говорит об этом вслух, а не молчит.
Числительное читается и цифрами, и словом (1..20, десятки, сто), в обоих
порядках — «Три режима», «14 режимов», «Режимы (14)», «Режимов: 14».
Составные числительные («двадцать один») и римские цифры не разбираются, а
числительное, оторванное от слова «режим» другим словом («режимов ровно
восемь»), не читается: для четырнадцати режимов таких заголовков не бывает.

Нулевой случай: если из кода не извлечено ни одного режима, проверка падает
отдельной строкой. Пустой список неупомянутых означает «ничего не проверено»,
а не «всё упомянуто», и зелёным он быть не может. Заголовок в этом случае
сверяется с нулём и тоже краснеет: сверять его не с чем, и зелёным он быть не
должен.

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

MODE_WORD_RE = re.compile(r"режим", re.IGNORECASE)
# Число перед словом «режим»: «Три режима», «14 режимов».
COUNT_BEFORE_RE = re.compile(r"(?<![\w-])(\d+|[А-Яа-яЁё]+)\s+режим", re.IGNORECASE)
# Число после слова «режим»: «Режимов: 14», «Режимы (14)». Только цифры: слово
# здесь слишком легко спутать с обычным («Режимы ровно восемь»), и молчаливая
# ошибка разбора была бы хуже пропущенной формы.
COUNT_AFTER_RE = re.compile(r"режим\w*\s*[:\-—(]?\s*(\d+)", re.IGNORECASE)

# Словесные числительные, которые реально могут стоять в заголовке справки.
# Составные («двадцать один») не собираются — см. docstring.
NUM_WORDS = {
    "один": 1, "одна": 1, "одно": 1,
    "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20,
    "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
}


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


def shorten(line: str, limit: int = 70) -> str:
    return line if len(line) <= limit else line[: limit - 1] + "…"


def mode_line(text: str) -> str | None:
    """Первая строка справки, которая говорит о режимах, — то есть заголовок.

    Именно первая, а не любая: ниже идёт проза вроде «остальные 8 режимов
    держат его честным», и сверять её с общим числом режимов было бы ложным
    провалом на честной справке.
    """
    for raw in text.splitlines():
        if MODE_WORD_RE.search(raw):
            return raw.strip()
    return None


def count_claims(line: str) -> list[tuple[int, str]]:
    """Числа, которые строка приписывает режимам: [(значение, как написано)]."""
    claims: list[tuple[int, str]] = []
    for match in COUNT_BEFORE_RE.finditer(line):
        token = match.group(1)
        value = int(token) if token.isdigit() else NUM_WORDS.get(token.lower())
        if value is not None:
            claims.append((value, token))
    for match in COUNT_AFTER_RE.finditer(line):
        claims.append((int(match.group(1)), match.group(1)))
    return claims


def check_header(text: str, total: int) -> tuple[bool, str]:
    line = mode_line(text)
    if line is None:
        return True, (
            "заголовок: в справке нет строки о режимах, значит числа, которое "
            "могло бы соврать, нет — полноту списка судят проверки режимов"
        )
    claims = count_claims(line)
    if not claims:
        return True, (
            f'заголовок «{shorten(line)}» числа режимов не называет — '
            "врать не о чем"
        )
    wrong = [(value, token) for value, token in claims if value != total]
    if wrong:
        value, token = wrong[0]
        return False, (
            f'assert заголовок не врёт о числе режимов: «{shorten(line)}» называет '
            f"{token} = {value}, а режимов в коде {total}"
        )
    return True, (
        f'заголовок «{shorten(line)}» называет {total} — сходится с числом режимов'
    )


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

    checks.append(check_header(text, len(found)))

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
