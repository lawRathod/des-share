"""GoDES experiment dashboard — drop-in viewer for out/ directory.

Usage:
    pip install streamlit pandas
    streamlit run dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")
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
    sampled = raw.iloc[::step]
    snap_df = pd.json_normalize(sampled["snapshot"].apply(_parse_snap)) if "snapshot" in sampled else pd.DataFrame()
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
    })
    if not result.empty:
        result = result.set_index("time_ms")
    return result


def _tv(r: dict, *keys: str):
    """Temporal value: search top-level keys, then Dashboard.*, then known aliases."""
    aliases = {"RetryAmplification": ["Ratio"]}
    for k in keys:
        v = r.get(k)
        if v is not None:
            return v
        v = r.get("Dashboard", {}).get(k)
        if v is not None:
            return v
        for a in aliases.get(k, []):
            v = r.get(a)
            if v is not None:
                return v
            v = r.get("Dashboard", {}).get(a)
            if v is not None:
                return v
    return None


def _show_results(r: dict, cols: list, meta: dict) -> None:
    """Display results dict in shape-aware metric columns.
    Supports temporal, tasqueue, and head_to_head result shapes."""
    # st is in scope from module-level import

    is_temporal = "TotalRPCs" in r
    is_head_to_head = "Label" in r

    if is_temporal:
        ms = _tv(r, "MonitorStatus") or {}
        metastable = ms.get("Metastable", False)
        status_icon = "✅" if metastable else "🟢"
        status_label = "Metastable" if metastable else "Stable"
        cols[3].metric(f"{status_icon} Status", status_label)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Workflow Success", r.get("WorkflowSuccess", "?"))
        c2.metric("Activity Success", r.get("ActivitySuccess", "?"))
        c3.metric("Retry Amplification", f"{_tv(r, 'RetryAmplification') or 0:.4f}")
        c4.metric("Arrivals", r.get("ArrivalsProcessed", "?"))

        c1, c2, c3, c4 = st.columns(4)
        score = ms.get("Score")
        c1.metric("Score", f"{score:.2f}" if score is not None else "?")
        c2.metric("Windows", ms.get("WindowsSeen", "?"))
        attempts = r.get("TaskAttempt", 0)
        count = r.get("TaskCount", 0)
        c3.metric("Attempts/Tasks", f"{attempts}/{count}" if (attempts or count) else "?")
        sts = _tv(r, "ScheduleToStartSeries") or []
        if sts:
            c4.metric("Sched→Start P50", f"{sorted(sts)[len(sts)//2]:.1f}ms")
        c1, c2, c3, _ = st.columns(4)
        if sts:
            c1.metric("P90", f"{sorted(sts)[int(len(sts)*0.9)]:.1f}ms")
            c2.metric("P99", f"{sorted(sts)[int(len(sts)*0.99)]:.1f}ms")
            c3.metric("Max", f"{max(sts):.1f}ms")
    elif is_head_to_head:
        cols[3].metric("Score", f"{r.get('Score', '?'):.2f}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Label", r.get("Label", "?"))
        c2.metric("Retries", r.get("Retries", "?"))
        c3.metric("Completions", r.get("Completions", "?"))
        c4.metric("Timeouts", r.get("Timeouts", "?"))
    else:
        # Tasqueue results — detect which keys are present
        cols[3].metric("Score", f"{r.get('score', '?'):.2f}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Retries", r.get("retries", "?"))
        c2.metric("Completions", r.get("completes", "?"))
        c3.metric("Retry Amplification", f"{r.get('amplification', 0):.4f}")
        # timeouts or drops may not exist in all scenarios
        c4.metric("Timeouts", r.get("timeouts", "—"))
        if r.get("drops") is not None:
            c4.metric("Drops", r.get("drops"))
        if r.get("timeout_rate") is not None:
            c4.metric("Timeout Rate", f"{r.get('timeout_rate', 0):.2%}")





# --- Render each experiment ---
_ORDER = {"temporal": 0, "tasqueue": 1}
for project in sorted(BASE.iterdir(), key=lambda p: (_ORDER.get(p.name, 99), p.name)):
    if not project.is_dir():
        continue
    st.header(project.name)

    for exp in sorted(project.iterdir()):
        if not exp.is_dir():
            continue
        for run in sorted(exp.iterdir()):
            if not run.is_dir():
                continue

            ex = st.expander(f"{exp.name} / {run.name}", expanded=False, on_change="rerun")
            if ex.open:
                with ex:
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
                    cols[0].metric("Seed", meta.get("seed", "?"))
                    cols[1].metric("Sim Time", f"{meta.get('sim_time_end_ms', '?')}ms")
                    cols[2].metric("Experiment", meta.get("experiment_name", exp.name))
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
                                key=f"rate_{exp.name}_{run.name}")
                            if sel_rate:
                                st.line_chart(sdf[sel_rate])
                        with r:
                            sel_count = st.multiselect("Counts/latency", count_cols,
                                default=[c for c in ["queue_mean", "sched_to_start"] if c in count_cols],
                                key=f"count_{exp.name}_{run.name}")
                            if sel_count:
                                st.line_chart(sdf[sel_count])

                        # --- Pool utilization ---
                        if isinstance(r, dict) and _tv(r, "PoolSeries"):
                            pool = _tv(r, "PoolSeries")
                            pool_step = max(1, len(pool) // 500)
                            pdf = pd.DataFrame(pool[::pool_step])
                            st.subheader("Connection Pool")
                            pool_cols = [c for c in ["Busy", "Waiters", "PeakBusy"] if c in pdf.columns]
                            if pool_cols:
                                st.line_chart(pdf[pool_cols])

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

                    # --- Config + metadata ---
                    with st.expander("Config & Metadata", key=f"cfg_{project.name}_{exp.name}_{run.name}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            if cfg:
                                st.json(cfg)
                        with c2:
                            if meta:
                                st.json(meta)

                    # --- Full results (collapsed by default) ---
                    if results_file.exists():
                        with st.expander("Results (raw)", key=f"raw_{project.name}_{exp.name}_{run.name}"):
                            r = load_json_head(results_file)
                            if isinstance(r, dict):
                                # Don't show SnapshotSeries in raw view (it's huge)
                                r_compact = {k: v for k, v in r.items() if k != "SnapshotSeries"}
                                st.json(r_compact)
                            else:
                                st.text(r)
