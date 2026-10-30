"""Пробы на 10 находок P1 из AUDIT-REPORT.md.

Одна проба — одна находка — одно утверждение о поведении. Каждая проба
проверяет ровно то поведение, которое отчёт объявил исправленным
("P1-N ПРИНЯТ"), и возвращает трёхзначный вердикт:

  HOLDS  — заявленное поведение на месте (находка закрыта);
  BROKEN — дефект воспроизводится (находка жива);
  VOID   — проба не состоялась (сетап/среда), вердикт не выносится.

VOID не считается ни HOLDS, ни BROKEN: молчаливый пропуск пробы — это
ложная уверенность, поэтому он валит код возврата отдельным значением.

Код возврата: 0 — все HOLDS, 1 — есть BROKEN, 2 — VOID без BROKEN.

Ожидаемый результат на HEAD 60d755e: P1-1..P1-8 — HOLDS (фиксы заходов
1-3 на месте), P1-9 и P1-10 — BROKEN (находки живы).
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from purr import EventBus, EventStream, Saga, Store  # noqa: E402
from purr.event import Event, EventType  # noqa: E402

HOLDS = "HOLDS"
BROKEN = "BROKEN"
VOID = "VOID"

Result = tuple[str, str]


class _FastTimeoutStore(Store):
    """Store, который сдаётся по блокировке за 25 мс вместо 5 с.

    P1-1 требует сбоя BEGIN IMMEDIATE. Ждать 5 с busy_timeout в пробе
    незачем: таймаут — не предмет проверки, предмет — что происходит с
    флагом и с записью после сбоя.
    """

    BUSY_TIMEOUT_MS = 25


def probe_p1_1() -> Result:
    """Флаг транзакции не отравляется сбоем BEGIN, записи не теряются.

    Сценарий: чужое соединение держит write-lock, transaction() падает на
    BEGIN IMMEDIATE. После снятия блокировки обычный set() обязан быть
    виден независимому соединению — то есть закоммичен.
    """
    tmp = Path(tempfile.mkdtemp(prefix="purr-p11-"))
    db = tmp / "kv.db"
    store = _FastTimeoutStore(str(db))
    holder = sqlite3.connect(str(db), isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        begin_error = None
        try:
            with store.transaction():
                store.set("k", "v")
        except sqlite3.OperationalError as exc:
            begin_error = str(exc)
        flag_after = store._in_transaction

        holder.execute("ROLLBACK")
        holder.close()

        if begin_error is None:
            return VOID, "BEGIN IMMEDIATE не упал при занятом write-lock — сбой не воспроизведён"

        store.set("after", 1)
        reader = sqlite3.connect(str(db))
        try:
            row = reader.execute("SELECT value FROM kv WHERE key = 'after'").fetchone()
        finally:
            reader.close()

        if row is None:
            return BROKEN, (
                f"BEGIN упал ({begin_error}), флаг после сбоя {flag_after}: "
                "запись после сбоя не видна из независимого соединения (не закоммичена)"
            )
        return HOLDS, (
            f"BEGIN упал ({begin_error}), флаг после сбоя {flag_after}, "
            "запись после сбоя закоммичена и видна извне"
        )
    finally:
        store.close()
        with contextlib.suppress(Exception):
            holder.close()
        shutil.rmtree(tmp, ignore_errors=True)


def probe_p1_2() -> Result:
    """`_in_transaction` не общий между потоками.

    Флаг живёт в threading.local вместе с соединением. Поток поднимает флаг,
    главный поток обязан видеть свой (False), а не чужой.
    """
    tmp = Path(tempfile.mkdtemp(prefix="purr-p12-"))
    store = Store(str(tmp / "kv.db"))
    seen: dict[str, bool] = {}
    raised = threading.Event()
    release = threading.Event()

    def worker() -> None:
        try:
            store._in_transaction = True
            seen["thread"] = store._in_transaction
            raised.set()
            release.wait(5)
            store._in_transaction = False
        finally:
            store.close()

    thread = threading.Thread(target=worker, daemon=True)
    try:
        thread.start()
        if not raised.wait(5):
            return VOID, "поток не поднял флаг за 5 с"
        seen["main"] = store._in_transaction
        release.set()
        thread.join(5)
    finally:
        release.set()
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if seen.get("main"):
        return BROKEN, (
            f"поток выставил флаг True, главный поток видит {seen['main']} — "
            "флаг общий на инстанс, второй поток получит ложный 'nested transaction'"
        )
    return HOLDS, (
        f"флаг в потоке {seen.get('thread')}, в главном потоке {seen.get('main')} — per-thread"
    )


def probe_p1_3() -> Result:
    """incr атомарен: N потоков × M инкрементов дают ровно N×M.

    decr отдельно не проверяется: decr(key, amount) — это incr(key, -amount)
    (store.py:373-375), отдельного кода у него нет.
    """
    threads_n, per_thread = 4, 200
    expected = threads_n * per_thread
    tmp = Path(tempfile.mkdtemp(prefix="purr-p13-"))
    store = Store(str(tmp / "kv.db"))
    errors: list[str] = []

    def worker() -> None:
        try:
            for _ in range(per_thread):
                store.incr("ctr")
        except Exception as exc:  # noqa: BLE001 - любая ошибка означает, что замер не состоялся
            errors.append(repr(exc))
        finally:
            store.close()

    try:
        threads = [threading.Thread(target=worker) for _ in range(threads_n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        if errors:
            return VOID, f"incr падал в потоках, замер не состоялся: {errors[:3]}"
        value = store.get("ctr")
    finally:
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if value != expected:
        return BROKEN, f"{threads_n} потоков × {per_thread} incr → {value} вместо {expected} (потеряно {expected - (value or 0)})"
    return HOLDS, f"{threads_n} потоков × {per_thread} incr → ровно {value}"


def probe_p1_4() -> Result:
    """incr не воскрешает истёкший ключ: счёт с нуля, а не с мёртвого значения."""
    tmp = Path(tempfile.mkdtemp(prefix="purr-p14-"))
    store = Store(str(tmp / "kv.db"))
    try:
        store.set("ctr", 100, ttl=0.2)
        time.sleep(0.4)
        value = store.incr("ctr")
        ttl = store.ttl("ctr")
    finally:
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if value != 1:
        return BROKEN, (
            f"set('ctr', 100, ttl=0.2) → sleep 0.4 → incr вернул {value}, "
            "ожидалось 1 (истёкшее значение воскрешено)"
        )
    return HOLDS, f"incr по истёкшему ключу вернул {value} (счёт с нуля), ttl={ttl}"


def probe_p1_5() -> Result:
    """append с существующим id не перезаписывает событие (append-only)."""
    tmp = Path(tempfile.mkdtemp(prefix="purr-p15-"))
    stream = EventStream(str(tmp / "events.db"))
    try:
        stream.append(Event(id="dup-1", type=EventType.SYSTEM, topic="t", payload={"v": 1}))
        rejected = False
        try:
            stream.append(Event(id="dup-1", type=EventType.SYSTEM, topic="t", payload={"v": 2}))
        except ValueError:
            rejected = True
        events, _ = stream.read()
        payload = events[0].payload if events else None
        count = stream.count()
    finally:
        stream.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if not rejected or payload != {"v": 1}:
        return BROKEN, (
            f"повторный append с id='dup-1': ValueError={rejected}, "
            f"сохранённый payload={payload}, событий {count} — оригинал подменён"
        )
    return HOLDS, (
        f"повторный append с id='dup-1' отвергнут ValueError, "
        f"сохранённый payload={payload}, событий {count}"
    )


def probe_p1_6() -> Result:
    """Повторный execute() не тащит состояние прошлого запуска и откатывает data.

    Проверяются две вещи, обе объявленные в отчёте принятыми:

    (а) saga.data откатывается при компенсации — ключ, добавленный
        компенсируемым шагом, из data удаляется;
    (б) per-step статусы сбрасываются в начале execute(): на втором запуске
        шаг, упавший в первом, уже не FAILED, пока до него не дошли.

    Отдельно про «стрельбу чужими компенсациями»: при последовательном
    перезапуске stale-компенсация недостижима — _compensate обходит индексы
    строго меньше упавшего, а все они в текущем запуске исполнились и
    завершились. Отчёт сам это фиксирует (раздел «заход 3», P1-6). Поэтому
    проба доказывает то, что фикс реально изменил: откат data и сброс статусов.
    """
    log: list[str] = []
    statuses_in_run2: list[str] = []
    state = {"run": 0}
    saga = Saga("p16")

    async def act1(data: dict) -> dict:
        if state["run"] == 2:
            statuses_in_run2.append(saga.get_state()["steps"][1]["status"])
        log.append("act1")
        return {"a": 1}

    async def comp1(data: dict) -> None:
        log.append("COMP1")

    async def boom(data: dict) -> dict:
        log.append("boom")
        raise RuntimeError("step failed")

    saga.add_step("s1", act1, comp1)
    saga.add_step("s2", boom)

    async def run() -> None:
        try:
            await saga.execute({"seed": 0})
        except RuntimeError:
            pass

    state["run"] = 1
    asyncio.run(run())
    data_after_run1 = dict(saga.data)
    log_after_run1 = list(log)
    state["run"] = 2
    asyncio.run(run())

    if data_after_run1 != {"seed": 0}:
        return BROKEN, (
            f"после компенсации saga.data={data_after_run1}, ожидалось {{'seed': 0}} — "
            f"данные компенсированного шага не откатились (log: {log_after_run1})"
        )
    if statuses_in_run2 and statuses_in_run2[0] != "pending":
        return BROKEN, (
            f"на втором запуске статус шага s2 в начале execute = {statuses_in_run2[0]!r}, "
            "ожидалось 'pending' — статусы прошлого запуска не сброшены"
        )
    if not statuses_in_run2:
        return VOID, "второй запуск не дошёл до шага s1 — замер статусов не состоялся"
    return HOLDS, (
        f"data после компенсации {data_after_run1}, статус s2 на втором запуске "
        f"{statuses_in_run2[0]!r}"
    )


def probe_p1_7() -> Result:
    """publish_sync доставляет событие подписчикам, а не только в history."""
    bus = EventBus()
    calls: list[str] = []

    def sync_handler(event: Event) -> None:
        calls.append("sync")

    async def async_handler(event: Event) -> None:
        calls.append("async")

    bus.subscribe("t", sync_handler)
    bus.subscribe("t", async_handler)
    bus.publish_sync(Event(type=EventType.SYSTEM, topic="t"))
    history = len(bus.get_history())

    if calls != ["sync", "async"]:
        return BROKEN, (
            f"подписчики получили {calls}, ожидалось ['sync', 'async'] — "
            f"publish_sync только положил событие в history ({history})"
        )
    return HOLDS, f"оба подписчика вызваны в порядке подписки: {calls}, history={history}"


def probe_p1_8() -> Result:
    """Два engine на одном файле БД не ломают миграции друг друга."""
    tmp = Path(tempfile.mkdtemp(prefix="purr-p18-"))
    db = tmp / "shared.db"
    store = Store(str(db))
    stream = None
    try:
        store.set("k", "v")
        stream = EventStream(str(db))
        try:
            stream.append(Event(type=EventType.SYSTEM, topic="t", payload={"v": 1}))
        except sqlite3.Error as exc:
            return BROKEN, (
                f"второй engine на том же файле не получил своих таблиц: "
                f"{type(exc).__name__}: {exc}"
            )
        count = stream.count()
    finally:
        if stream is not None:
            stream.close()
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if count != 1:
        return BROKEN, f"событие не записалось: count={count}"
    return HOLDS, "Store и EventStream на одном файле: events создана, append работает, count=1"


def probe_p1_9() -> Result:
    """get() на истёкшем ключе не мутирует хранилище.

    Проверяется и журнал (аудит мерил именно событие delete), и сами данные:
    после чтения истёкшего ключа строка в kv остаётся, новых событий нет.
    """
    tmp = Path(tempfile.mkdtemp(prefix="purr-p19-"))
    journal = EventStream(str(tmp / "events.db"))
    store = Store(str(tmp / "kv.db"), journal=journal)
    try:
        store.set("k", "v", ttl=0.1)
        time.sleep(0.25)
        before, _ = journal.read()
        value = store.get("k")
        after, _ = journal.read()
        new = [e for e in after[len(before) :] if e.payload.get("op") == "delete"]
        rows = store._get_conn().execute("SELECT COUNT(*) FROM kv WHERE key = ?", ("k",)).fetchone()[0]
    finally:
        store.close()
        journal.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if new or rows == 0:
        return BROKEN, (
            f"get() на истёкшем ключе вернул {value!r}, но породил {len(new)} событие(й) "
            f"delete в журнале и удалил строку из kv (осталось {rows})"
        )
    return HOLDS, f"get() вернул {value!r}, новых событий 0, строка в kv осталась"


def probe_p1_10() -> Result:
    """db_stats() видит фактический WAL для пути без суффикса.

    SQLite создаёт сайдкар как `<path>-wal`; `with_suffix('.db-wal')` для
    пути без суффикса смотрит на `<path>.db-wal` и всегда получает 0.
    """
    tmp = Path(tempfile.mkdtemp(prefix="purr-p110-"))
    path = tmp / "nosuffix"
    store = Store(str(path))
    try:
        store.set("k", "v" * 500)
        real = Path(str(path) + "-wal")
        real_bytes = real.stat().st_size if real.exists() else 0
        reported = store.db_stats()["wal_bytes"]
    finally:
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)

    if real_bytes == 0:
        return VOID, f"WAL пуст (0 байт) — сравнивать нечего, проба не состоялась"
    if reported != real_bytes:
        return BROKEN, (
            f"файл {real.name} = {real_bytes} байт на диске, db_stats сообщает {reported}"
        )
    return HOLDS, f"db_stats и фактический WAL совпадают ({real_bytes} байт)"


PROBES = (
    ("P1-1 флаг транзакции", probe_p1_1),
    ("P1-2 флаг между потоками", probe_p1_2),
    ("P1-3 incr атомарен", probe_p1_3),
    ("P1-4 incr не воскрешает", probe_p1_4),
    ("P1-5 append-only", probe_p1_5),
    ("P1-6 saga re-execute", probe_p1_6),
    ("P1-7 publish_sync", probe_p1_7),
    ("P1-8 два engine на файле", probe_p1_8),
    ("P1-9 get() мутирует", probe_p1_9),
    ("P1-10 db_stats WAL", probe_p1_10),
)


def main() -> int:
    results: list[tuple[str, str, str]] = []
    # Which tree is measured: an editable install of purr points at the working
    # copy, so a run inside a control clone must prove it imported the clone.
    print(f"purr: {Path(sys.modules['purr'].__file__).resolve().parent}")
    for name, probe in PROBES:
        try:
            status, detail = probe()
        except Exception as exc:  # noqa: BLE001 - упавшая проба не должна выдавать себя за вердикт
            status, detail = VOID, f"проба упала: {type(exc).__name__}: {exc}"
        results.append((status, name, detail))
        print(f"{status:<6}  {name}: {detail}")

    broken = sum(1 for status, _, _ in results if status == BROKEN)
    void = sum(1 for status, _, _ in results if status == VOID)
    holds = len(results) - broken - void
    print(f"ИТОГ: HOLDS {holds}, BROKEN {broken}, VOID {void}")
    if broken:
        return 1
    if void:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
