CLUSTER  := k8s-test-harness-lab
CONTEXT  := k3d-$(CLUSTER)
KUBECTL  := kubectl --context $(CONTEXT)

APPS     := api-a front

.PHONY: cluster-up cluster-down images render deploy verify

cluster-up: ## k3d クラスタを作成する (既にあれば何もしない)
	@k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml
	$(KUBECTL) wait --for=condition=Ready nodes --all --timeout=120s

cluster-down: ## k3d クラスタを削除する
	k3d cluster delete $(CLUSTER)

images: ## app/ 配下をビルドして k3d に import する
	@for app in $(APPS); do \
	  docker build -q -t $$app:local app/$$app && \
	  k3d image import -c $(CLUSTER) $$app:local >/dev/null && echo "imported $$app:local" || exit 1; \
	done

render: ## local overlay をレンダリングして標準出力に出す
	kubectl kustomize manifest/overlays/local

deploy: images ## イメージを取り込み、local overlay を適用する
	$(KUBECTL) apply -k manifest/overlays/local
	@# coredns-custom の変更は reload を待つと1分以上かかるため、再起動して即時に反映させる
	$(KUBECTL) -n kube-system rollout restart deploy/coredns
	$(KUBECTL) -n kube-system rollout status deploy/coredns --timeout=120s
	$(KUBECTL) -n idp rollout status deploy/keycloak --timeout=300s
	$(KUBECTL) -n db rollout status deploy/redis --timeout=120s
	@# イメージのタグは local 固定なので、ビルドし直した分を反映するため再起動する
	@for app in $(APPS); do \
	  $(KUBECTL) -n $$app rollout restart deploy/$$app && \
	  $(KUBECTL) -n $$app rollout status deploy/$$app --timeout=120s || exit 1; \
	done

verify: ## NameSpace / ingress (Step 1)、issuer の一致 (Step 2)、api-a の認可と sub 分離 (Step 3)、front の認可コード + PKCE と CORS (Step 4) を確認する
	$(KUBECTL) get ns -l app.kubernetes.io/part-of=k8s-test-harness-lab
	@# traefik は k3s 起動後に HelmChart の Job で入るため、Job の完了を待ってから見る
	@until $(KUBECTL) -n kube-system get job helm-install-traefik >/dev/null 2>&1; do sleep 2; done
	$(KUBECTL) -n kube-system wait --for=condition=complete job/helm-install-traefik --timeout=180s
	$(KUBECTL) -n kube-system rollout status deploy/traefik --timeout=120s
	@# rollout 完了後も svclb がポートを開くまで数秒かかるのでリトライする
	@for i in $$(seq 30); do \
	  code=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/); \
	  test "$$code" = 404 && break; sleep 2; \
	done; \
	echo "ingress http://localhost:8080/ -> $$code (traefik の 404 なら到達している)"; \
	test "$$code" = 404
	CONTEXT=$(CONTEXT) scripts/verify-idp.sh
	CONTEXT=$(CONTEXT) scripts/verify-api.py
	CONTEXT=$(CONTEXT) scripts/verify-front.py
