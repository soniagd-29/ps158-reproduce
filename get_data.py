"""
Download the Federal Reserve's Survey of Consumer Finances (SCF) Summary Extract
Public Data for every survey from 1989 to 2025, and compute net worth by the
education of the family's reference person.

Output: data/wealth_by_education.csv
        one row per families definition x survey year x education group.

Decisions:
  * Source: Summary Extract Public Data, CSV version, scfp{YEAR}excel.zip.
    The Fed re-released every year in 2025 dollars when the 2025 survey came out
    (Oct 9, 2026). Inflation adjustment is the Fed's (R-CPI-U-RS); nothing is
    re-deflated here.
  * Families: two definitions, both written to the CSV.
      "with children" = families with a child of the reference person or
                        spouse/partner living at home (KIDS > 0). This is what
                        the lab's dry run used, and what "parents" means.
      "all"           = all families (the SCF's "primary economic unit").
  * Education: EDCL, the education of the reference person (head).
      1 = no HS diploma, 2 = HS diploma/GED, 3 = some college/associate,
      4 = bachelor's or more.
    "HS or less" = EDCL 1-2; "College degree" = EDCL 4. Some college is kept as
    its own group (not in either side of the gap).
  * Weights: every statistic uses WGT. Each family appears 5 times (5 imputation
    "implicates"), and each copy carries one fifth of the family's weight, so
    statistics are computed on all 5 implicates pooled. This is how the Fed's
    published tables are computed: it reproduces them exactly (see the check).

Also downloads, for the checks:
  * the Fed's historical tables (public data, 2025 dollars), used here to check
    the numbers against Table 4;
  * the 1989 and 2025 replicate weights, used by check.py for 95% confidence
    intervals, and the Fed's published 2025 standard errors to check them;
  * the Census Bureau's SIPP wealth tables for 2024, a second source compared
    in check.py.

Usage:
  python3 get_data.py
"""

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

YEARS = list(range(1989, 2026, 3))  # 1989, 1992, ..., 2022, 2025
LATEST = YEARS[-1]
BASE_URL = "https://www.federalreserve.gov/econres/files/"
DOLLAR_YEAR = 2025

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
OUT_CSV = ROOT / "data" / "wealth_by_education.csv"
HIST_TABLES = RAW_DIR / "scf2025_tables_public_real_historical.xlsx"
# The Fed's published standard errors for its 2022 and 2025 tables.
SE_TABLES = RAW_DIR / f"{LATEST}_tables1_2_stderrs.xlsx"
# Replicate weights for the first and latest surveys (for 95% confidence
# intervals in check.py). The Fed names the 1989 file with a two-digit year.
REPLICATE_WEIGHTS = {1989: "scf89rw1s.zip", LATEST: f"scf{LATEST}rw1s.zip"}
# A second source: Census Bureau, SIPP, Wealth of Households: 2024, Table 1.
SIPP_URL = ("https://www2.census.gov/programs-surveys/demo/tables/wealth/2023/"
            "wealth-asset-ownership/wealth_tables_dy2024.xlsx")

# Groups used in the analysis (name -> EDCL codes). The four single categories
# are kept too so they can be checked against the Fed's published tables.
GROUPS = {
    "All families": [1, 2, 3, 4],
    "HS or less": [1, 2],
    "Some college": [3],
    "College degree": [4],
    "No HS diploma": [1],
    "HS diploma/GED": [2],
}
FAMILIES = {
    "with children": lambda df: df["kids"] > 0,
    "all": lambda df: df["kids"] >= 0,
}
# Row labels in the Fed's Table 4 for each of our single-category groups.
TABLE4_ROWS = {
    "All families": "All families",
    "No HS diploma": "No high school diploma",
    "HS diploma/GED": "High school diploma",
    "Some college": "Some college",
    "College degree": "College degree",
}


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have   {dest.name}")
        return
    print(f"  fetch  {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read()
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"\nCould not download {url}\n  {e}\n"
            "If this is an SSL certificate error on a python.org install of Python,\n"
            "run 'Install Certificates.command' in your Python folder, or download\n"
            f"the file in a browser and save it as {dest}"
        )
    dest.write_bytes(data)


def download_all() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading SCF summary extracts (CSV) ...")
    for y in YEARS:
        download(f"{BASE_URL}scfp{y}excel.zip", RAW_DIR / f"scfp{y}excel.zip")
    print("Downloading files used by check.py ...")
    download(f"{BASE_URL}{HIST_TABLES.name}", HIST_TABLES)
    download(f"{BASE_URL}{SE_TABLES.name}", SE_TABLES)
    for name in REPLICATE_WEIGHTS.values():
        download(f"{BASE_URL}{name}", RAW_DIR / name)
    download(SIPP_URL, RAW_DIR / SIPP_URL.rsplit("/", 1)[1])


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def read_extract(year: int) -> pd.DataFrame:
    path = RAW_DIR / f"scfp{year}excel.zip"
    with zipfile.ZipFile(path) as zf:
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(csvs) != 1:
            sys.exit(f"{path.name}: expected one CSV inside, found {csvs}")
        with zf.open(csvs[0]) as f:
            df = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), low_memory=False)
    df.columns = [c.strip().lower() for c in df.columns]
    # The 1989 extract names its ID variables X1/XX1; later years use Y1/YY1.
    df = df.rename(columns={"x1": "y1", "xx1": "yy1"})

    need = {"yy1", "y1", "wgt", "networth", "edcl", "kids"}
    missing = need - set(df.columns)
    if missing:
        sys.exit(f"{path.name}: missing columns {sorted(missing)}")

    df = df[sorted(need)].copy()
    # Y1 = YY1 * 10 + implicate number (1-5)
    df["implicate"] = df["y1"] - 10 * df["yy1"]
    bad = ~df["implicate"].isin([1, 2, 3, 4, 5])
    if bad.any():
        sys.exit(f"{path.name}: {bad.sum()} rows with an implicate number outside 1-5")
    per_family = df.groupby("yy1")["implicate"].nunique()
    if (per_family != 5).any():
        sys.exit(f"{path.name}: some families do not have exactly 5 implicates")
    df["year"] = year
    return df


