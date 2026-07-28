"""GoDES experiment dashboard — drop-in viewer for out/ directory.

Usage:
    pip install streamlit pandas
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")
st.title("GoDES Experiments")

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

            with st.expander(f"{exp.name} / {run.name}", expanded=project.name != "tasqueue"):
                # --- Key results at top ---
                results_file = run / "results.json"
                config_file = run / "config.json"
                metadata_file = run / "metadata.json"
                snaps_file = run / "scenario_snapshots.jsonl"
                metrics_file = run / "metrics.jsonl"

                # Show key metrics from metadata + config
                meta = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
                cfg = json.loads(config_file.read_text()) if config_file.exists() else {}

                cols = st.columns(4)
                cols[0].metric("Seed", meta.get("seed", "?"))
                cols[1].metric("Sim Time", f"{meta.get('sim_time_end_ms', '?')}ms")
                cols[2].metric("Experiment", meta.get("experiment_name", exp.name))

                # Shape-aware results display
                r = None
                if results_file.exists():
                    r = load_json_head(results_file)
                    if isinstance(r, dict):
                        _show_results(r, cols, meta)

                # --- Temporal-level metrics (scenario_snapshots.jsonl + PoolSeries + ScheduleToStart) ---
                if snaps_file.exists():
                    snaps = load_jsonl(snaps_file)
                    if snaps:
                        st.subheader("Temporal Metrics (per-poll snapshots)")
                        step = max(1, len(snaps) // 500)
                        sampled = snaps[::step]
                        sdf = pd.DataFrame([
                            {
                                "time_ms": s["sim_now_ms"],
                                "queue_mean": s["snapshot"].get("QueueMean", 0),
                                "retry_amp": s["snapshot"].get("RetryAmplification", 0),
                                "window_retry_amp": s["snapshot"].get("WindowRetryAmp", 0),
                                "timeout_rate": s["snapshot"].get("TimeoutRate", 0),
                                "drop_rate": s["snapshot"].get("DropRate", 0),
                                "sched_to_start": s["snapshot"].get("ScheduleToStartLatency", 0),
                                "tasks": s["snapshot"].get("Tasks", 0),
                                "attempts": s["snapshot"].get("Attempts", 0),
                                "task_rate": s["snapshot"].get("TaskRate", 0),
                                "resched_depth": s["snapshot"].get("ReschedulerDepth", 0),
                            }
                            for s in sampled
                        ])
                        sdf = sdf.set_index("time_ms")
                        # Split into two scale groups so large values don't squash small ones
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

                    # --- Pool utilization (from results.json PoolSeries) ---
                    if isinstance(r, dict) and _tv(r, "PoolSeries"):
                        pool = _tv(r, "PoolSeries")
                        pool_step = max(1, len(pool) // 500)
                        pdf = pd.DataFrame(pool[::pool_step])
                        st.subheader("Connection Pool")
                        pool_cols = [c for c in ["Busy", "Waiters", "PeakBusy"] if c in pdf.columns]
                        if pool_cols:
                            st.line_chart(pdf[pool_cols])

                    # --- Schedule-to-Start latency (from results.json ScheduleToStartSeries) ---
                    if isinstance(r, dict) and _tv(r, "ScheduleToStartSeries"):
                        sts_series = _tv(r, "ScheduleToStartSeries")
                        sts_step = max(1, len(sts_series) // 500)
                        sts_df = pd.DataFrame({"sched_to_start": sts_series[::sts_step]})
                        st.subheader("Schedule-to-Start Latency")
                        st.line_chart(sts_df)

                # --- GoDES Monitor metrics (metrics.jsonl) ---
                if metrics_file.exists():
                    mlines = load_jsonl(metrics_file)
                    if mlines:
                        st.subheader("GoDES Monitor (window summaries)")
                        step = max(1, len(mlines) // 500)
                        df = pd.DataFrame(mlines[::step])
                        if "StartMs" in df.columns:
                            df = df.set_index("StartMs")
                        cols = [c for c in ["QueueMean", "Retries", "CompletedIn", "Timeouts", "Dropped"] if c in df.columns]
                        # Drop columns with zero variance (e.g. all-zero Timeouts for temporal)
                        cols = [c for c in cols if df[c].nunique() > 1]
                        if cols:
                            st.line_chart(df[cols])

                # --- Config + metadata ---
                with st.expander("Config & Metadata"):
                    c1, c2 = st.columns(2)
                    with c1:
                        if cfg:
                            st.json(cfg)
                    with c2:
                        if meta:
                            st.json(meta)

                # --- Full results (collapsed by default) ---
                if results_file.exists():
                    with st.expander("Results (raw)"):
                        r = load_json_head(results_file)
                        if isinstance(r, dict):
                            # Don't show SnapshotSeries in raw view (it's huge)
                            r_compact = {k: v for k, v in r.items() if k != "SnapshotSeries"}
                            st.json(r_compact)
                        else:
                            st.text(r)
