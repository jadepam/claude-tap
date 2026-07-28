# Delete empty-active sessions evidence

## Source

Real dashboard session store created through claude-tap `TraceStore.create_session()`:

- DB: `.traces/delete-empty-active-sessions/traces.sqlite3`
- One finalized Claude Code session with a captured `/v1/messages` record
- Two abandoned active sessions with `record_count = 0` (the dashboard "空" shape)

## Capture

1. Start `LiveViewerServer(dashboard_mode=True)` against that SQLite DB.
2. Open `/dashboard`, enter edit mode, select an empty-active row.
3. Screenshot shows the empty-active checkbox enabled and selected (`1 selected`).

The screenshot proves abandoned zero-trace active sessions are selectable for deletion while active sessions with captured records remain protected.
