# Phase 2 — Assay: доказательство красного и вердикт по команде прогона

Дата: сессия по карточке «CI снова зелёный». База: `accept-base` @ `cb315a8bfebcd8e10f930e409ae018cf9a44d9d0`.
Окружение: Python 3.11.14, локальный ruff **0.16.3**, `uvx ruff@0.17.2` доступен.

---

## 1. Дословный красный вывод судьи

```
$ cd C:/Users/Sart-/Projects/repos/PURR && .venv/Scripts/python.exe .dev-team/judge_ci.py; echo "exit=$?"
FAIL  формат: 8 files would be reformatted, 28 files already formatted
FAIL  пин: ruff запинен как 'ruff>=0.1.0' — это диапазон, не версия
PASS  AST: нет изменённых .py относительно HEAD
PASS  тесты: 201 passed in 7.49s
ИТОГ: 2/4 проверок пройдено
exit=1
```

Воспроизводимость — **3 прогона, все `exit=1`, `2/4`**, содержательно идентичны, различается только
время pytest (`7.49s` / `7.59s` / `7.16s`). Строк, начинающихся с `ERROR`, в выводе нет.
После постановки тега детальная строка AST сменилась на `база accept-base`, остальное то же:

```
FAIL  формат: 8 files would be reformatted, 28 files already formatted
FAIL  пин: ruff запинен как 'ruff>=0.1.0' — это диапазон, не версия
PASS  AST: нет изменённых .py относительно accept-base
PASS  тесты: 201 passed in 7.16s
ИТОГ: 2/4 проверок пройдено
exit=1
```

**Красное состоялось и причина названа:** формат — 8 файлов не отформатированы; пин — `ruff>=0.1.0`
это диапазон. Причина не средовая: ruff и pytest на месте, тесты собираются и проходят.

---

## 2. Красный именно по причине из карточки, а не по посторонней

### 2.1 Линт зелёный → красный даёт форматирование, а не ошибки линта

```
$ .venv/Scripts/python.exe -m ruff check purr tests
All checks passed!
exit=0
```

### 2.2 8 файлов форматируемые, а не битые

```
$ .venv/Scripts/python.exe -m ruff format --check purr tests
unformatted: File would be reformatted
   --> purr\backend.py:172:69
   --> tests\test_backend_p1_fixes.py:65:11
  --> tests\test_fixer_pass3.py:81:11
  --> tests\test_fixer_pass4.py:42:1
   --> tests\test_fixer_pass6.py:198:29
  --> tests\test_fixer_pass7.py:35:19
   --> tests\test_fixer_pass8.py:49:34
  --> tests\test_fixer_perf_pragmas.py:39:26
8 files would be reformatted, 28 files already formatted
exit=1
```

Ни одного `failed to parse`, ни одного `error`. Список **совпадает с `## Файлы в границах` карточки
один в один**: `purr/backend.py` + те 7 тестов. Содержание диффов — переносы строк, склейка
конкатенации строк, удаление лишних пустых строк; изменения строковых литералов нет.

### 2.3 Версии ruff 0.16.3 и 0.17.2 форматируют одинаково

`--check` побайтово совпал:

```
$ diff <(0.16.3 format --check) <(uvx ruff@0.17.2 format --check)
(пусто, exit=0)
8 files would be reformatted, 28 files already formatted   # обе версии
```

Кросс-проверка на копии **вне репозитория** (`/tmp/fmtcross2`, с `pyproject.toml` проекта —
`line-length = 100`, `target-version = "py311"`):

```
format 0.16.3 (8 files reformatted) -> check 0.17.2 : exit=0  "36 files already formatted"
format 0.17.2 (36 left unchanged)   -> check 0.16.3 : exit=0  "36 files already formatted"
ruff check на отформатированной копии: 0.16.3 "All checks passed!", 0.17.2 "All checks passed!"
```

