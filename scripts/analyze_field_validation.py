#!/usr/bin/env python3
"""
Analyze SandStories field validation results:
- Load field_validation.csv (produced by evaluate_session.py)
- Load conditions.json and optional completeness_rating.json from each session folder
- Perform Kruskal-Wallis non-parametric tests on the 5 metrics across independent variables:
  * Sensor Height (60cm vs 80cm vs 100cm)
  * Lighting (sunlight vs shade vs overcast)
  * Surface Type (dry_loose vs wet_compacted)
- Generate a Markdown report detailing the findings.

Usage:
  python scripts/analyze_field_validation.py --csv field_validation.csv --sessions-dir /path/to/sessions --out stats_report.md
"""

import argparse
import csv
import json
import sys
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze SandStories field validation metrics")
    parser.add_argument("--csv", type=Path, required=True, help="Path to field_validation.csv")
    parser.add_argument("--sessions-dir", type=Path, required=True, help="Directory containing session folders")
    parser.add_argument("--out", type=Path, default=Path("stats_report.md"), help="Path to write stats_report.md")
    return parser.parse_args()

def run_kruskal(groups):
    """Safely run Kruskal-Wallis test. Returns (H-statistic, p-value)."""
    # Filter out empty groups
    active_groups = [g for g in groups if len(g) > 0]
    if len(active_groups) < 2:
        return float("nan"), float("nan")
        
    # Check if all values in all groups are identical
    all_vals = []
    for g in active_groups:
        all_vals.extend(g)
    if len(set(all_vals)) <= 1:
        return 0.0, 1.0
        
    try:
        from scipy import stats
        h_stat, p_val = stats.kruskal(*active_groups)
        return h_stat, p_val
    except ImportError:
        # Fallback if scipy is not installed (calculate a crude placeholder or return nan)
        return float("nan"), float("nan")
    except Exception:
        return float("nan"), float("nan")

