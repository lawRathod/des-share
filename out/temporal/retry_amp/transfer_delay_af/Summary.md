# Vector Confirm Summary

Model-side (DES search) vs bubble-side (synctest) evidence per candidate.
Shared monitor config (model.MonitorConfig); per-run monitor status in Summary.json.
Confirmation gate: bubble mean attempts/start >= 3.0 (critique A5).
Queue-depth + S2S-latency evidence (plan 2026-08-18): bubble max/final matching backlog, max history pending, worst-case S2S latency summary.

| vector | status | model aps | model fail | bubble aps | bubble fail | bubble score | bubble horizon | max backlog | final backlog | history max | s2s p50 | s2s p90 | s2s p99 | s2s max | s2s count |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| compose-transfer_delay+af | confirmed | 11.80 | 0 | 10.52 | 0 | 14.80 | 10825ms | 16 | 4 | 0 | 512.0 | 512.0 | 1024.0 | 2048.0 | 35297 |
