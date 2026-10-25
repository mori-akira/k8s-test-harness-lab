#!/usr/bin/env python3
"""Step 4 の確認: ブラウザと同じ順序で認可コード + PKCE フローを踏み、front のオリジンから api-a を呼べること。

JavaScript は実行しない (画面の確認はブラウザ、自動化は Step 7 の Playwright)。
ここで見るのはサーバ側の設定: front の配信、Keycloak のクライアント設定、CORS。
"""

import base64
import hashlib
import html
import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONTEXT = os.environ.get("CONTEXT", "k3d-k8s-test-harness-lab")
ISSUER = os.environ.get("ISSUER", "http://keycloak.localtest.me:8080/realms/lab")
FRONT = os.environ.get("FRONT", "http://front.localhost:8080")
API = os.environ.get("API", "http://api-a.localtest.me:8080")
CLIENT_ID = "front"
REDIRECT_URI = f"{FRONT}/"


# ブラウザは *.localhost を自前で loopback に解決するが、Python (glibc) は解決しないので合わせる
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, *a, **kw: _getaddrinfo(
    "127.0.0.1" if isinstance(host, str) and host.endswith(".localhost") else host, *a, **kw)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


jar = http.cookiejar.CookieJar()
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect)


def request(method: str, url: str, data: dict | None = None, headers: dict | None = None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        res = browser.open(req)
    except urllib.error.HTTPError as e:
        res = e
    return res.status, res.headers, res.read().decode(errors="replace")


failed = 0


def check(label: str, ok: bool) -> None:
    global failed
    print(f"{'OK ' if ok else 'NG '} {label}")
    failed += not ok


def secret(key: str) -> str:
    out = subprocess.check_output(["kubectl", "--context", CONTEXT, "-n", "idp", "get", "secret",
                                   "keycloak-secrets", "-o", f"jsonpath={{.data.{key}}}"])
    return base64.b64decode(out).decode()


# --- front の配信 ---------------------------------------------------------------
# Pod の入れ替え直後は traefik が古い endpoint を向いていることがあるのでリトライする
for _ in range(10):
    status, _, config_js = request("GET", f"{FRONT}/config.js")
    if status == 200:
        break
    time.sleep(2)
check("front の config.js -> 200", status == 200)
check("config.js の issuer が Keycloak と一致", f'issuer: "{ISSUER}"' in config_js)
check("config.js の apiBase が api-a と一致", f'apiBase: "{API}"' in config_js)
check("OIDC クライアントライブラリが配信される",
      request("GET", f"{FRONT}/vendor/oidc-client-ts.min.js")[0] == 200)

# --- 認可コード + PKCE ------------------------------------------------------------
auth_endpoint = f"{ISSUER}/protocol/openid-connect/auth"
base_params = {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "response_type": "code",
               "scope": "openid profile email", "state": secrets.token_urlsafe(8)}

status, headers, _ = request("GET", f"{auth_endpoint}?{urllib.parse.urlencode(base_params)}")
location = headers.get("Location", "")
check("PKCE なしの認可リクエストは拒否される", status == 302 and "error=invalid_request" in location)

status, _, _ = request("GET", f"{auth_endpoint}?{urllib.parse.urlencode({**base_params, 'redirect_uri': 'http://evil.localhost:8080/'})}")
check("登録外の redirect_uri は拒否される", status == 400)

verifier = secrets.token_urlsafe(48)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
params = {**base_params, "code_challenge": challenge, "code_challenge_method": "S256"}
status, _, page = request("GET", f"{auth_endpoint}?{urllib.parse.urlencode(params)}")
action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page)
check("Keycloak のログイン画面が出る", status == 200 and action is not None)

status, headers, _ = request("POST", html.unescape(action.group(1)),
                             {"username": "ci-01", "password": secret("user-password-ci"),
                              "credentialId": ""})
location = headers.get("Location", "")
query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
check("ログイン後に front へ code 付きでリダイレクトされる",
      status == 302 and location.startswith(REDIRECT_URI) and "code" in query)

origin = {"Origin": FRONT}
status, headers, body = request("POST", f"{ISSUER}/protocol/openid-connect/token",
                                {"grant_type": "authorization_code", "client_id": CLIENT_ID,
                                 "code": query["code"][0], "redirect_uri": REDIRECT_URI,
                                 "code_verifier": verifier}, origin)
check("code + code_verifier でトークンに交換できる", status == 200)
check("トークン交換のレスポンスが front のオリジンを CORS で許可",
      headers.get("Access-Control-Allow-Origin") == FRONT)
access_token = json.loads(body)["access_token"]
p = access_token.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
aud = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
check("アクセストークンの aud に api-a が入る", "api-a" in aud)

# --- front のオリジンから api-a を呼ぶ ---------------------------------------------
status, headers, _ = request("OPTIONS", f"{API}/notes",
                             headers={**origin, "Access-Control-Request-Method": "POST",
                                      "Access-Control-Request-Headers": "authorization,content-type"})
check("api-a の preflight が front のオリジンを許可",
      status == 200 and headers.get("Access-Control-Allow-Origin") == FRONT)

status, headers, _ = request("GET", f"{API}/notes",
                             headers={**origin, "Authorization": f"Bearer {access_token}"})
check("front のトークンで api-a を呼べる (CORS 許可付き)",
      status == 200 and headers.get("Access-Control-Allow-Origin") == FRONT)

status, headers, _ = request("OPTIONS", f"{API}/notes",
                             headers={"Origin": "http://evil.localhost:8080",
                                      "Access-Control-Request-Method": "GET"})
check("許可していないオリジンは CORS で許可されない", headers.get("Access-Control-Allow-Origin") is None)

sys.exit(1 if failed else 0)
