#!/usr/bin/env python3
"""Step 5 / 6 の確認。

Step 5: api-b が client_credentials で api-a を呼び、外部 (local では stub) を呼べること。run-id が下流に伝わること。
Step 6: 雛形 (CronJob export) から Job を起動し、成果物 export:<run-id> が DB に書かれること。
api-b には Ingress が無いので、クラスタ内の一時 Pod から呼ぶ。
"""

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

CONTEXT = os.environ.get("CONTEXT", "k3d-k8s-test-harness-lab")
ISSUER = os.environ.get("ISSUER", "http://keycloak.localtest.me:8080/realms/lab")
API = os.environ.get("API", "http://api-a.localtest.me:8080")
API_B_IN_CLUSTER = "http://api-b.api-b.svc.cluster.local:8080"
CURL_IMAGE = "curlimages/curl:8.11.1"
KUBECTL = ["kubectl", "--context", CONTEXT]
SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def kubectl(*args: str, check: bool = True) -> str:
    return subprocess.run([*KUBECTL, *args], check=check, capture_output=True, text=True).stdout


def secret(key: str) -> str:
    return base64.b64decode(kubectl("-n", "idp", "get", "secret", "keycloak-secrets",
                                    "-o", f"jsonpath={{.data.{key}}}")).decode()


def token(username: str, password: str) -> str:
    data = urllib.parse.urlencode({"grant_type": "password", "client_id": "test-runner",
                                   "username": username, "password": password}).encode()
    with urllib.request.urlopen(f"{ISSUER}/protocol/openid-connect/token", data) as res:
        return json.load(res)["access_token"]


def call_api_a(method: str, path: str, tok: str, body: dict | None = None, run_id: str | None = None):
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          **({"X-Test-Run-Id": run_id} if run_id else {})})
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def curl_in_cluster(url: str, run_id: str) -> str:
    return kubectl("-n", "test", "run", f"curl-{uuid.uuid4().hex[:8]}", "--rm", "-i", "--restart=Never",
                   "--quiet", f"--image={CURL_IMAGE}", "--", "curl", "-sf", "-H", f"X-Test-Run-Id: {run_id}", url)


failed = 0


def check(label: str, ok: bool) -> None:
    global failed
    print(f"{'OK ' if ok else 'NG '} {label}")
    failed += not ok


run_id = f"verify-{uuid.uuid4().hex[:8]}"
ci01 = token("ci-01", secret("user-password-ci"))

# 準備: この run-id で note を2件作る
note_ids = [call_api_a("POST", "/notes", ci01, {"title": t}, run_id)[1]["id"] for t in ("alpha", "beta")]

# --- Step 5: api-b -----------------------------------------------------------------
check("ユーザのトークンで api-a の /internal を呼ぶ -> 403",
      call_api_a("GET", f"/internal/notes/count?run_id={run_id}", ci01)[0] == 403)

summary = json.loads(curl_in_cluster(f"{API_B_IN_CLUSTER}/summary?run_id={run_id}", run_id))
check("api-b が client_credentials で api-a から件数を取れる (2件)", summary["note_count"] == 2)
check("api-b が外部 (stub) を呼べる", summary["external"].get("source") == "external-stub")

logs_b = kubectl("-n", "api-b", "logs", "deploy/api-b", "--tail=200")
logs_a = kubectl("-n", "api-a", "logs", "deploy/api-a", "--tail=200")
logs_ext = kubectl("-n", "stub", "logs", "deploy/external", "--tail=200")
check("run-id が api-b のログに載る", f"run_id={run_id}" in logs_b)
check("run-id が api-a に伝わる (api-b -> api-a)", f"run_id={run_id} count for run" in logs_a)
check("api-a 側で呼び出し元が api-b と判定される", f"requested by api-b" in logs_a)
check("run-id が外部 (stub) に伝わる", f"run_id={run_id}" in logs_ext)

# --- Step 6: export Job ------------------------------------------------------------
job = f"export-{run_id}"
subprocess.run([f"{SCRIPTS}/run-export-job.sh", run_id], check=True, capture_output=True,
               env={**os.environ, "CONTEXT": CONTEXT})
done = subprocess.run([*KUBECTL, "-n", "job", "wait", "--for=condition=complete", f"job/{job}", "--timeout=120s"],
                      capture_output=True, text=True).returncode == 0
check(f"雛形から起動した Job {job} が完了する", done)

raw = kubectl("-n", "db", "exec", "deploy/redis", "--", "redis-cli", "--json", "HGETALL", f"export:{run_id}")
export = json.loads(raw) if raw.strip() else {}
check("成果物 export:<run-id> が status=done で書かれる", export.get("status") == "done")
check("成果物の note_count が 2", export.get("note_count") == "2")
check("成果物の titles が作った note と一致",
      sorted(json.loads(export.get("titles", "[]"))) == ["alpha", "beta"])
check("成果物に Job 名が記録される", export.get("job_name") == job)
check("run-id が Job のログに載る", f"run_id={run_id}" in kubectl("-n", "job", "logs", f"job/{job}"))

# 後始末 (成果物と Job は残す。Job は ttlSecondsAfterFinished で消える)
for i in note_ids:
    call_api_a("DELETE", f"/notes/{i}", ci01)

sys.exit(1 if failed else 0)
