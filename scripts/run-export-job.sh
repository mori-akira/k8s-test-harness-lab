#!/bin/sh
# 使い方: run-export-job.sh <run-id>
# CronJob export を雛形に Job export-<run-id> を作り、RUN_ID を足して起動する。
# run-id は Job 名に入るため、英小文字・数字・ハイフンのみ。
set -eu
RUN_ID="$1"
CONTEXT="${CONTEXT:-k3d-k8s-test-harness-lab}"
KUBECTL="kubectl --context $CONTEXT -n job"

$KUBECTL create job "export-$RUN_ID" --from=cronjob/export --dry-run=client -o json |
  RUN_ID="$RUN_ID" python3 -c '
import json, os, sys
job = json.load(sys.stdin)
for c in job["spec"]["template"]["spec"]["containers"]:
    c.setdefault("env", []).append({"name": "RUN_ID", "value": os.environ["RUN_ID"]})
json.dump(job, sys.stdout)' |
  $KUBECTL create -f -
