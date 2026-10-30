"""Crash-durability harness for PURR.

Три режима:
    python crash_harness.py write  <db>          — дочерний процесс: пишет ключи, подтверждает каждый
    python crash_harness.py verify <db> <keys>   — дочерний процесс: проверяет, что подтверждённое выжило
    python crash_harness.py run    [runs]        — оркестратор: запускает сценарий N раз и печатает итог

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


def cmd_run(runs: int) -> None:
    python = sys.executable
    env = dict(os.environ)
    results = []

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


def cmd_run_txn(runs: int) -> None:
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


def cmd_write_journal(kv_path: str, ev_path: str, slow: bool = False) -> None:
    """Сценарий 3: запись в KV с журналом в отдельном файле.

    slow=True расширяет окно между коммитом KV и записью события: append тормозит,
    чтобы убийство гарантированно попало в этот зазор. Так проверяется не удача,
    а само окно.
    """
    from purr import EventStream, Store

    journal = EventStream(ev_path)
    if slow:
        original_append = journal.append

        def slow_append(event):
            time.sleep(0.05)
            return original_append(event)

        journal.append = slow_append

    store = Store(kv_path, journal=journal)
    i = 0
    while True:
        i += 1
        key = "j%d" % i
        if store.set(key, "v" * 100):
            sys.stdout.write("OK %s\n" % key)
            sys.stdout.flush()


def cmd_verify_journal(kv_path: str, ev_path: str, keys_path: str) -> None:
    from purr import Store

    with open(keys_path, encoding="utf-8") as f:
        confirmed = [line.strip() for line in f if line.strip()]

    conn = sqlite3.connect(kv_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        kv_keys = {row[0] for row in conn.execute("SELECT key FROM kv").fetchall()}
    finally:
        conn.close()

    conn = sqlite3.connect(ev_path)
    try:
        ev_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        rows = conn.execute("SELECT payload FROM events WHERE topic='store'").fetchall()
    finally:
        conn.close()

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


def cmd_run_journal(runs: int, slow: bool = False) -> None:
    python = sys.executable
    env = dict(os.environ)
    gaps = []
    phantoms = 0
    losses = 0

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



def cmd_write_journal_txn(kv_path: str, ev_path: str, marker_path: str) -> None:
    """Сценарий 4: транзакция + журнал. Убийство во время сброса буфера событий.

    События внутри транзакции копятся в буфере и пишутся ПОСЛЕ коммита.
    Маркер ставится на первом append — это значит: KV уже закоммичен, журнал ещё нет.
    """
    from purr import EventStream, Store

    journal = EventStream(ev_path)
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

    store = Store(kv_path, journal=journal)
    for i in range(1, 21):
        if store.set("pre%d" % i, "v" * 100):
            sys.stdout.write("OK pre%d\n" % i)
            sys.stdout.flush()

    sys.stdout.write("BATCH_START\n")
    sys.stdout.flush()
    with store.transaction():
        for i in range(1, 501):
            store.set("tx%d" % i, "v" * 100)
    sys.stdout.write("TX_DONE\n")
    sys.stdout.flush()


def cmd_verify_journal_txn(kv_path: str, ev_path: str) -> None:
    conn = sqlite3.connect(kv_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tx_kv = {row[0] for row in conn.execute("SELECT key FROM kv WHERE key LIKE 'tx%'").fetchall()}
    finally:
        conn.close()

    conn = sqlite3.connect(ev_path)
    try:
        ev_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        rows = conn.execute("SELECT payload FROM events WHERE topic='store'").fetchall()
    finally:
        conn.close()

    tx_ev = 0
    for (payload,) in rows:
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if data.get("op") == "set" and str(data.get("key", "")).startswith("tx"):
            tx_ev += 1

    print(json.dumps({
        "tx_in_kv": len(tx_kv),
        "tx_in_journal": tx_ev,
        "gap": len(tx_kv) - tx_ev,
        "integrity": integrity,
        "journal_integrity": ev_integrity,
    }))
    sys.exit(0 if len(tx_kv) in (0, 500) and len(tx_kv) == tx_ev and integrity == "ok" else 1)


def cmd_run_journal_txn(runs: int) -> None:
    python = sys.executable
    env = dict(os.environ)

    for n in range(1, runs + 1):
        tmp = tempfile.mkdtemp(prefix="purr-jtxn-")
        kv_path = os.path.join(tmp, "purr.db")
        ev_path = os.path.join(tmp, "events.db")
        marker = os.path.join(tmp, "flush.marker")

        child = subprocess.Popen(
            [python, SELF, "write-journal-txn", kv_path, ev_path, marker],
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
        time.sleep(0.2)  # дать сбросу начаться
        child.kill()
        child.wait()

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

        print("run %d: маркер сброса=%s | tx в KV %d/500 | событий tx %d | разрыв %d | "
              "integrity %s / журнал %s" % (
                  n, "да" if os.path.exists(marker) else "НЕТ",
                  data["tx_in_kv"], data["tx_in_journal"], data["gap"],
                  data["integrity"], data["journal_integrity"]))
        if data.get("stderr"):
            print("        stderr: %s" % data["stderr"].replace("\n", " ")[:250])


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
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
    elif mode == "verify-journal-txn":
        cmd_verify_journal_txn(sys.argv[2], sys.argv[3])
    elif mode == "run-journal-txn":
        cmd_run_journal_txn(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    elif mode == "run":
        cmd_run(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif mode == "run-txn":
        cmd_run_txn(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif mode == "run-journal":
        cmd_run_journal(int(sys.argv[2]) if len(sys.argv) > 2 else 5,
                        len(sys.argv) > 3 and sys.argv[3] == "slow")
    else:
        print("неизвестный режим: %s" % mode)
        sys.exit(2)


if __name__ == "__main__":
    main()
