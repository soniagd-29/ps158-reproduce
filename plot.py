"""
Median (or mean) family net worth by education of the reference person,
1989-2025, in 2025 dollars, with a second panel for the ratio between the two
groups. Drawn as a black-and-white academic journal figure: markers and line
styles instead of color, labeled axes, a numbered caption underneath.

Reads data/wealth_by_education.csv (made by get_data.py) and, if present,
data/confidence_intervals.csv (made by check.py) for 95% intervals on the ratio
in the first and last survey.

Writes:
  figure.png                          the main figure: medians, families with children
  figures/{stat}_{families}.png/.pdf  all four versions (median/mean x with children/all)

Usage:
  python3 plot.py
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "wealth_by_education.csv"
CI = ROOT / "data" / "confidence_intervals.csv"
FIG_DIR = ROOT / "figures"
MAIN = ("median", "with children")

SERIES = {  # group -> (label, line style, marker, marker face)
    "College degree": ("Bachelor's degree or more", "-", "o", "black"),
    "HS or less": ("High school diploma or less", "--", "s", "white"),
}
WHO = {
    "with children": "families with a child of the reference person living at home",
    "all": "all families",
}


def draw(df: pd.DataFrame, ci: pd.DataFrame | None, stat: str, families: str, number: int) -> plt.Figure:
    d = df[df.families == families]
    wide = d.pivot(index="year", columns="group", values=f"{stat}_networth") / 1000
    ratio = wide["College degree"] / wide["HS or less"]
    years = wide.index.to_numpy()
    dollar_year = int(d.dollar_year.iloc[0])

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(6.5, 6.6), sharex=True, gridspec_kw={"height_ratios": [2, 1], "hspace": 0.15}
    )

    # (a) net worth by education
    for group, (label, ls, marker, face) in SERIES.items():
        ax1.plot(years, wide[group], color="black", lw=1.2, ls=ls, marker=marker, ms=5,
                 markerfacecolor=face, markeredgecolor="black", label=label)
    ax1.set_ylim(0, None)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.set_ylabel(f"{stat.capitalize()} net worth\n(thousands of {dollar_year} dollars)")
    ax1.legend(loc="upper left", frameon=False)
    ax1.text(-0.13, 1.0, "(a)", transform=ax1.transAxes, va="top", weight="bold")

    # (b) ratio
    ax2.plot(years, ratio, color="black", lw=1.2, marker="D", ms=4.5, markerfacecolor="white")
    has_ci = False
    if ci is not None and stat == "median":
        r = ci[(ci.families == families) & (ci.statistic == "Ratio")]
        if not r.empty:
            ax2.errorbar(r.year, r.estimate, yerr=[r.estimate - r.low, r.high - r.estimate],
                         fmt="none", ecolor="black", elinewidth=0.9, capsize=3)
            has_ci = True
    ax2.set_ylim(0, None)
    ax2.yaxis.set_major_locator(mticker.MaxNLocator(5, integer=True))
    ax2.set_ylabel("Ratio, bachelor's\nto high school")
    ax2.text(-0.13, 1.0, "(b)", transform=ax2.transAxes, va="top", weight="bold")

    for ax in (ax1, ax2):
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(direction="out", length=3)
    ax2.set_xticks(years)
    ax2.set_xlabel("Survey year")

    caption = (
        f"Figure {number}. {stat.capitalize()} net worth by education of the family's reference person, "
        f"1989–{years[-1]}, {WHO[families]}. "
        f"Panel (a): {stat} net worth in thousands of {dollar_year} dollars. "
        f"Panel (b): ratio of the two {stat}s"
        + (f"; bars show 95% confidence intervals in {years[0]} and {years[-1]} "
           "(999 replicate weights and 5 implicates)." if has_ci else ".")
        + "\nNote: Weighted with the survey weights, pooling all five implicates. Dollar values were "
        "inflation-adjusted by the Federal Reserve. 'Some college' families are not shown.\n"
        "Source: Board of Governors of the Federal Reserve System, Survey of Consumer Finances, "
        "Summary Extract Public Data, 1989–2025."
    )
    caption = "\n".join(textwrap.fill(p, 104) for p in caption.split("\n"))
    fig.text(0.04, 0.015, caption, fontsize=7.6, va="bottom", ha="left")
    fig.subplots_adjust(left=0.17, right=0.97, top=0.97, bottom=0.23)
    return fig


def main() -> None:
    plt.rcParams.update({"font.family": "serif", "font.size": 9.5, "axes.linewidth": 0.8})
    df = pd.read_csv(DATA)
    ci = pd.read_csv(CI) if CI.exists() else None
    if ci is None:
        print("No data/confidence_intervals.csv (run check.py): drawing without intervals.")

    FIG_DIR.mkdir(exist_ok=True)
    for stat in ("median", "mean"):
        for families in WHO:
            is_main = (stat, families) == MAIN
            fig = draw(df, ci, stat, families, number=1)
            stem = f"{stat}_{families.replace(' ', '_')}"
            for ext in ("png", "pdf"):
                fig.savefig(FIG_DIR / f"{stem}.{ext}", dpi=300 if ext == "png" else None, facecolor="white")
            if is_main:
                fig.savefig(ROOT / "figure.png", dpi=300, facecolor="white")
            plt.close(fig)
            print(f"Wrote figures/{stem}.png/.pdf" + ("  and figure.png" if is_main else ""))


if __name__ == "__main__":
    main()