# --------------------------------------------------------------------------
# Weighted statistics
# --------------------------------------------------------------------------
def weighted_median(x: np.ndarray, w: np.ndarray) -> float:
    """Value where cumulative weight first reaches half the total.
    If it lands exactly on 50%, average that value and the next one."""
    order = np.argsort(x, kind="mergesort")
    x, w = x[order], w[order]
    cw = np.cumsum(w)
    half = cw[-1] / 2.0
    i = int(np.searchsorted(cw, half, side="left"))
    if np.isclose(cw[i], half) and i + 1 < len(x):
        return float((x[i] + x[i + 1]) / 2.0)
    return float(x[i])


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for families, keep in FAMILIES.items():
        fdf = df[keep(df)]
        for year, ydf in fdf.groupby("year"):
            total_w = ydf["wgt"].sum()
            for group, codes in GROUPS.items():
                g = ydf[ydf["edcl"].isin(codes)]
                x = g["networth"].to_numpy(float)
                w = g["wgt"].to_numpy(float)
                rows.append(
                    {
                        "families": families,
                        "year": year,
                        "group": group,
                        "median_networth": weighted_median(x, w),
                        "mean_networth": float(np.average(x, weights=w)),
                        "share_of_families": w.sum() / total_w,
                        "n_families": g["yy1"].nunique(),  # survey respondents, not weighted
                    }
                )
    out = pd.DataFrame(rows)
    out["dollar_year"] = DOLLAR_YEAR
    return out


# --------------------------------------------------------------------------
# Check against the Fed's own published table
# --------------------------------------------------------------------------
def read_table4() -> pd.DataFrame:
    """Median and mean net worth by education from Table 4 of the Fed's
    historical tables (public data, thousands of 2025 dollars)."""
    raw = pd.read_excel(HIST_TABLES, sheet_name="Table 4", header=None)
    year_row = raw.iloc[2]
    year_cols = {int(v): c for c, v in year_row.items() if isinstance(v, (int, float)) and not pd.isna(v)}
    rows = []
    labels = raw[0].astype(str).str.strip()
    for group, label in TABLE4_ROWS.items():
        r = raw[labels == label]
        if len(r) != 1:
            sys.exit(f"Table 4: expected one row labelled {label!r}, found {len(r)}")
        r = r.iloc[0]
        for year, c in year_cols.items():
            rows.append({"year": year, "group": group, "pub_median": r[c], "pub_mean": r[c + 1]})
    return pd.DataFrame(rows)


def check_against_published(out: pd.DataFrame) -> None:
    pub = read_table4()
    ours = out[out.families == "all"].merge(pub, on=["year", "group"])
    ours["d_median"] = ours.median_networth / 1000 - ours.pub_median
    ours["d_mean"] = ours.mean_networth / 1000 - ours.pub_mean
    print(f"\nCheck vs. the Fed's historical Table 4 (public data, thousands of {DOLLAR_YEAR} $):")
    print(f"  compared {len(ours)} medians and {len(ours)} means "
          f"({ours.year.nunique()} surveys x {ours.group.nunique()} groups)")
    for stat in ("median", "mean"):
        worst = ours.loc[ours[f"d_{stat}"].abs().idxmax()]
        print(f"  largest {stat} difference: {worst[f'd_{stat}']:+.3f}k "
              f"({int(worst.year)}, {worst.group})")
    if ours[["d_median", "d_mean"]].abs().max().max() > 0.01:
        print("  WARNING: some values differ from Table 4 by more than $10.")
    else:
        print("  All match Table 4 to within rounding ($10).")


def main() -> None:
    download_all()

    print("\nReading extracts ...")
    frames = []
    for y in YEARS:
        df = read_extract(y)
        print(f"  {y}: {df.yy1.nunique():>6,} families")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    out = summarize(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV.relative_to(ROOT)}  ({len(out)} rows)")

    check_against_published(out)

    for families in FAMILIES:
        wide = out[out.families == families].pivot(index="year", columns="group", values="median_networth")
        gap = pd.DataFrame(
            {
                "HS or less": wide["HS or less"] / 1000,
                "College degree": wide["College degree"] / 1000,
                "Ratio": wide["College degree"] / wide["HS or less"],
            }
        )
        print(f"\nMedian net worth, {families} families, thousands of {DOLLAR_YEAR} dollars:")
        print(gap.round(1).to_string())


if __name__ == "__main__":
    main()
