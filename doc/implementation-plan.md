# 実装計画

## このリポジトリの目的

EKS (dev) 上で IT を自動化する仕組みのうち、以下2点を local の k8s で技術検証する。

- **(1) IdP セルフホスト** — Keycloak を Git の realm JSON で宣言的に管理し、複数テストユーザを自前で持つ
- **(3) テストハーネスの k8s デプロイ** — テストデータ準備・E2E・ScaledJob 起動を1つの Job で回す

**(2) カオスエンジニアリング (Toxiproxy + WireMock) は本 PoC の対象外。** ただし後から挟めるよう、
外部呼び出しの seam (エンドポイント URL の env 化) だけは Step 5 で作る。

## 計画の扱い — 重要

**この計画は暫定であり、固定しない。**

- 実装を読んで理解が進んだ時点で、Step の順序・粒度・採用技術を随時変更する
- doc と実装が乖離したら **doc を直す**。計画との差分を正当化する作業はしない
- 「計画に書いたから作る」は禁止。合格条件 ([poc-acceptance.md](poc-acceptance.md)) に寄与しないものは落とす

## 方針

| 方針 | 理由 |
| --- | --- |
| サンプルアプリは先に作り切らない。Keycloak 単体から縦に薄く積む | アプリは既知の部分で情報価値がない。未知は IdP 起動周りとテストランナー周りに集中している |
| 最初から `base/` + `overlays/{local,dev}` に切る | 成果物は EKS に持っていくマニフェスト。local 専用に書くと書き直しになる |
| 認証とデプロイの seam だけ本物のスタックを使う | 証明したいのは JWT 検証設定とマニフェストの移植性 |
| ビジネスロジックは空でよい | ラボであり製品の原型ではない |

## Step

| Step | 内容 | 検証すること | 状態 |
| --- | --- | --- | --- |
| 0 | doc 一式 (本ファイル群) | — | 完了 |
| 1 | リポジトリ骨格 + kustomize base/overlays + k3d クラスタ構築手順 | local/dev 差分が overlay に閉じるか | 未着手 |
| 2 | **Keycloak 単体**を上げる | realm import / Secret レンダリング / **issuer 到達性** | 未着手 |
| 3 | api-a (Spring Boot resource server, `sub` スコープの CRUD 1つ) + MySQL | トークンで API を叩けるか | 未着手 |
| 4 | front (Nuxt SPA, 認可コード + PKCE, 画面1つ) | ブラウザフローが通るか | 未着手 |
| 5 | api-b (client_credentials で api-a 呼び出し + **外部呼び出し1本**) | サービス間認証。(2) の seam 設置 | 未着手 |
| 6 | job (KEDA ScaledJob, Redis list トリガ) | トリガ注入 → Job 起動 → 成果物 | 未着手 |
| 7 | **test-runner Job** (Playwright, 2 worker, teardown, レポート搬出) | 合格条件 2 / 3 / 4 | 未着手 |

Step 2 が最初のリスク消化。ここで詰まる想定なので、アプリを作る前に単独で通す。

## Step 2 の注意点 (既知の罠)

`iss` は1つの文字列なので、**ブラウザとクラスタ内 Pod の両方から同一 URL で解決できる**必要がある。
ブラウザが `http://keycloak.localtest.me:8080/realms/lab` にリダイレクトされるのに、api-a が JWKS を取得できない、という事故が起きる。

- local: ingress host を `keycloak.localtest.me` (公開 DNS で 127.0.0.1 に解決) にし、API Pod に `hostAliases` で同ホストを ingress controller の ClusterIP に向ける。または CoreDNS に rewrite を1行
- dev: 内部 ALB のホスト名が Pod からも社内ブラウザからも引けるか **要確認**。ここは PoC で決めた方式がそのまま dev の設計になる

## テストユーザ

realm JSON に **10人**を固定で定義する。リース機構は作らない。

| 用途 | 人数 | 割当方法 |
| --- | --- | --- |
| CI (test-runner Job) | 6 | Playwright の `TEST_PARALLEL_INDEX` で静的割当 |
| 人間の動作確認 | 4 | 1人1ユーザ固定 |

分割する理由: CI がプールを全消費すると、手動確認中に CI が走って壊す。
dev では実行開始を Slack 通知し、人 vs 人の衝突はそれで検知する。

## スコープ外

- Toxiproxy / WireMock の本格導入 (Step 5 で seam のみ)
- NetworkPolicy、リソース制限のチューニング
- dev (EKS) への実適用
- サンプルアプリの機能的な作り込み
