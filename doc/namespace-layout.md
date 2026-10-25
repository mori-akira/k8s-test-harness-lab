# NameSpace 構成と overlay 差分

## NameSpace

dev の実プロジェクトに合わせ、Deployment / ScaledJob の単位で分割する。

| NameSpace | 中身 | 導入 Step |
| --- | --- | --- |
| `idp` | Keycloak | 2 |
| `db` | MySQL | 3 |
| `api-a` | api-a (resource server) | 3 |
| `front` | Nuxt SPA | 4 |
| `api-b` | api-b (サービス間通信 + 外部呼び出し) | 5 |
| `job` | Redis + KEDA ScaledJob | 6 |
| `test` | test-runner Job + minio | 7 |
| `stub` | Toxiproxy + WireMock | (2) 導入時 |

local では prefix を付けない。dev に移す際は社内の命名規約に合わせる。
NetworkPolicy は PoC のスコープ外 (= 名前空間間は素通し)。

## ディレクトリ構成

```
/
├ doc/                  — 本ドキュメント群
├ realm/                — Keycloak realm JSON のテンプレート (10ユーザ定義)
├ manifest/
│  ├ base/              — NameSpace 単位のマニフェスト
│  │  ├ idp/
│  │  ├ db/
│  │  ├ api-a/
│  │  ├ api-b/
│  │  ├ front/
│  │  ├ job/
│  │  ├ test/
│  │  └ stub/
│  └ overlays/
│     ├ local/          — k3d 向け patch
│     └ dev/            — EKS 向け patch (PoC では適用しない)
├ app/                  — サンプルアプリ (破棄前提)
│  ├ front/
│  ├ api-a/
│  ├ api-b/
│  └ job/
└ test/                 — Playwright テストスイート + seed スクリプト
```

`overlays/dev` は PoC では適用しないが、**差分が overlay に閉じていることの証明**として書く。
書けない差分が出たら base の設計が間違っているシグナル。

## overlay 差分の一覧

| 項目 | local | dev |
| --- | --- | --- |
| Ingress | traefik | ALB Controller (annotation) |
| Keycloak の issuer host | `keycloak.localtest.me` | 内部 ALB のホスト名 |
| Secret 供給 | ダミー Secret マニフェスト | Secrets Manager 注入 (既存実績) |
| DB 接続先 | in-cluster MySQL の Service | Aurora MySQL のエンドポイント |
| Job トリガ | in-cluster Redis | SQS / ファイル連携 |
| レポート置き場 | minio の Service | S3 バケット |
| StorageClass / LoadBalancer | k3d 標準 | EKS |
| イメージ | ローカルビルドを k3d に import | ECR |

この表が増えすぎたら base の抽象が足りていない。随時見直す。
