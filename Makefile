CLUSTER  := k8s-test-harness-lab
CONTEXT  := k3d-$(CLUSTER)
KUBECTL  := kubectl --context $(CONTEXT)

.PHONY: cluster-up cluster-down render deploy verify

cluster-up: ## k3d クラスタを作成する (既にあれば何もしない)
	@k3d cluster list $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml
	$(KUBECTL) wait --for=condition=Ready nodes --all --timeout=120s

cluster-down: ## k3d クラスタを削除する
	k3d cluster delete $(CLUSTER)

render: ## local overlay をレンダリングして標準出力に出す
	kubectl kustomize manifest/overlays/local

deploy: ## local overlay を適用する
	$(KUBECTL) apply -k manifest/overlays/local

verify: ## Step 1 の確認: NameSpace と ingress の到達性
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