Вывод: отформатирует Chisel локальным 0.16.3 — CI-шный 0.17.2 согласится. Обратное тоже верно.
Побочный замер: без `pyproject.toml` в копии те же файлы дают `24 files reformatted` вместо 8 —
ruff берёт `line-length` из конфига проекта, копию надо брать с `pyproject.toml`, иначе замер врёт.

---

## 3. Сторож AST не слепой — негативный контроль

### 3.1 Мутация литерала меняет `ast.dump` (копия вне репозитория, `/tmp/astguard`)

```
оригинал:      ast.dump len=29708 sha1=7f8151019870
мутация PRAGMA: ast.dump len=29710 sha1=b03511a532ef
  совпадает с оригиналом? False   <- обязан быть False
мутация имени:  совпадает с оригиналом? False   <- обязан быть False
ruff format на копии: exit=0 1 file reformatted
  байты изменились? True   <- обязан быть True (иначе форматировать нечего)
отформатир.:    ast.dump len=29708 sha1=7f8151019870
  совпадает с оригиналом? True   <- обязан быть True
мутация комментариев: совпадает с оригиналом? True   <- слепое пятно, см. 3.3
```

Мутировал `"PRAGMA foreign_keys=ON"` → `"PRAGMA foreign_keys=OFF"` в `purr/backend.py` — ровно тот
литерал, что правит карточка.

### 3.2 End-to-end: судья краснеет на мутированном клоне

Клон вне репозитория (`C:/tmp/guardclone`, `PYTHONPATH` на клон, чтобы импортировался код клона).
База клона воспроизвела судью один в один (`2/4`, те же строки). Затем мутация литерала в клоне:

```
-        conn.execute("PRAGMA foreign_keys=ON")
+        conn.execute("PRAGMA foreign_keys=OFF")

FAIL  формат: 8 files would be reformatted, 28 files already formatted
FAIL  пин: ruff запинен как 'ruff>=0.1.0' — это диапазон, не версия
FAIL  AST: AST изменился у 1: purr/backend.py
PASS  тесты: 201 passed in 7.64s
ИТОГ: 1/4 проверок пройдено
```

Тесты при этом остались зелёными (201 passed) — то есть мутацию поймал именно сторож AST, а не тесты.
Это и есть доказательство, что сторож работает, а не декоративен.

### 3.3 Что сторож ловит и чего не видит (замерено)

| Сценарий | Результат |
|---|---|
| литерал изменён | **FAIL** `AST изменился у 1: purr/backend.py` |
| имя изменено | **FAIL** (sha1 ast.dump расходится) |
| файл удалён (`git rm`) | **FAIL** `AST изменился у 1: tests/test_fixer_pass3.py` |
| форматирование файла | **PASS** — задача не запрещена |
| добавлен **неотслеживаемый** новый `.py` | **PASS** `нет изменённых .py` — слепое пятно |
| изменены только комментарии / `# noqa` | **PASS** — AST их не содержит |

Слепое пятно «неотслеживаемый файл» безопасно для приёмки: в коммит он не попадёт, а закоммиченный
новый файл сторож поймает (в базе его нет → `old=None` ≠ `new=dump` → FAIL). Пятно «комментарии»
теоретически позволяет спрятать `# noqa`, но для задачи «только форматирование» это не путь.

Все отслеживаемые `.py` лежат внутри `purr/` и `tests/` (`git ls-files '*.py' | grep -v -E '^(purr|tests)/'` → пусто),
поэтому охват сторожа полный: файлов вне его диффа нет.

**Подозрение (не исполнял):** в `check_ast` при `git show` с ненулевым кодом `norm()` вернёт `None`, и
если файла нет на диске — `new` тоже `None`, сравнение даст `None == None` → PASS. Требует
одновременного сбоя `git show` и отсутствия файла; воспроизвести не пытался.

### 3.4 Полное зелёное достижимо — доказано на клоне

Отформатировал клон и поставил пин, совпадающий с окружением:

