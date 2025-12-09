#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
TARGET_DIR="${1:-$HOME/.remote-coder}"

copy_file() {
    local primary="$1"
    local fallback="$2"
    local dest_path="$3"
    local source=""

    if [[ -f "$primary" ]]; then
        source="$primary"
    elif [[ -n "$fallback" && -f "$fallback" ]]; then
        source="$fallback"
    else
        echo "Error: neither $primary nor $fallback exists." >&2
        exit 1
    fi

    cp "$source" "$dest_path"
    echo "Copied $(basename "$source") -> $dest_path"
}

mkdir -p "$TARGET_DIR"
echo "Syncing configuration into $TARGET_DIR"

copy_file "$REPO_ROOT/.env" "$REPO_ROOT/.env.example" "$TARGET_DIR/.env"
copy_file "$REPO_ROOT/config/projects.yaml" "$REPO_ROOT/config/projects.yaml.example" "$TARGET_DIR/projects.yaml"
copy_file "$REPO_ROOT/config/agents.yaml" "" "$TARGET_DIR/agents.yaml"

echo "Done."
