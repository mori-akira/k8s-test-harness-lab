# NameSpace 構成と overlay 差分

## NameSpace

dev の実プロジェクトに合わせ、Deployment / Job の単位で分割する。

| NameSpace | 中身 | 導入 Step |
| --- | --- | --- |
| `idp` | Keycloak | 2 |
| `db` | Redis (サンプルアプリのデータストア、インメモリ) | 3 |
| `api-a` | api-a (resource server, Python / FastAPI) | 3 |
| `front` | front (HTML + JS の SPA、nginx) | 4 |
| `api-b` | api-b (サービス間通信 + 外部呼び出し) | 5 |
| `job` | export Job (suspend の CronJob を雛形に起動) | 6 |
| `test` | test-runner Job + minio | 7 |
| `stub` | local: 外部 API の stub (nginx)。(2) 導入時に Toxiproxy + WireMock | 5 (local overlay のみ) |

local では prefix を付けない。dev に移す際は社内の命名規約に合わせる。
NetworkPolicy は PoC のスコープ外 (= 名前空間間は素通し)。

## ディレクトリ構成

```
/
├ doc/                  — 本ドキュメント群
├ Makefile              — クラスタ作成 / デプロイ / 確認のエントリポイント
├ cluster/              — k3d クラスタ定義 (local のみ)
├ manifest/
│  ├ base/              — NameSpace 単位のマニフェスト
│  │  ├ idp/
│  │  │  ├ realm/     — Keycloak realm JSON のテンプレート (10ユーザ定義)
│  │  │  └ scripts/   — realm JSON のレンダリングスクリプト (initContainer で実行)
│  │  ├ db/
│  │  ├ api-a/
│  │  ├ api-b/
│  │  ├ front/
│  │  ├ job/
│  │  ├ test/
│  │  └ stub/         — (2) 導入時に追加 (local の外部 stub は overlays/local に置く)
│  └ overlays/
│     └ local/          — k3d 向け patch
├ app/                  — サンプルアプリ (破棄前提)
│  ├ front/
│  ├ api-a/
│  ├ api-b/
│  └ job/
├ scripts/              — 確認用スクリプト (make verify から呼ぶ)
└ test/                 — Playwright テストスイート + seed スクリプト
```

このリポジトリでは dev 環境は構築しないため、`overlays/dev` は置かない。
dev へ持ち出す際に overlay で patch する項目は下表で管理する。
base に local 固有の値が入り込み、この表に書けない差分が出たら base の設計が間違っているシグナル。

## overlay 差分の一覧 (dev への持ち出し時に patch する項目)

| 項目 | local | dev |
| --- | --- | --- |
| Ingress | traefik | ALB Controller (annotation) |
| Keycloak の issuer (`KC_HOSTNAME`) | `http://keycloak.localtest.me:8080` | 内部 ALB のホスト名 |
| Keycloak の Ingress | host `keycloak.localtest.me` / class `traefik` | 内部 ALB のホスト名 / ALB |
| issuer host の Pod 内解決 | CoreDNS rewrite (`kube-system/coredns-custom`) | 要確認 (内部 ALB のホスト名が Pod から引けるか) |
| Secret 供給 | ダミー Secret マニフェスト | Secrets Manager 注入 (既存実績) |
| DB 接続先 (`REDIS_URL`) | in-cluster Redis の Service | 実プロジェクトの DB (Aurora MySQL)。サンプルアプリの DB は持ち出さない |
| api-a の issuer (`OIDC_ISSUER`) | `http://keycloak.localtest.me:8080/realms/lab` | 内部 ALB のホスト名 |
| api-a の Ingress | host `api-a.localtest.me` / class `traefik` | 内部 ALB のホスト名 / ALB |
| api-a の CORS (`CORS_ALLOW_ORIGINS`) | `http://front.localhost:8080` | front のオリジン |
| front のオリジン (realm の `FRONT_ORIGIN`) | `http://front.localhost:8080` (secure context にするため `*.localhost`) | 内部 ALB のホスト名 (HTTPS) |
| front の設定 (`front-config`) | issuer / api-a の URL を local のホスト名に | 内部 ALB のホスト名 |
| front の Ingress | host `front.localhost` / class `traefik` | 内部 ALB のホスト名 / ALB |
| 後続 Job の起動 | 雛形 CronJob から Job を作成 | 実プロジェクト側の起動方式 |
| api-b の issuer (`OIDC_ISSUER`) | `http://keycloak.localtest.me:8080/realms/lab` | 内部 ALB のホスト名 |
| api-b の外部呼び出し先 (`EXTERNAL_BASE_URL`) | `stub/external` (local overlay にだけ置く) | 実際の外部 API。(2) では Toxiproxy |
| api-b の client secret (`api-b-secrets`) | ダミー Secret マニフェスト | Secrets Manager 注入 |
| export Job の DB 接続先 (`job-config` の `REDIS_URL`) | in-cluster Redis | 実プロジェクトの DB |
| レポート置き場 | minio の Service | S3 バケット |
| StorageClass / LoadBalancer | k3d 標準 | EKS |
| `harness.lab/env` ラベル | `local` | `dev` |
| イメージ | ローカルビルドを k3d に import | ECR |

この表が増えすぎたら base の抽象が足りていない。随時見直す。
