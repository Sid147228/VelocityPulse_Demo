import os
os.environ["MPLCONFIGDIR"] = "/tmp"  # Ensure Matplotlib uses writable config path

from flask import Flask, render_template, request, redirect, url_for, flash
import json
import pandas as pd
from datetime import datetime
from werkzeug.utils import secure_filename

# Helpers
from jmeter_parser import parse_jmeter_csv
from generate_TestResult import evaluate_sla
from generate_graphs import generate_graphs_base64   # <-- updated
from generate_transaction_progress import generate_transaction_progress_base64  # <-- updated
from generate_rag_pie import generate_rag_pie_base64  # <-- updated

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
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

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

    return render_template("upload.html",
                           uploaded_file=uploaded_file,
                           uploaded_file_path=uploaded_file_path,
                           transactions=transactions)

@app.route("/analyze", methods=["POST"])
def analyze():
    file_path = request.form["file_path"]
    report_name = request.form["report_name"]
    green, amber = float(request.form["green"]), float(request.form["amber"])
    rag_basis = request.form["rag_basis"]

    # Parse and evaluate SLA
    summary, test_rag = parse_jmeter_csv(file_path, green, amber, rag_basis)
    summary, test_rag = evaluate_sla(summary, green, amber, rag_basis)

    # --- Build time-series data for Chart.js ---
    df = pd.read_csv(file_path)
    df['timeStamp'] = pd.to_numeric(df['timeStamp'], errors='coerce').fillna(0).astype(int)

    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timeStamp'], unit="ms", errors="coerce")
        df['elapsed'] = pd.to_numeric(df['elapsed'], errors="coerce")
        df['success'] = df['success'].astype(str).str.lower().isin(["true", "1"])
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

        time_index = df["timestamp"].dt.floor("min")
        time_labels = sorted(time_index.dropna().unique())
        labels_fmt = [ts.strftime("%H:%M") for ts in time_labels]

        series_avg_by_txn, series_p90_by_txn, series_error_rate_by_txn = {}, {}, {}
        for txn, g in df.groupby("label"):
            gb = g.groupby(g["timestamp"].dt.floor("min"))
            avg_ms = gb["elapsed"].mean()
            p90_ms = gb["elapsed"].quantile(0.90)
            err_pct = gb.apply(lambda x: 100.0 * ((~x["success"]).sum() / len(x)))
            series_avg_by_txn[txn] = [
                round(avg_ms.get(t, None)/1000.0, 3) if pd.notnull(avg_ms.get(t, None)) else None
                for t in time_labels
            ]
            series_p90_by_txn[txn] = [
                round(p90_ms.get(t, None)/1000.0, 3) if pd.notnull(p90_ms.get(t, None)) else None
                for t in time_labels
            ]
            series_error_rate_by_txn[txn] = [
                round(err_pct.get(t, None), 3) if pd.notnull(err_pct.get(t, None)) else None
                for t in time_labels
            ]

        throughput_over_time = df.groupby(df["timestamp"].dt.floor("min")).size()
        series_throughput_over_time = [int(throughput_over_time.get(t, 0)) for t in time_labels]
    else:
        labels_fmt = []
        series_avg_by_txn, series_p90_by_txn, series_error_rate_by_txn = {}, {}, {}
        series_throughput_over_time = []

    # --- Build report data ---
    report_data = {
        "report_name": report_name,
        "file_name": os.path.basename(file_path),
        "summary": summary,
        "rag_result": test_rag,
        "test_date": datetime.utcnow().strftime("%d-%m-%Y"),
        "test_period": "Demo mode",
        "total_duration": "Demo mode",
        "concurrent_users": "Demo mode",
        "steady_state": "Demo mode",
        "rag_counts": {
            "GREEN": sum(1 for r in summary if r.get("RAG") == "GREEN"),
            "AMBER": sum(1 for r in summary if r.get("RAG") == "AMBER"),
            "RED": sum(1 for r in summary if r.get("RAG") == "RED"),
        },
        "chart_time_labels": labels_fmt,
        "series_avg_by_txn": series_avg_by_txn,
        "series_p90_by_txn": series_p90_by_txn,
        "series_error_rate_by_txn": series_error_rate_by_txn,
        "series_throughput_over_time": series_throughput_over_time,
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        # Generate base64 graphs instead of saving files
        report_data["graph_img"] = generate_graphs_base64(df, green, amber)
        report_data["txn_progress_img"] = generate_transaction_progress_base64(df)
        report_data["rag_pie_img"] = generate_rag_pie_base64(summary)
    except Exception as e:
        print("Graph generation failed:", e)

    save_report(report_data)
    return redirect(url_for("report", report_index=0))

@app.route("/report/<int:report_index>")
def report(report_index):
    reports = load_history()
    if 0 <= report_index < len(reports):
        report_data = reports[report_index]
        return render_template("report.html", report_index=report_index, **report_data)
    flash("Report not found")
    return redirect(url_for("history"))

@app.route("/history")
def history():
    reports = load_history()
    return render_template("history.html", reports=reports[:2])  # only show last 2 in demo

@app.route("/about")
def about():
    return render_template("about.html", version="Demo", build="Demo", codename="Restricted")

if __name__ == "__main__":
    app.run(debug=True)