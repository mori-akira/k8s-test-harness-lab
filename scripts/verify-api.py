#!/usr/bin/env python3
"""Step 3 の確認: Keycloak のトークンで api-a を叩けること、データが sub ごとに分離されること。

ホストから Ingress 経由で叩く。api-a はクラスタ内から同じ issuer URL で JWKS を取得する。
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


def secret(key: str) -> str:
    out = subprocess.check_output(["kubectl", "--context", CONTEXT, "-n", "idp", "get", "secret",
                                   "keycloak-secrets", "-o", f"jsonpath={{.data.{key}}}"])
    return base64.b64decode(out).decode()


def token(username: str, password: str, client_id: str = "test-runner") -> str:
    data = urllib.parse.urlencode({"grant_type": "password", "client_id": client_id,
                                   "username": username, "password": password}).encode()
    with urllib.request.urlopen(f"{ISSUER}/protocol/openid-connect/token", data) as res:
        return json.load(res)["access_token"]


def call(method: str, path: str, tok: str | None = None, body: dict | None = None,
         run_id: str | None = None) -> tuple[int, object]:
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    if run_id:
        req.add_header("X-Test-Run-Id", run_id)
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


failed = 0


def check(label: str, ok: bool) -> None:
    global failed
    print(f"{'OK ' if ok else 'NG '} {label}")
    failed += not ok


run_id = f"verify-{uuid.uuid4().hex[:8]}"
pw_ci = secret("user-password-ci")
ci01, ci02 = token("ci-01", pw_ci), token("ci-02", pw_ci)
admin_cli = token("ci-01", pw_ci, client_id="admin-cli")

check("トークンなし -> 401", call("GET", "/notes")[0] == 401)
check("aud に api-a を含まないトークン (admin-cli) -> 401", call("GET", "/notes", admin_cli)[0] == 401)

status, note = call("POST", "/notes", ci01, {"title": "hello", "body": "from ci-01"}, run_id)
check("ci-01 が作成 -> 201", status == 201)
note_id = note["id"]
check("run-id が保存される", note["run_id"] == run_id)

check("ci-01 の一覧に含まれる", note_id in [n["id"] for n in call("GET", "/notes", ci01)[1]])
check("ci-02 の一覧に含まれない", note_id not in [n["id"] for n in call("GET", "/notes", ci02)[1]])
check("ci-02 が取得 -> 404", call("GET", f"/notes/{note_id}", ci02)[0] == 404)
check("ci-02 が更新 -> 404", call("PUT", f"/notes/{note_id}", ci02, {"title": "x"})[0] == 404)
check("ci-02 が削除 -> 404", call("DELETE", f"/notes/{note_id}", ci02)[0] == 404)

status, updated = call("PUT", f"/notes/{note_id}", ci01, {"title": "updated", "body": ""})
check("ci-01 が更新 -> 200", status == 200 and updated["title"] == "updated")
check("ci-01 が削除 -> 204", call("DELETE", f"/notes/{note_id}", ci01)[0] == 204)
check("削除後の取得 -> 404", call("GET", f"/notes/{note_id}", ci01)[0] == 404)

logs = subprocess.check_output(["kubectl", "--context", CONTEXT, "-n", "api-a", "logs",
                                "deploy/api-a", "--tail=200"], text=True)
check(f"api-a のログに run_id={run_id} が載る", f"run_id={run_id}" in logs)

sys.exit(1 if failed else 0)
