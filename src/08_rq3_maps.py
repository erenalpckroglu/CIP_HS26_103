"""RQ3: municipality characteristics and the spatial pattern of prices (choropleth maps).

Run from the repo root: python src/08_rq3_maps.py
Input:  data/processed/municipalities.gpkg (all 2,110 municipalities), municipality_summary.csv
Output: tables/rq3_spearman.csv, figures/rq3_income_scatter.png, figures/rq3_map_price_m2.png,
        figures/rq3_maps_panel.png, captions in figures/captions.md
"""
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_hex
from matplotlib.patches import Patch
from scipy.stats import spearmanr

from config import DATA_PROCESSED, FIGURES_DIR, MIN_LISTINGS_PER_MUNICIPALITY, TABLES_DIR
from utils import write_caption

DPI = 300
GREY = "#d9d9d9"
BORDER = {"edgecolor": "#8a8a8a", "linewidth": 0.1}  # thin municipality borders
CANTON_BORDER = {"color": "#262626", "linewidth": 0.6}  # slightly thicker canton borders
INSUFFICIENT = f"insufficient data\n(< {MIN_LISTINGS_PER_MUNICIPALITY} listings with price per m²)"
sns.set_theme(style="white", font_scale=1.0)


def load_geodata():
    """All municipalities with their summary values, and the canton borders (municipalities dissolved by canton)."""
    muni = gpd.read_file(DATA_PROCESSED / "municipalities.gpkg")
    summary = pd.read_csv(DATA_PROCESSED / "municipality_summary.csv")
    columns = ["bfs_nr", "n_listings", "n_price_m2", "median_price_m2", "median_rent", "income_mean", "enough_data"]
    gdf = muni.merge(summary[columns], on="bfs_nr", how="left")
    gdf["n_listings"] = gdf["n_listings"].fillna(0).astype(int)
    gdf["enough_data"] = gdf["enough_data"].fillna(False).astype(bool)
    cantons = muni.dissolve(by="canton_nr")
    return gdf, cantons


def spearman_table(summary):
    """Spearman correlation of the municipality median price per m2 with density and mean taxable income."""
    rows = []
    for column, label in (("density", "population density (inhabitants per km2)"), ("income_mean", "mean taxable income (CHF per taxpayer, 2022)")):
        pair = summary[["median_price_m2", column]].dropna()
        rho, p = spearmanr(pair["median_price_m2"], pair[column])
        rows.append({"variable": label, "n_municipalities": len(pair), "spearman_rho": round(rho, 3), "p_value": p})
    return pd.DataFrame(rows)


