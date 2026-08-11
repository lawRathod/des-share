"""GoDES experiment dashboard — drop-in viewer for out/ directory.

Usage:
    pip install streamlit pandas
    streamlit run dashboard.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")

# --- Global font compaction: default Streamlit typography is far too large
# for the dense sidebar metric grid and wide result tables. ---
st.markdown("""
<style>
html, body, [class*="css"] {
    font-size: 16px !important;
}
[data-testid="stSidebar"] {
    font-size: 0.85rem;
}
[data-testid="stSidebar"] [data-testid="stMetric"] {
    gap: 0.2rem;
    padding: 0.25rem 0;
}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {
    font-size: 0.9rem !important;
}
[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
    font-size: 0.68rem !important;
    opacity: 0.85;
}
[data-testid="stSidebar"] [data-testid="stMetricValue"] p,
[data-testid="stSidebar"] [data-testid="stMetricLabel"] p {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    font-size: 0.75rem;
}
h1 { font-size: 1.4rem !important; }
h2 { font-size: 1.15rem !important; }
h3 { font-size: 1.05rem !important; }
</style>
""", unsafe_allow_html=True)

st.title("GoDES Experiments")

_db = st.checkbox("Debug session state", key="debug_ss")
if _db:
    st.write("### Debug")
    st.write("all keys:", list(st.session_state.keys()))

BASE = Path("out")
if not BASE.exists():
    st.warning(f"'{BASE}' not found. Run experiments first.")
    st.stop()

@st.cache_data(show_spinner=False)
def load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file, return list of dicts. Cached to avoid re-parse on refresh."""
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

@st.cache_data(show_spinner=False)
def load_json_head(path: Path, max_size_mb: float = 10) -> dict | str:
    """Load JSON; if > max_size_mb, return summary string instead of full object."""
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        return f"({size_mb:.1f} MB — too large to display. Use jq/less to inspect: {path})"
    return json.loads(path.read_text())


@st.cache_data(show_spinner=False)
def _pick(path: Path, alt: str = ".parquet") -> Path | None:
    """Return path if exists, else path.with_suffix(alt). None if neither."""
    if path.exists():
        return path
    a = path.with_suffix(alt)
    return a if a.exists() else None


def _experiment_runs(exp: Path) -> list[Path]:
    """Find run directories in both flat and seed-partitioned layouts.

    Older exporters wrote ``experiment/<run>/`` while newer experiment
    entrypoints write ``experiment/<seed>/<run>/``. A run is identified by
    its results file rather than by directory depth so both layouts remain
    readable.
    """
    runs: list[Path] = []
    for child in sorted(exp.iterdir()):
        if not child.is_dir():
            continue
        if (child / "results.json").exists():
            runs.append(child)
            continue
        for nested in sorted(child.iterdir()):
            if nested.is_dir() and (nested / "results.json").exists():
                runs.append(nested)
    return runs


def _parse_snap(s):
    """Parse snapshot column: bytes, str, or dict → dict."""
    if isinstance(s, (bytes, str)):
        return json.loads(s.decode() if isinstance(s, bytes) else s)
    return s if isinstance(s, dict) else {}


