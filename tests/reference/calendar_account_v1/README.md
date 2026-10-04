Frozen pre-extraction reference only; never imported by production code.

`account.py` is byte-for-byte `rs60_eval_account_v1.py`, SHA-256
`b66ca8bbcc71835331daec6b7e834174408625cb406f17d619a1abe1865a7e0f`.
`performance.py` extracts the unchanged performance function from the accepted
driver. `calendar.py` extracts unchanged dates/calendar/selection/HAC helpers
with their historical IS constants for parity tests. The source hashes and
provenance are recorded in `docs/calendar-month-account.md`.

These fixtures contain no market data, research output or live dependencies.
