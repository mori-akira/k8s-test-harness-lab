// 認可コード + PKCE でログインし、アクセストークンで api-a を呼ぶだけの SPA。破棄前提。
const cfg = window.APP_CONFIG;
const $ = (id) => document.getElementById(id);

const mgr = new oidc.UserManager({
  authority: cfg.issuer,
  client_id: cfg.clientId,
  redirect_uri: `${location.origin}/`,
  post_logout_redirect_uri: `${location.origin}/`,
  response_type: "code", // PKCE は oidc-client-ts が自動で付ける (S256)
  scope: "openid profile email",
});

function showError(e) {
  $("error").textContent = String(e);
  $("error").hidden = false;
}

async function api(user, method, path, body) {
  const res = await fetch(`${cfg.apiBase}${path}`, {
    method,
    headers: { Authorization: `Bearer ${user.access_token}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

async function renderNotes(user) {
  const list = $("note-list");
  list.replaceChildren();
  for (const note of await api(user, "GET", "/notes")) {
    const li = document.createElement("li");
    li.dataset.testid = "note";
    const title = document.createElement("span");
    title.textContent = note.title;
    const del = document.createElement("button");
    del.textContent = "削除";
    del.dataset.testid = "note-delete";
    del.onclick = async () => {
      await api(user, "DELETE", `/notes/${note.id}`).catch(showError);
      await renderNotes(user).catch(showError);
    };
    li.append(title, del);
    list.append(li);
  }
}

async function main() {
  // Keycloak からのリダイレクトで戻ってきた場合はコードをトークンに交換する
  const params = new URLSearchParams(location.search);
  if (params.has("code") || params.has("error")) {
    await mgr.signinRedirectCallback();
    history.replaceState({}, "", "/");
  }

  const user = await mgr.getUser();
  if (!user || user.expired) {
    $("login-view").hidden = false;
    $("login").onclick = () => mgr.signinRedirect().catch(showError);
    return;
  }

  $("app-view").hidden = false;
  $("username").textContent = user.profile.preferred_username;
  $("logout").onclick = () => mgr.signoutRedirect({ id_token_hint: user.id_token }).catch(showError);
  $("create-form").onsubmit = async (ev) => {
    ev.preventDefault();
    await api(user, "POST", "/notes", { title: $("note-title").value }).catch(showError);
    $("note-title").value = "";
    await renderNotes(user).catch(showError);
  };
  await renderNotes(user);
}

main().catch(showError);
