FROM nginx:1.27-alpine
# OIDC クライアントはビルド時に取得して同梱する (実行時に CDN へ依存しない)
# (この環境の docker は BuildKit が無く ADD --chmod が使えないため wget で取る)
RUN mkdir -p /usr/share/nginx/html/vendor && \
    wget -qO /usr/share/nginx/html/vendor/oidc-client-ts.min.js \
      https://cdn.jsdelivr.net/npm/oidc-client-ts@3.4.1/dist/browser/oidc-client-ts.min.js
# nginx イメージは起動時に /etc/nginx/templates/*.template の ${VAR} を環境変数で置換する
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY public/ /usr/share/nginx/html/
EXPOSE 8080
