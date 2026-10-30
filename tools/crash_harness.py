"""Crash-durability harness for PURR.

Три режима:
    python crash_harness.py write  <db>          — дочерний процесс: пишет ключи, подтверждает каждый
    python crash_harness.py verify <db> <keys>   — дочерний процесс: проверяет, что подтверждённое выжило
    python crash_harness.py run    [runs]        — оркестратор: запускает сценарий N раз и печатает итог

Сценарии с журналом (run-journal-txn — приёмочный, остальные держат его честным):
    run-journal-txn             [runs]  — пачка в транзакции, убийство в окне сразу после коммита
    run-journal-txn-nonatomic   [runs]  — то же, но журнал моделируется НЕатомарным (порядок до правки);
                                          обязан краснеть всегда, в том числе после правки продукта
    run-journal                 [runs]  — одиночные записи, журнал в файле данных

Правило доказательства: ключ считается подтверждённым только после того, как set() вернул True
И после этого строка ушла в stdout с flush. Значит «подтверждено» никогда не опережает коммит.
"""

import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.abspath(__file__)


def cmd_write(db_path: str) -> None:
    from purr import Store

    store = Store(db_path)
    i = 0
    while True:
        i += 1
        key = "k%d" % i
        ok = store.set(key, "v" * 100)
        if ok:
            # Порядок важен: сначала коммит (set вернул True), потом подтверждение наружу.
            sys.stdout.write("OK %s\n" % key)
            sys.stdout.flush()


def cmd_verify(db_path: str, keys_path: str) -> None:
    from purr import Store

    with open(keys_path, encoding="utf-8") as f:
        confirmed = [line.strip() for line in f if line.strip()]

    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()

    store = Store(db_path)
    missing = [k for k in confirmed if store.get(k) is None]

    print(json.dumps({
        "confirmed": len(confirmed),
        "survived": len(confirmed) - len(missing),
        "missing": missing[:10],
        "missing_count": len(missing),
        "integrity": integrity,
    }))
    sys.exit(0 if not missing and integrity == "ok" else 1)


