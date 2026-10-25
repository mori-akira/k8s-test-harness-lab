"""api-a: resource server。JWT の sub ごとに分離した notes の CRUD を1つだけ持つ。

サンプルアプリは破棄前提。検証したいのは JWT 検証設定 (issuer / audience / JWKS) と run-id の伝播。
"""

import contextvars
import json
import logging
import os
import time
import urllib.request
import uuid
from functools import cache

import jwt
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

OIDC_ISSUER = os.environ["OIDC_ISSUER"]
OIDC_AUDIENCE = os.environ["OIDC_AUDIENCE"]
REDIS_URL = os.environ["REDIS_URL"]
CORS_ALLOW_ORIGINS = [o for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o]
# /internal/* を呼べるクライアント (トークンの azp)。カンマ区切り
INTERNAL_CLIENTS = [c for c in os.environ.get("INTERNAL_CLIENTS", "").split(",") if c]

RUN_ID_HEADER = "X-Test-Run-Id"
run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="-")


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


handler = logging.StreamHandler()
handler.addFilter(RunIdFilter())
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s run_id=%(run_id)s %(message)s"))
log = logging.getLogger("api-a")
log.addHandler(handler)
log.setLevel(logging.INFO)

db = redis.Redis.from_url(REDIS_URL, decode_responses=True)
app = FastAPI(title="api-a")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ALLOW_ORIGINS,
                   allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type", RUN_ID_HEADER])


@app.middleware("http")
async def run_id_middleware(request: Request, call_next):
    run_id_var.set(request.headers.get(RUN_ID_HEADER, "-"))
    start = time.monotonic()
    response = await call_next(request)
    log.info("%s %s -> %d (%.0fms)", request.method, request.url.path, response.status_code,
             (time.monotonic() - start) * 1000)
    return response


# --- 認証 ---------------------------------------------------------------------

@cache
def jwks_client() -> jwt.PyJWKClient:
    # issuer の discovery から JWKS の URL を引く。issuer はブラウザと同じ URL でクラスタ内から届く前提
    with urllib.request.urlopen(f"{OIDC_ISSUER}/.well-known/openid-configuration", timeout=5) as res:
        jwks_uri = json.load(res)["jwks_uri"]
    return jwt.PyJWKClient(jwks_uri, cache_keys=True)


def current_claims(cred: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))) -> dict:
    if cred is None:
        raise HTTPException(401, "missing bearer token")
    try:
        key = jwks_client().get_signing_key_from_jwt(cred.credentials)
        claims = jwt.decode(cred.credentials, key, algorithms=["RS256"],
                            issuer=OIDC_ISSUER, audience=OIDC_AUDIENCE,
                            # exp / iat / nbf の時刻ずれを許容する (Spring Security の既定は 60 秒)
                            leeway=30,
                            options={"require": ["exp", "iss", "aud", "sub"]})
    except jwt.PyJWTError as e:
        log.info("token rejected: %s", e)
        raise HTTPException(401, "invalid token")
    return claims


def current_sub(claims: dict = Depends(current_claims)) -> str:
    return claims["sub"]


def internal_client(claims: dict = Depends(current_claims)) -> str:
    # サービス間呼び出し (client_credentials) のみ許可する。ユーザのトークンは azp が front / test-runner になる
    if claims.get("azp") not in INTERNAL_CLIENTS:
        raise HTTPException(403, "internal clients only")
    return claims["azp"]


# --- notes --------------------------------------------------------------------
# note:<id>      hash  (owner, title, body, run_id, created_at)
# notes:<sub>    set   (その sub が持つ note の id)
# run:<run_id>   set   (その run-id で作られた note の id。api-b / export Job が参照する)

class NoteIn(BaseModel):
    title: str
    body: str = ""


def load_note(sub: str, note_id: str) -> dict:
    note = db.hgetall(f"note:{note_id}")
    # 他人の note は存在しないものとして扱う
    if not note or note["owner"] != sub:
        raise HTTPException(404, "not found")
    return {"id": note_id, **note}


@app.get("/healthz")
def healthz():
    db.ping()
    return {"status": "ok"}


@app.get("/notes")
def list_notes(sub: str = Depends(current_sub)):
    return [load_note(sub, i) for i in sorted(db.smembers(f"notes:{sub}"))]


@app.post("/notes", status_code=201)
def create_note(body: NoteIn, sub: str = Depends(current_sub)):
    note_id = uuid.uuid4().hex
    note = {"owner": sub, "title": body.title, "body": body.body,
            "run_id": run_id_var.get(), "created_at": str(int(time.time()))}
    with db.pipeline() as p:
        p.hset(f"note:{note_id}", mapping=note)
        p.sadd(f"notes:{sub}", note_id)
        if note["run_id"] != "-":
            p.sadd(f"run:{note['run_id']}", note_id)
        p.execute()
    log.info("created note %s", note_id)
    return {"id": note_id, **note}


@app.get("/notes/{note_id}")
def get_note(note_id: str, sub: str = Depends(current_sub)):
    return load_note(sub, note_id)


@app.put("/notes/{note_id}")
def update_note(note_id: str, body: NoteIn, sub: str = Depends(current_sub)):
    load_note(sub, note_id)
    db.hset(f"note:{note_id}", mapping={"title": body.title, "body": body.body})
    return load_note(sub, note_id)


@app.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str, sub: str = Depends(current_sub)):
    note = load_note(sub, note_id)
    with db.pipeline() as p:
        p.delete(f"note:{note_id}")
        p.srem(f"notes:{sub}", note_id)
        p.srem(f"run:{note['run_id']}", note_id)
        p.execute()
    return Response(status_code=204)


@app.get("/internal/notes/count")
def count_notes_by_run(run_id: str, client: str = Depends(internal_client)):
    count = db.scard(f"run:{run_id}")
    log.info("count for run %s requested by %s: %d", run_id, client, count)
    return {"run_id": run_id, "count": count}
