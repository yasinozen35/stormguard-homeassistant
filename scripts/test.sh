#!/usr/bin/env bash
# Create the test venv (uv), then run ruff, pytest and Home Assistant's hassfest.
#
#   ./scripts/test.sh                 # everything
#   ./scripts/test.sh -k blueprint    # extra args go to pytest
#   HASSFEST=0 ./scripts/test.sh      # skip hassfest (needs network the first time)
#   STORMGUARD_VENV=/tmp/venv ./scripts/test.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${STORMGUARD_VENV:-$ROOT/.venv}"
# pytest-homeassistant-custom-component 0.13.373 -> homeassistant 2026.10.2 -> Python >= 3.14.2
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
[ -x "$UV" ] || { echo "uv not found: https://docs.astral.sh/uv/" >&2; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  "$UV" python install "$PYTHON_VERSION"
  "$UV" venv --python "$PYTHON_VERSION" "$VENV"
fi
VIRTUAL_ENV="$VENV" "$UV" pip install --quiet -r "$ROOT/requirements_test.txt"

cd "$ROOT"
echo "== ruff"
"$VENV/bin/ruff" check .
"$VENV/bin/ruff" format --check .

echo "== pytest"
"$VENV/bin/python" -m pytest "$@"

if [ "${HASSFEST:-1}" = "1" ]; then
  echo "== hassfest"
  HA_VERSION="$("$VENV/bin/python" -c 'from homeassistant.const import __version__; print(__version__)')"
  CORE="${HASSFEST_CORE:-$VENV/hassfest-core-$HA_VERSION}"
  if [ ! -d "$CORE/script/hassfest" ]; then
    rm -rf "$CORE"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$HA_VERSION" --filter=blob:none --sparse \
      https://github.com/home-assistant/core.git "$CORE"
    git -C "$CORE" sparse-checkout set --no-cone /script/ /requirements_all.txt
  fi
  run_hassfest() {
    (cd "$CORE" && PATH="$VENV/bin:$PATH" python -m script.hassfest --action validate \
      --integration-path "$ROOT/custom_components/stormguard")
  }
  # hassfest imports a few core components whose libraries the test harness
  # does not ship; install them (pinned from requirements_all.txt) on demand.
  for _ in 1 2 3 4 5 6 7 8; do
    if out="$(run_hassfest 2>&1)"; then echo "$out" | tail -3; exit 0; fi
    mod="$(echo "$out" | grep -o "No module named '[^']*'" | head -1 | sed "s/No module named '//; s/'//" | cut -d. -f1)"
    if [ -z "$mod" ]; then echo "$out"; exit 1; fi
    pin="$(grep -i "^$(echo "$mod" | tr _ -)==" "$CORE/requirements_all.txt" | head -1 || true)"
    VIRTUAL_ENV="$VENV" "$UV" pip install --quiet "${pin:-$mod}"
  done
  echo "hassfest: could not resolve its dependencies" >&2
  exit 1
fi