```
$ .venv/Scripts/python.exe -m ruff format purr tests
8 files reformatted, 28 files left unchanged
$ judge_ci.py
PASS  формат: 36 files already formatted
PASS  пин: ruff==0.16.3, окружение совпадает
PASS  AST: AST совпал у 8 файлов (база HEAD)
PASS  тесты: 201 passed in 8.05s
ИТОГ: 4/4 проверок пройдено
exit=0
```

Строка `AST совпал у 8 файлов` — прямое доказательство, что форматирование всех 8 файлов не меняет
ни одного AST. Судья проходим, красное снимается ровно той правкой, что в карточке.

---

## 4. Вердикт по команде прогона

**Команда прогона подходит: да.** `.venv/Scripts/python.exe .dev-team/judge_ci.py` — годный судья:
падает сейчас по названной причине, воспроизводима (3/3), зеленеет ровно на правке из карточки,
ловит мутацию AST, повторяет команды CI дословно (`ci.yml:42-47`:
`ruff check purr tests`, `ruff format --check purr tests`,
`pytest --cov=purr --cov-report=term-missing --cov-fail-under=85`).

**Но с карточкой не сходится одно место, и оно блокирующее.**

Карточка (`## Что меняем`) требует пин **`ruff==0.17.2`**. Проверка `check_pin` судьи требует, чтобы
пин совпал с **установленной в `.venv`** версией, а там 0.16.3:

```
# клон, pyproject: "ruff==0.17.2"
FAIL  пин: пин 0.17.2, в окружении 0.16.3
ИТОГ: 2/4 проверок пройдено

# клон, pyproject: "ruff==0.16.3"
PASS  пин: ruff==0.16.3, окружение совпадает
```

То есть буквальное исполнение карточки (`ruff==0.17.2` в `pyproject.toml`) даёт **вечно красную**
проверку пина, и гейт не закрывается никогда. Требуется решение Keel, одно из двух:

- **ПРАВКА (рекомендую):** в `## Что меняем` и `## Файлы в границах` добавить шаг окружения —
  «`.venv` обновить до ruff 0.17.2 (`pip install ruff==0.17.2`), затем прогон судьи». `.venv`
  не отслеживается git, границы файлов это не нарушает, и тогда пин 0.17.2 совпадёт с окружением.
- либо пин в `pyproject.toml` ставить `ruff==0.16.3` и в карточке заменить `0.17.2` на `0.16.3`.
  CI тогда поставит 0.16.3; форматирование обеими версиями идентично (см. 2.3), дрейфа не будет.

Молча выбрать за Keel не могу: это меняет смысл «Что меняем» и требует правки карточки.

### Замечания к судье (не блокирующие)

- **P2.** Судья не запускает `ruff check purr tests`, а CI запускает (`ci.yml:42`). Проверил
  эмпирически: после форматирования линт зелёный обеими версиями, так что ложного зелёного сейчас
  не будет. Но полным прокси «CI зелёный» судья не является — стоит добавить пятой проверкой.
- **P3.** `check_pin` понимает только `==` и `>=`. Пин вида `==0.17.2,<0.18` или `~=0.17` даст
  сообщение «пин 0.17.2,<0.18, в окружении 0.16.3», то есть строгий пин будет отвергнут с невнятной
  причиной. Для `==0.17.2` работает верно.
- **P3.** Docstring `judge_ci.py:3-8`: «Три проверки», пункт «4. pytest» продублирован дважды
  (строки 7 и 8). Косметика.

---

## 5. Тег базы

```
$ git tag -l 'accept-*'          # до: пусто
$ git tag accept-base HEAD && git rev-parse accept-base
cb315a8bfebcd8e10f930e409ae018cf9a44d9d0
```

`accept-base` = `cb315a8` = текущий `HEAD`. Коммитов не создавал. Отслеживаемые файлы не менял:
`git status --porcelain` → только `?? HARNESS-RESULTS.md`. Все временные копии — вне репозитория
(`C:/tmp/astguard`, `C:/tmp/guardclone`, `C:/tmp/fmtcross2`).

