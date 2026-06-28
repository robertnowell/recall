#!/bin/bash
# Nightly recall refresh wrapper (launchd has no shell env, so load the key from ~/.zshrc)
export OPENAI_API_KEY=$(grep -oE "export OPENAI_API_KEY=[\"']?[^\"' ]+" ~/.zshrc 2>/dev/null | sed -E "s/.*=[\"']?//")
cd "$HOME/Projects/recall" || exit 1
echo "=== refresh $(date) ==="
"$HOME/Projects/recall/.venv/bin/python" src/refresh.py
"$HOME/Projects/recall/.venv/bin/python" src/digest.py --all
