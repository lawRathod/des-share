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


def _experiment_runs(exp: Path, max_depth: int = 2) -> list[Path]:
    """Find run directories in flat, seed-partitioned, and scenario layouts.

    Older exporters wrote ``experiment/<run>/``; newer entrypoints write
    ``experiment/<seed>/<run>/``; scenario groups write
    ``experiment/<scenario>/<seed>/<run>/``. A run is identified by its
    results.json file rather than by directory depth, so all layouts stay
    readable. max_depth bounds how many levels below exp we descend.
    """
    runs: list[Path] = []

    def _walk(d: Path, depth: int):
        if depth > max_depth:
            return
        for child in sorted(d.iterdir()):
            if not child.is_dir():
                continue
            if (child / "results.json").exists():
                runs.append(child)
                continue
            _walk(child, depth + 1)

    _walk(exp, 1)
    return runs


def _experiments(project: Path) -> list[Path]:
    """Navigable experiments under a project.

    Top-level dirs (retry_amp, s2s_dose, ...) plus their run-bearing or
    Summary-bearing subdirectories (e.g. retry_amp/af, retry_amp/transfer_delay_af)
    so scenario results and composed-confirm tables are reachable. The display
    name is the leaf dir name. Pure numeric seed dirs (42/) are skipped — they
    only partition runs under a real scenario."""
    exps = [p for p in sorted(project.iterdir()) if p.is_dir()]
    nested = []
    for e in exps:
        for child in sorted(e.iterdir()):
            if not child.is_dir() or child.name.isdigit():
                continue
            if (child / "Summary.json").exists() or _experiment_runs(child):
                nested.append(child)
    return exps + nested


def _is_scenario_group(exp: Path) -> bool:
    """True for a top-level dir whose runs live under scenario subdirs
    (retry_amp → af, calm, ...), i.e. it has no own results.json but its
    children do. Such an experiment is an aggregate of its scenarios."""
    if (exp / "results.json").exists():
        return False
    return any(_experiment_runs(child) for child in exp.iterdir() if child.is_dir())


def _scenario_group_children(exp: Path) -> list[Path]:
    """Run-bearing scenario subdirs of a scenario-group experiment."""
    return sorted(
        child for child in exp.iterdir()
        if child.is_dir() and _experiment_runs(child)
    )


def _parse_snap(s):
    """Parse snapshot column: bytes, str, or dict → dict."""
    if isinstance(s, (bytes, str)):
        return json.loads(s.decode() if isinstance(s, bytes) else s)
    return s if isinstance(s, dict) else {}


# --- Summary/data-file renderers -----------------------------------------
# The out/ tree mixes two shapes:
#   * run-directory experiments (retry_amp, s2s_dose, queue_envelope, ...) —
#     found by _experiment_runs();
#   * Summary/vectors files (model/*, transfer_delay_af/Summary.json,
#     s2s_dose/Summary.json, queue_envelope/Summary.json) — the model leg and
#     the composed/aggregate results the report's tables are built from.
# These renderers make the second shape visible so readers can verify the
# report's numbers directly.

_VECTOR_COLS = ["name", "kind", "aps", "fail", "score", "candidate"]


def _flatten_vector(v: dict) -> dict:
    """Flatten a model vector entry into a display row."""
    return {
        "name": v.get("name", "—"),
        "kind": v.get("kind", ""),
        "aps": v.get("bestAttemptsPerStart", v.get("meanAttemptsPerStart")),
        "fail": v.get("meanFail"),
        "score": v.get("meanScore"),
        "candidate": v.get("candidate"),
        "started": v.get("started"),
        "failPerStart": v.get("failPerStart"),
        "maxQueue": v.get("maxQueue"),
        "drainMs": v.get("drainMs"),
    }


