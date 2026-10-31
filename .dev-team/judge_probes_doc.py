"""Судья задачи «docstring набора проб не обещает результат, которого нет».

Дефект: в docstring `.dev-team/audit_probes.py` стоял абзац «Ожидаемый
результат на базе: ... P1-9 и P1-10 — BROKEN (находки живы)». Он был верен при
создании файла, но находки закрыты, прогон даёт `HOLDS 14, BROKEN 0`, а тегов
`accept-*` («базы») больше нет. Документация обещала исход, которого нет.

Три проверки, каждая — одно утверждение:
  1. нет устаревшего обещания — в docstring модуля нет ни одного оборота из
     FORBIDDEN_PHRASES и ни одного вердикта вида «P1-N — BROKEN» вне условной
     конструкции («... если ...»);
  2. инвариант сформулирован — docstring утверждает, что на текущем `main` все
     пробы дают HOLDS, а BROKEN означает регресс;
  3. прогон подтверждает инвариант — `audit_probes.py` возвращает 0 и печатает
     `BROKEN 0`.

Проверка 1 — запрет, проверка 2 — требование, и по отдельности каждая
вакуумна: на пустом docstring запрет молчит, а текст без запрещённых оборотов
проходит запрет, ничего не утверждая. Поэтому пустота ловится явно в обеих
(docstring обязан существовать и быть непустым), а проверка 3 не даёт судье
остаться текстовым: если находка вернётся и проба покраснеет, судья
покраснеет вместе с ней.

Что проверка 1 запрещает. Сравнение идёт по нормализованному тексту: нижний
регистр, `—`/`–`/`−` -> `-`, пробелы схлопнуты, поэтому перенос строки не
спасает устаревший абзац от совпадения.
  «находки живы»          — прямое утверждение, что находки не закрыты;
  «ожидаемый результат»   — обещание конкретного исхода прогона;
  «на базе»               — ссылка на базу, которой больше нет;
  «p1-9 и p1-10 - broken» — дословная устаревшая пара;
  «P1-N — BROKEN»         — вердикт пробы, обещанный без условия. Условное
                            «P1-9 — BROKEN, если get() снова начнёт писать»
                            законно и не запрещается: рядом с вердиктом стоит
                            «если/когда/при/в случае».

Что проверка 2 принимает. Точная цитата не требуется, нужны три смысла,
каждый — любой из своих формулировок:
  все пробы HOLDS:   «main|текущ...|сегодняшн...» + «все|всех|кажд...|
                     ни одн...|люб...» + «HOLDS» в одном предложении, в любом
                     порядке слов («на текущем main все 14 проб дают HOLDS»,
                     «все пробы HOLDS на текущем main»);
  BROKEN = регресс:  «BROKEN» рядом с «регресс...|снова|вновь|опять|повторно|
                     вернул...|воспроизв...|появ...» в любую сторону.
Пустой docstring, docstring без инварианта и docstring, где «все HOLDS»
говорится только про код возврата («0 — все HOLDS»), проверку валят: без
привязки к `main`/текущему состоянию это описание кода возврата, а не
утверждение об инварианте.

Причина падения печатается в форме `AssertionError: ...`: красный прогон
обязан называть упавшее утверждение и значение, а не только слово FAIL.
Код возврата: 0 — все три PASS, 1 — есть FAIL, 2 — судья сломался сам
(исключение не является ассертом, вердикт не выносится).
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBES_PATH = HERE / "audit_probes.py"
ROOT = HERE.parent

# Обороты, каждый из которых обещает исход прогона или ссылается на базу,
# которой больше нет. Список, а не одна подстрока: видно, что именно запрещено,
# и новая формулировка того же обещания добавляется одной строкой.
FORBIDDEN_PHRASES = (
    "находки живы",
    "ожидаемый результат",
    "на базе",
    "p1-9 и p1-10 - broken",
)

# Вердикт пробы, обещанный без условия: «P1-9 и P1-10 — BROKEN».
_VERDICT_PROMISE = re.compile(r"p1-\d+[a-z]?\s*(?:и\s+p1-\d+[a-z]?\s*)?-\s*broken")
_CONDITIONAL = re.compile(r"\b(если|когда|при|в случае)\b")

# Инвариант «на текущем main все пробы HOLDS». Порядок слов любой, но все три
# части обязаны стоять в одном предложении: «все HOLDS» без привязки к main —
# это описание кода возврата, а не утверждение о текущем состоянии.
ALL_HOLDS = (
    r"(main|текущ\w*|сегодняшн\w*)[^.]{0,100}(все|всех|кажд\w*|ни одн\w*|люб\w*)[^.]{0,60}"
    r"\bholds\b",
    r"(все|всех|кажд\w*|ни одн\w*|люб\w*)[^.]{0,60}\bholds\b[^.]{0,60}(main|текущ\w*|сегодняшн\w*)",
)

# Инвариант «BROKEN означает регресс» — вторая половина утверждения.
BROKEN_MEANS_REGRESSION = (
    r"\bbroken\b[^.]{0,100}(регресс\w*|снова|вновь|опять|повторно|вернул\w*|воспроизв\w*|появ\w*)",
    r"(регресс\w*)[^.]{0,100}\bbroken\b",
)

_DASHES = str.maketrans({"—": "-", "–": "-", "−": "-", "«": '"', "»": '"'})


def _normalise(text: str) -> str:
    """Приводит docstring к виду, в котором сравнение не зависит от вёрстки.

    Переносы строк и двойные пробелы схлопываются: устаревший абзац,
    разбитый на строки по 79 символов, обязан совпасть так же, как одна
    строка. Тире унифицируется, потому что «P1-9 и P1-10 — BROKEN» и
    «P1-9 и P1-10 - BROKEN» — одно и то же обещание.
    """
    return " ".join(text.translate(_DASHES).lower().split())


def module_docstring() -> str:
    """Docstring модуля `audit_probes.py` — по AST, без импорта и исполнения.

    Импорт запускал бы `sys.path`-правку и `from purr import ...`, то есть
    проверка текста зависела бы от того, что модуль вообще импортируется.
    AST читает ровно первый строковый литерал модуля.
    """
    tree = ast.parse(PROBES_PATH.read_bytes().decode("utf-8"), filename=str(PROBES_PATH))
    return ast.get_docstring(tree, clean=False) or ""


def _first_match(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def check_no_stale_promise() -> str:
    """В docstring нет оборота, обещающего конкретный исход прогона."""
    doc = module_docstring()
    assert doc.strip(), (
        "docstring модуля отсутствует или пуст: проверять нечего, и пустота не "
        "считается отсутствием обещания"
    )
    text = _normalise(doc)

    violations = [f"оборот {phrase!r}" for phrase in FORBIDDEN_PHRASES if phrase in text]
    for match in _VERDICT_PROMISE.finditer(text):
        # Условное утверждение законно: оно называет, при каком регрессе проба
        # покраснеет, а не обещает BROKEN сейчас.
        if not _CONDITIONAL.search(text[match.end() : match.end() + 80]):
            violations.append(f"вердикт без условия {match.group(0)!r}")

    assert not violations, "docstring обещает исход прогона: " + "; ".join(violations)
    return (
        f"ни одного из {len(FORBIDDEN_PHRASES)} запрещённых оборотов и ни одного "
        "вердикта «P1-N — BROKEN» без условия"
    )


def check_invariant_stated() -> str:
    """Docstring утверждает инвариант: все пробы HOLDS на main, BROKEN = регресс."""
    doc = module_docstring()
    text = _normalise(doc)
    assert text, "docstring модуля отсутствует или пуст: инвариант не сформулирован"

    missing: list[str] = []
    if not _first_match(ALL_HOLDS, text):
        missing.append("«на текущем main все пробы дают HOLDS»")
    if not _first_match(BROKEN_MEANS_REGRESSION, text):
        missing.append("«BROKEN означает регресс»")

    assert not missing, "docstring не формулирует инвариант, нет утверждения " + ", ".join(
        missing
    )
    return "инвариант на месте: все пробы HOLDS на текущем main, BROKEN назван регрессом"


def check_run_confirms() -> str:
    """Прогон набора проб действительно даёт `BROKEN 0` и код 0."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(PROBES_PATH)],
        cwd=ROOT,
        capture_output=True,
        env=env,
        timeout=300,
    )
    out = proc.stdout.decode("utf-8", "replace")
    summary = next(
        (line.strip() for line in out.splitlines() if "HOLDS" in line and "BROKEN" in line),
        "",
    )
    where = summary or "строка ИТОГ в выводе не найдена"

    assert proc.returncode == 0, (
        f"audit_probes.py вернул {proc.returncode}, нужен 0: {where}"
    )
    assert "BROKEN 0" in out, f"в выводе нет «BROKEN 0»: {where}"
    return f"{where} -> exit=0"


CHECKS = (
    ("нет устаревшего обещания", check_no_stale_promise),
    ("инвариант сформулирован", check_invariant_stated),
    ("прогон подтверждает инвариант", check_run_confirms),
)


def main() -> int:
    failed = 0
    for name, check in CHECKS:
        try:
            detail = check()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: AssertionError: {exc}")
        except Exception as exc:  # noqa: BLE001 - сломанный судья не должен выдавать себя за вердикт
            print(
                f"ОШИБКА: проверка {name!r} упала не ассертом: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 2
        else:
            print(f"PASS  {name}: {detail}")
    print(f"ИТОГ: провалено {failed} из {len(CHECKS)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
