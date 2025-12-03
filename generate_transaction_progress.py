import pandas as pd
import matplotlib
matplotlib.use("Agg")   # ensure non-GUI backend
import matplotlib.pyplot as plt
import seaborn as sns
import os
import io, base64

# Old disk-saving version (kept for local runs)
def generate_transaction_progress(df, out_file="static/reports/graphs/transaction_progress.png"):
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    # ✅ Ensure DataFrame
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception as e:
            print("⚠ Could not convert df to DataFrame:", e)
            return

    # ✅ Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    if "timestamp" in df.columns and "label" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        plt.figure(figsize=(8,4))
        grouped = df.groupby([df["timestamp"].dt.floor("min"), df["label"]]).size().unstack(fill_value=0)
        if not grouped.empty:
            grouped.plot(ax=plt.gca())
            plt.title("Transaction Progress Over Time")
            plt.xlabel("Time")
            plt.ylabel("Count")
            plt.tight_layout()
            plt.savefig(out_file)
            plt.close()
        else:
            print("⚠ Skipping transaction progress: no grouped data")
    else:
        print("⚠ Skipping transaction progress: required columns missing")


# New base64-returning version (for Vercel)
def generate_transaction_progress_base64(df):
    # ✅ Ensure DataFrame
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception as e:
            print("⚠ Could not convert df to DataFrame:", e)
            return None

    df.columns = [c.strip().lower() for c in df.columns]

    if "timestamp" in df.columns and "label" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        plt.figure(figsize=(8,4))
        grouped = df.groupby([df["timestamp"].dt.floor("min"), df["label"]]).size().unstack(fill_value=0)
        if not grouped.empty:
            grouped.plot(ax=plt.gca())
            plt.title("Transaction Progress Over Time")
            plt.xlabel("Time")
            plt.ylabel("Count")
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode("utf-8")
            plt.close()
            return img_base64
        else:
            print("⚠ Skipping transaction progress: no grouped data")
            return None
    else:
        print("⚠ Skipping transaction progress: required columns missing")
        return None