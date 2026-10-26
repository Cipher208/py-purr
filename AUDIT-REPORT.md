# AUDIT-REPORT.md — py-purr (PURR)

Дата: 2026-10-26. Репо: github.com/Cipher208/py-purr, HEAD `cfbea9e` на момент аудита, рабочее дерево чистое.
Метод: пять независимых линз (эксплуатация / корректность / структура-данные / архитектура-оптимизация / покрытие тестами), аудиторы работали параллельно без обмена находками; сведение и калибровка — главный аудитор; верификатор с независимым контекстом воспроизвёл 2 случайные находки прогонами (обе подтверждены) и проверил нулевую пробу по SQL (уточнена: f-string SQL две — backend.py:39 и backend.py:50, обе не эксплуатируемы).

**Сводка:** 95 тестов проходят (`uv run pytest -q`), coverage 92% — и тем не менее: **10 × P1, 13 × P2, ~12 × P3**. Все P1 подтверждены прогонами либо дословным кодом с двумя независимыми линзами. P0 нет: в библиотечном виде (доверенный код, один процесс) ничего не рвёт данные «сейчас», но половина P1 становится P0 при multi-tenant/недоверенных источниках — условия указаны. Coverage высокий и не значит ничего: все известные баги лежат на покрытых строках.

---

## P1 🔴

**P1-1. Флаг транзакции отравляется навсегда, записи молча теряются** — `store.py:64-68`
`self._in_transaction = True` ставится ДО `BEGIN IMMEDIATE`, вне try. Один сбой BEGIN (lock > busy_timeout 5 с) → флаг застревает True: все `transaction()` дают ложный «nested transaction not supported», `set()`/`delete()` проходят «успешно», но `_commit()` (store.py:53-56) — no-op, записи копятся в незакрытой транзакции и теряются. Верификатор: после сбоя BEGIN `set('k','v')` из нового соединения → `None`.

**P1-2. Общий `_in_transaction` между потоками** — `store.py:31`, `backend.py:44-52`
Соединения per-thread (threading.local), флаг — на инстансе один. Второй поток в `transaction()` → ложный RuntimeError + молчаливая потеря его записи; `_commit()` любого потока подавлен, пока флаг поднят. store.py:24 обещает «Thread-safe». Подтверждено двумя независимыми линзами.

**P1-3. incr/decr не атомарны** — `store.py:203-216`
SELECT → Python → set(), без BEGIN IMMEDIATE. Прогон: 4 потока × 200 incr → 200 вместо 800. Для счётчиков/квот/лимитов — тихий недочёт.

**P1-4. incr воскрешает истёкший ключ** — `store.py:206, 215, 126`
SELECT в incr не смотрит `kv_meta.expires_at`; `set(..., ttl=None)` удаляет мету. Верификатор: `set('ctr',100,ttl=0.2)`, sleep 0.4, `incr` → 101, ttl → None (Redis дал бы 1).

**P1-5. События подделываемы: `INSERT OR REPLACE`** — `event_stream.py:67, 138`
append события с существующим id молча перезаписывает старое (воспроизведено: оригинал исчез, payload подменён); курсоры любого консьюмера перезаписываемы. README и docstring обещают «append-only» — этого нет. При недоверенных источниках событий — P0.

**P1-6. Saga: повторный execute стреляет чужими компенсациями** — `saga.py:80-92, 107-109`
`execute()` не сбрасывает per-step `status`; `_compensate` компенсирует всё COMPLETED, включая шаги прошлого запуска. Прогон: run 2 (один падающий шаг) вызвал COMP1 из run 1: `log: ['act1','boom','COMP1']`. Также `saga.data` не откатывается после компенсации; компенсация самого падшего шага не предпринимается (`range(failed_step-1,...)`), а README говорит «automatic rollback» без этой оговорки.

**P1-7. `publish_sync` не доставляет события** — `event.py:75-79`
Только `_history.append`, хендлеры не вызываются (в отличие от `publish`, event.py:61-73). Прогон: подписчик → 0 вызовов. Все side effects в sync-контексте молча не происходят. Найдено всеми тремя линзами независимо.

