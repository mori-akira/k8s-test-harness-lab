#!/bin/sh
# 使い方: render-realm.sh <template> <output>
# テンプレート中のプレースホルダを置換する。値は JSON 文字列としてエスケープする。
#   {{secret:<name>}}  -> $SECRETS_DIR/<name> の内容 (パスワード等)
#   {{config:<name>}}  -> $CONFIG_DIR/<name> の内容 (URL 等、秘匿不要な環境差分)
# 参照先のファイルが無い・空の場合は失敗させる。
set -eu
SECRETS_DIR="${SECRETS_DIR:-/secrets}"
CONFIG_DIR="${CONFIG_DIR:-/config}"
awk -v secrets="$SECRETS_DIR" -v config="$CONFIG_DIR" '
function value(kind, name,   path, line, v, n) {
  path = (kind == "secret" ? secrets : config) "/" name
  v = ""; n = 0
  while ((getline line < path) > 0) { v = (n++ ? v "\n" : "") line }
  close(path)
  if (n == 0) { print "render: " kind " not found or empty: " path > "/dev/stderr"; exit 1 }
  gsub(/\\/, "\\\\", v)
  gsub(/"/, "\\\"", v)
  gsub(/\n/, "\\n", v)
  return v
}
{
  out = ""
  while (match($0, /\{\{(secret|config):[A-Za-z0-9_.-]+\}\}/)) {
    ref = substr($0, RSTART + 2, RLENGTH - 4)
    sep = index(ref, ":")
    out = out substr($0, 1, RSTART - 1) value(substr(ref, 1, sep - 1), substr(ref, sep + 1))
    $0 = substr($0, RSTART + RLENGTH)
  }
  print out $0
}' "$1" > "$2"
echo "render: $1 -> $2"