@st.cache_data(show_spinner=False)
def _snaps_df(path: Path) -> pd.DataFrame | None:
    """Load scenario snaps .jsonl or .parquet → standardised DataFrame."""
    if path.suffix == ".parquet":
        raw = pd.read_parquet(path)
    else:
        s = load_jsonl(path)
        raw = pd.DataFrame(s) if s else pd.DataFrame()
    if raw.empty:
        return None
    step = max(1, len(raw) // 500)
    # Reset the sampled index before normalising nested JSON. Otherwise the
    # scalar columns retain the original row labels (0, step, 2*step, ...)
    # while json_normalize creates a fresh 0..N index, causing every chart
    # value to become NaN once a run exceeds 500 snapshots.
    sampled = raw.iloc[::step].reset_index(drop=True)
    snap_df = pd.json_normalize(sampled["snapshot"].apply(_parse_snap)).reset_index(drop=True) if "snapshot" in sampled else pd.DataFrame()
    pool_df = pd.json_normalize(sampled["pool_stats"].apply(_parse_snap)).reset_index(drop=True) if "pool_stats" in sampled else pd.DataFrame()
    result = pd.DataFrame({
        "time_ms": sampled.get("sim_now_ms", 0),
        "queue_mean": snap_df.get("QueueMean", 0),
        "retry_amp": snap_df.get("RetryAmplification", 0),
        "window_retry_amp": snap_df.get("WindowRetryAmp", 0),
        "timeout_rate": snap_df.get("TimeoutRate", 0),
        "drop_rate": snap_df.get("DropRate", 0),
        "sched_to_start": sampled.get("schedule_to_start_ms", snap_df.get("ScheduleToStartLatency", 0)),
        "tasks": snap_df.get("Tasks", 0),
        "attempts": snap_df.get("Attempts", 0),
        "task_rate": snap_df.get("TaskRate", 0),
        "resched_depth": snap_df.get("ReschedulerDepth", 0),
        "pool_busy": pool_df.get("Busy", 0),
        "pool_waiters": pool_df.get("Waiters", 0),
        "pool_peak": pool_df.get("PeakBusy", 0),
    })
    if not result.empty:
        result = result.set_index("time_ms")
    return result


def _tv(r: dict, *keys: str):
    """Temporal value: top-level, then Dashboard.*, with case variants + aliases."""
    aliases = {"RetryAmplification": ["Ratio", "AttemptsPerStart"]}

    def _lookup(d: dict, k: str):
        for v in (k, k[:1].lower() + k[1:], re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()):
            val = d.get(v)
            if val is not None:
                return val
        return None

    for k in keys:
        v = _lookup(r, k)
        if v is not None:
            return v
        dash = r.get("Dashboard") or {}
        v = _lookup(dash, k)
        if v is not None:
            return v
        for a in aliases.get(k, []):
            v = _lookup(r, a)
            if v is not None:
                return v
            v = _lookup(dash, a)
            if v is not None:
                return v
    return None


def _d(v, default: str | int = "?"):
    """Return default when missing, else the value (0 stays 0)."""
    return default if v is None else v


def _fmt(v, spec: str = ".2f", default="?"):
    """Format numbers with spec; pass strings through; default when None."""
    if v is None:
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:{spec}}"
    return str(v)


