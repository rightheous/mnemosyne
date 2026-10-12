#!/usr/bin/env python3
"""Integrator-controlled byte-identical bundle generation; --check never writes."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest_files(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = ROOT / "contracts"
    if not args.check:
        files = digest_files(source)
        files.pop("manifest.json", None)
        (source / "manifest.json").write_text(json.dumps({
            "contract_version": "0.2.0", "status": "integrated-source-contract",
            "algorithm": "sha256", "files": files}, ensure_ascii=False, indent=2)+"\n")
    expected = digest_files(source)
    for name in ("Pumice", "DeepTutor"):
        destination = ROOT / "upstreams" / name / "MnemosyneContracts"
        if not args.check:
            destination.mkdir(exist_ok=True)
            for old in destination.rglob("*"):
                if old.is_file() and old.relative_to(destination).as_posix() not in expected:
                    old.unlink()
            for relative in expected:
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, output)
        if digest_files(destination) != expected:
            raise SystemExit(f"Contract bundle mismatch: {name}")
    print(json.dumps({"result": "PASS", "contract_version": "0.2.0",
                      "copies": 2, "bundle_files": len(expected)}))


if __name__ == "__main__":
    main()
