import os
os.environ["MPLCONFIGDIR"] = "/tmp"  # Ensure Matplotlib uses writable config path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import pandas as pd
import numpy as np
from datetime import datetime
from werkzeug.utils import secure_filename

# Helpers
from jmeter_parser import parse_jmeter_csv
from generate_TestResult import evaluate_sla
from generate_graphs import generate_graphs_base64
from generate_transaction_progress import generate_transaction_progress_base64
from generate_rag_pie import generate_rag_pie_base64

app = Flask(__name__)
app.secret_key = "velocitypulse_demo"

# Writable paths for Vercel
UPLOAD_FOLDER = "/tmp/uploads"
HISTORY_FILE = "/tmp/history.json"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- History helpers ---
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_report(report_data):
    history = load_history()
    history.insert(0, report_data)
    try:
        def convert(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.ndarray,)):
                return obj.tolist()
            return obj
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=convert)
    except Exception as e:
        print("⚠ Failed to save report metadata:", e)

def load_report(report_index):
    history = load_history()
    if 0 <= report_index < len(history):
        return history[report_index]
    return None

# --- Routes ---
@app.route("/")
def home():
    return redirect(url_for("upload"))

@app.route("/upload", methods=["GET", "POST"])
def upload():
    uploaded_file = None
    uploaded_file_path = None
    transactions = []

    if request.method == "POST":
        try:
            if "file" in request.files:
                file = request.files["file"]
                if file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    uploaded_file = filename
                    uploaded_file_path = file_path

                    # Attempt to parse the uploaded file
                    green, amber, rag_basis = 2.0, 5.0, "avg"
                    summary, test_rag = parse_jmeter_csv(file_path, green, amber, rag_basis)
                    transactions = [row.get("Transaction") for row in summary if row.get("Transaction")]
        except Exception as e:
            print("Upload error:", e)
            flash("⚠️ Failed to process uploaded file. Please check format and size.")

    return render_template(
        "upload.html",
        uploaded_file=uploaded_file,
        uploaded_file_path=uploaded_file_path,
        transactions=transactions
    )

