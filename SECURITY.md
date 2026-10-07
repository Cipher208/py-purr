# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

Only the latest release on `main` receives fixes.

## Reporting a Vulnerability

Please report privately. Do not open a public issue.

- Preferred: open a private advisory via the repository's
  **[Security tab](https://github.com/Cipher208/py-purr/security/advisories/new)**.
- Or email **Cipher208@proton.me** with `py-purr security` in the subject.

Please include steps to reproduce, a minimal sample, and the impact you see.
You will get an acknowledgement within **7 days**, and an assessment with a fix
timeline within **14 days**. If a fix is needed you will be credited in the
advisory, unless you ask otherwise.

## What this library does with your input

Stating the shape of the thing makes a report easier to judge:

- **No network code.** PURR opens no sockets. There is no client, no server, no
  telemetry, no update check. `grep -rE "socket|requests|urllib|http"` over
  `purr/` returns nothing, and that is meant to stay true.
- **The database file is the only untrusted input**, read through the standard
  library's `sqlite3`. If someone hands you a hostile `.db`, the parser in play
  is SQLite's, not ours.
- **SQL is parameterized.** Values are bound, never interpolated. The only
  string-formatted statements are `PRAGMA user_version` and
  `PRAGMA busy_timeout`, both built from integer constants defined in the code.
- **No `pickle`, no `eval`, no `exec`, no subprocess.** Values round-trip
  through JSON, which is why a stored value cannot execute on read.
- **No secrets of its own.** PURR has no credentials to leak.

## In scope

- A code path that lets a value stored in the database execute when read back.
- Injection through a key, topic or event payload that reaches SQL.
- Path traversal or file overwrite through a database, backup or destination
  path argument.
- A dependency (currently `pydantic`) made exploitable by how PURR uses it.

## Out of scope

- Vulnerabilities in SQLite, in `sqlite3`, or in `pydantic` — report those
  upstream. If PURR's usage makes one exploitable, that part is in scope.
- Reading a database file an attacker already controls: that is SQLite's parser,
  not a flaw in this library.
- Denial of service from very large values or an enormous number of keys. This
  is an embedded store with no quotas by design; limits belong to the
  application.
- Anything requiring an attacker who can already write your source files.
- The absence of encryption at rest. The file is a plain SQLite database. If you
  need encryption, use an encrypted volume or SQLCipher — PURR will not add it.

## For anyone embedding PURR

- It is a **local** store. Do not put the `.db` file on a network share with
  untrusted writers; SQLite's locking assumes a filesystem that behaves.
- Treat the database file as carefully as the data inside it. It is your data,
  in the clear.