def _render_model_vectors(exp: Path) -> bool:
    """Render a model/* experiment from vectors.json + candidates.json."""
    vf = exp / "vectors.json"
    cf = exp / "candidates.json"
    if not vf.exists():
        return False
    rows = [_flatten_vector(v) for v in json.loads(vf.read_text())]
    df = pd.DataFrame(rows)
    if df.empty:
        st.caption("vectors.json is empty.")
        return True
    st.subheader("Model search leg (vectors.json)")
    st.dataframe(df[_VECTOR_COLS].rename(columns={
        "name": "Vector", "kind": "Kind", "aps": "APS",
        "fail": "Fail", "score": "Score", "candidate": "Candidate"}),
        hide_index=True, width="stretch")
    st.caption("APS = best attempts/start across seeds; Fail = mean workflow failures; "
        "Candidate = model declared this vector worth bubble-confirming (A5 gate, ADR-071).")
    if cf.exists():
        cand = json.loads(cf.read_text())
        if cand:
            st.subheader("Candidates (bubble-confirm shortlist)")
            st.json(cand if len(json.dumps(cand)) < 4000 else cand[:10])
    return True


def _render_confirm_summary(exp: Path) -> bool:
    """Render a composed-confirm Summary.json (e.g. transfer_delay_af)."""
    sf = exp / "Summary.json"
    if not sf.exists():
        return False
    data = json.loads(sf.read_text())
    if not isinstance(data, list):
        return False
    for entry in data:
        vec = entry.get("vector") or {}
        st.subheader(f"Composed confirm: {vec.get('name', exp.name)}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Model APS", _fmt(entry.get("modelAps"), ".2f", "—"),
            help="Model attempts/start for the composed vector.")
        c2.metric("Model Fail", _d(entry.get("modelFail"), "—"),
            help="Model workflow failures (of started).")
        c3.metric("Model Score", _fmt(entry.get("modelScore"), ".2f", "—"),
            help="Model monitor score.")
        c4.metric("Bubble runs", _d(entry.get("bubbleRuns") and len(entry["bubbleRuns"]), "—"),
            help="Number of bubble confirm runs (N).")
        br = entry.get("bubbleRuns") or []
        if br:
            rows = []
            for i, b in enumerate(br):
                ms = b.get("monitorStatus") or {}
                rows.append({
                    "run": i,
                    "aps": b.get("attemptsPerStart"),
                    "score": ms.get("Score"),
                    "wfOK": b.get("workflowSuccess"),
                    "wfFail": b.get("workflowFail"),
                    "rejected": b.get("rejectedAdds"),
                })
            bdf = pd.DataFrame(rows)
            st.dataframe(bdf.rename(columns={
                "run": "Run", "aps": "APS", "score": "Score",
                "wfOK": "WF OK", "wfFail": "WF Fail", "rejected": "Rejected"}),
                hide_index=True, width="stretch")
            model_aps = entry.get("modelAps")
            if model_aps is not None:
                b_aps = [b.get("attemptsPerStart") for b in br if b.get("attemptsPerStart") is not None]
                if b_aps:
                    mean = sum(b_aps) / len(b_aps)
                    st.caption(f"Model/real ratio: {model_aps:.2f} / {mean:.2f} = "
                        f"{model_aps / mean:.2f}× (report §2 gap table).")
    return True


def _render_dose_summary(exp: Path) -> bool:
    """Render the S2S dose-response Summary.json (knee [700,1000] ms)."""
    sf = exp / "Summary.json"
    if not sf.exists():
        return False
    data = json.loads(sf.read_text())
    doses = data.get("doses")
    if not isinstance(doses, list):
        return False
    df = pd.DataFrame([{
        "doseMs": d.get("doseMs"),
        "medianFail": d.get("medianFail"),
        "minFail": d.get("minFail"),
        "maxFail": d.get("maxFail"),
        "medianAps": d.get("medianAps"),
        "pollRate": d.get("pollRatePerSec"),
        "addRate": d.get("addRatePerSec"),
    } for d in doses])
    st.subheader("S2S dose-response (Summary.json)")
    st.dataframe(df.rename(columns={
        "doseMs": "S2S deadline (ms)", "medianFail": "Median fail",
        "minFail": "Min fail", "maxFail": "Max fail",
        "medianAps": "Median APS", "pollRate": "Poll/s", "addRate": "Add/s"}),
        hide_index=True, width="stretch")
    st.caption("Report §4: bubble knee at [700, 1000]ms — fail jumps 1.0 → 0.54 → 0.0.")
    st.line_chart(df.set_index("doseMs")[["medianFail"]])
    return True