@app.route("/analyze", methods=["POST"])
def analyze():
    file_path = request.form.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "No valid file path provided"}), 400

    report_name = request.form.get("report_name", "Untitled Report")
    green = float(request.form.get("green", 2.0))
    amber = float(request.form.get("amber", 5.0))
    rag_basis = request.form.get("rag_basis", "avg")
    metrics = request.form.getlist("metrics") or ["avg", "p90", "p95", "samples", "error"]

    # Parse and evaluate SLA
    summary, test_rag = parse_jmeter_csv(file_path, green, amber, rag_basis)
    summary, test_rag = evaluate_sla(summary, green, amber, rag_basis)

    # Normalize summary keys
    def _norm_row_keys(row):
        mapping = {
            "Avg (s)": "avg",
            "90th % (s)": "p90",
            "95th % (s)": "p95",
            "Error %": "error",
            "Samples": "samples",
        }
        out = dict(row)
        for src, dst in mapping.items():
            if src in row and row[src] is not None:
                out[dst] = row[src]
        return out

    summary = [_norm_row_keys(r) for r in summary]

    # --- Build time-series data ---
    df = pd.read_csv(file_path)
    df.columns = [c.strip().lower() for c in df.columns]

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="coerce"), unit="ms", errors="coerce")
    else:
        df["timestamp"] = pd.NaT

    if "label" not in df.columns:
        if "samplerlabel" in df.columns:
            df["label"] = df["samplerlabel"].astype(str)
        else:
            df["label"] = "Transaction"

    df["elapsed"] = pd.to_numeric(df.get("elapsed"), errors="coerce")
    if "success" in df.columns:
        df["success"] = df["success"].astype(str).str.lower().isin(["true", "1"])
    else:
        df["success"] = True

    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    if not df.empty:
        time_index = df["timestamp"].dt.floor("s")
        time_labels = sorted(time_index.dropna().unique())
        labels_fmt = [ts.strftime("%H:%M:%S") for ts in time_labels]

        series_by_txn = {}
        for txn, g in df.groupby("label"):
            gb = g.groupby(g["timestamp"].dt.floor("s"))
            txn_series = {}
            if "avg" in metrics:
                avg_ms = gb["elapsed"].mean()
                txn_series["avg"] = [avg_ms.get(t, None)/1000.0 if pd.notnull(avg_ms.get(t, None)) else None for t in time_labels]
            if "p90" in metrics:
                p90_ms = gb["elapsed"].quantile(0.90)
                txn_series["p90"] = [p90_ms.get(t, None)/1000.0 if pd.notnull(p90_ms.get(t, None)) else None for t in time_labels]
            if "p95" in metrics:
                p95_ms = gb["elapsed"].quantile(0.95)
                txn_series["p95"] = [p95_ms.get(t, None)/1000.0 if pd.notnull(p95_ms.get(t, None)) else None for t in time_labels]
            if "samples" in metrics:
                samples = gb.size()
                txn_series["samples"] = [int(samples.get(t, 0)) for t in time_labels]
            if "error" in metrics:
                err_pct = gb.apply(lambda x: 100.0 * ((~x["success"]).sum() / len(x)))
                txn_series["error"] = [err_pct.get(t, None) if pd.notnull(err_pct.get(t, None)) else None for t in time_labels]
            if any(v is not None for arr in txn_series.values() for v in arr):
                series_by_txn[txn] = txn_series

        throughput_over_time = df.groupby(df["timestamp"].dt.floor("s")).size()
        series_throughput_over_time = [int(throughput_over_time.get(t, 0)) for t in time_labels]

        ts_min, ts_max = df["timestamp"].min(), df["timestamp"].max()
        total_duration_sec = (ts_max - ts_min).total_seconds() if pd.notnull(ts_min) and pd.notnull(ts_max) else 0
        test_period_str = f"{ts_min.strftime('%H:%M:%S')}–{ts_max.strftime('%H:%M:%S')}" if pd.notnull(ts_min) and pd.notnull(ts_max) else "N/A"
        total_duration_str = f"{int(total_duration_sec)}s" if total_duration_sec > 0 else "N/A"

        users_concurrent = None
        if "threadname" in df.columns:
            users_concurrent = df.groupby(df["timestamp"].dt.floor("s"))["threadname"].nunique().max()

        steady_state = "Yes" if series_throughput_over_time and pd.Series(series_throughput_over_time).std() < 0.1 * max(series_throughput_over_time) else "No"
    else:
        labels_fmt, series_by_txn, series_throughput_over_time = [], {}, []
        test_period_str, total_duration_str, users_concurrent, steady_state = "N/A", "N/A", None, "No"

    # --- Add samples count to summary rows ---
    if "samples" in metrics:
        for row in summary:
            txn = row.get("Transaction")
            if txn:
                row["samples"] = int(df[df["label"] == txn.shape[0])

    def _convert_numpy(val):
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        return val

    for txn, series in series_by_txn.items():
        for m, arr in series.items():
            series[m] = [_convert_numpy(v) if v is not None else None for v in arr]

    series_throughput_over_time = [_convert_numpy(v) for v in series_throughput_over_time]

    report_data = {
        "report_name": report_name,
        "file_name": os.path.basename(file_path),
        "summary": summary,
        "rag_result": test_rag,
        "test_date": datetime.utcnow().strftime("%d-%m-%Y"),
        "test_period": test_period_str,
        "total_duration": total_duration_str,
        "concurrent_users": users_concurrent if users_concurrent is not None else "N/A",
        "steady_state": steady_state,
        "rag_counts": {
            "GREEN": int(sum(1 for r in summary if r.get("RAG") == "GREEN")),
            "AMBER": int(sum(1 for r in summary if r.get("RAG") == "AMBER")),
            "RED": int(sum(1 for r in summary if r.get("RAG") == "RED")),
        },
        "chart_time_labels": labels_fmt,
        "series_by_txn": series_by_txn,
        "series_throughput_over_time": series_throughput_over_time,
        "timestamp": datetime.utcnow().isoformat(),
        "rag_basis": rag_basis,
        "green_sla": green,
        "amber_sla": amber,
        "metrics_selected": metrics,
    }

    try:
        report_data["graph_img"] = generate_graphs_base64(df, green, amber)
    except Exception as e:
        print("Graph generation failed (response distribution):", e)
        report_data["graph_img"] = None

    try:
        report_data["txn_progress_img"] = generate_transaction_progress_base64(df)
    except Exception as e:
        print("Graph generation failed (transaction progress):", e)
        report_data["txn_progress_img"] = None

    try:
        report_data["rag_pie_img"] = generate_rag_pie_base64(summary)
    except Exception as e:
        print("Graph generation failed (RAG pie):", e)
        report_data["rag_pie_img"] = None

    save_report(report_data)

    # ✅ Always return a response, even if template fails
    try:
        return render_template("report.html", **report_data)
    except Exception as e:
        print("Render failed:", e)
        return jsonify({"error": "Failed to render report", "details": str(e), "report_data": report_data}), 500


@app.route("/report/<int:report_index>")
def report(report_index):
    report_data = load_report(report_index)
    if report_data:
        return render_template("report.html", report_index=report_index, **report_data)
    else:
        flash("Report not found")
        return redirect(url_for("history"))


@app.route("/history")
def history():
    reports = load_history()
    return render_template(
        "history.html",
        reports=reports[:1]  # demo: only show the most recent report
    )


@app.route("/about")
def about():
    return render_template("about.html", version="Demo", build="Demo", codename="Restricted")


if __name__ == "__main__":
    app.run(debug=True)
