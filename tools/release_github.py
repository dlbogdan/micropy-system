#!/usr/bin/env python3
"""Validate, tag and push a project firmware release."""

import argparse
import re
import subprocess

from tooling import resolve_app_root


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def git(app_root, *arguments, capture=False, check=True):
    return subprocess.run(
        ["git", "-C", str(app_root), *arguments], check=check,
        capture_output=capture, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--app-root")
    args = parser.parse_args(argv)
    app_root = resolve_app_root(args.app_root)
    version = args.version.removeprefix("v")
    if not SEMVER.fullmatch(version):
        raise SystemExit("Error: version must be MAJOR.MINOR.PATCH")
    tag = "v" + version

    if git(app_root, "status", "--porcelain", capture=True).stdout.strip():
        raise SystemExit("Error: commit or stash application changes first")
    git(app_root, "fetch", "origin", "--tags")
    if git(app_root, "rev-parse", "-q", "--verify", "refs/tags/" + tag,
           capture=True, check=False).returncode == 0:
        raise SystemExit("Error: tag already exists: %s" % tag)
    branch = git(app_root, "branch", "--show-current", capture=True).stdout.strip()
    if not branch:
        raise SystemExit("Error: cannot release from detached HEAD")
    if git(app_root, "diff", "--quiet", "origin/%s...HEAD" % branch,
           check=False).returncode != 0:
        raise SystemExit(
            "Error: local branch differs from origin/%s; push it first" % branch)
    git(app_root, "tag", "-a", tag, "-m", "Firmware " + tag)
    git(app_root, "push", "origin", tag)
    print("Pushed %s; GitHub Actions will build and publish the release." % tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
