// =========================================================
// Kratos Juris — Web Push (frontend)
// Pede permissão e registra a inscrição no backend.
// Carregado no base.html, roda só quando há usuário logado.
// =========================================================

(function () {
  "use strict";

  // Só faz sentido se o navegador suportar push + service worker
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return;
  }

  // Converte a chave pública (base64url) para o formato que o navegador exige
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = window.atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function getPublicKey() {
    const r = await fetch("/push/public-key", { credentials: "same-origin" });
    const data = await r.json();
    return data.publicKey;
  }

  async function subscribe() {
    try {
      const reg = await navigator.serviceWorker.ready;

      // Já inscrito? não repete
      let sub = await reg.pushManager.getSubscription();

      if (!sub) {
        const publicKey = await getPublicKey();
        if (!publicKey) {
          console.log("[PUSH] sem chave pública configurada");
          return;
        }

        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey),
        });
      }

      // Manda a inscrição para o backend salvar no Neon
      await fetch("/push/subscribe", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub),
      });

      console.log("[PUSH] inscrição registrada");
    } catch (err) {
      console.log("[PUSH] falha ao inscrever:", err);
    }
  }

  // Pede permissão de forma educada (não no primeiro instante da página).
  // Dispara após um pequeno gesto/tempo para não assustar o usuário.
  function askPermissionAndSubscribe() {
    if (Notification.permission === "granted") {
      subscribe();
      return;
    }
    if (Notification.permission === "denied") {
      return; // usuário já negou; respeita
    }
    Notification.requestPermission().then(function (perm) {
      if (perm === "granted") subscribe();
    });
  }

  // Expõe um gatilho manual (ex.: botão "Ativar notificações")
  window.kjEnableNotifications = askPermissionAndSubscribe;

  // Tenta automaticamente alguns segundos após o load, uma vez por sessão.
  window.addEventListener("load", function () {
    if (sessionStorage.getItem("kj_push_asked") === "1") {
      if (Notification.permission === "granted") subscribe();
      return;
    }
    setTimeout(function () {
      sessionStorage.setItem("kj_push_asked", "1");
      askPermissionAndSubscribe();
    }, 4000);
  });
})();