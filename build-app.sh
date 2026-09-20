#!/usr/bin/env bash
# Build GitFourchette.app from the committed HEAD, sign it with a stable
# identity, and install it in /Applications.
#
# Local tooling: excluded through .git/info/exclude, never part of a PR.
#
# Why a stable identity: an ad-hoc signature changes with every build, so
# macOS treats each build as a new app and asks for folder access again.
# Signing with the same certificate every time keeps the permissions.
#
#   ./build-app.sh            build, sign, install (skipped if the app is running)
#   ./build-app.sh --no-install
#   GF_SIGN_IDENTITY=<sha1 or name> ./build-app.sh

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
venv="${GF_VENV:-$here/.venv}"
identity="${GF_SIGN_IDENTITY:-6BA9790976783E36E97297EE58BE4CBB33B837EB}"  # Apple Development: Songurov Fiodor (4R6999U5FD)
install=1
[ "${1:-}" = "--no-install" ] && install=0

work="${TMPDIR:-/tmp}/gitfourchette-build"
tree="$work/tree"
dist="$here/dist"
app="$dist/GitFourchette.app"

# Build from a clean checkout of HEAD, never from the working copy: the
# PyInstaller spec rewrites appconsts.py with the frozen commit.
rev="$(git -C "$here" rev-parse HEAD)"
echo "Building $rev"
if [ -d "$tree" ]; then
    git -C "$here" worktree remove --force "$tree" 2>/dev/null || rm -rf "$tree"
fi
mkdir -p "$work"
git -C "$here" worktree add --detach "$tree" "$rev" >/dev/null

(
    cd "$tree"
    PATH="$venv/bin:$PATH" python -m PyInstaller --noconfirm \
        --distpath "$dist" --workpath "$work/pyinstaller" \
        pkg/pyinstaller/gitfourchette.spec >"$work/build.log" 2>&1
) || { echo "Build failed, see $work/build.log"; exit 1; }

git -C "$here" worktree remove --force "$tree"

echo "Signing with $identity"
codesign --force --deep --timestamp=none --sign "$identity" "$app"
codesign --verify --deep --strict "$app"
codesign -d -r- "$app" 2>&1 | sed -n 's/^designated => /designated requirement: /p'

"$app/Contents/MacOS/GitFourchette" --version

if [ "$install" = 1 ]; then
    if pgrep -f "/Applications/GitFourchette.app/Contents/MacOS/GitFourchette" >/dev/null; then
        echo "GitFourchette is running: quit it, then run: ditto \"$app\" /Applications/GitFourchette.app"
        exit 0
    fi
    rm -rf /Applications/GitFourchette.app
    ditto "$app" /Applications/GitFourchette.app
    codesign --verify --deep --strict /Applications/GitFourchette.app
    echo "Installed /Applications/GitFourchette.app ($rev)"
fi