def _show_results(r: dict, cols: list, meta: dict) -> None:
    """Display results dict in shape-aware metric columns.
    Supports temporal, tasqueue, and head_to_head result shapes."""
    # st is in scope from module-level import

    is_temporal = _tv(r, "TotalRPCs", "WorkflowSuccess", "AttemptedAdds") is not None
    is_head_to_head = "Label" in r

    if is_temporal:
        ms = _tv(r, "MonitorStatus") or {}
        if ms:
            metastable = ms.get("Metastable", False)
            status_icon = "✅" if metastable else "🟢"
            status_label = "Metastable" if metastable else "Stable"
            cols[3].metric(f"{status_icon} Status", status_label,
                help="Monitor-declared metastability. True when weighted multi-dim score exceeds epsilon for N consecutive windows.")
        else:
            cols[3].metric("Mode", _d(_tv(r, "RunType")),
                help="Run mode: 'bubble' = synctest virtual-clock run; 'des' = pump-driven simulation.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Workflow Success", _d(_tv(r, "WorkflowSuccess")),
            help="Number of workflows that completed successfully (workflow_success cumulative metric).")
        c2.metric("Activity Success", _d(_tv(r, "ActivitySuccess")),
            help="Number of activity executions that completed successfully (activity_success).")
        c3.metric("Retry Amplification", _fmt(_tv(r, "RetryAmplification"), ".4f", "0"),
            help="Cumulative ratio: task_attempt / task_count. <1.0 means dispatch gap (tasks never attempted). >1.0 would mean retry amp but Temporal creates new task_count per retry cycle. Bubble mode: attempted adds / unique workflow starts.")
        c4.metric("Arrivals", _d(_tv(r, "ArrivalsProcessed", "UniqueWorkflowStarts")),
            help="Number of DES-scheduled workflow-start events consumed by the arrival channel. Should equal BurstCount + sustained arrivals. Bubble mode: unique workflow starts.")

        c1, c2, c3, c4 = st.columns(4)
        score = ms.get("Score")
        c1.metric("Score", f"{score:.2f}" if score is not None else "?",
            help="Multi-dimensional Monitor score: weighted L1 distance from baseline across queue depth, retries/sec, timeouts/sec, drops/sec. Higher = further from baseline.")
        c2.metric("Windows", ms.get("WindowsSeen", "?"),
            help="Total monitor windows seen (each = WindowMs ms of sim time). Warmup windows are excluded from score.")
        attempts = r.get("TaskAttempt") or _tv(r, "AttemptedAdds") or 0
        count = r.get("TaskCount") or _tv(r, "UniqueWorkflowStarts") or 0
        c3.metric("Attempts/Tasks", f"{attempts}/{count}" if (attempts or count) else "?",
            help="Total task_attempt entries vs task_count entries. Attempts include retries at both workflow and activity level. Bubble mode: attempted adds / unique workflow starts.")
        sts = _tv(r, "ScheduleToStartSeries") or []
        if sts:
            c4.metric("Sched→Start P50", f"{sorted(sts)[len(sts)//2]:.1f}ms",
                help="Median schedule-to-start latency: time from task creation to first poller pickup. Higher = matching backlog deeper.")
        c1, c2, c3, _ = st.columns(4)
        if sts:
            c1.metric("P90", f"{sorted(sts)[int(len(sts)*0.9)]:.1f}ms",
                help="90th percentile schedule-to-start latency.")
            c2.metric("P99", f"{sorted(sts)[int(len(sts)*0.99)]:.1f}ms",
                help="99th percentile schedule-to-start latency.")
            c3.metric("Max", f"{max(sts):.1f}ms",
                help="Maximum observed schedule-to-start latency during experiment.")

        # BubbleTime-only counters (no monitor/DES metrics exist in this mode).
        if _tv(r, "RunType") == "bubble":
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Workflow Fail", _d(_tv(r, "WorkflowFail"), 0),
                help="Workflows that failed to complete within the schedule-to-close window.")
            b2.metric("Attempted Adds", _d(_tv(r, "AttemptedAdds"), 0),
                help="AddActivityTask/AddWorkflowTask gRPC calls accepted by the server.")
            b3.metric("Rejected Adds", _d(_tv(r, "RejectedAdds"), 0),
                help="AddTask calls rejected by the server (persistence/matching backpressure).")
            b4.metric("Virtual Elapsed", f"{_d(_tv(r, 'VirtualElapsedMs'), 0)}ms",
                help="Wall-clock time the synctest bubble needed for the whole experiment (virtual).")
            b1, b2, b3, _ = st.columns(4)
            b1.metric("Attempts/Sec", _fmt(_tv(r, "AttemptsPerSec"), ".1f", "0"),
                help="Attempted adds per virtual second — the retry storm rate.")
            b2.metric("Attempts/Start", _fmt(_tv(r, "AttemptsPerStart"), ".2f", "0"),
                help="Attempted adds per unique workflow start — bubble-mode retry amplification.")
    elif is_head_to_head:
        cols[3].metric("Score", _fmt(r.get("Score"), ".2f"),
            help="Head-to-head comparison score.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Label", r.get("Label", "?"),
            help="Experiment label for head-to-head comparison.")
        c2.metric("Retries", r.get("Retries", "?"),
            help="Total retry events observed.")
        c3.metric("Completions", r.get("Completions", "?"),
            help="Total completion events observed.")
        c4.metric("Timeouts", r.get("Timeouts", "?"),
            help="Total timeout events observed.")
    elif "score" in r:
        # Tasqueue results — detect which keys are present
        cols[3].metric("Score", _fmt(r.get("score"), ".2f"),
            help="Tasqueue monitor score: weighted distance from baseline.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Retries", r.get("retries", "?"),
            help="Total retry events observed by Tasqueue monitor.")
        c2.metric("Completions", r.get("completes", "?"),
            help="Total completion events observed by Tasqueue monitor.")
        c3.metric("Retry Amplification", _fmt(r.get("amplification"), ".4f", "0"),
            help="Retry amplification ratio for Tasqueue: retries / completions.")
        # timeouts or drops may not exist in all scenarios
        c4.metric("Timeouts", r.get("timeouts", "—"),
            help="Total timeout events observed.")
        if r.get("drops") is not None:
            c4.metric("Drops", r.get("drops"),
                help="Total drop events observed (requests rejected by queue).")
        if r.get("timeout_rate") is not None:
            c4.metric("Timeout Rate", _fmt(r.get("timeout_rate"), ".2%"),
                help="Fraction of requests that timed out.")
    else:
        # Generic / sweep-shaped runs (e.g. pri_heap sweeps, recovery sweeps):
        # no score, no Label, no temporal counters — show scalar keys as-is.
        cols[3].metric("Type", r.get("run_type", "—"),
            help="Run type from results; generic sweep runs have no score shape.")
        scalars = [kv for kv in r.items() if isinstance(kv[1], (int, float, str, bool))]
        for i in range(0, len(scalars), 4):
            cs = st.columns(4)
            for c, (k, v) in zip(cs, scalars[i:i + 4]):
                c.metric(str(k), v)





