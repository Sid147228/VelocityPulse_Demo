import pandas as pd
import matplotlib
matplotlib.use("Agg")   # ensure non-GUI backend
import matplotlib.pyplot as plt
import seaborn as sns
import os
import io, base64

# Old disk-saving version (kept for local runs)
def generate_rag_pie(summary, out_file="static/reports/graphs/rag_pie.png"):
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    rag_counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for row in summary:
        rag = row.get("RAG")
        if rag in rag_counts:
            rag_counts[rag] += 1

    labels = list(rag_counts.keys())
    sizes = list(rag_counts.values())

    plt.figure(figsize=(4, 4))
    plt.pie(sizes, labels=labels, autopct="%1.1f%%", colors=["green", "orange", "red"])
    plt.title("RAG Distribution")
    plt.savefig(out_file)
    plt.close()


# New base64-returning version (for Vercel)
def generate_rag_pie_base64(summary):
    rag_counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for row in summary:
        rag = row.get("RAG")
        if rag in rag_counts:
            rag_counts[rag] += 1

    labels = list(rag_counts.keys())
    sizes = list(rag_counts.values())

    plt.figure(figsize=(4, 4))
    plt.pie(sizes, labels=labels, autopct="%1.1f%%", colors=["#28a745", "#ffc107", "#dc3545"])
    plt.title("RAG Distribution")

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close()
    return img_base64