#!/bin/sh
# Generate/update SID file for coreconf-m2m
# Usage: ./sid.sh [yang-file]
#   default: coreconf-m2m@2026-03-08.yang

YANG="${1:-coreconf-m2m@2026-03-16.yang}"

uvx --from git+https://github.com/ltn22/pyang@sid-extension pyang \
  --path ../pyang/modules/ietf \
  --path ../pyang/modules/iana \
  --sid-generate-file=100000:400 \
  --sid-list \
  --sid-extension \
  "$YANG"
