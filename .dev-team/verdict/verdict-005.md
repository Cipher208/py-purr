# Вердикт приёмки № 005

Дата: 2026-10-30
Задача: контракт журнала — вариант C (журнал в той же БД и транзакции)
Теги: accept-base dcc0919, accept-fix b822d52, accept-docs 65d6c17
Приёмщик: Warder (acceptance, режим plan, клоны вне рабочего каталога)

## Тело вердикта (транскрипция)

ВЕРДИКТ: ПРИНЯТО

ОСНОВАНИЕ: Обе стороны критерия воспроизведены (accept-base → exit=1/разрыв 497, accept-docs → exit=0/разрыв 0), неатомарный контроль остался красным (exit=1/разрыв 496, три прогона из трёх), и все девять изменённых тестов падают на коде базы — зелёными на обоих остаются ровно два заявленных Chisel, а удалённый тест буфера удалён вместе с самим буфером.

ПРОВЕРЕНО (16 пунктов, ключевые):
- accept-base exit=1 разрыв 497; accept-fix exit=0 разрыв 0; accept-docs три прогона 0/0/0;
- `run-journal-txn-nonatomic 1` на accept-docs → exit=1, разрыв 496 трижды — детектор не ослеп;
- подмена стенда на `sys.exit(0)` → зелёными становятся оба режима, то есть заглушка ловится парой прогонов; порча `_journal_emit` → exit=1 разрыв 500; порча «событие после коммита» → exit=1 «ПРОГОН НЕ СОСТОЯЛСЯ»;
- тесты не ослаблены: код accept-base + тесты с accept-fix → 9 failed, 66 passed; краснеют именно контрактные (`test_journal_events_join_the_txn`, `test_journal_drops_on_txn_rollback`, `test_mset_journals_inside_the_transaction`, `test_foreign_journal_path_rejected` ×2, `test_incr_journals_inside_the_transaction`, `test_journal_failure_rolls_back_the_data`, `test_close_resets_thread_state`, `test_transition_appended_to_journal`); ни одного skip/xfail в диффе;
- удалённый `test_journal_buffer_per_thread` обоснован: `hasattr(Store, "_journal_buffer")` → False;
- продукт: чужие пути журнала для `Store` и `StateMachine` → ValueError; `purr.JournalFlushError` → AttributeError; строка и событие видны второму соединению только после коммита; сбой вставки события откатывает данные;
- пробы аудита: HOLDS 8, BROKEN 2, VOID 0 — проба P1-9 не заглушена;
- документация: пример «Journaling mutations» прогнан дословно; миграция проверена сквозным сценарием (3 события и курсор переносятся, чтение продолжается; без мержа — ValueError и `reset_cursor`);
- бюджет 484 из 500, файлы дифа совпадают с границами посимвольно;
- 202 passed, ruff без регресса (44 ошибки против 45 на базе, ни одной новой).

ЧЕГО НЕ ПРОВЕРЯЛ: coverage-гейт 85%; конфигурацию CI; другие ОС и версии Python (только 3.11.14/Windows); стабильность `run`/`run-txn`/`run-journal` по одному прогону; числа производительности из ADR; частичный мерж старой `events.db`.

ЗАМЕЧАНИЯ: нет.

## Действие лида

Принято. Отдельно записано в отчёт карточки: в шапке ADR осталась устаревшая фраза «Поле `## Решение` пустое» — на заполненность поля не влияет, правится следующим касанием ADR.
