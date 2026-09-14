#!/bin/bash
set -e

# Compatibility launcher; all options are forwarded to the canonical builder.
python3 prepare_release.py "$@"
