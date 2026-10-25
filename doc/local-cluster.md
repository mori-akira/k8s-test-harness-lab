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
make verify        # NameSpace / ingress の到達性と、Keycloak の issuer がホストと Pod で一致することを確認
```

`make verify` が最後に次の行を出せば完了。

```
OK: issuer がホストと Pod で一致
```

作成されるもの:

| 項目 | 値 |
| --- | --- |
| クラスタ名 | `k8s-test-harness-lab` |
| kubectl context | `k3d-k8s-test-harness-lab` |
| ノード | `k3d-k8s-test-harness-lab-server-0` / `k3d-k8s-test-harness-lab-agent-0` |
| 定義 | [cluster/k3d.yaml](../cluster/k3d.yaml) |

`make cluster-up` は `~/.kube/config` に context を追加するが、**current-context は切り替えない**。

## Keycloak を開く

`make deploy` 後、ホストのブラウザ (Windows 側のブラウザでも可) で開ける。

| 画面 | URL | ログイン |
| --- | --- | --- |
| 管理コンソール | http://keycloak.localtest.me:8080/admin/ | `admin` / `admin` |
| テストユーザのアカウント画面 | http://keycloak.localtest.me:8080/realms/lab/account | `ci-01`〜`ci-06` / `ci-password`、`human-01`〜`human-04` / `human-password` |
| issuer (OIDC discovery) | http://keycloak.localtest.me:8080/realms/lab/.well-known/openid-configuration | — |

値は local 専用のダミー ([manifest/overlays/local/idp-secret.yaml](../manifest/overlays/local/idp-secret.yaml))。
Keycloak は H2 (揮発) で動いており、Pod が作り直されると realm JSON から同じユーザ群が戻る。
管理コンソールで行った変更は Pod の再作成で消える。残したい変更は realm JSON に書く。

## front を開く

ブラウザで http://front.localhost:8080 を開き、「ログイン」→ Keycloak のログイン画面で `ci-01` / `ci-password` などを入れる。
ログイン後はノートの追加・削除ができる。ユーザを変えると別のノートが見える。

## api-a を叩く

`http://api-a.localtest.me:8080` で Ingress 経由で届く。Keycloak の `test-runner` クライアントで取ったトークンを付ける。

```sh
TOKEN=$(curl -s -d grant_type=password -d client_id=test-runner -d username=ci-01 -d password=ci-password \
  http://keycloak.localtest.me:8080/realms/lab/protocol/openid-connect/token | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H 'X-Test-Run-Id: manual' \
  -d '{"title":"hello"}' http://api-a.localtest.me:8080/notes
curl -s -H "Authorization: Bearer $TOKEN" http://api-a.localtest.me:8080/notes
```

API ドキュメント (FastAPI の Swagger UI): http://api-a.localtest.me:8080/docs

`app/` を変更したら `make deploy` でビルド・取り込み・再起動まで行う。

## export Job を起動する

```sh
scripts/run-export-job.sh manual-01     # Job export-manual-01 を起動 (run-id は英小文字・数字・ハイフン)
kubectl --context k3d-k8s-test-harness-lab -n job logs job/export-manual-01
kubectl --context k3d-k8s-test-harness-lab -n db exec deploy/redis -- redis-cli HGETALL export:manual-01
```

run-id が `manual-01` の note (api-a に `X-Test-Run-Id: manual-01` を付けて作ったもの) が集計される。
同じ run-id で再実行するときは、先に `kubectl ... -n job delete job/export-manual-01` する。

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

クラスタ内のデータ (Keycloak / Redis / minio) は揮発する前提。作り直しで消えてよい。

Keycloak だけ作り直す場合: `kubectl --context k3d-k8s-test-harness-lab -n idp delete pod -l app=keycloak`

## トラブルシュート

| 症状 | 原因と対処 |
| --- | --- |
| `kubectl get ns` に `idp` などが出ない | current-context が別クラスタを向いている。`kubectl config current-context` で確認し、`--context` を付けるか切り替える |
| `make cluster-up` がポート競合で失敗する | `8080` / `8443` / `6550` を他プロセスが使用中。`ss -ltn` で確認する |
| ブラウザで `keycloak.localtest.me` が開けない | 社内 DNS などが 127.0.0.1 への解決をブロックしている可能性がある。hosts ファイル (Windows は `C:\Windows\System32\drivers\etc\hosts`) に `127.0.0.1 keycloak.localtest.me` を追記する |
| ログイン時に `Crypto.subtle is available only in secure contexts` | front を `front.localhost` 以外のホスト名で開いている。http では `localhost` / `*.localhost` だけが secure context になる |
| `front.localhost` が curl 以外のツール (Python, PowerShell 等) で解決できない | ブラウザと curl は `*.localhost` を自前で loopback に解決するが、OS のリゾルバは解決しない。必要なら hosts に `127.0.0.1 front.localhost` を足す |
| Pod から `keycloak.localtest.me` に届かない | CoreDNS が `coredns-custom` を取り込んでいない。`make deploy` を再実行するか、`kubectl --context k3d-k8s-test-harness-lab -n kube-system rollout restart deploy/coredns` |
| 作成直後に `localhost:8080` へつながらない | traefik は k3s 起動後に入り、ポートが開くまで数十秒かかる。`make verify` は待つので、それを使う |