def _render_envelope_summary(exp: Path) -> bool:
    """Render the queue_envelope Summary.json (8 cells × N=3)."""
    sf = exp / "Summary.json"
    if not sf.exists():
        return False
    data = json.loads(sf.read_text())
    cells = data.get("cells")
    if not isinstance(cells, list):
        return False
    rows = []
    for c in cells:
        dep = c.get("depth") or {}
        lat = c.get("latency") or {}
        rows.append({
            "name": c.get("name"),
            "workload": c.get("workload"),
            "pollers": c.get("pollers"),
            "readPart": c.get("readPartitions"),
            "writePart": c.get("writePartitions"),
            "failFrac": c.get("failFraction"),
            "aps": c.get("attemptsPerStart"),
            "maxBacklog": dep.get("maxMatchingBacklogMedian"),
            "finalDepth": dep.get("finalDepthMedian"),
            "latP50": lat.get("p50Ms"),
            "latP99": lat.get("p99Ms"),
        })
    df = pd.DataFrame(rows)
    st.subheader("Queue envelope (Summary.json)")
    st.dataframe(df.rename(columns={
        "name": "Cell", "workload": "Workload", "pollers": "Pollers",
        "readPart": "Read parts", "writePart": "Write parts",
        "failFrac": "Fail frac", "aps": "APS",
        "maxBacklog": "Max backlog", "finalDepth": "Final depth",
        "latP50": "S2S p50 (ms)", "latP99": "S2S p99 (ms)"}),
        hide_index=True, width="stretch")
    return True


def _render_summary_file(exp: Path) -> bool:
    """Dispatch experiment-level Summary/vectors renderers; False if none apply."""
    sf = exp / "Summary.json"
    if sf.exists():
        data = json.loads(sf.read_text())
        if isinstance(data, dict):
            if _render_dose_summary(exp):
                return True
            if _render_envelope_summary(exp):
                return True
        elif isinstance(data, list) and _render_confirm_summary(exp):
            return True
    if _render_model_vectors(exp):
        return True
    return False


def _s2s_pct_from_buckets(row: pd.Series, p: float) -> float:
    """Per-window S2S percentile from the 32-bucket log-scale histogram
    (ADR-076 semantics: bucket i covers [2^(i-1), 2^i) ms, lower-bound
    reporting, rank = round(p/100 * count), empty → 0). Mirrors Go's
    S2SHistogram.PercentileMs exactly, so dashboard numbers match Go exports."""
    total = 0
    vals = []
    for i in range(32):
        v = row.get(f"S2SHistogram.{i}", 0)
        if v is None or pd.isna(v):
            v = 0
        v = int(v)
        vals.append(v)
        total += v
    if total == 0:
        return 0.0
    rank = max(1, round(p / 100.0 * total))
    cum = 0
    for i, v in enumerate(vals):
        cum += v
        if cum >= rank:
            return float(0 if i == 0 else 2 ** (i - 1))
    return float(2 ** 31)


def _s2s_percentile_cols(snap_df: pd.DataFrame) -> pd.DataFrame:
    """Derive per-window s2s_p50/s2s_p90/s2s_p99 columns from the histogram
    bucket array when present (runs exported after ADR-076). Empty DataFrame
    for older runs without the histogram."""
    if "S2SHistogram.0" not in snap_df.columns:
        return pd.DataFrame()
    return pd.DataFrame({
        "s2s_p50": snap_df.apply(lambda r: _s2s_pct_from_buckets(r, 50), axis=1),
        "s2s_p90": snap_df.apply(lambda r: _s2s_pct_from_buckets(r, 90), axis=1),
        "s2s_p99": snap_df.apply(lambda r: _s2s_pct_from_buckets(r, 99), axis=1),
    })


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
        "matching_backlog": snap_df.get("MatchingBacklogCount", 0),
        "physical_backlog": snap_df.get("PhysicalMatchingBacklogCount", 0),
        "history_pending": snap_df.get("HistoryPendingTasks", 0),
        "hist_resched_depth": snap_df.get("HistoryReschedulerDepth", 0),
    })
    if not result.empty:
        result = result.set_index("time_ms")
        s2s = _s2s_percentile_cols(snap_df)
        if not s2s.empty:
            result = result.join(s2s.reset_index(drop=True))
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


