# Карточка задачи
## Задача
Заменить дырявого судью-«детектора намерений» на честный механический сторож целостности переноса и зафиксировать серверное направление в отдельном документе.
## Что меняем
Решение владельца от 2026-11-04, дословно: **«вариант А»** — «упростить судью: оставить только проверяемое, отказаться от детектора обещаний и прямо написать в карточке, что он не ловит парафразы». Обоснование: две независимые проверки показали, что регулярки не могут доказать отсутствие серверных обещаний в русскоязычном тексте, а каждая новая эвристика порождает следующий обход.

- `.dev-team/judge_roadmap_direction.py` переписывается: удаляются `SERVER_MARKERS`, `PROMISE_FORMS`, `NEGATION_FORMS`, `is_pointer`, `states_absence`, `MIN_POINTERS`, `MIN_FRAGMENT_SECTIONS` и вся проверка «нет серверных обещаний». Остаются пять МЕХАНИЧЕСКИХ проверок.
- `FUTURE_PLAN.md` и `FUTURE_PLAN_SERVER.md` — физическое разделение серверного и активного плана,выполненное ранее и сохранённое в бэкапе; код продукта не меняется.
- В карточке и отчёте ЯВНО помечается непроверенное: новые серверные обещания, парафразы, Unicode-гомоглифы, семантика строк-указателей судьёй не проверяются.

Отдельно, разовым замером при приёмке, проверяется перенос без потерь: все непустые строки `git show 2f465b9:FUTURE_PLAN.md` обязаны присутствовать в объединении двух документов.
## Тип работы
дефект
## Тип правки
поведение
## Команда прогона
uv run python .dev-team/judge_roadmap_direction.py
## Критерий приёмки
`uv run python .dev-team/judge_roadmap_direction.py` возвращает `0` и печатает `провалено 0 из 5`. Пять проверок, все детерминированные, без распознавания естественного языка:
1. Дословное решение владельца «Берем за основу концепцию А, сервер возможно потом» с датой 2026-11-04 в шапке активного документа и то же решение с датой в шапке вынесенного.
2. Шапка активного документа содержит поля Status и Vision, принятую формулировку встроенной библиотеки и формулировку «без сервера/без инфраструктуры»; запрещённая строка «full redis-like database engine» отсутствует.
3. `FUTURE_PLAN_SERVER.md` существует, >=150 строк, его шапка содержит решение, дату и пометку отложенности; все 19 контрольных фрагментов `MOVED_FRAGMENTS` найдены ЦЕЛЫМИ строками (strip-совпадение) вне HTML-комментариев.
4. В активном документе есть непустой раздел «Активный план» (>=3 строк / 120 символов) со ссылками на все шесть разделов ядра 3.11/3.12/3.16/3.21/3.36/3.37.
5. Оба документа полные: активный >=100 строк и содержит Roadmap, Milestones, Open Questions с телами; вынесенный >=2000 символов.

**Явно НЕ проверяется и обязано быть названо в отчёте:** отсутствие серверных обещаний в активном документе, парафразы и переформулировки, Unicode-гомоглифы, семантическая корректность строк-указателей, новые обещания добавленные после переноса. Судья — сторож целостности переноса, а не детектор намерений. Требовать от него ловить парафразы запрещено решением владельца.