**P1-8. Два engine на одном db-файле ломают миграции** — `backend.py:34-40`
`PRAGMA user_version` — глобальный счётчик на файл, не per-engine. Воспроизведено: `Store(shared.db)` → `EventStream(shared.db)` → user_version=1, миграции EventStream пропущены, таблица events не создана, `append()` → `no such table: events`. При этом `SQLiteBackend` документирован как «Base for file-backed engines sharing one SQLite database file» (backend.py:17).

**P1-9. `get()` мутирует хранилище** — `store.py:139-141`
Чтение просроченного ключа выполняет delete + journal-emit + commit внутри get. Замер: `get(expired)` породил событие в журнале. «Чтение не мутирует» нарушено: read-подписчик журнала видит delete от get; get() может бросить `database is locked` на ЧТЕНИИ.

**P1-10. `db_stats` неверно считает WAL для путей без суффикса** — `backend.py:80`
`with_suffix(".db-wal")`: для `Store("nosuffix")` ищет `nosuffix.db-wal`, SQLite создаёт `nosuffix-wal`. Замер: `wal_bytes: 0` при живом WAL. Рост WAL невидим для maintain()/мониторинга — тихая неправда.

## P2 🟠

**Корректность/данные:**
- **FK объявлены, не включены** — `PRAGMA foreign_keys`=0 (backend.py:46-51); ключи в схеме (store.py:96, state_machine.py:99) — декорация. Проверено.
- **Журнал не атомарен с коммитом** — store.py:128-129: crash между commit и `_journal_emit` = данные есть, события нет. Внутри transaction() тот же порядок: `conn.commit(); self._journal_flush()` (store.py:71-72) — исключение во flush после успешного коммита выглядит у caller'а как откат. Замер: mset 5k с журналом 0.65s против 0.02s без — 32× замедление, каждый append — отдельный commit.
- **Event stream без retention** — event_stream.py:180-181 «Never prunes»; 7 610 app/s → ~27 млн строк/час; ротации нет, `clear()` сбрасывает все курсоры.
- **Cursor на несуществующий id = вечный блок** — event_stream.py:107-110: NULL-подзапрос, сравнение всегда false; read → `[]` навсегда. Пустой read возвращает `last_id=""` (falsy) — консьюмер, сохранив его, получает replay с начала.
- **StateMachine: переходы не персистятся** — state_machine.py:68 (RAM) при персистентном состоянии; рестарт → `send()` молча False. Плюс action/on_exit выполняются до `_save_state` (state_machine.py:151-163) — упавший on_enter оставляет «закоммиченное» состояние; half-applied transition без отката action.
- **Versioning: дыра в цепочке миграций молча оставляет старую версию** — versioning.py:44-47 break без ошибки; forged high version пропускает все миграции; `migrate` мутирует Event in-place (versioning.py:48-49, замер: same object True) — ломает immutable-события.
- **ttl() против docstring** — store.py:185 возвращает произвольный негатив (замер −0.101); истёкшие ключи видны в `keys()`/`size()` до sweep. README «TTL auto-expiry» — expiry только lazy/ручной.
- **Исключения как система отсутствуют** — наружу протекает `sqlite3.OperationalError` (замер); семантика ошибок разнобой: TypeError / RuntimeError / False / None без единого кастомного исключения.
- **README против кода по durability** — Saga (saga.py:39-51), EventBus history, RetryHandler — чисто in-memory, процесс упал — всё потеряно; README:24,99 продаёт saga как замену Celery-сценариев без оговорки.
- **Жизненный цикл ресурсов** — `close()` закрывает только конн текущего потока (backend.py:54-59), остальные утекают до GC и держат WAL-read-locks; `__del__`/context manager нет; `backup()` дважды по тому же пути падает `output file already exists` (backend.py:73).
- **Расширяемость Backend хрупкая** — подкласс перезаписывает MIGRATIONS целиком; SCHEMA_VERSION объявлен в 3 местах и нигде не проверяется; `executescript` (backend.py:38) исполняет DDL вне единой транзакции (частичная миграция — гипотеза).