def _pct(sorted_vals: list, p: float) -> float:
    """p-th percentile (0-100) of an ascending list; None when empty.

    Uses nearest-rank so p99 never indexes past the end (the previous
    int(len*p) slicing raised IndexError on small series)."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = min(n - 1, int(round(p / 100.0 * (n - 1))))
    return sorted_vals[idx]


def _show_results(r: dict, cols: list, meta: dict) -> None:
    """Display results dict in shape-aware metric columns.
    Supports temporal, tasqueue, and head_to_head result shapes."""
    # st is in scope from module-level import

    is_temporal = _tv(r, "TotalRPCs", "WorkflowSuccess", "AttemptedAdds") is not None
    is_head_to_head = "Label" in r
    is_real_amp = "retryAmp" in r
    run_type = _tv(r, "RunType") or "des"

    if is_real_amp:
        # Real-server leg (real_amp): results.json is {name, run_type: "real",
        # workflowSuccess, workflowFail, retryAmp: {attempts, unique}, ...}.
        cols[3].metric("Mode", _d(run_type),
            help="Real-server run outside the synctest bubble — wall-clock, no virtual clock.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Workflow Success", _d(r.get("workflowSuccess")),
            help="Workflows that completed successfully.")
        c2.metric("Workflow Fail", _d(r.get("workflowFail"), 0),
            help="Workflows that failed.")
        ra = r.get("retryAmp") or {}
        c3.metric("Attempted Adds", _d(ra.get("attempts")),
            help="Total AddActivityTask/AddWorkflowTask attempts observed by the real server.")
        u = ra.get("unique")
        a = ra.get("attempts")
        if a is not None and u:
            c4.metric("Attempts/Start", f"{a / u:.2f}",
                help="Attempted adds per unique workflow start — the real-server retry amplification (report §7: mean 9.70).")
        else:
            c4.metric("Unique Starts", _d(u),
                help="Unique workflow starts.")
        st.caption("Real-server leg — this is the anchor the simulation is compared against "
            "(report §7: real mean 9.70 vs sim 9.58).")

    elif is_temporal:
        ms = _tv(r, "MonitorStatus") or {}
        if run_type == "bubble" and ms:
            metastable = ms.get("Metastable", False)
            status_icon = "🔴" if metastable else "🟢"
            status_label = "Storm" if metastable else "Stable"
            cols[3].metric(f"{status_icon} Status", status_label,
                help="Bubble monitor: 'Storm' when the weighted multi-dim score exceeds epsilon for N consecutive windows (a metastable episode, not a permanent state); 'Stable' otherwise.")
        else:
            cols[3].metric("Mode", _d(run_type),
                help="Run mode: 'bubble' = synctest virtual-clock run; 'real' = real server without a virtual clock; 'des' = pump-driven simulation.")

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
        sts_sorted = sorted(sts)
        if sts_sorted:
            c4.metric("Sched→Start P50", f"{_pct(sts_sorted, 50):.1f}ms",
                help="Median schedule-to-start latency: time from task creation to first poller pickup. Higher = matching backlog deeper.")
        c1, c2, c3, _ = st.columns(4)
        if sts_sorted:
            c1.metric("P90", f"{_pct(sts_sorted, 90):.1f}ms",
                help="90th percentile schedule-to-start latency.")
            c2.metric("P99", f"{_pct(sts_sorted, 99):.1f}ms",
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
            b3.metric("Max Matching Backlog", _d(_tv(r, "MaxMatchingBacklog"), 0),
                help="Run-maximum per-window matching logical backlog (approximate_backlog_count, sampled last-value per window, ADR-076). 0 when the gauge never emitted.")
            b4.metric("Final Backlog", _d(_tv(r, "FinalMatchingBacklog"), 0),
                help="Matching backlog in the last window that observed depth — the drained state (0 = fully drained).")

            # Run-level S2S latency summary (results.latency from ADR-076/077).
            lat = _tv(r, "Latency")
            if isinstance(lat, dict) and lat.get("count"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("S2S Latency Count", _d(lat.get("count"), 0),
                    help="Schedule-to-start observations in this run (task_schedule_to_start_latency TimerDef).")
                c2.metric("S2S p50", f"{lat.get('p50Ms', 0):.1f}ms",
                    help="Median schedule-to-start latency (histogram-derived, bucket lower bounds).")
                c3.metric("S2S p90", f"{lat.get('p90Ms', 0):.1f}ms",
                    help="90th percentile schedule-to-start latency.")
                c4.metric("S2S p99", f"{lat.get('p99Ms', 0):.1f}ms",
                    help="99th percentile schedule-to-start latency.")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("S2S Max", f"{lat.get('maxMs', 0):.1f}ms",
                    help="Maximum observed schedule-to-start latency.")
                c2.metric("S2S Mean", f"{lat.get('meanMs', 0):.1f}ms",
                    help="Bucket-midpoint mean schedule-to-start latency.")
                c3.metric("History Pending Max", _d(_tv(r, "HistoryPendingMax"), 0),
                    help="Run-maximum per-window history pending_tasks (per-shard last-value sum).")
            else:
                b1, b2, b3, _ = st.columns(4)
                b1.metric("Max Matching Backlog", _d(_tv(r, "MaxMatchingBacklog"), 0),
                    help="Run-maximum per-window matching logical backlog (sampled last-value per window, ADR-076). 0 when the gauge never emitted.")
                b2.metric("Final Backlog", _d(_tv(r, "FinalMatchingBacklog"), 0),
                    help="Matching backlog in the last window that observed depth (0 = fully drained).")
                b3.metric("History Pending Max", _d(_tv(r, "HistoryPendingMax"), 0),
                    help="Run-maximum per-window history pending_tasks (per-shard last-value sum).")
            st.caption("Run-level S2S latency summary from results.latency (ADR-076/077) — "
                "the p50/p90/p99/max/mean of schedule-to-start latency.")

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


def _sim_duration_ms(meta: dict):
    """Simulated duration from metadata: end−start when both exist; None if absent.

    Real-server runs (run_type 'real') carry no sim clock — callers decide
    how to label the missing value."""
    end = meta.get("sim_time_end_ms")
    start = meta.get("sim_time_start_ms")
    if end is None:
        return None
    if start is None:
        return end
    return end - start


@st.cache_data(show_spinner=False)
def _runs_table(exp: Path) -> pd.DataFrame:
    """Interest-sorted run index: storms first, then monitor score desc.

    For a scenario-group experiment (retry_amp → af/calm/...), adds a Scenario
    column so the top-level table aggregates its scenarios instead of being a
    dead-end."""
    group = _is_scenario_group(exp)
    rows = []
    for run in _experiment_runs(exp, max_depth=3 if group else 2):
        meta = json.loads((run / "metadata.json").read_text()) if (run / "metadata.json").exists() else {}
        r = {}
        if (run / "results.json").exists():
            r = json.loads((run / "results.json").read_text())
        run_type = _tv(r, "RunType")
        ms = _tv(r, "MonitorStatus") or {}
        metastable = bool(ms.get("Metastable")) if ms else None
        # Only bubble runs carry a monitor status; DES runs show their mode.
        if run_type == "bubble" and ms:
            status = "Storm" if metastable else "Stable"
        else:
            status = _d(run_type, "—")
        score = ms.get("Score") if ms else (r.get("Score") if isinstance(r, dict) else None)
        dur_ms = _sim_duration_ms(meta)
        scenario = ""
        if group:
            # run = .../retry_amp/<scenario>/42/harness-*
            rel = run.relative_to(exp)
            scenario = rel.parts[0] if len(rel.parts) > 1 else ""
        rows.append({
            "Run": _run_label(meta, run),
            "Scenario": scenario,
            "Seed": meta.get("seed", "—"),
            "Sim (ms)": dur_ms,
            "Status": status,
            "Score": score,
            "is_meta": metastable if run_type == "bubble" else False,
            "path": str(run),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["is_meta", "Score"], ascending=[False, False], na_position="last")
    return df


def _render_run(run: Path, label: str, uid: str = "", idx: int = 0) -> None:
    """Full detail for one run: key metrics, temporal charts, pool, monitor, config.

    uid + idx namespace inner widget keys (rate_/count_/depth_/...) so the
    same run dir under different experiments — or the same experiment with
    multiple selected runs — doesn't collide Streamlit element keys."""
    k = f"{uid}_{idx}_{run.name}" if uid else run.name
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
    rtype = _tv(r, "RunType") if isinstance(r, dict) else None
    dur = _sim_duration_ms(meta)
    cols = st.columns(4)
    cols[0].metric("Seed", meta.get("seed", "?"),
        help="PRNG seed for deterministic reproducibility. Same seed + same config = identical run.")
    if rtype == "real":
        cols[1].metric("Wall Clock", f"{_d((r or {}).get('wallDurationMs'), '?')}ms",
            help="Wall-clock duration of the real-server run (no virtual clock).")
    else:
        cols[1].metric("Sim Time", f"{_d(dur, '?')}ms",
            help="Simulated duration (end − start). Not wall-clock — this is DES/synctest time.")
    cols[2].metric("Experiment", meta.get("experiment_name", label),
        help="Experiment name from metadata. Matches the output directory name.")
    if isinstance(r, dict):
        _show_results(r, cols, meta)

    # --- Temporal-level metrics (scenario_snapshots + ScheduleToStart) ---
    if sdf is not None:
        st.subheader("Temporal Metrics (per-poll snapshots)")
        rate_cols = [c for c in ["retry_amp", "window_retry_amp",
            "timeout_rate", "drop_rate", "task_rate"] if c in sdf.columns]
        count_cols = [c for c in ["queue_mean", "sched_to_start",
            "tasks", "attempts", "resched_depth"] if c in sdf.columns]
        depth_cols = [c for c in ["matching_backlog", "physical_backlog",
            "history_pending", "hist_resched_depth"] if c in sdf.columns]
        lat_cols = [c for c in ["s2s_p50", "s2s_p90", "s2s_p99"] if c in sdf.columns]
        l, r = st.columns(2)
        with l:
            sel_rate = st.multiselect("Rates/proportions", rate_cols,
                default=[c for c in ["retry_amp", "timeout_rate"] if c in rate_cols],
                key=f"rate_{k}")
            if sel_rate:
                st.line_chart(sdf[sel_rate])
        with r:
            sel_count = st.multiselect("Counts/latency", count_cols,
                default=[c for c in ["queue_mean", "sched_to_start"] if c in count_cols],
                key=f"count_{k}")
            if sel_count:
                st.line_chart(sdf[sel_count])

        if depth_cols:
            st.subheader("Queue Depth (per-window sampled gauges, ADR-076)")
            sel_depth = st.multiselect("Depth series", depth_cols,
                default=[c for c in ["matching_backlog"] if c in depth_cols],
                key=f"depth_{k}")
            if sel_depth:
                st.line_chart(sdf[sel_depth])
            st.caption("matching_backlog = logical approximate_backlog_count (last-value per window); "
                "physical_backlog = physical_approximate_backlog_count (ack/update paths only); "
                "history_pending = pending_tasks (history shards); hist_resched_depth = history rescheduler.")

        if lat_cols:
            st.subheader("Schedule-to-Start Latency (per-window percentiles)")
            sel_lat = st.multiselect("Latency series", lat_cols,
                default=[c for c in ["s2s_p50", "s2s_p90", "s2s_p99"] if c in lat_cols],
                key=f"lat_{k}")
            if sel_lat:
                st.line_chart(sdf[sel_lat])
            st.caption("Percentiles derived from the per-window S2S histogram buckets (lower bounds; "
                "bucket i covers [2^(i-1), 2^i) ms).")

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
    with st.expander("ℹ️ Metric Descriptions", key=f"help_{k}"):
        st.markdown("""
| Chart Field | Source | Description |
|---|---|---|
| `queue_mean` | Snapshot.QueueMean | Time-weighted avg matching/persistence queue depth. Primary load signal. |
| `retry_amp` | Snapshot.RetryAmplification | Per-window delta task_attempt/task_count. >1 = retry amp in that window. |
| `window_retry_amp` | Snapshot.WindowRetryAmp | Same as retry_amp — per-window attempt/task ratio. |
| `timeout_rate` | Snapshot.TimeoutRate | Per-window timeout fraction of tasks (service_errors / task_count). |
| `drop_rate` | Snapshot.DropRate | Per-window drop fraction (persistence_error_with_type / task_requests). |
| `task_rate` | Snapshot.TaskRate | Per-window new task arrivals (delta of task_requests metric). Burst spike signal. |
| `sched_to_start` | Snapshot.ScheduleToStartLatency | Per-window mean schedule-to-start latency (histogram bucket-midpoint mean, ADR-076). |
| `tasks` | Snapshot.Tasks | Per-window completed task count (delta of cumulative task_count). |
| `attempts` | Snapshot.Attempts | Per-window attempt count (delta of task_attempt + workflow_task_attempt). |
| `resched_depth` | Snapshot.ReschedulerDepth | DEPRECATED (ADR-076). History rescheduler pending depth, sampled (no longer a cumulative sum). |
| `matching_backlog` | Snapshot.MatchingBacklogCount | Matching logical backlog (approximate_backlog_count), last-value per window, summed across priorities. Primary QueueMean source. |
| `physical_backlog` | Snapshot.PhysicalMatchingBacklogCount | Matching physical backlog (physical_approximate_backlog_count), last-value per window. Emitted on ack/update paths only. |
| `history_pending` | Snapshot.HistoryPendingTasks | History pending_tasks, last-value per shard summed across shards. |
| `hist_resched_depth` | Snapshot.HistoryReschedulerDepth | History rescheduler pending executables (task_rescheduler_pending_tasks), sampled. |
| `s2s_p50/p90/p99` | Snapshot.S2SHistogram | Per-window schedule-to-start latency percentiles derived from the 32-bucket log-scale histogram (lower bounds; bucket i covers [2^(i-1), 2^i) ms). |
""")
        st.caption("All values are per-100ms-poll-window unless labeled 'running avg'. Hover chart legend for series names.")

    # --- Config + metadata ---
    with st.expander("Config & Metadata", key=f"cfg_{k}"):
        c1, c2 = st.columns(2)
        with c1:
            if cfg:
                st.json(cfg)
        with c2:
            if meta:
                st.json(meta)

    # --- Full results (collapsed by default) ---
    if results_file.exists():
        with st.expander("Results (raw)", key=f"raw_{k}"):
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
    exps = sorted(_experiments(project))
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
        if _is_scenario_group(exp):
            st.caption(f"{len(opts)} runs across {len(_scenario_group_children(exp))} scenarios — "
                "the table sorts storms first. The aggregate rows are per-run; pick runs to compare.")
        else:
            st.caption(f"{len(opts)} runs — table sorts storms first. Click a run to focus it.")

        # --- Aggregate metrics across all runs (below the run count) ---
        score = runs_df["Score"].dropna()
        sim = pd.to_numeric(runs_df["Sim (ms)"], errors="coerce").dropna()
        meta_n = int(runs_df["is_meta"].sum())
        agg = st.columns(3)
        agg[0].metric("Total runs", len(opts))
        agg[1].metric("Storm", f"{meta_n} ({meta_n / len(opts):.0%})",
            help="Fraction of bubble runs where the monitor declared a metastable episode (weighted multi-dim score > epsilon for N consecutive windows).")
        agg[2].metric("Median score", f"{score.median():.3f}" if not score.empty else "—",
            help="Median monitor score across all runs. Higher = further from baseline.")
        agg = st.columns(3)
        agg[0].metric("Max score", f"{score.max():.3f}" if not score.empty else "—",
            help="Worst (highest) monitor score across all runs.")
        agg[1].metric("Median sim", f"{sim.median():.0f} ms" if not sim.empty else "—",
            help="Median simulated duration across all runs (DES time, not wall-clock).")
        agg[2].metric("Stable", len(opts) - meta_n,
            help="Bubble runs with no declared metastable episode.")

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

# --- Experiment-level Summary/vectors files (model leg, composed confirm,
# dose-response, envelope) — render before the per-run drill-down so the
# report's tables are visible even when an experiment has no run dirs. ---
if _render_summary_file(exp):
    st.divider()

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
                "window_retry_amp", "queue_mean", "sched_to_start",
                "matching_backlog", "history_pending", "s2s_p50", "s2s_p90", "s2s_p99"]
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
    for i, (run, lb) in enumerate(sel_runs):
        with st.expander(f"Run {lb}", expanded=len(sel_runs) == 1,
                key=f"run_{project.name}_{exp.name}_{run.name}_{i}"):
            _render_run(run, lb, uid=f"{project.name}_{exp.name}", idx=i)