def cmd_run(runs: int) -> int:
    python = sys.executable
    env = dict(os.environ)
    results = []
    bad = 0

    for n in range(1, runs + 1):
        tmp = tempfile.mkdtemp(prefix="purr-crash-")
        db_path = os.path.join(tmp, "purr.db")
        keys_path = os.path.join(tmp, "confirmed.txt")

        target = random.randint(40, 160)
        child = subprocess.Popen(
            [python, SELF, "write", db_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )

        confirmed = []
        try:
            for line in child.stdout:
                if line.startswith("OK "):
                    confirmed.append(line[3:].strip())
                    if len(confirmed) >= target:
                        break
        finally:
            # Небольшая случайная пауза, чтобы убийство попало внутрь следующей записи.
            time.sleep(random.uniform(0.0, 0.03))
            child.kill()
            child.wait()

        with open(keys_path, "w", encoding="utf-8") as f:
            f.write("\n".join(confirmed))

        verify = subprocess.run(
            [python, SELF, "verify", db_path, keys_path],
            capture_output=True, text=True, env=env,
        )
        try:
            data = json.loads(verify.stdout.strip().splitlines()[-1])
        except Exception:
            data = {"confirmed": len(confirmed), "survived": 0, "missing_count": len(confirmed),
                    "missing": confirmed[:10], "integrity": "VERIFY_FAILED",
                    "stderr": verify.stderr[-400:]}

        # Вердикт выносит verify (у него правило одно), оркестратор его только переносит.
        if verify.returncode != 0:
            bad += 1

        data["run"] = n
        data["killed_at"] = len(confirmed)
        results.append(data)
        print("run %d: убит после %d подтверждений → выжило %d, потеряно %d, integrity=%s" % (
            n, len(confirmed), data.get("survived", 0), data.get("missing_count", 0),
            data.get("integrity", "?")))
        if data.get("missing"):
            print("        первые потерянные: %s" % ", ".join(data["missing"][:5]))
        if data.get("stderr"):
            print("        stderr verify: %s" % data["stderr"].replace("\n", " ")[:300])

    total_confirmed = sum(r.get("confirmed", 0) for r in results)
    total_missing = sum(r.get("missing_count", 0) for r in results)
    bad_integrity = [r["run"] for r in results if r.get("integrity") != "ok"]
    print()
    print("ИТОГ: прогонов %d, подтверждено записей %d, потеряно %d, сломанная целостность в %s" % (
        len(results), total_confirmed, total_missing, bad_integrity or "нет"))
    return 1 if bad else 0


def cmd_write_txn(db_path: str) -> None:
    """Сценарий 2: подтверждённые ключи, затем ОДНА транзакция из 500 записей."""
    from purr import Store

    store = Store(db_path)
    for i in range(1, 21):
        key = "pre%d" % i
        if store.set(key, "v" * 100):
            sys.stdout.write("OK %s\n" % key)
            sys.stdout.flush()

    sys.stdout.write("BATCH_START\n")
    sys.stdout.flush()
    with store.transaction():
        for i in range(1, 501):
            store.set("tx%d" % i, "v" * 100)
            if i % 50 == 0:
                sys.stdout.write("PROGRESS %d\n" % i)
                sys.stdout.flush()
    sys.stdout.write("BATCH_DONE\n")
    sys.stdout.flush()


def cmd_verify_txn(db_path: str, keys_path: str) -> None:
    from purr import Store

    with open(keys_path, encoding="utf-8") as f:
        pre = [line.strip() for line in f if line.strip()]

    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()

    store = Store(db_path)
    missing_pre = [k for k in pre if store.get(k) is None]
    tx_present = sum(1 for i in range(1, 501) if store.get("tx%d" % i) is not None)

    # Транзакция либо вся, либо никак. Что-то посередине — частичный коммит.
    partial = 0 < tx_present < 500
    print(json.dumps({
        "pre_confirmed": len(pre),
        "pre_missing": len(missing_pre),
        "tx_present": tx_present,
        "partial_commit": partial,
        "integrity": integrity,
    }))
    sys.exit(0 if not missing_pre and not partial and integrity == "ok" else 1)


def cmd_run_txn(runs: int) -> int:
    python = sys.executable
    env = dict(os.environ)
    bad = 0

    for n in range(1, runs + 1):
        tmp = tempfile.mkdtemp(prefix="purr-txn-")
        db_path = os.path.join(tmp, "purr.db")
        keys_path = os.path.join(tmp, "confirmed.txt")

        child = subprocess.Popen(
            [python, SELF, "write-txn", db_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )

        pre = []
        inside_at = None
        try:
            for line in child.stdout:
                if line.startswith("OK "):
                    pre.append(line[3:].strip())
                elif line.startswith("BATCH_START"):
                    continue
                elif line.startswith("PROGRESS "):
                    inside_at = int(line.split()[1])
                    if inside_at >= 100:  # гарантированно внутри транзакции
                        break
                elif line.startswith("BATCH_DONE"):
                    break
        finally:
            child.kill()
            child.wait()

        with open(keys_path, "w", encoding="utf-8") as f:
            f.write("\n".join(pre))

        verify = subprocess.run(
            [python, SELF, "verify-txn", db_path, keys_path],
            capture_output=True, text=True, env=env,
        )
        try:
            data = json.loads(verify.stdout.strip().splitlines()[-1])
        except Exception:
            data = {"pre_confirmed": len(pre), "pre_missing": -1, "tx_present": -1,
                    "partial_commit": True, "integrity": "VERIFY_FAILED",
                    "stderr": verify.stderr[-300:]}

        flag = "OK " if (data["pre_missing"] == 0 and not data["partial_commit"]
                         and data["integrity"] == "ok") else "БРАК"
        if flag == "БРАК":
            bad += 1
        where = ("внутри транзакции на %d" % inside_at) if inside_at else "НЕ попали внутрь"
        print("run %d: %s  убит %s  pre потеряно=%s  tx записано=%d/500  частичный=%s  integrity=%s" % (
            n, flag, where, data["pre_missing"], data["tx_present"],
            data["partial_commit"], data["integrity"]))
        if data.get("stderr"):
            print("        stderr: %s" % data["stderr"].replace("\n", " ")[:250])

    print()
    print("ИТОГ: прогонов %d, брак %d" % (runs, bad))
    return 1 if bad else 0


def cmd_write_journal(kv_path: str, ev_path: str, slow: bool = False) -> None:
    """Сценарий 3: одиночные записи с журналом.

    Под вариантом C журнал живёт в файле данных, поэтому ev_path не
    используется: двухфайловый режим отвергнут продуктом на старте. Окна
    «коммит KV → запись события» больше нет, так что slow растягивает саму
    вставку события внутри транзакции, а не зазор после неё.
    """
    from purr import EventStream, Store

    journal = EventStream(kv_path)
    if slow:
        original_insert = journal.insert_in

        def slow_insert(conn, event):
            time.sleep(0.05)
            return original_insert(conn, event)

        journal.insert_in = slow_insert

    store = Store(kv_path, journal=journal)
    i = 0
    while True:
        i += 1
        key = "j%d" % i
        if store.set(key, "v" * 100):
            sys.stdout.write("OK %s\n" % key)
            sys.stdout.flush()


def cmd_verify_journal(kv_path: str, ev_path: str, keys_path: str) -> None:
    """Журнал читается из файла данных: под C он живёт там же, что и KV."""
    from purr import Store

    with open(keys_path, encoding="utf-8") as f:
        confirmed = [line.strip() for line in f if line.strip()]

    conn = sqlite3.connect(kv_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        kv_keys = {row[0] for row in conn.execute("SELECT key FROM kv").fetchall()}
        rows = conn.execute("SELECT payload FROM events WHERE topic='store'").fetchall()
    finally:
        conn.close()
    ev_integrity = integrity

    journal_keys = set()
    for (payload,) in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if data.get("op") == "set" and "key" in data:
            journal_keys.add(data["key"])

    store = Store(kv_path)
    confirmed_missing = [k for k in confirmed if store.get(k) is None]
    gap = sorted(kv_keys - journal_keys)        # запись есть, события нет
    phantom = sorted(journal_keys - kv_keys)    # событие есть, записи нет

    print(json.dumps({
        "confirmed": len(confirmed),
        "confirmed_missing": len(confirmed_missing),
        "kv_keys": len(kv_keys),
        "journal_events": len(journal_keys),
        "gap": len(gap),
        "gap_sample": gap[:5],
        "phantom": len(phantom),
        "phantom_sample": phantom[:5],
        "integrity": integrity,
        "journal_integrity": ev_integrity,
    }))
    sys.exit(0 if not confirmed_missing and not phantom
             and integrity == "ok" and ev_integrity == "ok" else 1)


def cmd_run_journal(runs: int, slow: bool = False) -> int:
    python = sys.executable
    env = dict(os.environ)
    gaps = []
    phantoms = 0
    losses = 0
    bad = 0

    for n in range(1, runs + 1):
        tmp = tempfile.mkdtemp(prefix="purr-jrn-")
        kv_path = os.path.join(tmp, "purr.db")
        ev_path = os.path.join(tmp, "events.db")
        keys_path = os.path.join(tmp, "confirmed.txt")

        target = random.randint(40, 120)
        child = subprocess.Popen(
            [python, SELF, "write-journal", kv_path, ev_path] + (["slow"] if slow else []),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )

        confirmed = []
        try:
            for line in child.stdout:
                if line.startswith("OK "):
                    confirmed.append(line[3:].strip())
                    if len(confirmed) >= target:
                        break
        finally:
            time.sleep(random.uniform(0.0, 0.02))
            child.kill()
            child.wait()

        with open(keys_path, "w", encoding="utf-8") as f:
            f.write("\n".join(confirmed))

        verify = subprocess.run(
            [python, SELF, "verify-journal", kv_path, ev_path, keys_path],
            capture_output=True, text=True, env=env,
        )
        try:
            data = json.loads(verify.stdout.strip().splitlines()[-1])
        except Exception:
            data = {"confirmed": len(confirmed), "confirmed_missing": -1, "kv_keys": -1,
                    "journal_events": -1, "gap": -1, "phantom": -1,
                    "integrity": "VERIFY_FAILED", "journal_integrity": "?",
                    "stderr": verify.stderr[-300:]}

        if verify.returncode != 0:
            bad += 1

        gaps.append(data.get("gap", 0))
        phantoms += data.get("phantom", 0)
        losses += data.get("confirmed_missing", 0)

        print("run %d: подтверждено %d | в KV %d | событий %d | разрыв %d | фантом %d | "
              "integrity %s / журнал %s" % (
                  n, data.get("confirmed", 0), data.get("kv_keys", 0), data.get("journal_events", 0),
                  data.get("gap", 0), data.get("phantom", 0),
                  data.get("integrity", "?"), data.get("journal_integrity", "?")))
        if data.get("gap_sample"):
            print("        пример разрыва: %s" % ", ".join(data["gap_sample"]))
        if data.get("stderr"):
            print("        stderr: %s" % data["stderr"].replace("\n", " ")[:250])

    print()
    print("ИТОГ: прогонов %d | потеряно подтверждённых %d | разрывов всего %d (макс %d) | фантомов %d" % (
        runs, losses, sum(gaps), max(gaps) if gaps else 0, phantoms))
    return 1 if bad else 0



HOLD_AFTER_COMMIT = 1.0


def _open_store_for_batch(kv_path: str, ev_path: str):
    """Открыть Store в той конфигурации, которую поддерживает продукт.

    Возвращает (store, journal, co_located). Проба, а не вера в текущий код:
    до правки Store принимает чужой путь журнала (два файла), после варианта C
    отвергает его явной ошибкой, и журнал живёт в файле данных.

    В co-located случае журнал открывается на пути ДАННЫХ, а не на ev_path:
    иначе store остался бы вообще без журнала, и стенд мерил бы пустоту.
    """
    from purr import EventStream, Store

    journal = EventStream(ev_path)
    try:
        store = Store(kv_path, journal=journal)
        return store, journal, False
    except ValueError:
        # C.1-b: чужой путь журнала отвергнут на старте, журнал — в файле данных.
        journal.close()
        co_located_journal = EventStream(kv_path)
        return Store(kv_path, journal=co_located_journal), co_located_journal, True


def cmd_write_journal_txn(kv_path: str, ev_path: str, marker_path: str) -> None:
    """Сценарий 4: транзакция + журнал. Убийство в окне сразу после коммита пачки.

    Конфигурация выбирается пробой (_open_store_for_batch), потому что правка
    меняет её саму: двухфайловый режим под C отвергается на старте.
      - два файла (до правки): события пишутся ПОСЛЕ коммита пачки; каждый
        append растянут на 50 мс, поэтому окно после коммита живёт секунды и
        убийство через 0.2 с от BATCH_START попадает внутрь него;
      - co-located (после C): события вставляются в транзакцию данных; маркер
        ставится сразу после коммита пачки, и процесс держится живым
        HOLD_AFTER_COMMIT секунд, чтобы убийство попало в тот же момент
        «сразу после коммита», а не в уже завершившийся процесс.

    Маркер в двухфайловом режиме ставит первый append журнала — а это событие
    первого pre-ключа, задолго до коммита пачки. Поэтому маркер здесь только
    избавляет от пустого ожидания; доказательством он не служит. Что окно
    открылось, оркестратор решает по факту: пачка в KV есть целиком.
    """
    store, journal, co_located = _open_store_for_batch(kv_path, ev_path)

    if not co_located:
        original_append = journal.append
        state = {"first": True}

        def slow_append(event):
            if state["first"]:
                state["first"] = False
                with open(marker_path, "w", encoding="utf-8") as f:
                    f.write("flush-started\n")
            time.sleep(0.05)
            return original_append(event)

        journal.append = slow_append

    for i in range(1, 21):
        if store.set("pre%d" % i, "v" * 100):
            sys.stdout.write("OK pre%d\n" % i)
            sys.stdout.flush()

    sys.stdout.write("BATCH_START\n")
    sys.stdout.flush()
    with store.transaction():
        for i in range(1, 501):
            store.set("tx%d" % i, "v" * 100)

    if co_located:
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write("kv-committed\n")
        time.sleep(HOLD_AFTER_COMMIT)

    sys.stdout.write("TX_DONE\n")
    sys.stdout.flush()


def cmd_write_journal_txn_nonatomic(kv_path: str, ev_path: str, marker_path: str) -> None:
    """Сценарий 5: модель НЕатомарного журнала — порядок, который был до правки.

    Восстановлен по базе: `store.py:223-228` — сначала `_commit()`, затем
    `_journal_emit`, и внутри `transaction()` сброс буфера уже после коммита
    (`store.py:141`). Здесь: KV коммитится целиком, событие пишется отдельной
    транзакцией после, в отдельный файл.

    Запись KV сделана raw sqlite3, а не через Store, намеренно: под вариантом C
    Store вставляет событие в ту же транзакцию, и через публичный API
    неатомарный порядок уже не воспроизводится. Схему KV создаёт настоящий
    Store — подменяется только порядок записи, не схема. Журнал — настоящий
    EventStream, с настоящими событиями и настоящим коммитом на каждое.

    Зачем режим нужен: он держит детектор живым. Приёмка предъявляет три
    прогона — база красная, фикс зелёный, эта модель снова красная. Если
    детектор разучился видеть «KV закоммичен, журнал отстал», третий прогон
    позеленеет, и приёмка это заметит. Режим не зависит от того, сделана ли
    правка, — поэтому он красный и до неё, и после.
    """
    from purr import Event, EventStream, EventType, Store

    Store(kv_path).close()  # настоящая схема KV (kv, kv_meta), без подмены
    journal = EventStream(ev_path)

    conn = sqlite3.connect(kv_path)
    now = datetime.now(UTC).isoformat()

    def write_key(key: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value, type, created_at, updated_at)"
            " VALUES (?, ?, 'str', ?, ?)",
            (key, json.dumps("v" * 100), now, now),
        )

    def emit(key: str) -> None:
        journal.append(
            Event(type=EventType.STORE, topic="store",
                  payload={"op": "set", "key": key, "value": "v" * 100})
        )

    # Подтверждённые ключи: коммит на ключ, затем событие — как set() на базе.
    for i in range(1, 21):
        key = "pre%d" % i
        write_key(key)
        conn.commit()
        emit(key)
        sys.stdout.write("OK %s\n" % key)
        sys.stdout.flush()

    sys.stdout.write("BATCH_START\n")
    sys.stdout.flush()
    for i in range(1, 501):
        write_key("tx%d" % i)
    conn.commit()  # пачка в KV закоммичена, событий по ней ещё нет
    conn.close()

    with open(marker_path, "w", encoding="utf-8") as f:
        f.write("kv-committed\n")

    # То же окно, что у сброса буфера в базе: убийство застаёт журнал недописанным.
    for i in range(1, 501):
        time.sleep(0.05)
        emit("tx%d" % i)

    sys.stdout.write("TX_DONE\n")
    sys.stdout.flush()


def _tx_journal_keys(db_path: str) -> tuple[set[str], str]:
    """Ключи tx, по которым в этом файле есть событие журнала, и integrity файла.

    Журнал ищется в обоих файлах: до правки он лежит отдельно, после варианта C —
    в файле данных. Отсутствие таблицы events — не ошибка, а «журнала здесь нет»:
    иначе стенд зеленел бы на файле, которого продукт больше не создаёт.
    """
    if not os.path.exists(db_path):
        return set(), "ok"
    conn = sqlite3.connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        try:
            rows = conn.execute("SELECT payload FROM events WHERE topic='store'").fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        conn.close()

    keys = set()
    for (payload,) in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if data.get("op") == "set" and str(data.get("key", "")).startswith("tx"):
            keys.add(data["key"])
    return keys, integrity


def cmd_verify_journal_txn(kv_path: str, ev_path: str) -> None:
    conn = sqlite3.connect(kv_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tx_kv = {row[0] for row in conn.execute("SELECT key FROM kv WHERE key LIKE 'tx%'").fetchall()}
    finally:
        conn.close()

    kv_events, kv_integrity = _tx_journal_keys(kv_path)
    ev_events, ev_integrity = _tx_journal_keys(ev_path)
    # Под вариантом C журнал живёт в файле данных. Если события есть там, то
    # журнал — этот файл; отдельный events.db тогда остаётся только следом
    # пробы конфигурации, и засчитывать его значило бы мерить файл, которого
    # продукт больше не пишет. До правки журнал — второй файл.
    if kv_events:
        journal_keys, journal_integrity = kv_events, kv_integrity
    else:
        journal_keys, journal_integrity = ev_events, ev_integrity

    print(json.dumps({
        "tx_in_kv": len(tx_kv),
        "tx_in_journal": len(journal_keys),
        "gap": len(tx_kv) - len(journal_keys),
        "integrity": integrity,
        "journal_integrity": journal_integrity,
    }))
    sys.exit(0 if (len(tx_kv) in (0, 500) and len(tx_kv) == len(journal_keys)
                   and integrity == "ok" and journal_integrity == "ok") else 1)


def cmd_run_journal_txn(runs: int, nonatomic: bool = False) -> int:
    python = sys.executable
    env = dict(os.environ)
    bad = 0
    child_mode = "write-journal-txn-nonatomic" if nonatomic else "write-journal-txn"

    if nonatomic:
        print("режим: неатомарный журнал (модель порядка до правки: KV коммитится, "
              "событие — отдельной транзакцией после). Красный здесь — норма.")
        print()

    for n in range(1, runs + 1):
        tmp = tempfile.mkdtemp(prefix="purr-jtxn-")
        kv_path = os.path.join(tmp, "purr.db")
        ev_path = os.path.join(tmp, "events.db")
        marker = os.path.join(tmp, "flush.marker")

        child = subprocess.Popen(
            [python, SELF, child_mode, kv_path, ev_path, marker],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )

        started = False
        try:
            for line in child.stdout:
                if line.startswith("BATCH_START"):
                    started = True
                    break
        finally:
            pass

        waited = 0.0
        while started and not os.path.exists(marker) and waited < 10.0:
            time.sleep(0.05)
            waited += 0.05
        time.sleep(0.2)  # дать окну после коммита открыться (сбросу — начаться)
        alive_before_kill = child.poll() is None
        child.kill()
        child.wait()

        try:
            with open(marker, encoding="utf-8") as f:
                world = f.read().strip()
        except OSError:
            world = ""

        verify = subprocess.run(
            [python, SELF, "verify-journal-txn", kv_path, ev_path],
            capture_output=True, text=True, env=env,
        )
        try:
            data = json.loads(verify.stdout.strip().splitlines()[-1])
        except Exception:
            data = {"tx_in_kv": -1, "tx_in_journal": -1, "gap": -1,
                    "integrity": "VERIFY_FAILED", "journal_integrity": "?",
                    "stderr": verify.stderr[-300:]}

        # Нулевой случай. Проверка пустой пары файлов даёт exit=0 (0 ключей,
        # 0 событий, разрыв 0), поэтому «зелёное» само по себе ещё ничего не
        # значит: ровно так выглядит и процесс, убитый до коммита пачки, и
        # процесс, завершившийся до убийства. Окно дефекта открывается коммитом
        # пачки — значит прогон состоялся, только если пачка в KV есть целиком
        # и процесс был жив в момент убийства. Маркер здесь не годится: в
        # двухфайловом режиме его ставит первый append журнала, а это событие
        # первого pre-ключа, задолго до коммита пачки.
        exercised = data["tx_in_kv"] == 500 and alive_before_kill
        if verify.returncode != 0 or not exercised:
            bad += 1

        print("run %d: маркер сброса=%s | tx в KV %d/500 | событий tx %d | разрыв %d | "
              "integrity %s / журнал %s" % (
                  n, "да" if os.path.exists(marker) else "НЕТ",
                  data["tx_in_kv"], data["tx_in_journal"], data["gap"],
                  data["integrity"], data["journal_integrity"]))
        if not exercised:
            reason = ("пачка не закоммичена, убийство до коммита — окно не открылось"
                      if data["tx_in_kv"] != 500
                      else "процесс завершился до убийства — авария не разыграна")
            print("        ПРОГОН НЕ СОСТОЯЛСЯ: %s, вердикт не выносится" % reason)
        if world == "kv-committed" and not nonatomic:
            print("        конфигурация: журнал в файле данных (co-located), "
                  "двухфайловый режим отвергнут продуктом")
        if data.get("stderr"):
            print("        stderr: %s" % data["stderr"].replace("\n", " ")[:250])

    return 1 if bad else 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    code = 0
    if mode == "write":
        cmd_write(sys.argv[2])
    elif mode == "write-txn":
        cmd_write_txn(sys.argv[2])
    elif mode == "write-journal":
        cmd_write_journal(sys.argv[2], sys.argv[3], len(sys.argv) > 4 and sys.argv[4] == "slow")
    elif mode == "verify":
        cmd_verify(sys.argv[2], sys.argv[3])
    elif mode == "verify-txn":
        cmd_verify_txn(sys.argv[2], sys.argv[3])
    elif mode == "verify-journal":
        cmd_verify_journal(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == "write-journal-txn":
        cmd_write_journal_txn(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == "write-journal-txn-nonatomic":
        cmd_write_journal_txn_nonatomic(sys.argv[2], sys.argv[3], sys.argv[4])
    elif mode == "verify-journal-txn":
        cmd_verify_journal_txn(sys.argv[2], sys.argv[3])
    elif mode == "run-journal-txn":
        code = max(code, cmd_run_journal_txn(int(sys.argv[2]) if len(sys.argv) > 2 else 3))
    elif mode == "run-journal-txn-nonatomic":
        code = max(code, cmd_run_journal_txn(
            int(sys.argv[2]) if len(sys.argv) > 2 else 3, nonatomic=True))
    elif mode == "run":
        code = max(code, cmd_run(int(sys.argv[2]) if len(sys.argv) > 2 else 5))
    elif mode == "run-txn":
        code = max(code, cmd_run_txn(int(sys.argv[2]) if len(sys.argv) > 2 else 5))
    elif mode == "run-journal":
        code = max(code, cmd_run_journal(int(sys.argv[2]) if len(sys.argv) > 2 else 5,
                                         len(sys.argv) > 3 and sys.argv[3] == "slow"))
    else:
        print("неизвестный режим: %s" % mode)
        sys.exit(2)
    return code


if __name__ == "__main__":
    sys.exit(main())
