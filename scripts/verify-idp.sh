#!/bin/sh
# Step 2 の確認: ホストとクラスタ内 Pod の両方から同一の issuer で Keycloak に到達できること。
set -eu
CONTEXT="${CONTEXT:-k3d-k8s-test-harness-lab}"
ISSUER="${ISSUER:-http://keycloak.localtest.me:8080/realms/lab}"
CURL_IMAGE="curlimages/curl:8.11.1"
KUBECTL="kubectl --context $CONTEXT"

issuer_of() { python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])'; }
iss_of_token() {
  python3 -c '
import base64, json, sys
p = json.load(sys.stdin)["access_token"].split(".")[1]
print(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["iss"])'
}

password=$($KUBECTL -n idp get secret keycloak-secrets -o jsonpath='{.data.user-password-ci}' | base64 -d)

host_issuer=$(curl -sf "$ISSUER/.well-known/openid-configuration" | issuer_of)
echo "host issuer : $host_issuer"

# make deploy で CoreDNS を再起動しているが、起動直後の取りこぼしに備えて Pod 側は数回リトライする
errf=$(mktemp); trap 'rm -f "$errf"' EXIT
pod_out=""
for i in $(seq 5); do
  pod_out=$($KUBECTL -n api-a run "issuer-check-$$-$i" --rm -i --restart=Never --quiet --image="$CURL_IMAGE" -- \
    sh -c "curl -sf $ISSUER/.well-known/openid-configuration && echo && \
           curl -sf -d grant_type=password -d client_id=admin-cli -d username=ci-01 \
             --data-urlencode password='$password' $ISSUER/protocol/openid-connect/token" 2>"$errf") && break
  pod_out=""; sleep 5
done
test -n "$pod_out" || { cat "$errf"; echo "pod から $ISSUER に到達できない (CoreDNS の rewrite を確認)"; exit 1; }

pod_issuer=$(echo "$pod_out" | sed -n 1p | issuer_of)
token_iss=$(echo "$pod_out" | sed -n 2p | iss_of_token)
echo "pod issuer  : $pod_issuer"
echo "token iss   : $token_iss (ci-01 でログイン)"

test "$host_issuer" = "$ISSUER" && test "$pod_issuer" = "$ISSUER" && test "$token_iss" = "$ISSUER"
echo "OK: issuer がホストと Pod で一致"
