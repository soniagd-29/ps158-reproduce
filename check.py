"""
Checks on the numbers behind the figure (run get_data.py first).

1. 95% confidence intervals for the 1989 and 2025 medians and for the
   college / HS-or-less ratio, the way the Fed recommends
   (federalreserve.gov/econres/files/Standard_Error_Documentation.pdf):
     total variance = sampling variance + (1 + 1/5) x imputation variance
   and compare one standard error with the one the Fed publishes;
   * sampling variance: recompute the statistic on the first implicate with each
     of the 999 bootstrap replicate weights (wt1b{k} x mm{k}) and take the
     variance of those 999 estimates;
   * imputation variance: the variance of the statistic across the 5 implicates.
2. A second source: the Census Bureau's Survey of Income and Program
   Participation (SIPP), Wealth of Households: 2024, Table 1.

The check against the Fed's own published tables (Table 4) is in get_data.py.

Usage:
  python3 check.py
"""

import zipfile

import numpy as np
import pandas as pd

from get_data import RAW_DIR, REPLICATE_WEIGHTS, SE_TABLES, SIPP_URL, read_extract, weighted_median

GROUPS = {"College degree": [4], "HS or less": [1, 2]}
FAMILIES = {
    "with children": lambda df: df["kids"] > 0,
    "all": lambda df: df["kids"] >= 0,
}
Z = 1.96


def read_replicate_weights(year: int) -> pd.DataFrame:
    """Replicate weights (wt1b{k} x mm{k}) for each family, keyed on y1 of the
    first implicate. A family not drawn in replicate k has a missing weight: 0."""
    path = RAW_DIR / REPLICATE_WEIGHTS[year]
    with zipfile.ZipFile(path) as zf:
        (name,) = [n for n in zf.namelist() if n.lower().endswith(".dta")]
        with zf.open(name) as f:
            rw = pd.read_stata(f)
    rw.columns = [c.lower() for c in rw.columns]
    rw = rw.rename(columns={"x1": "y1", "xx1": "yy1"})
    reps = sorted(int(c[4:]) for c in rw.columns if c.startswith("wt1b"))
    w = rw[[f"wt1b{k}" for k in reps]].fillna(0).to_numpy(float)
    if f"mm{reps[0]}" in rw.columns:
        w = w * rw[[f"mm{k}" for k in reps]].fillna(0).to_numpy(float)
    return pd.DataFrame(w, index=rw["y1"].astype(int).to_numpy())


def weighted_median_many(x: np.ndarray, W: np.ndarray) -> np.ndarray:
    """Weighted median of x for every column of weights W at once."""
    order = np.argsort(x, kind="mergesort")
    x, W = x[order], W[order]
    cw = np.cumsum(W, axis=0)
    idx = (cw >= cw[-1] / 2.0).argmax(axis=0)
    return x[idx]


def medians(df: pd.DataFrame, rw: pd.DataFrame) -> dict:
    """For each group: the pooled point estimate, the 5 implicate estimates,
    and the 999 replicate estimates (first implicate only)."""
    imp1 = df[df.implicate == 1]
    W = rw.reindex(imp1["y1"].to_numpy()).fillna(0).to_numpy()
    out = {}
    for group, codes in GROUPS.items():
        g = df[df.edcl.isin(codes)]
        g1 = imp1.edcl.isin(codes).to_numpy()
        out[group] = {
            "point": weighted_median(g.networth.to_numpy(float), g.wgt.to_numpy(float)),
            "implicates": np.array([
                weighted_median(s.networth.to_numpy(float), s.wgt.to_numpy(float))
                for _, s in g.groupby("implicate")
            ]),
            "replicates": weighted_median_many(imp1.networth.to_numpy(float)[g1], W[g1]),
        }
    a, b = out["College degree"], out["HS or less"]
    out["Ratio"] = {k: a[k] / b[k] for k in ("point", "implicates", "replicates")}
    return out


def std_error(est: dict) -> float:
    sampling = np.var(est["replicates"], ddof=1)
    imputation = np.var(est["implicates"], ddof=1)
    return float(np.sqrt(sampling + (1 + 1 / 5) * imputation))


def confidence_intervals() -> pd.DataFrame:
    rows = []
    for year in REPLICATE_WEIGHTS:
        df = read_extract(year)
        rw = read_replicate_weights(year)
        if not df[df.implicate == 1].y1.isin(rw.index).all():
            raise SystemExit(f"{year}: some families have no replicate weights")
        for families, keep in FAMILIES.items():
            for stat, est in medians(df[keep(df)], rw).items():
                se = std_error(est)
                rows.append({"families": families, "year": year, "statistic": stat,
                             "estimate": est["point"], "se": se})
    ci = pd.DataFrame(rows)
    ci["low"] = ci.estimate - Z * ci.se
    ci["high"] = ci.estimate + Z * ci.se
    return ci


