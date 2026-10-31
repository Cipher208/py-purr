"""Судья задачи «docstring набора проб не обещает результат, которого нет».

Дефект: в docstring `.dev-team/audit_probes.py` стоял абзац «Ожидаемый
результат на базе: ... P1-9 и P1-10 — BROKEN (находки живы)». Он был верен при
создании файла, но находки закрыты, прогон даёт `HOLDS 14, BROKEN 0`, а тегов
`accept-*` («базы») больше нет. Документация обещала исход, которого нет.

Тот же оборот стоял не только в модульном docstring: у каждой пробы своя проза,
и «на базе» нашлось в docstring'ах `probe_p1_9b` (строки 750 и 766) и
`probe_p1_10b` (строка 847). Судья, читающий только модульный docstring,
проверял половину дефекта, поэтому проверка 4 обходит все docstring'и модуля.

Четыре проверки, каждая — одно утверждение:
  1. нет устаревшего обещания — в docstring модуля нет ни одного оборота из
     FORBIDDEN_PHRASES и ни одного вердикта вида «P1-N — BROKEN» вне условной
     конструкции («... если ...»);
  2. инвариант сформулирован — docstring утверждает, что на текущем `main` все
     пробы дают HOLDS, а BROKEN означает регресс;
  3. прогон подтверждает инвариант — `audit_probes.py` возвращает 0 и печатает
     `BROKEN 0`;
  4. ссылки на базу нет ни в одном docstring'е — оборота «на базе» нет ни в
     модульном docstring'е, ни в docstring'ах функций, методов и классов.

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

Проверка 4 устроена иначе: она не формулирует требование, а обходит дерево и
берёт docstring каждого узла, поэтому видит и прозу проб, которую проверка 1
прочитать не может. Место называется парой «имя узла:строка»: на файле в 900
строк возврат «где-то есть оборот» не адресуем. Строка считается от строки
литерала плюс число переносов до совпадения, поэтому два оборота в одном
docstring'е дают две разные строки, а не одну. Обход нулевой: если docstring'ов
не нашлось ни одного, проверка 4 падает — пустой обход не доказывает отсутствия
оборота.

Причина падения печатается в форме `AssertionError: ...`: красный прогон
обязан называть упавшее утверждение и значение, а не только слово FAIL.
Код возврата: 0 — все четыре PASS, 1 — есть FAIL, 2 — судья сломался сам
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

# Ссылка на базу, которой больше нет. Проверка 4 ищет её во всех docstring'ах, а
# не только в модульном. Шаблон терпит перенос строки внутри оборота
# («на\n    базе»): иначе вёрстка по 79 символов прячет его от поиска.
_BASE_REFERENCE = re.compile(r"на\s+базе", re.IGNORECASE)

# Узлы, у которых `ast.get_docstring` вообще имеет право быть вызванным: на
# остальных он бросает TypeError, и судья вернул бы 2 («сломался сам») вместо
# вердикта. Замерено: `get_docstring` на `ast.Expr` — `TypeError: 'Expr' can't
# have docstrings`.
_DOCSTRING_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

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


def _docstring_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Родитель каждого узла дерева.

    `ast.walk` отдаёт узлы без ссылки вверх, а имя docstring'а собирается как
    раз снизу вверх (`Store.sweep`, а не `sweep`). Карта строится тем же
    обходом: для каждого узла перечисляются его дети.
    """
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _qualified_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """Имя узла так, как его ищут в файле: `probe_p1_9b`, `Store.sweep`, `<module>`.

    Модуль в префикс не попадает: у всех верхнеуровневых имён общий префикс
    `<module>.` не различает ничего. Само дерево модуля называется `<module>`,
    иначе у него не осталось бы имени вовсе.
    """
    parts: list[str] = []
    current: ast.AST | None = node
    while current is not None and not isinstance(current, ast.Module):
        name = getattr(current, "name", None)
        if name:
            parts.append(name)
        current = parents.get(current)
    return ".".join(reversed(parts)) or "<module>"


def docstring_locations() -> list[tuple[str, str, int]]:
    """Все docstring'и модуля как `(имя узла, текст, строка литерала)`.

    Читается тот же AST, что и в `module_docstring`, но не только вершина:
    `ast.get_docstring` вызывается у модуля, каждого класса, каждой функции и
    каждого метода. Порядок — обход `ast.walk` (в ширину), он детерминирован,
    поэтому вывод судьи воспроизводим.
    """
    tree = ast.parse(PROBES_PATH.read_bytes().decode("utf-8"), filename=str(PROBES_PATH))
    parents = _docstring_parents(tree)
    found: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_NODES):
            continue
        doc = ast.get_docstring(node, clean=False)
        if doc is None:
            continue
        # `node.body[0]` — тот самый строковый литерал, из которого взят
        # docstring, поэтому его строка и есть начало отсчёта.
        found.append((_qualified_name(node, parents), doc, node.body[0].lineno))
    return found


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


def check_no_base_reference_anywhere() -> str:
    """Ни в одном docstring'е модуля нет ссылки на базу, которой больше нет."""
    locations = docstring_locations()
    assert locations, (
        "в audit_probes.py не найдено ни одного docstring'а: проверять нечего, и "
        "пустой обход не считается отсутствием оборота"
    )

    hits: list[str] = []
    for name, doc, literal_line in locations:
        for match in _BASE_REFERENCE.finditer(doc):
            line = literal_line + doc[: match.start()].count("\n")
            hits.append(f"{name}:{line}")

    assert not hits, (
        f"оборот «на базе» найден {len(hits)} раз(а), просмотрено docstring'ов: "
        f"{len(locations)}: " + ", ".join(hits)
    )
    return f"«на базе» нет ни в одном из {len(locations)} docstring'ов модуля"


CHECKS = (
    ("нет устаревшего обещания", check_no_stale_promise),
    ("инвариант сформулирован", check_invariant_stated),
    ("прогон подтверждает инвариант", check_run_confirms),
    ("нет ссылки на базу ни в одном docstring", check_no_base_reference_anywhere),
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
