#!/bin/bash
set -e

# Ensure output directory exists
mkdir -p release

# Run the Python packager
python3 prepare_release.py
