#!/usr/bin/env python3
"""
SandStories FAIR Exporter
=========================

Compiles a publication-ready FAIR data package from a raw session directory:
- Copies raw session files (manifest.json, depth/, rgb/, strokes, audio, objects, boundary) into a `data/` subdirectory.
- Copies evaluation results (evaluation_report.json, dropouts.jsonl, conditions.json, completeness_rating.json) if present.
- Generates a standard RO-Crate compliant `metadata.json` describing the crate.
- Generates a human-readable metadata `README.txt`.
- Calculates SHA-256 checksums for all files and writes them to `CHECKSUMS.sha256`.

Usage:
    python3 scripts/export_fair_package.py --session /path/to/session_folder --out-dir /path/to/output_fair_pkg
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

def parse_args():
    parser = argparse.ArgumentParser(description="Compile a SandStories session into a publication-ready FAIR package.")
    parser.add_argument("--session", type=Path, required=True, help="Path to the active session folder")
    parser.add_argument("--out-dir", type=Path, required=True, help="Destination directory for the FAIR package")
    parser.add_argument("--creator", type=str, default="SandStories Researcher", help="Creator/Researcher name")
    parser.add_argument("--license", type=str, default="https://creativecommons.org/licenses/by/4.0/", help="License URL")
    return parser.parse_args()

def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 checksum for a file using streaming chunks."""
    sha = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(64 * 1024):
            sha.update(chunk)
    return sha.hexdigest()

def get_mime_type(ext: str) -> str:
    """Return standard MIME type based on file extension."""
    mapping = {
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".m4a": "audio/x-m4a",
        ".txt": "text/plain",
        ".sha256": "text/plain",
    }
    return mapping.get(ext.lower(), "application/octet-stream")

def build_ro_crate(
    session_id: str,
    creator_name: str,
    license_url: str,
    modalities: List[str],
    schema_version: int,
    files_list: List[Dict[str, str]]
) -> Dict:
    """Builds a compliant RO-Crate 1.1 JSON-LD dictionary structure."""
    current_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    descriptor = {
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        "about": {"@id": "./"}
    }
    
    # Root dataset
    root_dataset = {
        "@id": "./",
        "@type": "Dataset",
        "name": f"SandStories Session - {session_id}",
        "description": "Standardized multimodal storytelling capture dataset package.",
        "creator": {
            "@type": "Person",
            "name": creator_name
        },
        "datePublished": current_date,
        "license": license_url,
        "schemaVersion": schema_version,
        "modalities": modalities,
        "timestampSemantics": "ContinuousClock",
        "hasPart": [{"@id": f["rel_path"]} for f in files_list]
    }
    
    graph = [descriptor, root_dataset]
    for f in files_list:
        graph.append({
            "@id": f["rel_path"],
            "@type": "File",
            "name": f["name"],
            "encodingFormat": f["mime"],
            "sha256": f["sha256"]
        })
        
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": graph
    }

def generate_readme(session_id: str, creator_name: str, license_url: str, modalities: List[str], files_list: List[Dict[str, str]]) -> str:
    """Generates the README.txt documentation content."""
    lines = [
        "========================================================================",
        f"SandStories FAIR Data Package: {session_id}",
        "========================================================================",
        f"Creator: {creator_name}",
        f"Export Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"License: {license_url}",
        f"Capture Modalities: {', '.join(modalities)}",
        "",
        "DESCRIPTION:",
        "This directory contains a complete, standardized dataset package mapping a",
        "sandplay storytelling session. The dataset includes depth profiles, RGB frames,",
        "digitized stroke paths, audio, and computed annotations.",
        "",
        "DIRECTORY STRUCTURE:",
        "- data/                   Contains all source/raw files collected during capture.",
        "- metadata.json           RO-Crate v1.1 compliant metadata index.",
        "- CHECKSUMS.sha256        SHA-256 hashes of all package files for verification.",
        "- README.txt              This documentation file.",
        "",
        "CONTENTS SUMMARY:"
    ]
    for f in sorted(files_list, key=lambda x: x["rel_path"]):
        lines.append(f"  - {f['rel_path']} ({f['mime']})")
    
    lines.append("\nCITATION SUGGESTION:")
    lines.append(f"Pugalia, V. (2026). SandStories Dataset: {session_id}. Private Repository.")
    lines.append("========================================================================")
    return "\n".join(lines)

