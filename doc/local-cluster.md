# ローカルクラスタの手順

local (k3d) クラスタの作成・削除と、kubectl の context 切り替えの手順。
構成の決定事項と理由は [implementation-plan.md](implementation-plan.md) の「ローカルクラスタ」を参照。

## 前提

| ツール | 確認済みのバージョン |
| --- | --- |
| docker | 27.4 |
| k3d | v5.8 |
| kubectl | v1.31 (kustomize 同梱のもので足りる) |

ホスト側で以下のポートが空いていること。

| ポート | 用途 |
| --- | --- |
| `8080` / `8443` | ingress (traefik) |
| `127.0.0.1:6550` | Kubernetes API |

同一ホストに別の k3d クラスタ (例: `dev`) があっても共存できる。そちらには触れない。

## クラスタの作成

リポジトリのルートで実行する。

```sh
make cluster-up    # クラスタ k8s-test-harness-lab を作成 (既にあれば何もしない)
make deploy        # manifest/overlays/local を適用
make verify        # NameSpace と ingress の到達性を確認
```

`make verify` が最後に次の行を出せば完了。

```
ingress http://localhost:8080/ -> 404 (traefik の 404 なら到達している)
```

作成されるもの:

| 項目 | 値 |
| --- | --- |
| クラスタ名 | `k8s-test-harness-lab` |
| kubectl context | `k3d-k8s-test-harness-lab` |
| ノード | `k3d-k8s-test-harness-lab-server-0` / `k3d-k8s-test-harness-lab-agent-0` |
| 定義 | [cluster/k3d.yaml](../cluster/k3d.yaml) |

`make cluster-up` は `~/.kube/config` に context を追加するが、**current-context は切り替えない**。

## kubectl の context

### 確認

```sh
kubectl config get-contexts       # 一覧 (* が今の向き先)
kubectl config current-context    # 今の向き先だけ表示
```

### 切り替え

```sh
kubectl config use-context k3d-k8s-test-harness-lab   # このリポジトリのクラスタへ
kubectl config use-context k3d-dev                    # 元のクラスタへ戻す (例)
```

`use-context` は `~/.kube/config` を書き換えるため、他のターミナルも含めて向き先が変わる。

### 切り替えずに使う

1コマンドだけ向き先を指定する。

```sh
kubectl --context k3d-k8s-test-harness-lab get ns
```

`make` の各ターゲットは常に `--context k3d-k8s-test-harness-lab` を付けて実行するため、
current-context がどこを向いていても影響しない。

## 削除と作り直し

```sh
make cluster-down                 # クラスタと context を削除
make cluster-up && make deploy    # 作り直し
```

クラスタ内のデータ (Keycloak / MySQL / minio) は揮発する前提。作り直しで消えてよい。

## トラブルシュート

| 症状 | 原因と対処 |
| --- | --- |
| `kubectl get ns` に `idp` などが出ない | current-context が別クラスタを向いている。`kubectl config current-context` で確認し、`--context` を付けるか切り替える |
| `make cluster-up` がポート競合で失敗する | `8080` / `8443` / `6550` を他プロセスが使用中。`ss -ltn` で確認する |
| 作成直後に `localhost:8080` へつながらない | traefik は k3s 起動後に入り、ポートが開くまで数十秒かかる。`make verify` は待つので、それを使う |
