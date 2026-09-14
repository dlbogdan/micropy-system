git -C vendor/micropy-system pull --ff-only origin main
git add vendor/micropy-system .gitignore
git commit -m "Update framework builder and add app ignores"
git push origin main
