#!/usr/bin/env python3
"""
SandStories Session Review & Visual Rating Tool
===============================================

Replays and displays a summary of a SandStories storytelling session,
allowing researchers to visually inspect the modalities and assign an offline
completeness score (1-5) along with review notes.

It:
- Displays session file structure and metadata.
- Plots the digitized drawing stroke paths and saves it as `review_replay.png` inside the session folder.
- Prompts the user for a completeness rating and qualitative notes.
- Saves the visual review information into `completeness_rating.json`.

Usage:
    python3 scripts/review_session.py --session /path/to/session_folder
"""

import argparse
import json
import sys
import time
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Review and score a SandStories session.")
    parser.add_argument("--session", type=Path, required=True, help="Path to the session folder to review")
    parser.add_argument("--reviewer", type=str, default="SandStories Researcher", help="Reviewer/Researcher name")
    return parser.parse_args()

def plot_strokes(strokes_path: Path, output_plot_path: Path) -> bool:
    """Load strokes and plot them to a file using matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend to avoid GUI crashes
        import matplotlib.pyplot as plt
    except ImportError:
        print("Warning: matplotlib not installed. Skipping stroke path rendering. Run 'pip install matplotlib' to enable.")
        return False

    if not strokes_path.is_file():
        return False

    try:
        with strokes_path.open("r", encoding="utf-8") as f:
            strokes = json.load(f)
            
        if not strokes:
            print("Strokes file is empty.")
            return False

        plt.figure(figsize=(8, 6))
        plt.title("SandStories Session Stroke Path Replay")
        plt.xlabel("X Position (meters)")
        plt.ylabel("Y Position (meters)")
        plt.grid(True, linestyle="--", alpha=0.5)

        stroke_count = 0
        for stroke in strokes:
            points = stroke.get("points", [])
            if not points:
                continue
            x = [p.get("x", 0.0) for p in points]
            y = [p.get("y", 0.0) for p in points]
            plt.plot(x, y, marker="o", markersize=2, label=f"Stroke {stroke_count+1}" if stroke_count < 10 else "")
            stroke_count += 1

        plt.tight_layout()
        plt.savefig(output_plot_path, dpi=150)
        plt.close()
        print(f"Rendered stroke visualization to: {output_plot_path}")
        return True
    except Exception as e:
        print(f"Error plotting strokes: {e}")
        return False

def main():
    args = parse_args()
    
    if not args.session.is_dir():
        print(f"Error: Session directory does not exist: {args.session}", file=sys.stderr)
        sys.exit(1)
        
    manifest_path = args.session / "manifest.json"
    strokes_path = args.session / "strokes.json"
    dropouts_path = args.session / "dropouts.jsonl"
    
    if not manifest_path.is_file():
        print(f"Error: manifest.json not found in {args.session}", file=sys.stderr)
        sys.exit(1)
        
    # Load manifest
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error reading manifest: {e}", file=sys.stderr)
        sys.exit(1)
        
    print("\n" + "="*50)
    print(f"REVIEWING SESSION: {manifest.get('sessionId', args.session.name)}")
    print("="*50)
    print(f"Device Model: {manifest.get('deviceModel', 'Unknown')}")
    print(f"OS Version:   {manifest.get('osVersion', 'Unknown')}")
    print(f"App Version:  {manifest.get('appVersion', 'Unknown')}")
    print(f"Start Time:   {time.ctime(manifest.get('wallClockStartUnix', 0.0))}")
    print(f"Duration:     {manifest.get('monotonicSessionEndElapsedSeconds', 0.0):.2f} seconds")
    print("-"*50)
    print(f"Depth Frames: {len(manifest.get('depthFrames', []))}")
    print(f"RGB Frames:   {len(manifest.get('rgbFrames', []))}")
    print(f"Audio Config: {manifest.get('audio', {}).get('format', 'None')}")
    print(f"Storage:      {manifest.get('storage', {}).get('destination', 'internal')}")
    
    # Load and print dropouts if present
    if dropouts_path.is_file():
        print("-"*50)
        print("LOGGED DROPOUTS (>= 2s):")
        try:
            dropout_count = 0
            with dropouts_path.open("r", encoding="utf-8") as df:
                for line in df:
                    drop = json.loads(line)
                    print(f"  - Stream: {drop.get('stream', 'unknown')} | Start: {drop.get('start', 0.0):.1f}s | Duration: {drop.get('duration', 0.0):.1f}s")
                    dropout_count += 1
            if dropout_count == 0:
                print("  No dropouts detected.")
        except Exception as e:
            print(f"  Error reading dropouts: {e}")
            
    # Replay stroke paths
    print("-"*50)
    plot_path = args.session / "review_replay.png"
    has_plot = plot_strokes(strokes_path, plot_path)
    if not has_plot:
        print("No stroke paths plotted.")
        
    print("\n" + "="*50)
    print("VISUAL QUALITY REVIEW")
    print("="*50)
    
    # Prompt for score (1 to 5)
    while True:
        try:
            score_input = input("Enter visual completeness score (1.0 - 5.0): ").strip()
            score = float(score_input)
            if 1.0 <= score <= 5.0:
                break
            print("Score must be between 1.0 and 5.0.")
        except ValueError:
            print("Invalid input. Please enter a decimal number.")
            
    # Prompt for notes
    notes = input("Enter qualitative review notes: ").strip()
    
    # Save score to completeness_rating.json
    rating_data = {
        "sessionId": manifest.get("sessionId", args.session.name),
        "completenessRating": score,
        "visualReviewNotes": notes,
        "reviewer": args.reviewer,
        "reviewedAtUnix": time.time()
    }
    
    rating_path = args.session / "completeness_rating.json"
    try:
        with rating_path.open("w", encoding="utf-8") as rf:
            json.dump(rating_data, rf, indent=2)
        print(f"\n[review_session] Saved completeness rating to: {rating_path}")
    except Exception as e:
        print(f"Error saving rating: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