def plot_scatter(summary, table):
    """Scatter of mean taxable income vs median price per m2; point area = number of listings."""
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter(summary["income_mean"], summary["median_price_m2"], s=2.5 * summary["n_listings"], alpha=0.5,
               color="#2b6a99", edgecolor="white", linewidth=0.4)
    for bfs, name in ((261, "Zürich"), (1061, "Luzern")):
        row = summary[summary["bfs_nr"] == bfs].iloc[0]
        ax.annotate(name, (row["income_mean"], row["median_price_m2"]), xytext=(10, 8), textcoords="offset points",
                    fontsize=10, fontweight="bold", arrowprops={"arrowstyle": "-", "color": "black", "linewidth": 0.7})
    income_row = table[table["variable"].str.startswith("mean")].iloc[0]
    ax.text(0.03, 0.96, f"Spearman ρ = {income_row['spearman_rho']:.2f}\nn = {int(income_row['n_municipalities'])} municipalities",
            transform=ax.transAxes, va="top", fontsize=10, bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": "#bbbbbb"})
    handles = [ax.scatter([], [], s=2.5 * n, color="#2b6a99", alpha=0.5, edgecolor="white", label=f"{n} listings") for n in (10, 50, 200)]
    ax.legend(handles=handles, title="Point area =\nnumber of listings", loc="center left", bbox_to_anchor=(1.01, 0.5),
              frameon=True, labelspacing=2.2, borderpad=1.2, handletextpad=1.5)
    ax.set_xlabel("Mean taxable income per taxpayer, 2022 (CHF per year)")
    ax.set_ylabel("Median price per m² (CHF per m² per month)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(True, color="#e5e5e5")
    fig.savefig(FIGURES_DIR / "rq3_income_scatter.png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def class_colors(values, cmap, k=5):
    """Quantile classes: per-value colour and legend labels (lower to upper class limit)."""
    bins = pd.qcut(values, k, duplicates="drop")
    levels = len(bins.cat.categories)
    palette = [to_hex(c) for c in plt.get_cmap(cmap)(np.linspace(0.2, 0.95, levels))]
    lows = [values.min()] + [iv.right for iv in bins.cat.categories[:-1]]
    highs = [iv.right for iv in bins.cat.categories]
    labels = [f"{lo:,.0f} – {hi:,.0f}" if highs[-1] > 100 else f"{lo:.1f} – {hi:.1f}" for lo, hi in zip(lows, highs)]
    return bins.cat.codes.map(dict(enumerate(palette))), palette, labels


def draw_borders(ax, gdf, cantons, colors):
    """Fill the municipalities with the given colours and draw municipality and canton borders."""
    gdf.plot(ax=ax, color=colors, **BORDER)
    cantons.boundary.plot(ax=ax, **CANTON_BORDER)
    ax.set_axis_off()


def class_map(ax, gdf, cantons, column, valid, cmap, legend_title, grey_label=INSUFFICIENT, k=5):
    """Quantile-class choropleth; municipalities without a valid value are light grey."""
    colors = pd.Series([GREY] * len(gdf), index=gdf.index, dtype=object)
    class_color, palette, labels = class_colors(gdf.loc[valid, column], cmap, k)
    colors[valid] = class_color
    draw_borders(ax, gdf, cantons, colors.tolist())
    handles = [Patch(facecolor=c, edgecolor="#8a8a8a", linewidth=0.3, label=lab) for c, lab in zip(palette, labels)]
    handles.append(Patch(facecolor=GREY, edgecolor="#8a8a8a", linewidth=0.3, label=grey_label))
    ax.legend(handles=handles, title=legend_title, loc="upper center", bbox_to_anchor=(0.5, 0.03), ncol=3, frameon=False,
              fontsize=8.5, title_fontsize=9.5, columnspacing=1.5)


def count_map(ax, gdf, cantons):
    """Number of listings per municipality in fixed classes (0 is its own class)."""
    edges, labels = [-1, 0, 4, 19, 99, np.inf], ["0", "1 – 4", "5 – 19", "20 – 99", "100 or more"]
    codes = pd.cut(gdf["n_listings"], edges, labels=False)
    palette = [to_hex(c) for c in plt.get_cmap("Greens")(np.linspace(0.08, 0.95, len(labels)))]
    draw_borders(ax, gdf, cantons, [palette[c] for c in codes])
    handles = [Patch(facecolor=c, edgecolor="#8a8a8a", linewidth=0.3, label=lab) for c, lab in zip(palette, labels)]
    ax.legend(handles=handles, title="Listings per municipality (number)", loc="upper center", bbox_to_anchor=(0.5, 0.03), ncol=5,
              frameon=False, fontsize=8.5, title_fontsize=9.5, columnspacing=1.5)


def density_map(ax, gdf, cantons, valid):
    """Population density with a logarithmic colour scale; municipalities without enough data are light grey."""
    values = gdf.loc[valid, "density"]
    norm = LogNorm(vmin=values.min(), vmax=values.max())
    cmap = LinearSegmentedColormap.from_list("pubu", plt.get_cmap("PuBu")(np.linspace(0.15, 0.95, 256)))
    colors = pd.Series([GREY] * len(gdf), index=gdf.index, dtype=object)
    colors[valid] = [to_hex(cmap(norm(v))) for v in values]
    draw_borders(ax, gdf, cantons, colors.tolist())
    bar = plt.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, orientation="horizontal", fraction=0.035, pad=0.03, shrink=0.55)
    bar.set_label("Population density (inhabitants per km², log scale)", fontsize=9)
    bar.ax.tick_params(labelsize=8)
    ax.legend(handles=[Patch(facecolor=GREY, edgecolor="#8a8a8a", linewidth=0.3, label=INSUFFICIENT)], loc="upper center",
              bbox_to_anchor=(0.5, -0.17), frameon=False, fontsize=8.5)


def add_scale_bar(ax, gdf, km=50):
    """Simple scale bar in the lower right corner (coordinates are metres in EPSG:2056)."""
    minx, miny, maxx, maxy = gdf.total_bounds
    x0, y0 = maxx - (km + 20) * 1000, miny + 8000
    ax.plot([x0, x0 + km * 1000], [y0, y0], color="black", linewidth=2)
    ax.text(x0 + km * 500, y0 + 4000, f"{km} km", ha="center", va="bottom", fontsize=8)


def main():
    FIGURES_DIR.mkdir(exist_ok=True)
    gdf, cantons = load_geodata()
    summary = gdf[gdf["enough_data"]].copy()

    table = spearman_table(summary)
    table.to_csv(TABLES_DIR / "rq3_spearman.csv", index=False)
    print(f"municipalities in Switzerland: {len(gdf)} | with listings: {int((gdf['n_listings'] > 0).sum())} | enough data: {len(summary)}")
    print("\n=== Spearman (median price per m2, municipalities with enough data)\n", table.to_string(index=False))
    plot_scatter(summary.dropna(subset=["income_mean"]), table)

    price_valid = gdf["enough_data"] & gdf["median_price_m2"].notna()
    fig, ax = plt.subplots(figsize=(13, 8.5))
    class_map(ax, gdf, cantons, "median_price_m2", price_valid, "YlOrRd", "Median price per m²\n(CHF per m² per month, quantile classes)")
    add_scale_bar(ax, gdf)
    ax.set_title("Median advertised rent per m² by municipality", fontsize=13)
    fig.savefig(FIGURES_DIR / "rq3_map_price_m2.png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(16, 13))
    class_map(axes[0, 0], gdf, cantons, "median_price_m2", price_valid, "YlOrRd", "Median price per m²\n(CHF per m² per month)")
    axes[0, 0].set_title("a) Median price per m²", fontsize=12)
    income_valid = price_valid & gdf["income_mean"].notna()
    class_map(axes[0, 1], gdf, cantons, "income_mean", income_valid, "BuPu", "Mean taxable income per taxpayer\n(CHF per year, 2022)",
              grey_label=INSUFFICIENT[:-1] + ",\nor no 2022 income value)")
    axes[0, 1].set_title("b) Mean taxable income", fontsize=12)
    density_map(axes[1, 0], gdf, cantons, gdf["enough_data"])
    axes[1, 0].set_title("c) Population density", fontsize=12)
    count_map(axes[1, 1], gdf, cantons)
    axes[1, 1].set_title("d) Number of listings", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "rq3_maps_panel.png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)

    n_inc = int(table.loc[table["variable"].str.startswith("mean"), "n_municipalities"].iloc[0])
    write_caption("rq3_income_scatter.png",
                  f"Mean taxable income per taxpayer (ESTV, tax year 2022, CHF per year) against the median advertised rent per m² "
                  f"(CHF per m² per month) for {n_inc} Swiss municipalities with at least {MIN_LISTINGS_PER_MUNICIPALITY} listings that have a "
                  f"known living area (Flatfox, November 2026). The area of each point is proportional to the number of listings; the cities "
                  f"of Zürich and Luzern are labelled. Spearman correlations are in tables/rq3_spearman.csv.")
    write_caption("rq3_map_price_m2.png",
                  f"Median advertised rent per m² (CHF per m² per month) by municipality, in five quantile classes. Thin grey lines are "
                  f"municipality borders (swissBOUNDARIES3D 2026), dark lines canton borders. Light grey municipalities have insufficient "
                  f"data (fewer than {MIN_LISTINGS_PER_MUNICIPALITY} listings with known living area): {int((~price_valid).sum())} of {len(gdf)}. "
                  f"Municipalities on Lake Geneva include their share of the lake in the official boundary data (wedge shapes); "
                  f"the other lakes are not part of any municipality.")
    write_caption("rq3_maps_panel.png",
                  f"Spatial pattern of the municipality characteristics used for RQ3: a) median advertised rent per m² (CHF per m² per month, "
                  f"quantile classes), b) mean taxable income per taxpayer (CHF per year, 2022, quantile classes), c) population density "
                  f"(inhabitants per km², logarithmic colour scale), d) number of Flatfox listings. Panels a to c show only municipalities "
                  f"with at least {MIN_LISTINGS_PER_MUNICIPALITY} listings that have a known living area; the others are light grey. "
                  f"Dark lines are canton borders. Municipalities merged after 2022 have no income value.")


if __name__ == "__main__":
    main()