# --- Navigation helpers ---

def _run_label(meta: dict, run: Path) -> str:
    """Short label: seed + r-index or repeat counter; else directory name."""
    seed = meta.get("seed")
    if seed is not None:
        m = re.search(r"-r(\d+)-", run.name)
        if m:
            return f"seed{seed}·r{m.group(1)}"
        m = re.search(r"-(\d+)$", run.name)
        if m and len(m.group(1)) < 15:  # 19-digit nano timestamps are not repeats
            return f"seed{seed}·{m.group(1)}"
    return run.name


@st.cache_data(show_spinner=False)
def _runs_table(exp: Path) -> pd.DataFrame:
    """Interest-sorted run index: metastable first, then monitor score desc."""
    rows = []
    for run in _experiment_runs(exp):
        meta = json.loads((run / "metadata.json").read_text()) if (run / "metadata.json").exists() else {}
        r = {}
        if (run / "results.json").exists():
            r = json.loads((run / "results.json").read_text())
        ms = _tv(r, "MonitorStatus") or {}
        metastable = bool(ms.get("Metastable")) if ms else None
        status = "Metastable" if metastable else ("Stable" if metastable is False else "—")
        score = ms.get("Score") if ms else (r.get("Score") if isinstance(r, dict) else None)
        rows.append({
            "Run": _run_label(meta, run),
            "Seed": meta.get("seed", "—"),
            "Sim (ms)": meta.get("sim_time_end_ms", "—"),
            "Status": status,
            "Score": score,
            "is_meta": metastable,
            "path": str(run),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["is_meta", "Score"], ascending=[False, False], na_position="last")
    return df


def _render_run(run: Path, label: str) -> None:
    """Full detail for one run: key metrics, temporal charts, pool, monitor, config."""
    # Load data — file I/O, cached, fast after first open
    results_file = run / "results.json"
    config_file = run / "config.json"
    metadata_file = run / "metadata.json"
    snaps_file = _pick(run / "scenario_snapshots.jsonl")
    metrics_file = _pick(run / "metrics.jsonl")
    meta = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
    cfg = json.loads(config_file.read_text()) if config_file.exists() else {}
    r = None
    if results_file.exists():
        r = load_json_head(results_file)
    sdf = _snaps_df(snaps_file) if snaps_file else None

    # Key results (fast — always show immediately)
    cols = st.columns(4)
    cols[0].metric("Seed", meta.get("seed", "?"),
        help="PRNG seed for deterministic reproducibility. Same seed + same config = identical run.")
    cols[1].metric("Sim Time", f"{meta.get('sim_time_end_ms', '?')}ms",
        help="Total simulated time in milliseconds. Not wall-clock — this is DES simulation time.")
    cols[2].metric("Experiment", meta.get("experiment_name", label),
        help="Experiment name from metadata. Matches the output directory name.")
    if isinstance(r, dict):
        _show_results(r, cols, meta)

    # --- Temporal-level metrics (scenario_snapshots + PoolSeries + ScheduleToStart) ---
    if sdf is not None:
        st.subheader("Temporal Metrics (per-poll snapshots)")
        rate_cols = [c for c in ["retry_amp", "window_retry_amp",
            "timeout_rate", "drop_rate", "task_rate"] if c in sdf.columns]
        count_cols = [c for c in ["queue_mean", "sched_to_start",
            "tasks", "attempts", "resched_depth"] if c in sdf.columns]
        l, r = st.columns(2)
        with l:
            sel_rate = st.multiselect("Rates/proportions", rate_cols,
                default=[c for c in ["retry_amp", "timeout_rate"] if c in rate_cols],
                key=f"rate_{run.name}")
            if sel_rate:
                st.line_chart(sdf[sel_rate])
        with r:
            sel_count = st.multiselect("Counts/latency", count_cols,
                default=[c for c in ["queue_mean", "sched_to_start"] if c in count_cols],
                key=f"count_{run.name}")
            if sel_count:
                st.line_chart(sdf[sel_count])

        # --- Pool utilization (results PoolSeries, else snapshot pool_stats) ---
        if isinstance(r, dict) and _tv(r, "PoolSeries"):
            pool = _tv(r, "PoolSeries")
            pool_step = max(1, len(pool) // 500)
            pdf = pd.DataFrame(pool[::pool_step])
            st.subheader("Connection Pool")
            pool_cols = [c for c in ["Busy", "Waiters", "PeakBusy"] if c in pdf.columns]
            if pool_cols:
                st.line_chart(pdf[pool_cols])
        elif any(c in sdf.columns for c in ("pool_busy", "pool_waiters", "pool_peak")):
            pool_cols = [c for c in ["pool_busy", "pool_waiters", "pool_peak"] if c in sdf.columns]
            st.subheader("Connection Pool")
            st.line_chart(sdf[pool_cols])

        # --- Schedule-to-Start latency ---
        if isinstance(r, dict) and _tv(r, "ScheduleToStartSeries"):
            sts_series = _tv(r, "ScheduleToStartSeries")
            sts_step = max(1, len(sts_series) // 500)
            sts_df = pd.DataFrame({"sched_to_start": sts_series[::sts_step]})
            st.subheader("Schedule-to-Start Latency")
            st.line_chart(sts_df)

    # --- GoDES Monitor metrics (metrics.parquet or metrics.jsonl) ---
    if metrics_file is not None:
        if metrics_file.suffix == ".parquet":
            mdf = pd.read_parquet(metrics_file)
        else:
            mlines = load_jsonl(metrics_file)
            mdf = pd.DataFrame(mlines) if mlines else pd.DataFrame()
        if not mdf.empty:
            step = max(1, len(mdf) // 500)
            mdf = mdf.iloc[::step]
            st.subheader("GoDES Monitor (window summaries)")
            if "StartMs" in mdf.columns:
                mdf = mdf.set_index("StartMs")
            cols = [c for c in ["QueueMean", "Retries", "CompletedIn", "Timeouts", "Dropped"] if c in mdf.columns]
            cols = [c for c in cols if mdf[c].nunique() > 1]
            if cols:
                st.line_chart(mdf[cols])

    # --- Metric reference ---
    with st.expander("ℹ️ Metric Descriptions", key=f"help_{run.name}"):
        st.markdown("""
| Chart Field | Source | Description |
|---|---|---|
| `queue_mean` | Snapshot.QueueMean | Time-weighted avg matching/persistence queue depth. Primary load signal. |
| `retry_amp` | Snapshot.RetryAmplification | Per-window delta task_attempt/task_count. >1 = retry amp in that window. |
| `window_retry_amp` | Snapshot.WindowRetryAmp | Same as retry_amp — per-window attempt/task ratio. |
| `timeout_rate` | Snapshot.TimeoutRate | Per-window timeout fraction of tasks (service_errors / task_count). |
| `drop_rate` | Snapshot.DropRate | Per-window drop fraction (persistence_error_with_type / task_requests). |
| `task_rate` | Snapshot.TaskRate | Per-window new task arrivals (delta of task_requests metric). Burst spike signal. |
| `sched_to_start` | Snapshot.ScheduleToStartLatency | Running avg schedule-to-start latency (cumulative ns/cumulative tasks → ms). |
| `tasks` | Snapshot.Tasks | Per-window completed task count (delta of cumulative task_count). |
| `attempts` | Snapshot.Attempts | Per-window attempt count (delta of task_attempt + workflow_task_attempt). |
| `resched_depth` | Snapshot.ReschedulerDepth | Current matching task-rescheduler pending queue depth. Backlog signal. |
""")
        st.caption("All values are per-100ms-poll-window unless labeled 'running avg'. Hover chart legend for series names.")

    # --- Config + metadata ---
    with st.expander("Config & Metadata", key=f"cfg_{run.name}"):
        c1, c2 = st.columns(2)
        with c1:
            if cfg:
                st.json(cfg)
        with c2:
            if meta:
                st.json(meta)

    # --- Full results (collapsed by default) ---
    if results_file.exists():
        with st.expander("Results (raw)", key=f"raw_{run.name}"):
            r = load_json_head(results_file)
            if isinstance(r, dict):
                # Don't show SnapshotSeries in raw view (it's huge)
                r_compact = {k: v for k, v in r.items() if k != "SnapshotSeries"}
                st.json(r_compact)
            else:
                st.text(r)


# --- Sidebar drill-down navigation ---
_ORDER = {"retry_amp": 0, "temporal": 0, "tasqueue": 1}
projects = sorted((p for p in BASE.iterdir() if p.is_dir()), key=lambda p: (_ORDER.get(p.name, 99), p.name))


def _persist_nav():
    """Write current nav selections to URL params (survive reloads, shareable).
    Runs as widget callback → before widget instantiation → legal writes."""
    p = st.session_state.get("nav_proj")
    e = st.session_state.get("nav_exp")
    q = {}
    if p is not None:
        q["project"] = Path(p).name
    if e is not None:
        q["exp"] = Path(e).name
    runs = st.session_state.get(f"sel_{Path(p).name}_{Path(e).name}") if p is not None and e is not None else None
    if runs:
        q["run"] = ",".join(quote(r) for r in runs)
    st.query_params.update(q)


def _on_project_change():
    """Project switch: exp/run params of the old project are invalid."""
    st.session_state.pop("nav_exp", None)
    st.query_params.pop("exp", None)
    st.query_params.pop("run", None)
    _persist_nav()


def _on_exp_change():
    """Experiment switch: run labels are not unique across experiments."""
    st.query_params.pop("run", None)
    _persist_nav()


with st.sidebar:
    st.header("Navigation")
    qp = st.query_params
    proj_names = [p.name for p in projects]
    proj_name = qp.get("project")
    project = st.selectbox("Project", projects, format_func=lambda p: p.name,
        index=proj_names.index(proj_name) if proj_name in proj_names else 0,
        key="nav_proj", on_change=_on_project_change)
    exps = sorted(e for e in project.iterdir() if e.is_dir())
    exp_names = [e.name for e in exps]
    exp_name = qp.get("exp")
    exp = st.selectbox("Experiment", exps, format_func=lambda e: e.name,
        index=exp_names.index(exp_name) if exp_name in exp_names else 0,
        key="nav_exp", on_change=_on_exp_change)
    runs_df = _runs_table(exp)
    if runs_df.empty:
        st.caption("No runs found.")
        sel = []
    else:
        opts = runs_df["Run"].tolist()
        ms_key = f"sel_{project.name}_{exp.name}"
        rq = qp.get("run")
        if rq:
            saved = [unquote(x) for x in rq.split(",") if unquote(x) in opts]
            if saved:
                st.session_state[ms_key] = saved
        # No default once widget state exists: default + session-state value
        # together trigger a Streamlit policy warning.
        default = None if ms_key in st.session_state else opts[:1]
        sel = st.multiselect("Runs (pick 2+ to compare)", opts, default=default,
            key=ms_key, on_change=_persist_nav)
        st.caption(f"{len(opts)} runs — table sorts worst first. Click a run to focus it.")

        # --- Aggregate metrics across all runs (below the run count) ---
        score = runs_df["Score"].dropna()
        sim = pd.to_numeric(runs_df["Sim (ms)"], errors="coerce").dropna()
        meta_n = int(runs_df["is_meta"].sum())
        agg = st.columns(3)
        agg[0].metric("Total runs", len(opts))
        agg[1].metric("Metastable", f"{meta_n} ({meta_n / len(opts):.0%})",
            help="Fraction of runs where the monitor declared metastability (weighted multi-dim score > epsilon for N consecutive windows).")
        agg[2].metric("Median score", f"{score.median():.3f}" if not score.empty else "—",
            help="Median monitor score across all runs. Higher = further from baseline.")
        agg = st.columns(3)
        agg[0].metric("Max score", f"{score.max():.3f}" if not score.empty else "—",
            help="Worst (highest) monitor score across all runs.")
        agg[1].metric("Median sim", f"{sim.median():.0f} ms" if not sim.empty else "—",
            help="Median simulated duration across all runs (DES time, not wall-clock).")
        agg[2].metric("Stable", len(opts) - meta_n,
            help="Runs with no declared metastability.")

# --- localStorage resume bridge: copy URL params to localStorage on unload;
# restore them into the URL on next load so the nav selection survives
# browser/tab restarts, not just reloads. ---
st.iframe("""
<script>
try {
  var K = "godes_dash_nav_v1";
  window.addEventListener("beforeunload", function () {
    localStorage.setItem(K, window.parent.location.search);
  });
  var q = new URLSearchParams(window.parent.location.search);
  if (!q.has("project")) {
    var s = localStorage.getItem(K);
    if (s && s.indexOf("project=") !== -1) {
      window.parent.location.search = s;
    }
  }
} catch (e) {}
</script>
""", height=1)

st.header(f"{project.name} / {exp.name}")
if runs_df.empty:
    st.info("No runs with results.json under this experiment.")
    st.stop()

# --- Run index table (click row → focus in sidebar, no reload) ---
st.markdown("""
<style>
[data-testid="stDataFrame"] .glideDataEditor { cursor: pointer; }
</style>
""", unsafe_allow_html=True)


def _focus_from_table():
    """Row-click callback: runs before widgets instantiate, so writing the
    sidebar multiselect key here is legal (post-instantiation writes crash)."""
    state = st.session_state.get(f"tbl_{project.name}_{exp.name}") or {}
    rows = (state.get("selection") or {}).get("rows") or []
    if rows:
        st.session_state[f"sel_{project.name}_{exp.name}"] = [runs_df.iloc[rows[0]]["Run"]]
        _persist_nav()


ev = st.dataframe(runs_df.drop(columns=["path", "is_meta"]), width="stretch",
    hide_index=True, on_select=_focus_from_table, selection_mode="single-row",
    key=f"tbl_{project.name}_{exp.name}")

sel_runs = []
for lb in sel:
    row = runs_df[runs_df["Run"] == lb]
    if not row.empty:
        sel_runs.append((Path(row.iloc[0]["path"]), lb))

if not sel_runs:
    st.info("Select at least one run in the sidebar.")
else:
    # --- Cross-run comparison (2+ runs) ---
    if len(sel_runs) >= 2:
        sdfs = {}
        for run, lb in sel_runs:
            snaps = _pick(run / "scenario_snapshots.jsonl")
            sdf = _snaps_df(snaps) if snaps else None
            if sdf is not None:
                sdfs[lb] = sdf
        if len(sdfs) >= 2:
            st.subheader("Cross-run comparison")
            metrics = ["retry_amp", "timeout_rate", "drop_rate", "task_rate",
                "window_retry_amp", "queue_mean", "sched_to_start"]
            avail = [m for m in metrics if sum(1 for d in sdfs.values() if m in d.columns) >= 2]
            if avail:
                tabs = st.tabs([m.replace("_", " ") for m in avail])
                for tab, m in zip(tabs, avail):
                    with tab:
                        merged = pd.DataFrame({lb: d[m] for lb, d in sdfs.items() if m in d.columns})
                        st.line_chart(merged.dropna(how="all").ffill())
            else:
                st.info("Selected runs share no comparable snapshot metrics.")
        else:
            st.info("Selected runs have no scenario snapshots to compare.")
        st.divider()

    # --- Per-run detail ---
    for run, lb in sel_runs:
        with st.expander(f"Run {lb}", expanded=len(sel_runs) == 1,
                key=f"run_{project.name}_{exp.name}_{run.name}"):
            _render_run(run, lb)