Негативный контроль, каждая мутация даёт `exit=1` и называет причину: убрать решение; вернуть старый Vision; удалить или урезать вынесенный документ; испортить один контрольный фрагмент (в том числе попытка восстановить его в HTML-комментарии); опустошить активный план; опустошить активный документ.
## Текущий вывод
FUTURE_PLAN.md: прочитано 49757 байт, 1632 строк
FAIL  1 решение владельца: assert «дословное решение владельца с датой 2026-11-04» -- нарушено: фраза 'Берем за основу концепцию А, сервер возможно потом' не найдена (1632 строк просмотрено)
FAIL  2 шапка Status/Vision: assert «шапка Status/Vision фиксирует встроенную библиотеку без инфраструктуры» -- нарушено: шапка обещает 'full redis-like database engine' как ближайшую цель
FAIL  3 серверные обещания отложены по всему документу: assert «ни одного серверного обещания без пометки «отложено»» -- нарушено: непокрытых мест 63 из 63 найденных строк с серверными маркерами, все поименно:
    - [1] «Phase 3: Networking» строка 193 [этап Networking / Python client] -> '### Phase 3: Networking'
    - [2] «Phase 3: Networking» строка 195 [server side / remote access / client library] -> 'Add the server side for remote access.'
    - [3] «Phase 3: Networking» строка 199 [TCP Server / TCP-сервер; RESP / Redis Protocol] -> '| **TCP Server** | Redis-compatible protocol | P1 |'
    - [4] «Phase 3: Networking» строка 200 [HTTP API / REST API] -> '| **HTTP API** | REST API for CRUD | P1 |'
    - [5] «Phase 3: Networking» строка 201 [WebSocket] -> '| **WebSocket** | Pub/Sub over WebSocket | P2 |'
    - [6] «Phase 3: Networking» строка 202 [RESP / Redis Protocol] -> '| **Redis Protocol** | RESP (Redis Serialization Protocol) | P1 |'
    - [7] «TCP Server» строка 204 [TCP Server / TCP-сервер] -> '#### TCP Server'
    - [8] «TCP Server» строка 206 [дерево server/ / purr/server.py] -> '# purr/server.py'
    - [9] «TCP Server» строка 207 [TCP Server / TCP-сервер] -> 'class PurrServer:'
    - [10] «TCP Server» строка 214 [TCP Server / TCP-сервер] -> '"""Start TCP server."""'
    - [11] «TCP Server» строка 215 [TCP Server / TCP-сервер] -> 'server = await asyncio.start_server('
    - [12] «TCP Server» строка 219 [TCP Server / TCP-сервер] -> 'await server.serve_forever()'
    - [13] «TCP Server» строка 222 [RESP / Redis Protocol] -> '"""Handle client connection (RESP protocol)."""'
    - [14] «TCP Server» строка 223 [RESP / Redis Protocol] -> '# Parse RESP, execute commands, return results'
    - [15] «HTTP API» строка 227 [HTTP API / REST API] -> '#### HTTP API'
    - [16] «HTTP API» строка 229 [HTTP API / REST API] -> '# purr/http_api.py'
    - [17] «HTTP API» строка 230 [HTTP API / REST API] -> 'from aiohttp import web'
    - [18] «Phase 4: Advanced Features» строка 273 [Cluster / Clustering / консенсус; Replication / replicas / master-slave] -> '| **Cluster** | Multi-node replication | P2 |'
    - [19] «Phase 4: Advanced Features» строка 274 [RDB / AOF] -> '| **Persistence** | RDB snapshots + AOF | P1 |'
    - [20] «Phase 4: Advanced Features» строка 276 [TLS / Auth / ACL] -> '| **TLS** | Encrypted connections | P2 |'
    - [21] «Phase 4: Advanced Features» строка 277 [TLS / Auth / ACL] -> '| **Auth** | Password/AUTH command | P1 |'
    - [22] «Phase 5: Developer Experience» строка 316 [server side / remote access / client library; этап Networking / Python client] -> '| **Client Library** | Python client for remote access | P1 |'
    - [23] «Phase 5: Developer Experience» строка 317 [Docker] -> '| **Docker** | Docker image | P1 |'
    - [24] «3.6 Replication (WAL Log Shipping)» строка 505 [Replication / replicas / master-slave] -> '### 3.6 Replication (WAL Log Shipping)'
    - [25] «3.6 Replication (WAL Log Shipping)» строка 507 [Replication / replicas / master-slave] -> 'The master ships WAL logs; the replicas apply the diffs.'
    - [26] «3.6 Replication (WAL Log Shipping)» строка 510 [Replication / replicas / master-slave] -> '# purr/replication.py'
    - [27] «3.6 Replication (WAL Log Shipping)» строка 517 [Replication / replicas / master-slave] -> '"""Add a replica to replicate to."""'
    - [28] «3.6 Replication (WAL Log Shipping)» строка 520 [Replication / replicas / master-slave] -> '"""Send WAL changes to replicas."""'
    - [29] «3.6 Replication (WAL Log Shipping)» строка 522 [Replication / replicas / master-slave] -> '# 2. Send diff to each replica'
    - [30] «3.6 Replication (WAL Log Shipping)» строка 525 [Replication / replicas / master-slave] -> 'async def catchup(self, replica: ReplicaConnection) -> None:'
    - [31] «3.6 Replication (WAL Log Shipping)» строка 526 [Replication / replicas / master-slave] -> '"""Full sync for new replica."""'
    - [32] «3.7 Sharding (hash-based partitioning)» строка 529 [Sharding] -> '### 3.7 Sharding (hash-based partitioning)'
    - [33] «3.7 Sharding (hash-based partitioning)» строка 534 [Sharding] -> '# purr/sharded_store.py'
    - [34] «3.7 Sharding (hash-based partitioning)» строка 535 [Sharding] -> 'class ShardedStore:'
    - [35] «3.14 CLI Tools» строка 751 [purr serve / --port; RESP / Redis Protocol] -> 'purr serve --port 6379          # Redis-compatible protocol (RESP)'
    - [36] «3.14 CLI Tools» строка 752 [purr serve / --port; HTTP API / REST API] -> 'purr serve --http --port 8080   # HTTP API'
    - [37] «3.18 Key Decisions» строка 819 [RESP / Redis Protocol] -> '- **RESP is not required in v1**: start with HTTP + the Python SDK'
    - [38] «3.23 REST API Spec» строка 926 [HTTP API / REST API] -> '### 3.23 REST API Spec'
    - [39] «3.26 Limitations» строка 1013 [Cluster / Clustering / консенсус; Planned / in the future / ETA] -> '| **Not for distributed systems** | PURR lives on one machine | Clustering in the future |'
    - [40] «Target (v1.0.0)» строка 1480 [Milestones v0.4/v0.5/v0.7/v1.0] -> '### Target (v1.0.0)'
    - [41] «Target (v1.0.0)» строка 1506 [TLS / Auth / ACL] -> '│   └── auth.py           # Authentication'
    - [42] «Target (v1.0.0)» строка 1507 [дерево server/ / purr/server.py] -> '├── server/'
    - [43] «Target (v1.0.0)» строка 1508 [TCP Server / TCP-сервер; RESP / Redis Protocol] -> '│   ├── tcp.py            # TCP server (RESP)'
    - [44] «Target (v1.0.0)» строка 1509 [HTTP API / REST API] -> '│   ├── http.py           # REST API'
    - [45] «Target (v1.0.0)» строка 1510 [WebSocket] -> '│   └── websocket.py      # WebSocket'
    - [46] «Target (v1.0.0)» строка 1511 [server side / remote access / client library] -> '├── client/'
    - [47] «Target (v1.0.0)» строка 1512 [этап Networking / Python client] -> '│   ├── __init__.py       # Python client'
    - [48] «Target (v1.0.0)» строка 1513 [server side / remote access / client library] -> '│   └── connection.py     # Connection pool'
    - [49] «6. Comparison with Redis» строка 1587 [RDB / AOF] -> '| **Storage** | In-memory + RDB/AOF | SQLite WAL |'
    - [50] «6. Comparison with Redis» строка 1590 [Replication / replicas / master-slave; Planned / in the future / ETA] -> '| **Replication** | Master-slave | Planned (Phase 4) |'
    - [51] «6. Comparison with Redis» строка 1591 [Cluster / Clustering / консенсус; Planned / in the future / ETA] -> '| **Cluster** | Redis Cluster | Planned (Phase 4) |'
    - [52] «6. Comparison with Redis» строка 1592 [RESP / Redis Protocol; Planned / in the future / ETA] -> '| **Protocol** | RESP | Planned (Phase 3) |'
    - [53] «6. Comparison with Redis» строка 1607 [Cluster / Clustering / консенсус] -> '- Cluster support'
    - [54] «7. Milestones» строка 1614 [Planned / in the future / ETA] -> '| Milestone | Features | ETA |'
    - [55] «7. Milestones» строка 1618 [TCP Server / TCP-сервер; HTTP API / REST API; Milestones v0.4/v0.5/v0.7/v1.0] -> '| **v0.4.0** | TCP Server, HTTP API | 3 weeks |'
    - [56] «7. Milestones» строка 1619 [TLS / Auth / ACL; Milestones v0.4/v0.5/v0.7/v1.0] -> '| **v0.5.0** | Pub/Sub, Auth | 1 month |'
    - [57] «7. Milestones» строка 1620 [server side / remote access / client library] -> '| **v0.6.0** | Client Library, CLI | 1.5 months |'
    - [58] «7. Milestones» строка 1621 [Cluster / Clustering / консенсус; Replication / replicas / master-slave; Milestones v0.4/v0.5/v0.7/v1.0] -> '| **v0.7.0** | Cluster, Replication | 2 months |'
    - [59] «7. Milestones» строка 1622 [Milestones v0.4/v0.5/v0.7/v1.0; Full Redis compatibility] -> '| **v1.0.0** | Full Redis compatibility | 3 months |'
    - [60] «8. Open Questions» строка 1628 [RESP / Redis Protocol] -> '1. **RESP Protocol**: Implement full RESP2 or simplified version?'
    - [61] «8. Open Questions» строка 1629 [RDB / AOF] -> '2. **Persistence**: RDB snapshots vs AOF vs both?'
    - [62] «8. Open Questions» строка 1630 [Cluster / Clustering / консенсус] -> '3. **Cluster**: Consensus algorithm (Raft vs Paxos)?'
    - [63] «8. Open Questions» строка 1631 [TLS / Auth / ACL] -> '4. **Auth**: Password-only or ACL-based?'
