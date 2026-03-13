#!/usr/bin/env python3
"""Export/import agent data."""
import json
import tarfile
from pathlib import Path
from .identity import CLAKU_DIR, load_identity

def export_data(output_file: str):
    """Export all agent data to tar.gz."""
    identity = load_identity()
    if not identity:
        raise ValueError("No identity found")
    
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(CLAKU_DIR / "identity.json", arcname="identity.json")
        if (CLAKU_DIR / "config.json").exists():
            tar.add(CLAKU_DIR / "config.json", arcname="config.json")
        if (CLAKU_DIR / "circles").exists():
            tar.add(CLAKU_DIR / "circles", arcname="circles")
        if (CLAKU_DIR / "workspaces").exists():
            tar.add(CLAKU_DIR / "workspaces", arcname="workspaces")
    
    return output_file

def import_data(input_file: str):
    """Import agent data from tar.gz."""
    with tarfile.open(input_file, "r:gz") as tar:
        tar.extractall(CLAKU_DIR)
    return True
