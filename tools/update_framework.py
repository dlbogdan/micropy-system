#!/usr/bin/env python3
"""Fast-forward the framework submodule in its consuming project."""

import argparse
import os
from pathlib import Path
import subprocess

from tooling import framework_root, resolve_app_root


def git(*arguments, cwd=None, capture=False, check=True):
    return subprocess.run(["git", *map(str, arguments)], cwd=cwd, check=check,
                          capture_output=capture, text=True)


def find_submodule(app_root, explicit=None):
    if explicit:
        return explicit
    modules = app_root / ".gitmodules"
    if modules.is_file():
        result = git("config", "--file", ".gitmodules", "--get-regexp", "path",
                     cwd=app_root, capture=True, check=False)
        actual = framework_root().resolve()
        for line in result.stdout.splitlines():
            fields = line.split(None, 1)
            if len(fields) == 2:
                candidate = fields[1]
                path = app_root / candidate
                if path.exists() and path.resolve() == actual:
                    return candidate
    return "micropy-system"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root")
    args = parser.parse_args(argv)
    app_root = resolve_app_root(args.app_root)
    submodule = find_submodule(
        app_root, os.environ.get("MICROPY_SUBMODULE_PATH"))
    git("submodule", "update", "--init", submodule, cwd=app_root)
    checkout = app_root / submodule
    git("fetch", "origin", "main", cwd=checkout)
    git("checkout", "main", cwd=checkout)
    git("merge", "--ff-only", "origin/main", cwd=checkout)
    print("Framework updated. Review and commit the submodule pointer:")
    print("  git add %s && git commit -m 'Update micropy-system framework'" %
          submodule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
