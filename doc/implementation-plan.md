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
| 最初から `base/` + `overlays/local` に切る | 成果物は EKS に持っていくマニフェスト。local 専用に書くと書き直しになる。dev overlay はこのリポジトリでは書かず、差分は [namespace-layout.md](namespace-layout.md) の表で管理する |
| 認証とデプロイの seam だけ本物のスタックを使う | 証明したいのは JWT 検証設定とマニフェストの移植性 |
| ビジネスロジックは空でよい | ラボであり製品の原型ではない |

## Step

| Step | 内容 | 検証すること | 状態 |
| --- | --- | --- | --- |
| 0 | doc 一式 (本ファイル群) | — | 完了 |
| 1 | リポジトリ骨格 + kustomize base/overlays + k3d クラスタ構築手順 | local 固有の値が overlay に閉じるか | 完了 |
| 2 | **Keycloak 単体**を上げる | realm import / Secret レンダリング / **issuer 到達性** | 完了 |
| 3 | api-a (Spring Boot resource server, `sub` スコープの CRUD 1つ) + MySQL | トークンで API を叩けるか | 未着手 |
| 4 | front (Nuxt SPA, 認可コード + PKCE, 画面1つ) | ブラウザフローが通るか | 未着手 |
| 5 | api-b (client_credentials で api-a 呼び出し + **外部呼び出し1本**) | サービス間認証。(2) の seam 設置 | 未着手 |
| 6 | job (KEDA ScaledJob, Redis list トリガ) | トリガ注入 → Job 起動 → 成果物 | 未着手 |
| 7 | **test-runner Job** (Playwright, 2 worker, teardown, レポート搬出) | 合格条件 2 / 3 / 4 | 未着手 |

Step 2 が最初のリスク消化。ここで詰まる想定なので、アプリを作る前に単独で通す。

## ローカルクラスタ (Step 1 で決定)

k3d を使う。定義は [cluster/k3d.yaml](../cluster/k3d.yaml)、操作は `Makefile` に集約する。
手順は [local-cluster.md](local-cluster.md)。

| 項目 | 値 | 理由 |
| --- | --- | --- |
| クラスタ名 / context | `k8s-test-harness-lab` / `k3d-k8s-test-harness-lab` | 同一ホストの既存 k3d クラスタ (`dev`) と区別できるようリポジトリ名を入れる |
| ノード | server 1 + agent 1 | Job / ScaledJob が別ノードに載るケースを最低限再現する |
| k3s | `v1.31.5-k3s1` 固定 | 再現性のため |
| ingress ポート | host `8080` → traefik `80` (`8443` → `443`) | 既存クラスタが 80/443 を使用中。issuer を `keycloak.localtest.me:8080` にする前提とも一致 |
| API ポート | `127.0.0.1:6550` | 既存クラスタの 6445 を避ける |
| current-context | 切り替えない | 他の作業を壊さないため。操作は常に `--context k3d-k8s-test-harness-lab` |
| イメージ供給 | `k3d image import` | レジストリは立てない (dev では ECR) |

既知の挙動: traefik は k3s 起動後に HelmChart の Job で入り、rollout 完了後も svclb がポートを開くまで数秒かかる。
`make verify` はこれを待ってから ingress の 404 を確認する。

## Step 2 の注意点 (既知の罠)

`iss` は1つの文字列なので、**ブラウザとクラスタ内 Pod の両方から同一 URL で解決できる**必要がある。
ブラウザが `http://keycloak.localtest.me:8080/realms/lab` にリダイレクトされるのに、api-a が JWKS を取得できない、という事故が起きる。

- local (採用): issuer は `http://keycloak.localtest.me:8080/realms/lab`。
  - ブラウザ: `localtest.me` は公開 DNS で 127.0.0.1 → host 8080 → traefik → Service `keycloak:8080`
  - Pod: CoreDNS の rewrite (`kube-system/coredns-custom`) で `keycloak.localtest.me` を `keycloak.idp.svc.cluster.local` に読み替え → Service `keycloak:8080` に直接届く
  - Service の port を issuer の port (8080) と揃えているので、ホスト名だけ読み替えれば URL が一致する
  - 当初案の `hostAliases` で traefik の ClusterIP に向ける方式は、traefik がクラスタ内では 80 番で待つため port が合わず不採用
  - CoreDNS は `coredns-custom` の作成・変更を reload で取り込むまで1分以上かかる。`make deploy` で CoreDNS を再起動して即時に反映させている
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