def main():
    args = parse_args()
    
    if not args.csv.is_file():
        print(f"Error: CSV file not found: {args.csv}", file=sys.stderr)
        return 1
    if not args.sessions_dir.is_dir():
        print(f"Error: Sessions directory not found: {args.sessions_dir}", file=sys.stderr)
        return 1
        
    # Check if scipy is available
    has_scipy = True
    try:
        from scipy import stats
    except ImportError:
        has_scipy = False
        print("Warning: scipy not installed. Kruskal-Wallis p-values will be skipped. Run 'pip install scipy' to enable.", file=sys.stderr)
        
    rows = []
    with args.csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            
    if not rows:
        print("Error: CSV file is empty", file=sys.stderr)
        return 1
        
    # Load conditions and rating sidecars
    data = []
    for r in rows:
        name = r["sessionName"]
        folder = args.sessions_dir / name
        if not folder.is_dir():
            # Try matching lower/upper or direct folder
            print(f"Warning: Session folder {name} not found in {args.sessions_dir}. Skipping sidecar merge.")
            continue
            
        cond_path = folder / "conditions.json"
        rate_path = folder / "completeness_rating.json"
        
        # Default conditions if missing
        cond = {
            "sensorHeightCm": "Unknown",
            "lighting": "Unknown",
            "surfaceType": "Unknown",
            "replicate": 1
        }
        if cond_path.is_file():
            try:
                with cond_path.open("r", encoding="utf-8") as cf:
                    cond.update(json.load(cf))
            except Exception as e:
                print(f"Warning: Failed to parse {cond_path}: {e}")
                
        rating = None
        if rate_path.is_file():
            try:
                with rate_path.open("r", encoding="utf-8") as rf:
                    rating_data = json.load(rf)
                    rating = float(rating_data.get("completenessRating", 0.0))
            except Exception:
                pass
                
        metrics = {
            "depthRetention": float(r.get("depthRetention", 0.0)),
            "objectDetectionConfidence": float(r.get("objectDetectionConfidence", 0.0)),
            "gestureContinuity": float(r.get("gestureContinuity", 0.0)),
            "boundaryDetection": float(r.get("boundaryDetection", 0.0)),
            "audioContinuity": float(r.get("audioContinuity", 0.0))
        }
        if rating is not None:
            metrics["completenessRating"] = rating
            
        data.append({
            "name": name,
            "conditions": cond,
            "metrics": metrics
        })
        
    if not data:
        print("Error: No session folders were successfully merged with CSV rows.", file=sys.stderr)
        return 1
        
    # Independent variables
    ivs = ["sensorHeightCm", "lighting", "surfaceType"]
    metrics_keys = ["depthRetention", "objectDetectionConfidence", "gestureContinuity", "boundaryDetection", "audioContinuity"]
    if any("completenessRating" in item["metrics"] for item in data):
        metrics_keys.append("completenessRating")
        
    report = []
    report.append("# SandStories Field Validation Statistical Report")
    report.append(f"\nAnalyzed {len(data)} sessions from {args.csv.name}.\n")
    
    if not has_scipy:
        report.append("> [!WARNING]\n> Scipy not installed. Skipping Kruskal-Wallis p-values. Showing means and group sizes only.\n")
        
    # Overall summary table
    report.append("## Overall Metrics Summary")
    report.append("| Metric | Mean | Min | Max |")
    report.append("| :--- | :---: | :---: | :---: |")
    for mk in metrics_keys:
        vals = [item["metrics"][mk] for item in data if mk in item["metrics"]]
        if vals:
            mean_v = sum(vals) / len(vals)
            report.append(f"| {mk} | {mean_v:.3f} | {min(vals):.3f} | {max(vals):.3f} |")
    report.append("")
    
    # Analyze each independent variable
    for iv in ivs:
        report.append(f"## Impact of {iv}")
        
        # Find all distinct levels
        levels = sorted(list(set(str(item["conditions"][iv]) for item in data)))
        
        report.append(f"Levels compared: {', '.join(levels)}\n")
        
        # Summary table for this IV
        headers = ["Metric"] + [f"{lvl} (mean ± std, n)" for lvl in levels]
        report.append("| " + " | ".join(headers) + " |")
        report.append("| :--- | " + " | ".join([":---:" for _ in levels]) + " |")
        
        kruskal_results = {}
        for mk in metrics_keys:
            # Group values
            group_vals = {}
            for lvl in levels:
                group_vals[lvl] = []
                
            for item in data:
                if mk not in item["metrics"]:
                    continue
                item_lvl = str(item["conditions"][iv])
                group_vals[item_lvl].append(item["metrics"][mk])
                
            # Calculate stats per group
            row_cells = [mk]
            groups_list = []
            for lvl in levels:
                g = group_vals[lvl]
                groups_list.append(g)
                if len(g) > 0:
                    mean = sum(g) / len(g)
                    var = sum((x - mean) ** 2 for x in g) / len(g)
                    std = var ** 0.5
                    row_cells.append(f"{mean:.3f} ± {std:.3f} (n={len(g)})")
                else:
                    row_cells.append("N/A")
            report.append("| " + " | ".join(row_cells) + " |")
            
            # Run Kruskal-Wallis
            h_stat, p_val = run_kruskal(groups_list)
            kruskal_results[mk] = (h_stat, p_val)
            
        report.append("")
        
        if has_scipy:
            report.append(f"### Kruskal-Wallis Test Results ({iv})")
            report.append("| Metric | H-Statistic | p-value | Significance |")
            report.append("| :--- | :---: | :---: | :--- |")
            for mk in metrics_keys:
                h_stat, p_val = kruskal_results[mk]
                sig = "Not Significant"
                if p_val < 0.05:
                    sig = "**Significant (p < 0.05)**"
                if p_val < 0.01:
                    sig = "***Highly Significant (p < 0.01)***"
                
                p_str = f"{p_val:.4f}" if not np_isnan(p_val) else "N/A"
                h_str = f"{h_stat:.3f}" if not np_isnan(h_stat) else "N/A"
                report.append(f"| {mk} | {h_str} | {p_str} | {sig} |")
            report.append("")
            
    # Qualitative trade-offs section per RP
    report.append("## Qualitative Trade-offs & Guidelines")
    report.append("- **Sensor Height**: Lower sensor heights (60cm) maximize depth resolution but restrict the field of view and tracking area for gestures.")
    report.append("- **Lighting Conditions**: Direct sunlight causes infrared saturation, leading to depth stream frames being dropped. Overcast/shade minimizes dropouts.")
    report.append("- **Surface conditions**: Wet compacted sand darkens the surface, potentially reducing contrast for tray boundary color detection.")
    
    # Write output
    with args.out.open("w", encoding="utf-8") as f:
        f.write("\n".join(report))
        
    print(f"Wrote analysis report to {args.out}")
    return 0

def np_isnan(x):
    import math
    return math.isnan(x)

if __name__ == "__main__":
    sys.exit(main())
