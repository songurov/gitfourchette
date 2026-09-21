 #!/usr/bin/env bash

set -e
set -x

export QT_API=${QT_API:-pyqt6}
export PYVER=${PYVER:-"3.14"}

HERE="$(dirname "$(readlink -f -- "$0")" )"
ROOT="$(readlink -f -- "$HERE/../..")"

ARCH="$(uname -m)"

cd "$ROOT"
APPVER="$(python3 -c 'from gitfourchette.appconsts import APP_VERSION; print(APP_VERSION)')"
echo "App version: $APPVER"

mkdir -p "$ROOT/build"
cd "$ROOT/build"

# Freeze Qt api
"$ROOT/update_resources.py" --freeze $QT_API

# Write requirements file so python_appimage knows what to include.
# The path to gitfourchette's root dir must be absolute.
echo -e "$PINNED_REQUIREMENTS\n$ROOT[$QT_API,pygments,mfusepy]" > "$HERE/requirements.txt"

# Use python_appimage to create AppImage contents directory
python3 -m python_appimage --verbose build app --python-version $PYVER --no-packaging "$HERE"

# Remove junk that we don't need
pushd GitFourchette-$ARCH
junklist=$(cat "$HERE/junklist.txt")
rm -rfv $junklist
popd

# Package the AppImage ourselves
wget -N https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage
chmod +x appimagetool-$ARCH.AppImage
# appimagetool fetches the AppImage runtime from GitHub on every run, and a bad
# day there (504 from the release CDN) fails a build that is otherwise finished.
# Point APPIMAGE_RUNTIME_FILE at a copy to skip that download.
runtimeArgs=()
if [ -n "${APPIMAGE_RUNTIME_FILE:-}" ]; then
    runtimeArgs=(--runtime-file "$APPIMAGE_RUNTIME_FILE")
fi
./appimagetool-$ARCH.AppImage --no-appstream "${runtimeArgs[@]}" GitFourchette-$ARCH
chmod +x GitFourchette-$ARCH.AppImage
mv -v GitFourchette{,-$APPVER}-$ARCH.AppImage