---

## 6. Не проверял

1. **Резолв `pip install -e ".[dev]"` на CI** — что GitHub Actions действительно поставит 0.17.2
   при пине `==0.17.2`. Сети не трогал; утверждение «CI резолвит 0.17.2» взято из карточки, не измерено.
2. **Матрицу Python 3.12 / 3.13** из `ci.yml:25` — локально только 3.11.14, `201 passed` замерено на 3.11.
3. **Реальную правку в репозитории** — 4/4 зелёное получено на клоне, в рабочем дереве я ничего не
   форматировал (не моя роль и запрещено границами).
4. **`CHANGELOG.md`** — требование карточки, судьёй не проверяется и мной не оценивалось.
5. **Флаки тестов** — гонял судью 3 раза (все одинаковы), но 201 тест по отдельности на флаки не проверял.
6. **Слепое пятно `norm() -> None`** из 3.3 — подозрение, воспроизведения не делал.

---

## 7. Перенос стенда в репозиторий и перестановка тега accept-base

Заход 2. Стенд перенесён байт-в-байт, тег `accept-base` переставлен на коммит переноса.
Логика стенда не тронута: ни строки не правил.

### 7.1 Перенос без правки содержимого

Источник: `C:/Users/Sart-/WorkBuddy AI/2026-10-24-07-59-40/harness/crash_harness.py`
Копия в репозитории: `tools/crash_harness.py` (каталога `tools/` до этого не было — создан)

| Что | Источник | Копия | Блоб в коммите |
|---|---|---|---|
| sha256 | `745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887` | `745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887` | `745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887` |
| размер, байт | 20459 | 20459 | 20459 |

Доказательства равенства:

```
$ cp "<источник>" tools/crash_harness.py ; echo "cp exit=$?"
cp exit=0
$ cmp "<источник>" tools/crash_harness.py ; echo "cmp exit=$?"
cmp exit=0 (0 = identical)
$ sha256sum "<источник>" tools/crash_harness.py
745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887 *C:/Users/Sart-/WorkBuddy AI/2026-10-24-07-59-40/harness/crash_harness.py
745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887 *tools/crash_harness.py
$ wc -c "<источник>" tools/crash_harness.py
20459 <источник>
20459 tools/crash_harness.py
```

Копия сделана `cp`, не текстовым инструментом (предупреждение о CRLF в задании учтено).
CR-байт в источнике: 0, в копии: 0 — файл чисто LF. `core.autocrlf=true` и правило
`.gitattributes` `*.py text eol=lf` на этот файл не влияют: содержимое блоба в git
совпадает с файлом побайтно, проверено чтением объекта, а не рабочего файла:

```
$ git cat-file blob HEAD:tools/crash_harness.py | sha256sum
745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887 *-
$ git cat-file blob HEAD:tools/crash_harness.py | wc -c
20459
```

### 7.2 Коммит переноса

Один коммит, один файл. Стадия проверена до коммита: `git diff --cached --name-only`
показал ровно `tools/crash_harness.py`.

```
$ git add tools/crash_harness.py && git commit -m "test(harness): move the crash harness into the repository"
[main afb5f31] test(harness): move the crash harness into the repository
 1 file changed, 544 insertions(+)
 create mode 100644 tools/crash_harness.py

$ git show --stat --oneline HEAD
afb5f31 test(harness): move the crash harness into the repository
 tools/crash_harness.py | 544 +++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 544 insertions(+)
```

**Коммит переноса: `afb5f312f72d5ce54d764334d53bcb6fd30704a4`** (`afb5f31`).

### 7.3 Перестановка тега

`git tag -f` не использовал — старый тег снят, новый поставлен заново:

