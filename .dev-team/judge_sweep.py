"""Судья задачи «уборка и flush попадают в журнал».

Проверяет то, ради чего журнал существует: по нему можно восстановить состояние.
  1. контроль: убирать нечего -> sweep() возвращает 0 и не пишет событий;
  2. sweep() удаляет истёкший ключ -> в журнале событие delete на этот ключ;
  3. flush() удаляет всё -> в журнале событие delete на каждый удалённый ключ.

Сейчас второй и третий пункты падают: sweep/flush делают сырые DELETE без
_journal_emit, поэтому журнал считает удалённые ключи живыми.
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


def ops(stream: EventStream) -> list[tuple[str, str]]:
    events, _ = stream.read()
    out = []
    for e in events:
        payload = e.payload if isinstance(e.payload, dict) else json.loads(e.payload)
        out.append((payload.get("op"), payload.get("key")))
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="purr-sweep-"))
    db = tmp / "store.db"
    journal = EventStream(str(db))
    store = Store(str(db), journal=journal)
    failed = 0
    try:
        store.set("live", 1, ttl=60)
        store.set("dead", 2, ttl=0.05)
        time.sleep(0.15)

        before = ops(journal)
        swept = store.sweep()
        after = ops(journal)
        new = [op for op in after[len(before):]]
        ok = swept == 1 and ("delete", "dead") in new
        print(f"{'PASS' if ok else 'FAIL'}  sweep: удалено {swept}, новых событий {new} (ожидалось delete dead)")
        failed += 0 if ok else 1

        before = ops(journal)
        flushed = store.flush()
        after = ops(journal)
        new = [op for op in after[len(before):]]
        ok = flushed == 1 and ("delete", "live") in new
        print(f"{'PASS' if ok else 'FAIL'}  flush: удалено {flushed}, новых событий {new} (ожидалось delete live)")
        failed += 0 if ok else 1

        store.set("nothing", 1, ttl=60)
        before = ops(journal)
        swept = store.sweep()
        after = ops(journal)
        new = after[len(before):]
        ok = swept == 0 and new == []
        print(f"{'PASS' if ok else 'FAIL'}  контроль: убирать нечего -> удалено {swept}, событий {new}")
        failed += 0 if ok else 1
    finally:
        store.close()
        journal.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"ИТОГ: провалено {failed} из 3")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