**Оптимизация (замеры на 50k kv / 100k events):**
- **Append по одному с коммитом: 7 494 app/s; батч в одной транзакции: 181 605 (24×)** — batch API отсутствует.
- **read(cursor+topic): TEMP B-TREE сортировка** — EQP подтверждает; лечится композитным индексом `(topic, timestamp, rowid)` (оценка ~1ms вместо 20.7ms на 100 строк — гипотеза, индекс не создавал). Аналогично `count_since(topic=...)` 12.5ms против 1.0ms.
- **sweep: SCAN kv_meta** — нет индекса на expires_at; при 50k TTL-ключей full scan + N+1 delete.
- **PRAGMA недокрутка** (замер значений): cache_size=-2000 (2MB), mmap_size=0, temp_store=0, journal_size_limit=-1 (WAL не обрезается — усилитель роста).
- **mget = N×2 запросов** — 1000 ключей = 10.2ms; единый `IN (...)` дал бы ~1-2ms.

## P3 🟢

- set() = 2 лишних SELECT: 17k оп/с vs get 94-103k; один `INSERT ... ON CONFLICT ... RETURNING` схлопывает 3 запроса в 1.
- PRAGMA f-строки backend.py:39 и backend.py:50 — сейчас безопасны (внутренние int), укрепить.
- WAL растёт ~2,3× БД без авточекпоинтов (замер 1.8 МБ / 4.1 МБ).
- retry: max_delay клампится до jitter → эффективный max 1.5×; `_pending` (retry.py:41) — мёртвый код.
- TTL-экспирация в журнале неотличима от явного delete (store.py:140).
- Курсорная семантика зависит от часов продюсера (event_stream.py:106-109) — гипотеза о skew.
- health.py:71-77 — не-bool результат check_fn молча игнорируется.
- `keys()` LIKE case-insensitive для ASCII — расходится с Redis KEYS (проверено по коду).
- rate-limit refill / dedup TTL expiry внутри middleware не покрыты и частично не написаны эффективно (DedupMiddleware `_evict` — O(n log n) sort, middleware.py:105).
- EventBus: handlers + wildcard создают новый список на каждый publish (event.py:70) — микро.
- type=__name__ в kv-значениях пишется, при get не используется — похоже, мёртвое поле (не проверено на круг).

## Архитектура — что чисто

Слои не протекают: backend владеет соединением/pragmas/миграциями, SQLite не наружу (Row + JSON на границе); циклических импортов нет (TYPE_CHECKING guards); module-level state нет; миграции версионированы через user_version, апгрейд v0→1 работает; SQL параметризован (кроме двух PRAGMA f-строк), LIKE-escaping корректен (backslash → %/_ → ESCAPE). Benchmark (Windows, repo venv): get 94-103k оп/с, set 17k, append 7.5k (батч 181k), read ~137k событий/с, bus.publish 128k оп/с.

## Закрытость тестами — чего не хватает

Coverage: **92%** (реальный прогон `uv run pytest --cov=purr --cov-report=term-missing`, 95 passed). Слабые места по строкам: middleware.py 68%, health 89%, state_machine 93%; точечно — store.py:65, event.py:65/79/90, event_stream.py:182-188, versioning.py:47, state_machine.py:262-269.

**Главный вывод: все 10 багов P1 лежат на покрытых строках — line coverage маскирует отсутствие поведенческих тестов.** В suite нет ни одного threading-теста (test_concurrency.py проверяет только значения PRAGMA).

Отсутствующие тесты по цене пропуска:

