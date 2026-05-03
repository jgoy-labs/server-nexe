# Operations

Operational notes for running server-nexe in production-like setups.

## Log rotation

The RAG/memory subsystem (`memory.memory.rag_logger`) writes detailed
operational lines to `rag.log` on every chat exchange (embedding generation,
collection search, MEM_SAVE/MEM_DELETE intents, Qdrant timings). Without
rotation, this file grew unbounded — a long-running local install could fill
the disk in weeks.

Since v1.0.4-beta the handler is `TimedRotatingFileHandler`:

- **Rotates** at local midnight (`when="midnight"`, `interval=1`).
- **Retains** 14 daily backups (`backupCount=14`); older snapshots are
  deleted automatically by the handler.
- **Encoding** is `utf-8` so the emoji prefixes used by `RAGEmojis` survive
  on stripped containers and CI runners.
- **Path** is unchanged: the resolver still tries
  `$NEXE_LOGS_DIR/rag.log`, then `<project>/storage/logs/rag.log`, then
  `/tmp/nexe-logs/rag.log`. Operators tailing the original path keep
  visibility — only the rotation behaviour changes.

Backup files appear next to the primary log as
`rag.log.YYYY-MM-DD` (suffix added by the handler). To preserve history
beyond 14 days, copy the dated files to long-term storage **before** the
handler ages them out — for example, with a daily cron job:

```sh
# Snapshot any rag.log.* file older than 7 days that is not yet in the archive.
find "$HOME/Nexe-Logs" -name 'rag.log.*' -mtime +7 \
  -exec rsync --ignore-existing {} /path/to/archive/ \;
```

The `nexe.security` logger (`plugins/security/security_logger`) ships its
own per-day filename pattern (`security_YYYYMMDD.log`) and is not affected
by this change. Adding `backupCount` retention to that logger is tracked
as `R6-11b` in `nat/dev/server-nexe/diari/BACKLOG-v1.0.4.md`.
