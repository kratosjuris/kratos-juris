/**
 * tasks.js
 * - Drag-and-drop entre colunas do kanban (tasks/kanban.html)
 * - Polling do sino de notificações
 *
 * Requer no base.html:
 *   <span id="notif-bell-count"></span>
 *   <div id="notif-bell-list"></div>
 */

(function () {
  "use strict";

  function initKanban() {
    const dropzones = document.querySelectorAll(".kanban-dropzone");
    if (!dropzones.length) return;

    document.querySelectorAll(".kanban-card").forEach((card) => {
      card.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", card.dataset.tarefaId);
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", () => card.classList.remove("dragging"));
    });

    dropzones.forEach((zone) => {
      zone.addEventListener("dragover", (e) => e.preventDefault());

      zone.addEventListener("drop", async (e) => {
        e.preventDefault();
        const tarefaId = e.dataTransfer.getData("text/plain");
        const novoStatus = zone.dataset.status;
        if (!tarefaId || !novoStatus) return;

        try {
          const resp = await fetch(`/tarefas/api/${tarefaId}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: novoStatus }),
          });
          const data = await resp.json();

          if (data.ok) {
            window.location.reload();
          } else {
            alert(data.erro || "Não foi possível mover a tarefa para essa coluna.");
          }
        } catch (err) {
          console.error("Erro ao atualizar status da tarefa:", err);
          alert("Erro de conexão ao atualizar a tarefa.");
        }
      });
    });
  }

  const NOTIF_POLL_INTERVAL_MS = 45000;

  async function carregarNotificacoes() {
    const badge = document.getElementById("notif-bell-count");
    const lista = document.getElementById("notif-bell-list");
    if (!badge && !lista) return;

    try {
      const resp = await fetch("/tarefas/api/notificacoes");
      const data = await resp.json();

      if (badge) {
        badge.textContent = data.nao_lidas > 0 ? data.nao_lidas : "";
        badge.style.display = data.nao_lidas > 0 ? "inline-block" : "none";
      }

      if (lista) {
        lista.innerHTML = "";
        data.itens.forEach((n) => {
          const item = document.createElement("a");
          item.className = "dropdown-item small" + (n.lida ? "" : " fw-semibold");
          item.href = n.tarefa_id ? `/tarefas/${n.tarefa_id}` : "#";
          item.textContent = `${n.mensagem} — ${n.criado_em}`;
          item.addEventListener("click", () => marcarComoLida(n.id));
          lista.appendChild(item);
        });
      }
    } catch (err) {
      console.error("Erro ao buscar notificações:", err);
    }
  }

  async function marcarComoLida(notificacaoId) {
    try {
      await fetch(`/tarefas/api/notificacoes/${notificacaoId}/lida`, { method: "POST" });
    } catch (err) {
      console.error("Erro ao marcar notificação como lida:", err);
    }
  }

  function initNotificacoes() {
    carregarNotificacoes();
    setInterval(carregarNotificacoes, NOTIF_POLL_INTERVAL_MS);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initKanban();
    initNotificacoes();
  });
})();