def print_intervals(ci: pd.DataFrame) -> None:
    print("\n95% confidence intervals (medians in thousands of 2025 $):")
    for families in FAMILIES:
        print(f"\n  {families} families")
        for _, r in ci[ci.families == families].iterrows():
            k = 1 if r.statistic == "Ratio" else 1000
            unit = "x" if r.statistic == "Ratio" else "k"
            print(f"    {r.year}  {r.statistic:<15} {r.estimate / k:7.1f}{unit}"
                  f"   [{r.low / k:6.1f}, {r.high / k:6.1f}]")
        rat = ci[(ci.families == families) & (ci.statistic == "Ratio")].set_index("year")
        first, last = rat.index.min(), rat.index.max()
        diff = rat.estimate[last] - rat.estimate[first]
        se = np.sqrt(rat.se[last] ** 2 + rat.se[first] ** 2)  # independent samples
        print(f"    change in ratio {first}->{last}: {diff:+.1f}x  "
              f"[{diff - Z * se:+.1f}, {diff + Z * se:+.1f}]")


def compare_published_se(ci: pd.DataFrame) -> None:
    """Our standard error for the 2025 college median (all families) next to the
    one the Fed publishes. In the Fed's Table 2 the education labels sit one row
    below their numbers: the 'Education of reference person' heading row holds
    the no-diploma numbers, so college is the fourth row from the heading."""
    t = pd.read_excel(SE_TABLES, sheet_name="Table 2", header=None)
    head = t[t[0].astype(str).str.strip() == "Education of reference person"].index[0]
    row = t.loc[head + 3]
    pub_median, pub_se = row[3], row[4]  # 2025 median and its standard error
    ours = ci[(ci.families == "all") & (ci.year == 2025) & (ci.statistic == "College degree")].iloc[0]
    print("\nCheck vs. the Fed's published standard error, 2025 college median, all families:")
    print(f"  ours: {ours.estimate / 1000:.1f}k, s.e. {ours.se / 1000:.1f}k   "
          f"Fed (internal data): {pub_median:.1f}k, s.e. {pub_se:.1f}k")


def compare_sipp() -> None:
    """SIPP 2024 medians by the highest education of anyone in the household,
    next to SCF 2025 medians by the education of the reference person."""
    path = RAW_DIR / SIPP_URL.rsplit("/", 1)[1]
    t = pd.read_excel(path, sheet_name="Table 1", header=None)
    labels = t[0].astype(str).str.strip()
    start = labels[labels.str.startswith("Highest Level of Educational Attainment")].index[0]
    sipp = {labels[i]: t.loc[i, 1] for i in range(start + 1, start + 7)}
    sipp_total = t.loc[labels[labels == "Total"].index[0], 1]

    scf = pd.read_csv(RAW_DIR.parent / "wealth_by_education.csv")
    scf = scf[(scf.families == "all") & (scf.year == 2025)].set_index("group").median_networth

    print("\nSecond source: Census SIPP 2024 vs. SCF 2025, median net worth (thousands):")
    print("  SIPP groups households by the most-educated member; SCF by the reference person.")
    print("  SIPP is in 2024 dollars, SCF in 2025 dollars.")
    print(f"  {'':34s} {'SIPP 2024':>10} {'SCF 2025':>10}")
    print(f"  {'All':34s} {sipp_total / 1000:10.1f} {scf['All families'] / 1000:10.1f}")
    pairs = [("No high school diploma", "No HS diploma"),
             ("High school graduate only", "HS diploma/GED"),
             ("Some college, no degree", "Some college"),
             ("Associate's degree", None),
             ("Bachelor's degree", "College degree"),
             ("Graduate or professional degree", None)]
    notes = {"Some college": "  SCF: some college incl. associate's",
             "College degree": "  SCF: bachelor's or more"}
    for s_label, scf_group in pairs:
        right = f"{scf[scf_group] / 1000:10.1f}{notes.get(scf_group, '')}" if scf_group else ""
        print(f"  {s_label:34s} {sipp[s_label] / 1000:10.1f} {right}")


def main() -> None:
    ci = confidence_intervals()
    out = RAW_DIR.parent / "confidence_intervals.csv"
    ci.to_csv(out, index=False)
    print_intervals(ci)
    print(f"\nWrote {out.relative_to(RAW_DIR.parent.parent)}")
    compare_published_se(ci)
    compare_sipp()


if __name__ == "__main__":
    main()
