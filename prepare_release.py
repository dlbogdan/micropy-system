#!/usr/bin/env python3
"""Compatibility entry point for the canonical local_builder implementation."""

import sys

from local_builder import main


def compatibility_args(argv):
    """Supply historical defaults while allowing every canonical CLI option."""
    args = list(argv)
    if '--source-dir' not in args:
        args.extend(['--source-dir', 'src'])
    if '--output-dir' not in args:
        args.extend(['--output-dir', 'release'])
    if '--output-mode' not in args:
        args.extend(['--output-mode', 'github-assets'])
    if '--model' not in args:
        args.extend(['--model', 'pico-w-rp2040'])
    return args


if __name__ == '__main__':
    main(compatibility_args(sys.argv[1:]))