**P1-пробелы (каждый тест сейчас падал бы или закрепляет баг):**
1. `test_transaction_flag_reset_on_begin_failure` — сбой BEGIN → флаг сброшен (находка P1-1; строка store.py:65 не покрыта).
2. `test_incr_concurrent_threads` (N×M == N*M) и `test_incr_expired_key_resurrects` (P1-3, P1-4).
3. `test_append_same_id_overwrites` — документирует подмену истории (P1-5).
4. `test_publish_sync_calls_subscribers` (P1-7; строки event.py:65/79/90 не покрыты) и `test_subscriber_exception_swallowed_documented`.
5. `test_saga_reexecute_after_failure` — компенсации прошлого запуска не стреляют (P1-6); `test_saga_data_rolled_back_on_compensation`.
6. `test_read_cursor_nonexistent_id` и `test_empty_read_last_id_contract` (P2 cursor).
7. `test_reopen_send_without_reregistering_transitions` — сейчас молча False (P2 FSM).
8. `test_migration_chain_gap_raises_or_flags` (versioning.py:47 не покрыта).
9. `test_ttl_expired_key_value_contract`, `test_keys_excludes_expired`, `test_mget_skips_expired` — сегодня падают.
10. `test_two_engines_shared_db_file` — второй engine получает свои таблицы (P1-8).

**Существующие тесты, закрепляющие баги:**
- test_store.py:122 `assert store.size() == 2` с мёртвым ключом — баг «истёкшие видны» возведён в контракт.
- test_saga.py:67 `assert saga.status in (FAILED, COMPENSATED)` — мягкий assert маскирует неоднозначность.
- test_event_bus.py:53-61 — publish_sync проверяется только длиной history, подписчики не ассертятся.
- test_concurrency.py — «writer-contention contract», но реальной контенции нет.
- test_backend.py:63-77 «legacy_safe» не тестирует дыру в середине цепочки миграций.

**P2-пробелы (пути отказа):** lock timeout под реальной контенцией; сбой journal_emit посреди set(); исключение в хендлере/on_enter/компенсации (saga.py:111 suppress без теста); middleware: dedup expiry, rate-limit refill, pipeline error propagation (файл покрыт на 68%).

**P3-пробелы:** EventStream persist→reopen (events+cursors); state_data при reopen; count_since точная граница; use-after-close; кириллица в keys()/payload.

**Интеграционный уровень (юнит-тестом не закрывается):** kill -9 mid-write, WAL recovery, journal replay после нечистого shutdown, мультипроцессная контенция.

**Первый batch:** 8 тестов из пунктов 1,2,4,5,9 — каждый красный сегодня, закрывает P1-1..P1-7 частично.

## Подозрения (не доказано)

- Окно между conn.commit() и flush журнала — crash теряет журнал (рассуждение по коду).
- executescript partial-DDL при падении миграции (гипотеза).
- EventBus._history держит payload'ы в RAM — удержание чувствительных данных.

## Не проверено

- Мультипроцессная конкурентность и реальный lock-timeout под нагрузкой.
- Crash-рекавери (kill -9, потеря коммитов при synchronous=NORMAL на OS-crash).
- Кириллица/сурогаты в LIKE-escaping и JSON payload; круг type-field.
- 8+ потоков writers; Windows-специфика WAL при process kill.

Композитный индекс снят с «не проверено» — замерен 2026-10-26, см. «Открытые зоны», пункт 7.

## Исправлено и подтверждено (заход 4, 2026-10-26)

Файлы: purr/event_stream.py, purr/store.py, purr/event.py, тесты event_stream/store/event_bus, CHANGELOG.md. Verifier-агент трижды завершился инфраструктурной ошибкой «empty stream», поэтому приёмку выполнил лид отдельными откатами и прогонами. Красный прогон ДО: **9 failed, 51 passed** на откате трёх production-файлов; после: **130 passed**, `ruff check purr` — All checks passed.