```
$ git tag -d accept-base
Deleted tag 'accept-base' (was 0590229)
$ git tag accept-base HEAD
$ git rev-parse HEAD
afb5f312f72d5ce54d764334d53bcb6fd30704a4
$ git rev-parse accept-base
afb5f312f72d5ce54d764334d53bcb6fd30704a4
$ git log --oneline -1 accept-base
afb5f31 test(harness): move the crash harness into the repository
$ git ls-tree -r accept-base --name-only | grep tools/
tools/crash_harness.py
```

**Тег `accept-base` = `afb5f312f72d5ce54d764334d53bcb6fd30704a4`**, до перестановки был
`0590229908437a3d84b224543fcaa463d3e62717` (коммит `0590229`, документация).

### 7.4 Прогон в рабочем дереве

```
$ cd C:/Users/Sart-/Projects/repos/PURR && PYTHONPATH=. .venv/Scripts/python.exe tools/crash_harness.py run-journal-txn 1; echo "exit=$?"
run 1: маркер сброса=да | tx в KV 500/500 | событий tx 3 | разрыв 497 | integrity ok / журнал ok
exit=0
```

### 7.5 Прогон в свежем клоне на accept-base

Клон вне репозитория: `mktemp -d` → `tmp.nrvJ1N7lfm/base`, `git clone --no-hardlinks`,
затем `git checkout accept-base`. Файл в клоне есть, дерево клона чистое:

```
$ git -C "$TMP/base" rev-parse accept-base
afb5f312f72d5ce54d764334d53bcb6fd30704a4
$ sha256sum "$TMP/base/tools/crash_harness.py"
745eea163ce607be66b866fb11023231862b6f7e0e895cb4211db582bf436887 *.../base/tools/crash_harness.py
$ wc -c "$TMP/base/tools/crash_harness.py"
20459 .../base/tools/crash_harness.py
$ git -C "$TMP/base" status --porcelain
(пусто)
```

Прогон в клоне (интерпретатор — венв основного репозитория по абсолютному пути:
`.venv/` в `.gitignore:33` и в клон не попадает; `SELF = os.path.abspath(__file__)`,
поэтому дочерние процессы берут файл клона, а не рабочего дерева):

```
$ cd "$TMP/base" && PYTHONPATH=. "<repo>/.venv/Scripts/python.exe" tools/crash_harness.py run-journal-txn 1; echo "exit=$?"
run 1: маркер сброса=да | tx в KV 500/500 | событий tx 3 | разрыв 497 | integrity ok / журнал ok
exit=0
```

Вывод в клоне совпадает с рабочим деревом до последнего символа. Стенд в клоне есть и
работает — это и требовалось доказать переносом.

### 7.6 Устойчивость вывода (не флаки)

Стенд использует `random`, поэтому одного прогона мало. Шесть прогонов, все одинаковые:
3 в рабочем дереве + 3 в клоне → каждый `разрыв 497`, `exit=0`.

```
--- работа дерево, прогон 1/2/3 ---
run 1: маркер сброса=да | tx в KV 500/500 | событий tx 3 | разрыв 497 | integrity ok / журнал ok
exit=0        (×3, вывод идентичен)
--- клон accept-base, прогон 1/2/3 ---
run 1: маркер сброса=да | tx в KV 500/500 | событий tx 3 | разрыв 497 | integrity ok / журнал ok
exit=0        (×3, вывод идентичен)
```

### 7.7 Что этот шаг НЕ доказывает

Перенос доказывает только то, что стенд доступен из репозитория и воспроизводит дефект.
Он **не** доказывает, что стенд умеет отказывать: сейчас на `HEAD` он печатает
`разрыв 497` и возвращает `0`, то есть дефект жив. Красное по критерию карточки
(`exit=1` при разрыве) появится только после правки Chisel; негативный контроль
(«стенд, который всегда возвращает 0, приёмку не проходит») ставит Warder на приёмке.

Состояние рабочего дерева после шага (до правки этой заметки): ` M .dev-team/card.md`
(правка Keel), `?? .dev-team/archive/judge_ci.py.bak`, `?? HARNESS-RESULTS.md` — чужое,
не трогал.
