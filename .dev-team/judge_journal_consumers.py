"""Судья задачи «обещания про потребителей журнала проверены».

Три проверки, каждая — про утверждение, которое раньше было обещанием:
  1. читатель, трогающий только op/key/value, не падает на новой форме события;
  2. корректный реплей (понимает set/delete/flush) сходится с живой базой;
  3. отказ поиска срока в mset() оставляет базу нетронутой — ни ключей, ни событий.

Отдельно печатает предупреждение: реплей, игнорирующий неизвестные op, теряет
flush и оставляет удалённые ключи живыми. Это не проверка, а факт, который
должен быть в документации.
"""

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from purr import EventStream, Store  # noqa: E402


class Injected(Exception):
    pass


class _Proxy:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, *args, **kwargs):
        if "SELECT key, expires_at" in sql:
            raise Injected("injected: expiry lookup failed")
        return self._conn.execute(sql, *args, **kwargs)


class _Broken(Store):
    def _get_conn(self):
        return _Proxy(super()._get_conn())


def read_all(stream: EventStream) -> list[dict]:
    out, cursor = [], None
    while True:
        batch, last = stream.read(cursor=cursor, limit=500)
        if not batch:
            break
        out.extend(e.payload if isinstance(e.payload, dict) else {} for e in batch)
        if last is None or last == cursor:
            break
        cursor = last
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="purr-consumers-"))
    db = tmp / "store.db"
    journal = EventStream(str(db))
    store = Store(str(db), journal=journal)
    bad = 0
    try:
        store.set("a", 1)
        store.set("b", 2, ttl=60)
        store.flush()
        store.set("c", 3)  # после flush: проверка не должна проходить на пустоте
        ops = read_all(journal)

        # 1. читатель, который смотрит только на поля
        try:
            seen = [(op.get("op"), op.get("key"), op.get("value")) for op in ops]
            ok = ("flush", None, None) in seen and ("set", "a", 1) in seen
            print(f"{'PASS' if ok else 'FAIL'}  читатель полей: {seen}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"FAIL  читатель полей упал: {exc!r}")
        bad += 0 if ok else 1

        # 2. корректный реплей понимает flush
        clone = Store(str(tmp / "replay.db"))
        for op in ops:
            kind = op.get("op")
            if kind == "set":
                ttl = None
                if op.get("expires_at"):
                    from datetime import UTC, datetime

                    left = (datetime.fromisoformat(op["expires_at"]) - datetime.now(UTC)).total_seconds()
                    ttl = max(0.0, left)
                clone.set(op["key"], op["value"], ttl=ttl)
            elif kind == "delete":
                clone.delete(op["key"])
            elif kind == "flush":
                clone.flush()
        same = sorted(clone.keys()) == sorted(store.keys())
        print(f"{'PASS' if same else 'FAIL'}  корректный реплей: {sorted(clone.keys())} == {sorted(store.keys())}")
        bad += 0 if same else 1
        clone.close()

        # 3. отказ поиска срока в mset не оставляет полузаписи
        broken = _Broken(str(tmp / "broken.db"), journal=EventStream(str(tmp / "broken.db")))
        broken.set("keep", "v", ttl=60)
        keys_before = sorted(broken.keys())
        events_before = len(read_all(broken._journal))  # noqa: SLF001
        try:
            broken.mset({"x": 1, "y": 2})
            ok = False
            print("FAIL  отказ mset не сработал — инжекция не применилась")
        except Injected:
            ok = sorted(broken.keys()) == keys_before and len(read_all(broken._journal)) == events_before  # noqa: SLF001
            print(f"{'PASS' if ok else 'FAIL'}  отказ mset: ключи {sorted(broken.keys())}, событий {len(read_all(broken._journal))} (было {events_before})")  # noqa: SLF001
        bad += 0 if ok else 1
        broken.close()

        print("ВНИМАНИЕ: реплей, игнорирующий неизвестный op, теряет flush и оставляет удалённые ключи живыми — см. README.")
    finally:
        store.close()
        journal.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"ИТОГ: провалено {bad} из 3")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