def main():
    args = parse_args()
    
    if not args.session.is_dir():
        print(f"Error: Session folder does not exist: {args.session}", file=sys.stderr)
        sys.exit(1)
        
    # Create output directories
    args.out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = args.out_dir / "data"
    data_dir.mkdir(exist_ok=True)
    
    # 1. Gather all files in the session folder and copy them to 'data/'
    # Also capture files directly in session folder that are metadata artifacts (evaluation_report, etc.)
    copied_files: List[Path] = []
    
    # Simple recursive copy
    for item in args.session.rglob("*"):
        if item.is_file():
            rel_to_src = item.relative_to(args.session)
            # We copy all raw capturing files and postprocessing reports into data/
            dest_file = data_dir / rel_to_src
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest_file)
            copied_files.append(dest_file)
            
    # Parse manifest to extract details
    manifest_path = data_dir / "manifest.json"
    session_id = args.session.name
    schema_version = 1
    modalities = ["strokes"]
    
    if manifest_path.is_file():
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
                session_id = manifest.get("sessionId", session_id)
                schema_version = manifest.get("schemaVersion", 1)
                if manifest.get("depthFrames"):
                    modalities.append("depth")
                if manifest.get("rgbFrames"):
                    modalities.append("rgb")
                if manifest.get("audio"):
                    modalities.append("audio")
                if manifest.get("trayBoundary"):
                    modalities.append("boundary")
                if manifest.get("objectDetectionsFile"):
                    modalities.append("objects")
        except Exception as e:
            print(f"Warning: failed to read manifest.json: {e}", file=sys.stderr)

    # 2. Add extra modalities if specific sidecars are copied
    if (data_dir / "completeness_rating.json").is_file():
        modalities.append("completeness_review")
        
    # 3. Compute SHA-256 for all copied files
    files_record: List[Dict[str, str]] = []
    checksum_lines: List[str] = []
    
    for file_path in copied_files:
        rel_path = "data/" + str(file_path.relative_to(data_dir))
        sha = compute_sha256(file_path)
        mime = get_mime_type(file_path.suffix)
        files_record.append({
            "rel_path": rel_path,
            "name": file_path.name,
            "mime": mime,
            "sha256": sha
        })
        checksum_lines.append(f"{sha}  {rel_path}")
        
    # Sort files_record by relative path for determinism
    files_record.sort(key=lambda x: x["rel_path"])
    checksum_lines.sort()
    
    # 4. Generate metadata.json (RO-Crate)
    crate = build_ro_crate(session_id, args.creator, args.license, modalities, schema_version, files_record)
    ro_crate_path = args.out_dir / "metadata.json"
    with ro_crate_path.open("w", encoding="utf-8") as f:
        json.dump(crate, f, indent=2)
        
    # Calculate checksum for metadata.json and add it to CHECKSUMS.sha256
    meta_sha = compute_sha256(ro_crate_path)
    checksum_lines.append(f"{meta_sha}  metadata.json")
    
    # 5. Generate README.txt
    readme_content = generate_readme(session_id, args.creator, args.license, modalities, files_record)
    readme_path = args.out_dir / "README.txt"
    with readme_path.open("w", encoding="utf-8") as f:
        f.write(readme_content)
        
    readme_sha = compute_sha256(readme_path)
    checksum_lines.append(f"{readme_sha}  README.txt")
    
    # 6. Write CHECKSUMS.sha256
    checksum_path = args.out_dir / "CHECKSUMS.sha256"
    with checksum_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")
        
    print(f"[export_fair_package] Successfully compiled FAIR package at {args.out_dir}")

if __name__ == "__main__":
    main()