- **P2 cursor ПРИНЯТ**: missing event id → явный `ValueError`; пустая выдача → `last_id=None`; чтение без cursor с начала сохранено.
- **P2 retention ПРИНЯТ**: `max_events`/`max_age_seconds`, подрезка в maintain(), default без лимитов сохранён; курсоры не удаляются и сигнализируют ValueError после ротации.
- **P2 mset ordering ПРИНЯТ**: journal emits after commit; независимая raw-sqlite проверка увидела обе записи `[2, 2]` в момент emit.
- **P2 handler errors ПРИНЯТ**: optional `on_handler_error`, callback получает event+exception, callback exception не ломает dispatch, default silent сохранён.
- **P2 journal buffer ПРИНЯТ**: `_journal_buffer` per-thread; независимая одновременная проверка дала разные list ids `[2603728094656, 2603728094336]`.

Первый независимый probe ошибочно сравнил id списков после завершения потоков (адреса переиспользовались); повторный probe с одновременным удержанием объектов прошёл. Это не дефект фикса.

**Итог после захода 4:** 5 P2 event-контурных дыр закрыты; осталось P2/P3 + интеграционные зоны (crash recovery, multiprocess contention, error-system consistency, lifecycle, PRAGMA tuning).

## Исправлено и подтверждено (заход 3, 2026-10-26)

