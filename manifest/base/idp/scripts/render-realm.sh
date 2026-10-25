#!/bin/sh
# 使い方: render-realm.sh <template> <output>
# テンプレート中の {{secret:<name>}} を $SECRETS_DIR/<name> の内容 (JSON 文字列としてエスケープ) で置換する。
# 参照先のファイルが無い・空の場合は失敗させる。
set -eu
SECRETS_DIR="${SECRETS_DIR:-/secrets}"
awk -v dir="$SECRETS_DIR" '
function secret(name,   path, line, v, n) {
  path = dir "/" name
  v = ""; n = 0
  while ((getline line < path) > 0) { v = (n++ ? v "\n" : "") line }
  close(path)
  if (n == 0) { print "render: secret not found or empty: " path > "/dev/stderr"; exit 1 }
  gsub(/\\/, "\\\\", v)
  gsub(/"/, "\\\"", v)
  gsub(/\n/, "\\n", v)
  return v
}
{
  out = ""
  while (match($0, /\{\{secret:[A-Za-z0-9_.-]+\}\}/)) {
    name = substr($0, RSTART + 9, RLENGTH - 11)
    out = out substr($0, 1, RSTART - 1) secret(name)
    $0 = substr($0, RSTART + RLENGTH)
  }
  print out $0
}' "$1" > "$2"
echo "render: $1 -> $2"
