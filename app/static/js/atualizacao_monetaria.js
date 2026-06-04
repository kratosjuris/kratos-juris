let lancamentos = [];
let deducoes = [];

function limparMoeda(valor) {
  if (!valor) return "0,00";
  return String(valor).replace("R$", "").trim();
}

function adicionarLancamento() {
  const tipo = document.getElementById("lanc_tipo").value;
  const data = document.getElementById("lanc_data").value;
  const descricao = document.getElementById("lanc_descricao").value;
  const valor = limparMoeda(document.getElementById("lanc_valor").value);

  if (!data || !valor) {
    alert("Informe a data e o valor do lançamento.");
    return;
  }

  lancamentos.push({
    tipo: tipo,
    data: data,
    descricao: descricao,
    valor: valor
  });

  document.getElementById("lanc_data").value = "";
  document.getElementById("lanc_descricao").value = "";
  document.getElementById("lanc_valor").value = "";

  renderLancamentos();
}

function excluirLancamento(index) {
  if (!confirm("Deseja excluir este lançamento?")) return;
  lancamentos.splice(index, 1);
  renderLancamentos();
}

function editarLancamento(index) {
  const item = lancamentos[index];

  document.getElementById("lanc_tipo").value = item.tipo;
  document.getElementById("lanc_data").value = item.data;
  document.getElementById("lanc_descricao").value = item.descricao;
  document.getElementById("lanc_valor").value = item.valor;

  lancamentos.splice(index, 1);
  renderLancamentos();
}

function gerarLote() {
  const tipo = document.getElementById("lote_tipo").value;
  const dataInicial = document.getElementById("lote_data").value;
  const nome = document.getElementById("lote_nome").value || "Parcela";
  const valor = limparMoeda(document.getElementById("lote_valor").value);
  const qtd = parseInt(document.getElementById("lote_qtd").value || "0");

  if (!dataInicial || !valor || qtd <= 0) {
    alert("Informe data inicial, valor e quantidade de parcelas.");
    return;
  }

  const partes = dataInicial.split("-");
  let ano = parseInt(partes[0]);
  let mes = parseInt(partes[1]) - 1;
  let dia = parseInt(partes[2]);

  for (let i = 0; i < qtd; i++) {
    let data = new Date(ano, mes + i, dia);

    if (data.getDate() !== dia) {
      data = new Date(data.getFullYear(), data.getMonth() + 1, 0);
    }

    const yyyy = data.getFullYear();
    const mm = String(data.getMonth() + 1).padStart(2, "0");
    const dd = String(data.getDate()).padStart(2, "0");

    lancamentos.push({
      tipo: tipo,
      data: `${yyyy}-${mm}-${dd}`,
      descricao: `${nome} ${String(i + 1).padStart(2, "0")}/${String(qtd).padStart(2, "0")}`,
      valor: valor
    });
  }

  document.getElementById("lote_data").value = "";
  document.getElementById("lote_nome").value = "";
  document.getElementById("lote_valor").value = "";
  document.getElementById("lote_qtd").value = "";

  renderLancamentos();
}

function renderLancamentos() {
  const tbody = document.getElementById("tbodyLancamentos");

  if (!lancamentos.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="text-muted">Nenhum lançamento adicionado.</td>
      </tr>
    `;
    atualizarHidden();
    return;
  }

  tbody.innerHTML = "";

  lancamentos.forEach((item, index) => {
    tbody.innerHTML += `
      <tr>
        <td>${formatarData(item.data)}</td>
        <td>${item.tipo}</td>
        <td>${item.descricao || ""}</td>
        <td>R$ ${item.valor}</td>
        <td>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarLancamento(${index})">
            Editar
          </button>
          <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirLancamento(${index})">
            Excluir
          </button>
        </td>
      </tr>
    `;
  });

  atualizarHidden();
}

function adicionarDeducao() {
  const nome = document.getElementById("ded_nome").value || "Dedução";
  const tipo = document.getElementById("ded_tipo").value;
  const valor = limparMoeda(document.getElementById("ded_valor").value);
  const percentual = document.getElementById("ded_percentual").value || "0";

  if (tipo === "valor" && (!valor || valor === "0,00")) {
    alert("Informe o valor da dedução.");
    return;
  }

  if (tipo === "percentual" && (!percentual || percentual === "0")) {
    alert("Informe o percentual da dedução.");
    return;
  }

  deducoes.push({
    nome: nome,
    tipo: tipo,
    valor: valor,
    percentual: percentual
  });

  document.getElementById("ded_nome").value = "";
  document.getElementById("ded_valor").value = "";
  document.getElementById("ded_percentual").value = "";

  renderDeducoes();
}

function editarDeducao(index) {
  const item = deducoes[index];

  document.getElementById("ded_nome").value = item.nome;
  document.getElementById("ded_tipo").value = item.tipo;
  document.getElementById("ded_valor").value = item.valor;
  document.getElementById("ded_percentual").value = item.percentual;

  deducoes.splice(index, 1);
  renderDeducoes();
}

function excluirDeducao(index) {
  if (!confirm("Deseja excluir esta dedução?")) return;
  deducoes.splice(index, 1);
  renderDeducoes();
}

function renderDeducoes() {
  const tbody = document.getElementById("tbodyDeducoes");

  if (!deducoes.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" class="text-muted">Nenhuma dedução adicionada.</td>
      </tr>
    `;
    atualizarHidden();
    return;
  }

  tbody.innerHTML = "";

  deducoes.forEach((item, index) => {
    const ref = item.tipo === "percentual" ? `${item.percentual}%` : `R$ ${item.valor}`;

    tbody.innerHTML += `
      <tr>
        <td>${item.nome}</td>
        <td>${item.tipo === "percentual" ? "Percentual" : "Valor fixo"}</td>
        <td>${ref}</td>
        <td>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarDeducao(${index})">
            Editar
          </button>
          <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirDeducao(${index})">
            Excluir
          </button>
        </td>
      </tr>
    `;
  });

  atualizarHidden();
}

function atualizarHidden() {
  const lancamentosInput = document.getElementById("lancamentos_json");
  const deducoesInput = document.getElementById("deducoes_json");

  if (lancamentosInput) {
    lancamentosInput.value = JSON.stringify(lancamentos);
  }

  if (deducoesInput) {
    deducoesInput.value = JSON.stringify(deducoes);
  }
}

function formatarData(dataIso) {
  if (!dataIso) return "";
  const partes = dataIso.split("-");
  if (partes.length !== 3) return dataIso;
  return `${partes[2]}/${partes[1]}/${partes[0]}`;
}

document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("formCalculo");

  if (form) {
    form.addEventListener("submit", function () {
      atualizarHidden();
    });
  }
});