Файлы: purr/saga.py, purr/backend.py, по одной строке ENGINE_NAME в store/event_stream/state_machine, README.md, CHANGELOG.md; новые tests/test_saga_p1_fixes.py (4 теста), tests/test_backend_p1_fixes.py (4 теста). Приёмка выполнена лидом (спавн verifier'а дважды упал на инфраструктурной ошибке; лид — не автор правок): откат захода 3 → 6 failed по сути; независимое воспроизведение своим скриптом; полный прогон **118 passed**, ruff чист, старые тесты не тронуты (git diff --stat tests/ пуст по существующим файлам).

- **P1-6 ПРИНЯТ**: execute() сбрасывает per-step статусы; snapshot-трекинг written-ключей; _compensate откатывает written-данные каждого компенсируемого шага НЕЗАВИСИМО от наличия compensation-колбэка (зазор найден верификацией и закрыт отдельным red-first циклом: шаг без колбэка раньше оставлял свои данные в saga.data); легитимная компенсация в рамках одного запуска — обратный порядок C2→C1 подтверждён. Семантическое уточнение: stale-компенсации прошлого запуска при последовательном перезапуске недостижимы (execute перезапускает все шаги и перезавершает их — компенсация легитимна); дефект был в stale-статусах и неоткате data. Компенсация падшего шага не добавлена (решение владельца: небезопасно) — задокументировано в README/docstring.
- **P1-8 ПРИНЯТ**: per-engine реестр `_purr_schema(engine, version)`; три engine (Store, EventStream, StateMachine) на одном файле работают — проверено независимо; legacy-БД (user_version без реестра) апгрейдится без потери данных, реестр восстанавливается; user_version синхронизируется вверх.
- **README/CHANGELOG ПРИНЯТЫ**: TTL lazy, saga in-memory + rollback-оговорка, append-only + ValueError на дубликат (Breaking в [Unreleased]), publish_sync, incr-семантика; счётчик тестов обновлён.

**Итог по всем трём заходам: все 8 находок P1 закрыты. 118 тестов (95 исходных + 23 новых), ни один старый тест не изменён.** Непокрытым остаётся P2/P3-хвост (глотание исключений хендлеров, cursor-семантика NULL/"" , retention, journal-атомарность, README «TTL auto-expiry» частично) — в соответствующих разделах выше.

## Исправлено и подтверждено (заход 2, 2026-10-26)

Файлы: purr/event_stream.py (+39/−6), purr/event.py (+37/−1), tests/test_fixer_pass2.py (9 тестов). Verifier: откат захода 2 → 8 failed по сути находок; независимое воспроизведение всех сценариев своим скриптом; полный прогон **110 passed**. store.py не тронут.

- **P1-5 ПРИНЯТ**: append() — INSERT вместо INSERT OR REPLACE; дубликат id → `ValueError("duplicate event id: ...")`; set_cursor перезапись закреплена pin-тестом как контракт.
- **P2 индекс ПРИНЯТ**: миграция схемы v2 (`user_version=2`), индекс `idx_events_topic_ts ON events(topic, timestamp)`; EQP без TEMP B-TREE; апгрейд старой БД v1→v2 воспроизведён независимо. Замер (замерялся ранее): 20.10 → 0.74 ms/op на 100k.
- **P2 batch API ПРИНЯТ**: `append_many()` — атомарный батч, дубликат → rollback, 0 записей. Замер: 5000 событий — 0.077s vs 0.750s по одному (~10×).
- **P1-7 ПРИНЯТ**: publish_sync диспетчит подписчиков: sync — напрямую; async вне цикла — asyncio.run; async внутри работающего цикла → RuntimeError «use await bus.publish()». Глотание исключений оставлено консистентным с async publish (P2 остаётся в списке).

## Исправлено и подтверждено (заход 1, 2026-10-26)

Файл: purr/store.py (+60/−13) + tests/test_store_p1_fixes.py (6 тестов). Verifier: независимо воспроизвёл все баги ДО правок (откат store.py к HEAD) и их отсутствие ПОСЛЕ своим скриптом; полный прогон **101 passed** (95 старых + 6 новых, старые не тронуты).

- **P1-1 ПРИНЯТ**: BEGIN IMMEDIATE в try/except, сброс флага при сбое (store.py:76-80).
- **P1-2 ПРИНЯТ**: `_in_transaction` — property поверх threading.local, per-thread (store.py:35-42).
- **P1-3/P1-4 ПРИНЯТ**: incr переписан атомарно (свой BEGIN IMMEDIATE вне внешнего transaction()), истёкший ключ удаляется и трактуется как отсутствующий (incr == amount), TTL живого ключа сохранён, TypeError для нечисловых сохранён (store.py:215-263). Verifier усилил прогон: 8×100 incr → ровно 800.

Решения владельца в рамках захода:
- keys()/size() продолжают показывать истёкшие до sweep/get — lazy-expiry сохранена (минимальный дифф; README-вопрос P2 остаётся открытым).
- set(key, None) → incr даёт TypeError (как incr по тексту) — поведение консистентно, оставлено.
- **Новое подозрение (зарегистрировано fixer'ом)**: `_journal_buffer` общий на инстанс, не per-thread — два потока в transaction() с journal могут подмешать события друг друга в один буфер. Кандидат в следующий заход или в P2-раздел.

## Открытые зоны — ревизия 2026-10-26 (что осталось и как закрывать)

Фиксация непокрытых областей и подозрений с планом закрытия. Исполнение — после старта фазы фиксов.

**1. Crash-рекавери — kill -9 mid-write, WAL recovery, journal replay.** Самая дорогая зона: юнит-тестом не закрывается, нужен интеграционный прогон. Риск: WAL + synchronous=NORMAL теряет последние коммиты на OS-crash (принятый trade-off SQLite, но нигде не задокументирован); окно P2-журнала (commit KV → append журнала) при crash = данные без событий. План: (а) сценарий «заполнить → kill -9 дочернего процесса посреди батча → перезапустить → сверить kv/журнал»; (б) тест replay журнала после нечистого shutdown (journal-стрим восстанавливает события?); (в) решение по окну — либо 2-phase запись, либо честное «журнал best-effort» в README. Критерий: скрипт-воспроизведение с фиксированным выводом «что выжило» до и после фикса.

**2. Мультипроцессная конкурентность — 8+ писателей, lock-timeout под нагрузкой.** Все замеры — один процесс; known finding P1-1 (отравление флага) и P1-2 (общий флаг) проверены только в threads. Неизвестно: поведение busy_timeout=5000 при 8 одновременных писателях-процессах (очередь или каскад OperationalError), деградация throughput, взаимоблокировка при transaction() в двух процессах. План: мультипроцессный бенчмарк (multiprocessing, 8 воркеров, общий файл) с подсчётом ошибок и оп/с; сценарий «два процесса в transaction() одновременно».

**3. Windows-специфика WAL при process kill.** WAL/-shm на Windows ведут себя иначе (file locks, отсутствие POSIX-семантики удаления); checkpoint(TRUNCATE) может молча не отработать при держащих коннах (перекликается с P2-жизненным циклом: утёкшие конны других потоков ломают TRUNCATE). План: после мультипроцессного прогона (п.2) — замер размеров WAL до/после maintain() при живых и убитых процессах на Windows; фиксация, ломается ли checkpoint.

**4. Окно commit() → flush журнала (было подозрением).** store.py:71-72 `conn.commit(); self._journal_flush()` — crash между ними теряет журнал для закоммиченных данных; исключение во flush после успешного коммита caller читает как откат (проверено по коду, не по crash). План закрытия: сначала тест-семантика (что возвращает transaction() при падении flush — сейчас исключение вопреки факту коммита), затем решение: писать журнал в ту же БД в той же транзакции (убирает окно полностью, но ломает разделение файлов) или принять и задокументировать. Уровень: P2 до подтверждения crash-прогоном.

**5. executescript при падении миграции — частичный DDL (было гипотезой).** backend.py:38: `executescript` неявно коммитит; падение посреди скрипта оставляет часть таблиц с неподнятым user_version → повторный запуск упадёт на уже созданных объектах (частично спасает IF NOT EXISTS, но не для ALTER). План: тест с MIGRATIONS-подклассом, где второй statement бросает → замерить состояние схемы и user_version; затем обёртка «DDL в одной транзакции» (BEGIN/COMMIT вокруг executescript не работает — нужно исполнять стейтменты по одному в транзакции).

**6. EventBus._history держит payload'ы в RAM (было подозрением).** event.py:47-48, cap 1000 событий с полными payload — удержание чувствительных данных без API очистки/исключения payload из истории. Замер tracemalloc уже сделан (0.9MB стабильно — память не проблема), проблема — семантика retention. План: решение владельца (Лили): параметр `history_payloads: bool` / `max_history=0` / документирование; тест, что история опустошается/не хранит payload при настройке.

**7. Композитный индекс — СНЯТО С ОЦЕНКИ, замерено (проверено).** Был прогноз ~1ms вместо 20.7ms. Реальный замер 2026-10-26, 100k событий (bulk insert 2.22s, temp db, repo venv):
```
BEFORE index: 2000 events, 20.10 ms/op   (20 повторов read(cursor,topic=t1,limit=100))
AFTER  index idx_events_topic_ts ON events(topic, timestamp):
               2000 events,  0.74 ms/op   (27× быстрее)
EQP AFTER: SEARCH events USING INDEX idx_events_topic_ts (topic=? AND timestamp>?)
           — TEMP B-TREE FOR ORDER BY исчез из плана
```
Уточнение против исходной оценки: `rowid` в индекс не включается (SQLite запрещает явно) — индекс `(topic, timestamp)` достаточен: записи индекса неявно оканчиваются rowid, порядок (topic, timestamp, rowid) получается из индекса. Побочный факт из прогона: передача в `read(cursor=...)` строки-не-id молча вернула `[]` — ещё одно живое подтверждение P2-находки про NULL-курсор. В фикс войдёт: индекс в MIGRATIONS (версия схемы 2) + batch append API (24× на записи, замер от system-auditor).

## Вне скоупа

CI (GitHub Actions), публикация PyPI, документация как артефакт.

## Следующий шаг

1. **Фиксы store.py** одним заходом: P1-1 + P1-2 (модель владения флагом — thread-local или контекст-менеджер на соединении) + атомарный incr через `UPDATE ... RETURNING` с учётом expires_at (P1-3, P1-4).
2. **event_stream.py**: `INSERT` вместо `INSERT OR REPLACE` + ошибка на дубликат (P1-5); композитный индекс (topic, timestamp, rowid); batch append API.
3. **Правка README**: saga in-memory, TTL lazy, publish_sync-семантика — либо фиксить код, либо честно документировать (P1-7, P2 README).
4. **Тесты first batch** (8 красных тестов выше) до любых правок — red first.

Порядок честности: падающие тесты пишутся первыми, затем минимальные правки, затем зелёный прогон.
