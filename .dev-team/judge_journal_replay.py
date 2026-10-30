"""Судья задачи «журнал восстанавливает состояние полностью».

Шесть проверок, каждая — про то, что реплей даёт то же, что и база:
  1. set(ttl=) несёт срок истечения, реплей его восстанавливает;
  2. set() без TTL срока не несёт (поле не появляется от фонаря);
  3. incr по ключу с TTL несёт срок — он TTL сохраняет, значит и в журнале;
  4. mset по ключу с TTL несёт срок — он TTL тоже сохраняет;
  5. flush() пишет ОДНО событие op=flush, реплей очищает хранилище;
  6. sweep() по-прежнему пишет delete на каждый ключ (не сломан).

Красное до правки: 1, 3, 4 (срока нет), 5 (событий N вместо одного).
"""

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from purr import EventStream, Store  # noqa: E402


def events(stream: EventStream) -> list[dict]:
    out, cursor = [], None
    while True:
        batch, last = stream.read(cursor=cursor, limit=500)
        if not batch:
            break
        out.extend(e.payload if isinstance(e.payload, dict) else json.loads(e.payload) for e in batch)
        if last is None or last == cursor:
            break
        cursor = last
    return out


def replay(ops: list[dict], path: Path) -> Store:
    store = Store(str(path))
    for op in ops:
        kind = op.get("op")
        if kind == "set":
            ttl = None
            if op.get("expires_at"):
                ttl = max(0.0, _seconds_left(op["expires_at"]))
                if ttl == 0:
                    store.delete(op["key"])
                    continue
            store.set(op["key"], op["value"], ttl=ttl)
        elif kind == "delete":
            store.delete(op["key"])
        elif kind == "flush":
            store.flush()
        elif kind == "expire":
            store.expire(op["key"], _seconds_left(op["expires_at"]))
    return store


def _seconds_left(iso: str) -> float:
    from datetime import UTC, datetime

    return (datetime.fromisoformat(iso) - datetime.now(UTC)).total_seconds()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="purr-replay-"))
    db = tmp / "store.db"
    journal = EventStream(str(db))
    store = Store(str(db), journal=journal)
    bad = 0
    try:
        # 1. set(ttl=) несёт срок
        store.set("s1", "v", ttl=120)
        last = events(journal)[-1]
        ok = bool(last.get("expires_at"))
        print(f"{'PASS' if ok else 'FAIL'}  set(ttl): expires_at={'есть' if ok else 'НЕТ'} в событии {last}")
        bad += 0 if ok else 1

        # 2. set() без TTL срока не несёт
        store.set("s2", "v")
        last = events(journal)[-1]
        ok = not last.get("expires_at")
        print(f"{'PASS' if ok else 'FAIL'}  set() без TTL: expires_at отсутствует")
        bad += 0 if ok else 1

        # 3. incr по ключу с TTL
        store.set("c1", 1, ttl=120)
        store.incr("c1", 1)
        last = events(journal)[-1]
        ok = last.get("op") == "set" and bool(last.get("expires_at"))
        print(f"{'PASS' if ok else 'FAIL'}  incr с TTL: expires_at={'есть' if ok else 'НЕТ'}")
        bad += 0 if ok else 1

        # 4. mset по ключу с существующим TTL
        store.set("m1", "old", ttl=120)
        store.mset({"m1": "new"})
        last = events(journal)[-1]
        ok = bool(last.get("expires_at"))
        print(f"{'PASS' if ok else 'FAIL'}  mset с TTL: expires_at={'есть' if ok else 'НЕТ'}")
        bad += 0 if ok else 1

        # 5. flush — одно событие, реплей очищает
        bulk = Store(str(tmp / "bulk.db"), journal=EventStream(str(tmp / "bulk.db")))
        bulk_journal = bulk._journal  # noqa: SLF001 - судье нужен тот же поток
        for i in range(200):
            bulk.set(f"f{i}", i)
        before = len(events(bulk_journal))
        bulk.flush()
        after = events(bulk_journal)
        new = after[before:]
        ok = len(new) == 1 and new[0].get("op") == "flush"
        print(f"{'PASS' if ok else 'FAIL'}  flush 200 ключей: новых событий {len(new)}, op={new[0].get('op') if new else '-'} (ожидалось 1 × flush)")
        bad += 0 if ok else 1

        # 6. sweep по-прежнему по-событию
        store.set("sw", 1, ttl=0.05)
        time.sleep(0.12)
        before = len(events(journal))
        store.sweep()
        new = events(journal)[before:]
        ok = any(op.get("op") == "delete" and op.get("key") == "sw" for op in new)
        print(f"{'PASS' if ok else 'FAIL'}  sweep: события {new} (ожидалось delete sw)")
        bad += 0 if ok else 1

        # реплей всего журнала основной базы
        ops = events(journal)
        clone = replay(ops, tmp / "replay.db")
        same = sorted(clone.keys()) == sorted(store.keys())
        ttl_ok = clone.ttl("s1") is not None and store.ttl("s1") is not None
        print(f"{'PASS' if same and ttl_ok else 'FAIL'}  реплей: ключи {sorted(clone.keys())} == {sorted(store.keys())}, ttl(s1)={'есть' if ttl_ok else 'НЕТ'}")
        bad += 0 if same and ttl_ok else 1
        clone.close()
        bulk.close()
    finally:
        store.close()
        journal.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"ИТОГ: провалено {bad} из 7")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
