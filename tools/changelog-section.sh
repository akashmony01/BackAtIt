#!/bin/bash
# Print one version's section of CHANGELOG.md, without its heading:
#
#   tools/changelog-section.sh 2.0
#
# A section starts at a line "## 2.0" (anything may follow, such as a date)
# and runs until the next "## " heading. Exits 1 if there is no such section
# or it is empty, so a release cannot go out with blank notes.
set -eu
VERSION=${1:?usage: changelog-section.sh VERSION}
FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/CHANGELOG.md"

[ -r "$FILE" ] || { echo "CHANGELOG.md not found" >&2; exit 1; }

section=$(awk -v v="$VERSION" '
    /^## / {
        if (found) exit
        split($0, w, /[ \t]+/)
        if (w[2] == v || w[2] == "[" v "]") { found = 1; next }
    }
    found { print }
' "$FILE" | sed -e '/./,$!d')   # drop leading blank lines

if [ -z "$(printf '%s' "$section" | tr -d '[:space:]')" ]; then
    echo "CHANGELOG.md has no section for $VERSION (expected a line starting \"## $VERSION\")" >&2
    exit 1
fi
printf '%s\n' "$section"
