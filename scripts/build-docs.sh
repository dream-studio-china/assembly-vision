#!/bin/bash
# Build the bilingual docs site: auto-translate -> English (site/) + Chinese (site/zh/)
#
# Adapted from the crud-skeleton project. Steps:
#   1. scripts/translate-docs.py  mirrors docs/ -> docs-zh/ (Chinese translation,
#      including research/ and Mermaid diagram labels)
#   2. scripts/generate-mkdocs-configs.py  produces mkdocs-en.yml and mkdocs-zh.yml
#   3. build English site into site/
#   4. build Chinese site into site/zh/
#
# Prerequisites:
#   pip install mkdocs-material deep-translator
#
# Usage:
#   bash scripts/build-docs.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== 1. Translating docs/ -> docs-zh/ ==="
python scripts/translate-docs.py

echo ""
echo "=== 2. Generating bilingual mkdocs configs ==="
python scripts/generate-mkdocs-configs.py

echo ""
echo "=== 3. Building English site (site/) ==="
mkdocs build -f mkdocs-en.yml --clean

echo ""
echo "=== 4. Building Chinese site (site/zh/) ==="
mkdocs build -f mkdocs-zh.yml --clean

echo ""
echo "=== Done ==="
echo "  English: site/index.html"
echo "  Chinese: site/zh/index.html"
