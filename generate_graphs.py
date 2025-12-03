import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import io, base64

# Old disk-saving version (works locally, but not on Vercel)
def generate_graphs(df, green_sla=None, amber_sla=None, out_dir="static/reports/graphs"):
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception as e:
            print("⚠ generate_graphs: could not convert input to DataFrame:", e)
            return

    df.columns = [c.strip() for c in df.columns]

    if 'timeStamp' in df.columns and 'timestamp' not in df.columns:
        df['timeStamp'] = pd.to_numeric(df['timeStamp'], errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timeStamp'], unit='ms', errors='coerce')
    elif 'timestamp' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    else:
        df['timestamp'] = pd.NaT

    if 'elapsed' in df.columns:
        df['elapsed'] = pd.to_numeric(df['elapsed'], errors='coerce')
    else:
        df['elapsed'] = pd.NA

    if 'success' in df.columns:
        df['success'] = df['success'].astype(str).str.lower().isin(['true', '1'])
    else:
        df['success'] = True

    # Response Time Distribution
    if 'elapsed' in df.columns and not df['elapsed'].dropna().empty:
        plt.figure(figsize=(8, 4))
        sns.histplot(df['elapsed'].dropna(), bins=30, kde=True, color='steelblue')
        if green_sla is not None:
            plt.axvline(x=green_sla * 1000, color='green', linestyle='--', label=f'Green SLA ({green_sla}s)')
        if amber_sla is not None:
            plt.axvline(x=amber_sla * 1000, color='orange', linestyle='--', label=f'Amber SLA ({amber_sla}s)')
        plt.title('Response Time Distribution')
        plt.xlabel('Elapsed (ms)')
        plt.ylabel('Frequency')
        if green_sla is not None or amber_sla is not None:
            plt.legend()
        plt.tight_layout()
        plt.savefig(f'{out_dir}/response_distribution.png')
        plt.close()

    # Error Trend
    if 'timestamp' in df.columns and not df['timestamp'].isna().all():
        error_df = df.groupby(df['timestamp'].dt.floor('min'))['success'] \
                     .apply(lambda x: 100.0 * (1.0 - x.sum() / len(x)))
        if not error_df.empty:
            plt.figure(figsize=(8, 4))
            error_df.plot(color='crimson')
            plt.title('Error Trend Over Time')
            plt.xlabel('Time')
            plt.ylabel('Error %')
            plt.tight_layout()
            plt.savefig(f'{out_dir}/error_trend.png')
            plt.close()

    # SLA Heatmap (Option B: groupby + unstack)
    if all(col in df.columns for col in ['label', 'elapsed', 'timestamp']) and not df['timestamp'].isna().all():
        heatmap_data = (
            df.groupby([df['label'], df['timestamp'].dt.floor('min')])['elapsed']
              .mean()
              .unstack(fill_value=0)
        )
        if heatmap_data is not None and not heatmap_data.empty:
            plt.figure(figsize=(10, 6))
            sns.heatmap(heatmap_data, cmap='coolwarm', linewidths=0.5)
            plt.title('SLA Heatmap')
            plt.xlabel('Time')
            plt.ylabel('Transaction')
            plt.tight_layout()
            plt.savefig(f'{out_dir}/sla_heatmap.png')
            plt.close()

    # Threads Over Time
    if 'threadName' in df.columns and 'timestamp' in df.columns and not df['timestamp'].isna().all():
        thread_counts = df.groupby(df['timestamp'].dt.floor('min'))['threadName'].nunique()
        if not thread_counts.empty:
            plt.figure(figsize=(8, 4))
            thread_counts.plot(color='darkgreen')
            plt.title('Threads Over Time')
            plt.xlabel('Time')
            plt.ylabel('Active Threads')
            plt.tight_layout()
            plt.savefig(f'{out_dir}/threads_over_time.png')
            plt.close()


# New base64-returning version (for Vercel)
def generate_graphs_base64(df, green_sla=None, amber_sla=None):
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except Exception as e:
            print("⚠ generate_graphs_base64: could not convert input to DataFrame:", e)
            return None

    df.columns = [c.strip() for c in df.columns]

    if 'elapsed' not in df.columns or df['elapsed'].dropna().empty:
        return None

    plt.figure(figsize=(8, 4))
    sns.histplot(df['elapsed'].dropna(), bins=30, kde=True, color='steelblue')
    if green_sla is not None:
        plt.axvline(x=green_sla * 1000, color='green', linestyle='--', label=f'Green SLA ({green_sla}s)')
    if amber_sla is not None:
        plt.axvline(x=amber_sla * 1000, color='orange', linestyle='--', label=f'Amber SLA ({amber_sla}s)')
    plt.title('Response Time Distribution')
    plt.xlabel('Elapsed (ms)')
    plt.ylabel('Frequency')
    if green_sla is not None or amber_sla is not None:
        plt.legend()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close()
    return img_base64