FAIL  4 активный план концепции А: assert «непустой активный план под концепцию А с разделами ядра и без сервера следующим шагом» -- нарушено: раздел активного плана не найден (принятые заголовки: «Активный план» / «Active Plan»)
PASS  5 документ непустой и полный: 1632 строк, 49245 символов; Roadmap/Milestones/Open Questions с телом
провалено 4 из 5
exit=1
## Файлы в границах
FUTURE_PLAN.md
FUTURE_PLAN_SERVER.md
.dev-team/judge_roadmap_direction.py
## Бюджет правки
900
## Документация
не требуется
## Решение нужно
нет
## Правки карточки
ПРАВКА: 2026-11-05 | Keel | `## Текущий вывод` переписан из фактического прогона на состоянии до работы (`провалено 4 из 5`, exit=1) после возврата дерева к HEAD; блок дословно сверен diff'ом. Гейты A/C/D/E закрыты: A=0, C по красному выводу Assay и вердикту «команда подходит», D=`627 строк из 900`, E=0.
ПРАВКА: 2026-11-04 | Keel | решение владельца «вариант А» записано дословно в `## Что меняем`; критерий перезаморожен ДО работы под механического судью, проверка «нет серверных обещаний» удалена, непроверенное поименовано явно. ADR не заводится: `ADR-001-journal-contract.md` уже существует, гейт B требует ровно один ADR-файл.
ПРАВКА: 2026-11-04 | независимый проверяющий (2-й заход) | вердикт ОТКЛОНЕНО повторно: `MIN_FRAGMENT_SECTIONS` обходится фальшивыми подзаголовками, `NEGATION_FORMS` оправдывает любую строку с отрицанием, Unicode-гомоглифы и парафразы не видны маркерам, подмена имени файла в указателе проходит как подстрока, `PROMISE_FORMS` даёт ложное срабатывание на честном тексте, `## Текущий вывод` устарел | применено частично (Keel, 2026-11-04): `## Текущий вывод` заменён на воспроизведённое в клоне красное `провалено 5 из 5`, `exit=1`. Остальные дыры НЕ закрыты: дальнейшее латание регулярок порождает новые обходы, требуется решение владельца о смене критерия. Задача НЕ принята, коммита и пуша нет.
ПРАВКА: 2026-11-04 | независимый проверяющий | вердикт ОТКЛОНЕНО: четыре обхода судьи (кириллическое обещание, P1-обещание под видом указателя, фрагмент в HTML-комментарии, подстрочная проверка) и два расхождения карточки с кодом (15 против 19 фрагментов, «хотя бы одна» против MIN_POINTERS=3) | применено (Keel, 2026-11-04): добавлены кириллические маркеры и PROMISE_FORMS, is_pointer ужесточён до строки-цитаты без живого обещания, фрагменты проверяются целыми строками вне комментариев в >=8 разделах, числа карточки выверены по коду; дополнительно вынесены 4 сетевые строки из раздела 3.38
ПРАВКА: 2026-11-04 | Keel | владелец изменил подход: «Всё сесрверное в отдельную доку на потом выноси». Критерий со счётчика пометок переписан на физическое разделение документов; бюджет поднят, потому что переносится ~300 строк серверного содержимого. Решение записано дословно в `## Что меняем`.
ПРАВКА: 2026-11-04 | Keel | маркер интерфейса снова снял выбор эксперта; гейты A-F и роли не применяются, но независимая проверка сохраняется отдельным агентом в чистом контексте, арбитр — исполняемый судья.
ПРАВКА: 2026-11-04 | Keel | Assay честно вернул, что проверка 3 покрывает только семь мест; лид своим замером нашёл серверные обещания ещё в таблицах Phase 4/5, дереве `server/`, `purr serve`, разделе Limitations и `Cluster support`. Критерий расширен до инварианта «ни одного серверного обещания без пометки», иначе была бы починена половина документа. База переставляется ДО первой правки роадмапа, поэтому красное остаётся в диапазоне base..fix.
ПРАВКА: 2026-11-04 | Keel | решение владельца уже принято до фазы 1 и записано дословно в `## Что меняем`; ADR не заводится, потому что гейт B считает файлы `ADR-*.md` и требует ровно один, а `ADR-001-journal-contract.md` уже занят контрактом журнала. Фаза решения с Vitruv придёт отдельной задачей при выборе первого продуктового этапа.
## Отчёт
