"""RQ2: how is public-transport accessibility associated with the price per m2?

Run from the repo root: python src/07_rq2.py
Input:  data/processed/analysis.parquet (listings with price_m2 and distance to the nearest railway station)
Output: tables/rq2_bands.csv, tables/rq2_spearman.csv, figures/rq2_price_by_distance.png, caption in figures/captions.md
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr

from config import DATA_PROCESSED, DISTANCE_LABELS, FIGURES_DIR, TABLES_DIR
from utils import write_caption

DPI = 300
sns.set_theme(style="whitegrid", font_scale=1.0)


def band_table(df):
    """Median price_m2 (with quartiles) and number of listings per distance band."""
    table = df.groupby("station_band", observed=True)["price_m2"].agg(
        n="count", median_price_m2="median", q25=lambda s: s.quantile(0.25), q75=lambda s: s.quantile(0.75))
    table = table.reindex(DISTANCE_LABELS).round({"median_price_m2": 2, "q25": 2, "q75": 2})
    return table.reset_index()


def spearman_table(df):
    """Spearman correlation of station_km with price_m2 for all listings and for exact locations only."""
    rows = []
    for name, subset in (("all listings", df), ("exact_location only (own coordinates and street)", df[df["exact_location"]])):
        rho, p = spearmanr(subset["station_km"], subset["price_m2"])
        rows.append({"subset": name, "n": len(subset), "spearman_rho": round(rho, 3), "p_value": p})
    return pd.DataFrame(rows)


def plot_boxes(df, bands):
    """Box plot of price_m2 by distance band (outliers of the boxes not drawn)."""
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(x="station_band", y="price_m2", data=df, order=DISTANCE_LABELS, color="#7fb3d5", showfliers=False, ax=ax)
    ax.set_xticks(range(len(DISTANCE_LABELS)))
    ax.set_xticklabels([f"{label}\nn={n:,}" for label, n in zip(bands["station_band"], bands["n"])])
    ax.set_xlabel("Straight-line distance to the nearest railway station (n = number of listings)")
    ax.set_ylabel("Price per m² (CHF per m² per month)")
    ax.plot([], [], color="#7fb3d5", linewidth=8, label="Interquartile range (box), line = median")
    ax.plot([], [], color="black", linewidth=1, label="Whiskers: 1.5 x IQR")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "rq2_price_by_distance.png", dpi=DPI)
    plt.close(fig)


def main():
    df = pd.read_parquet(DATA_PROCESSED / "analysis.parquet")
    df = df[df["price_m2"].notna() & df["station_km"].notna()]
    FIGURES_DIR.mkdir(exist_ok=True)

    bands = band_table(df)
    bands.to_csv(TABLES_DIR / "rq2_bands.csv", index=False)
    print("=== Median price per m2 by distance band\n", bands.to_string(index=False))

    correlations = spearman_table(df)
    correlations.to_csv(TABLES_DIR / "rq2_spearman.csv", index=False)
    print("\n=== Spearman station_km vs price_m2\n", correlations.to_string(index=False))

    plot_boxes(df, bands)
    write_caption("rq2_price_by_distance.png",
                  f"Price per m² (CHF per month) of {len(df):,} Swiss rental apartments with known living area, grouped by "
                  f"straight-line distance to the nearest railway station (Flatfox, November 2026; stations: atlas service points of "
                  f"the SBB). Boxes show the interquartile range with the median as line, whiskers extend to 1.5 x IQR, outliers of the "
                  f"boxes are not drawn; n per band is given below each label. Medians and quartiles are in tables/rq2_bands.csv.")


if __name__ == "__main__":
    main()
