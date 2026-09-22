# Conditional numerical semantics

Read when the estimator is sparse/event-based, recursive or partitioned; use only the applicable checks.

For sparse/event measurements, distinguish unavailable history or undefined
baseline from a valid no-event observation. Preserve missingness and expose
coverage diagnostics. Test raw-versus-projected variation and order: zero MAD
does not imply constant input. Keep equal values tied; never manufacture
deciles by ticker/random tie-breaking. Any numerical fallback must be explicit
and fixed before inspecting payoff results. A report baseline and an invented
extension remain separately identified implementations.

For a day-partitioned implementation, use an explicit complete trading calendar
and retain only the necessary rolling state. Chunk boundaries must not reset a
window; missing dates must not be compressed; a future security must not alter
earlier cross-sections. Compare streaming output with the frozen numerical
reference across at least one rolling-window/chunk boundary. A failed day must
not partially update the rolling state or silently trigger a second input read.
An in-memory sample ceiling is not a justification to limit an otherwise
bounded day-streaming implementation to an arbitrary short research window.
