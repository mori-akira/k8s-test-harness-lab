"""api-b: client_credentials で api-a を呼び、外部 API を1本呼ぶ。破棄前提。

検証したいのはサービス間認証 (client_credentials) と、外部呼び出し先を env で差し替える seam。
(2) を導入するときは EXTERNAL_BASE_URL を Toxiproxy に向けるだけで済むようにしておく。
"""

import contextvars
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException, Request

OIDC_ISSUER = os.environ["OIDC_ISSUER"]
OIDC_CLIENT_ID = os.environ["OIDC_CLIENT_ID"]
API_A_BASE_URL = os.environ["API_A_BASE_URL"]
EXTERNAL_BASE_URL = os.environ["EXTERNAL_BASE_URL"]
SECRETS_DIR = os.environ.get("SECRETS_DIR", "/secrets")

RUN_ID_HEADER = "X-Test-Run-Id"
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


handler = logging.StreamHandler()
handler.addFilter(RunIdFilter())
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s run_id=%(run_id)s %(message)s"))
log = logging.getLogger("api-b")
log.addHandler(handler)
log.setLevel(logging.INFO)

app = FastAPI(title="api-b")


@app.middleware("http")
async def run_id_middleware(request: Request, call_next):
    run_id_var.set(request.headers.get(RUN_ID_HEADER, "-"))
    start = time.monotonic()
    response = await call_next(request)
    log.info("%s %s -> %d (%.0fms)", request.method, request.url.path, response.status_code,
             (time.monotonic() - start) * 1000)
    return response


# --- client_credentials -------------------------------------------------------

class TokenCache:
    """client_credentials のアクセストークンを期限の少し前まで使い回す。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    def get(self) -> str:
        with self._lock:
            if time.time() < self._expires_at - 30:
                return self._token
            with open(f"{SECRETS_DIR}/client-secret") as f:
                secret = f.read().strip()
            data = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": OIDC_CLIENT_ID,
                                           "client_secret": secret}).encode()
            with urllib.request.urlopen(f"{OIDC_ISSUER}/protocol/openid-connect/token", data, timeout=5) as res:
                body = json.load(res)
            self._token = body["access_token"]
            self._expires_at = time.time() + body["expires_in"]
            log.info("fetched client_credentials token (expires_in=%ss)", body["expires_in"])
            return self._token


tokens = TokenCache()


def get_json(url: str, token: str | None = None) -> dict:
    req = urllib.request.Request(url)
    # run-id は下流 (api-a / 外部) にも引き継ぐ
    req.add_header(RUN_ID_HEADER, run_id_var.get())
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        log.warning("GET %s -> %d", url, e.code)
        raise HTTPException(502, f"upstream {url} -> {e.code}")
    except urllib.error.URLError as e:
        log.warning("GET %s failed: %s", url, e.reason)
        raise HTTPException(502, f"upstream {url} unreachable")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/summary")
def summary(run_id: str):
    """run-id で作られた note の数 (api-a) と外部 API の値をまとめて返す。"""
    count = get_json(f"{API_A_BASE_URL}/internal/notes/count?{urllib.parse.urlencode({'run_id': run_id})}",
                     tokens.get())
    external = get_json(f"{EXTERNAL_BASE_URL}/rate")
    return {"run_id": run_id, "note_count": count["count"], "external": external}
