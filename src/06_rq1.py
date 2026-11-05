"""RQ1: which property characteristics are most strongly associated with the gross rent?

Run from the repo root: python src/06_rq1.py
Input:  data/processed/analysis.parquet
Output: tables/rq1_spearman.csv, tables/rq1_rent_by_rooms.csv, tables/rq1_model.csv,
        figures/rq1_spearman.png, figures/rq1_rent_by_rooms.png, captions in figures/captions.md
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import spearmanr
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from config import DATA_PROCESSED, FIGURES_DIR, RANDOM_STATE, TABLES_DIR, TEST_SIZE
from utils import write_caption

FEATURES = {"area_m2": "Living area (m²)", "rooms": "Number of rooms", "floor": "Floor",
            "has_balcony": "Balcony / garden", "has_lift": "Lift", "has_parking": "Parking space / garage"}
BINARY = ["has_balcony", "has_lift", "has_parking"]
MIN_GROUP = 20  # smallest rooms group shown in the box plot
DPI = 300
sns.set_theme(style="whitegrid", font_scale=1.0)


def spearman_table(df):
    """Spearman correlation of rent_gross with each characteristic (rows with both values present)."""
    rows = []
    for col, label in FEATURES.items():
        pair = df[["rent_gross", col]].astype(float).dropna()
        rho, p = spearmanr(pair["rent_gross"], pair[col])
        rows.append({"variable": col, "label": label, "n": len(pair), "spearman_rho": round(rho, 3), "p_value": p})
    return pd.DataFrame(rows).sort_values("spearman_rho", ascending=False).reset_index(drop=True)


def plot_spearman(table):
    """Horizontal bar chart of the Spearman correlations."""
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    kind = np.where(table["variable"].isin(BINARY), "Yes/no feature", "Numeric variable")
    sns.barplot(x="spearman_rho", y="label", hue=kind, data=table, dodge=False, ax=ax,
                palette={"Numeric variable": "#2b6a99", "Yes/no feature": "#e08a1e"})
    for i, rho in enumerate(table["spearman_rho"]):
        ax.text(rho + (0.015 if rho >= 0 else -0.015), i, f"{rho:.3f}", va="center", ha="left" if rho >= 0 else "right", fontsize=9)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlim(min(0, table["spearman_rho"].min()) - 0.08, table["spearman_rho"].max() + 0.1)
    ax.set_xlabel("Spearman rank correlation with gross rent (ρ, no unit)")
    ax.set_ylabel("")
    ax.legend(title="Type of variable", loc="lower right", frameon=True)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "rq1_spearman.png", dpi=DPI)
    plt.close(fig)


def rent_by_rooms(df):
    """Median gross rent by number of rooms (rounded to 0.5); groups with at least MIN_GROUP listings."""
    data = df[["rent_gross", "rooms"]].dropna().copy()
    data["rooms_group"] = (data["rooms"] * 2).round() / 2
    stats = data.groupby("rooms_group")["rent_gross"].agg(n="count", median_rent="median",
                                                          q25=lambda s: s.quantile(0.25),
                                                          q75=lambda s: s.quantile(0.75)).reset_index()
    stats = stats[stats["n"] >= MIN_GROUP].round({"median_rent": 0, "q25": 0, "q75": 0})
    return data[data["rooms_group"].isin(stats["rooms_group"])], stats


def plot_rent_by_rooms(data, stats):
    """Box plot of the gross rent per rooms group (outliers of the boxes not drawn)."""
    fig, ax = plt.subplots(figsize=(11, 5))
    order = stats["rooms_group"].tolist()
    sns.boxplot(x="rooms_group", y="rent_gross", data=data, order=order, color="#7fb3d5", showfliers=False, ax=ax)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"{r:g}\nn={n:,}" for r, n in zip(stats["rooms_group"], stats["n"])], fontsize=9)
    ax.set_xlabel("Number of rooms (rounded to 0.5; n = number of listings)")
    ax.set_ylabel("Gross rent (CHF per month)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.plot([], [], color="#7fb3d5", linewidth=8, label="Interquartile range (box), line = median")
    ax.plot([], [], color="black", linewidth=1, label="Whiskers: 1.5 x IQR")
    ax.legend(loc="upper left", frameon=True)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "rq1_rent_by_rooms.png", dpi=DPI)
    plt.close(fig)


def fit_model(df):
    """Linear regression of rent_gross on the characteristics (80/20 split) against a median-per-rooms baseline."""
    cols = ["rent_gross", *FEATURES]
    data = df.loc[~df["is_outlier"], cols].astype(float).dropna()
    train, test = train_test_split(data, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    model = LinearRegression().fit(train[list(FEATURES)], train["rent_gross"])
    pred = model.predict(test[list(FEATURES)])
    group = lambda d: (d["rooms"] * 2).round() / 2  # noqa: E731
    medians = train.groupby(group(train))["rent_gross"].median()
    baseline = group(test).map(medians).fillna(train["rent_gross"].median())
    rows = []
    for name, y_pred in (("linear_regression", pred), ("baseline_median_per_rooms", baseline)):
        rows += [{"model": name, "metric": "n_train", "value": len(train)}, {"model": name, "metric": "n_test", "value": len(test)},
                 {"model": name, "metric": "mae_chf", "value": round(mean_absolute_error(test["rent_gross"], y_pred), 1)},
                 {"model": name, "metric": "r2", "value": round(r2_score(test["rent_gross"], y_pred), 3)}]
    rows.append({"model": "linear_regression", "metric": "intercept", "value": round(model.intercept_, 1)})
    rows += [{"model": "linear_regression", "metric": f"coef_{c}", "value": round(v, 1)} for c, v in zip(FEATURES, model.coef_)]
    return pd.DataFrame(rows), len(data)


def main():
    df = pd.read_parquet(DATA_PROCESSED / "analysis.parquet")
    FIGURES_DIR.mkdir(exist_ok=True)

    table = spearman_table(df)
    table.drop(columns="label").to_csv(TABLES_DIR / "rq1_spearman.csv", index=False)
    plot_spearman(table)
    print("=== Spearman correlation with rent_gross\n", table.drop(columns="label").to_string(index=False))

    data, stats = rent_by_rooms(df)
    stats.to_csv(TABLES_DIR / "rq1_rent_by_rooms.csv", index=False)
    plot_rent_by_rooms(data, stats)
    print("\n=== Median gross rent by rooms (groups with n >= %d)\n" % MIN_GROUP, stats.to_string(index=False))

    model, n_complete = fit_model(df)
    model.to_csv(TABLES_DIR / "rq1_model.csv", index=False)
    print(f"\n=== Linear regression (complete rows without outliers: {n_complete})\n", model.to_string(index=False))

    n_sp = table.set_index("variable")["n"]
    write_caption("rq1_spearman.png",
                  f"Spearman rank correlation between the gross monthly rent (CHF) and six property characteristics of Swiss rental "
                  f"apartments (Flatfox, November 2026). Each bar uses all listings with both values present (n = {n_sp.min():,} to "
                  f"{n_sp.max():,}); all p-values are listed in tables/rq1_spearman.csv. Colour separates numeric variables from yes/no features.")
    write_caption("rq1_rent_by_rooms.png",
                  f"Gross monthly rent (CHF) by number of rooms (rounded to 0.5) for {len(data):,} listings. Boxes show the interquartile range "
                  f"with the median as line, whiskers extend to 1.5 x IQR, outliers of the boxes are not drawn. Groups with fewer than "
                  f"{MIN_GROUP} listings are omitted; n per group is given below each label. Medians are in tables/rq1_rent_by_rooms.csv.")


if __name__ == "__main__":
    main()
