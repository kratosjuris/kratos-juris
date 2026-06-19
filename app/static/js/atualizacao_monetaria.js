let lancamentos = [];
let deducoes    = [];
let multas      = [];
let honorarios  = [];

let editandoLancamentoIndex = null;
let editandoDeducaoIndex    = null;
let editandoMultaIndex      = null;
let editandoHonorarioIndex  = null;

// ---------------------------------------------------------------------------
// Utilitários
// ---------------------------------------------------------------------------
function limparMoeda(v) {
  return v ? String(v).replace("R$","").trim() : "0,00";
}
function formatarData(iso) {
  if (!iso) return "";
  const p = iso.split("-");
  return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : iso;
}
function atualizarHidden() {
  const set = (id, arr) => { const el = document.getElementById(id); if (el) el.value = JSON.stringify(arr); };
  set("lancamentos_json", lancamentos);
  set("deducoes_json",    deducoes);
  set("multas_json",      multas);
  set("honorarios_json",  honorarios);
}

// ---------------------------------------------------------------------------
// Lançamentos
// ---------------------------------------------------------------------------
function adicionarLancamento() {
  const tipo      = document.getElementById("lanc_tipo").value;
  const data      = document.getElementById("lanc_data").value;
  const descricao = document.getElementById("lanc_descricao").value;
  const valor     = limparMoeda(document.getElementById("lanc_valor").value);
  if (!data || !valor) { alert("Informe a data e o valor."); return; }
  // Sempre adiciona novo — edição é feita inline na tabela
  lancamentos.push({ tipo, data, descricao, valor });
  document.getElementById("lanc_data").value = "";
  document.getElementById("lanc_descricao").value = "";
  document.getElementById("lanc_valor").value = "";
  renderLancamentos();
}
function editarLancamento(i) {
  // Salva qualquer edição anterior antes de abrir nova
  if (editandoLancamentoIndex !== null && editandoLancamentoIndex !== i) {
    confirmarEdicaoLancamento(editandoLancamentoIndex);
  }
  editandoLancamentoIndex = i;
  renderLancamentos();
}

function confirmarEdicaoLancamento(i) {
  const tipo      = document.getElementById(`edit_lanc_tipo_${i}`).value;
  const data      = document.getElementById(`edit_lanc_data_${i}`).value;
  const descricao = document.getElementById(`edit_lanc_desc_${i}`).value;
  const valor     = limparMoeda(document.getElementById(`edit_lanc_valor_${i}`).value);
  if (!data || !valor) { alert("Informe a data e o valor."); return; }
  lancamentos[i] = { tipo, data, descricao, valor };
  editandoLancamentoIndex = null;
  renderLancamentos();
}

function cancelarEdicaoLancamento() {
  editandoLancamentoIndex = null;
  renderLancamentos();
}

function excluirLancamento(i) {
  if (!confirm("Excluir este lançamento?")) return;
  if (editandoLancamentoIndex === i) editandoLancamentoIndex = null;
  lancamentos.splice(i,1);
  renderLancamentos();
}

function renderLancamentos() {
  const tbody = document.getElementById("tbodyLancamentos");
  if (!lancamentos.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-muted">Nenhum lançamento adicionado.</td></tr>`;
    atualizarHidden(); return;
  }

  const tiposOpts = ["Dano Material","Dano Moral","Parcela Contratual","Restituição","Indenização","Outro"];

  let html = "";
  lancamentos.forEach((item, i) => {
    if (editandoLancamentoIndex === i) {
      // Linha editável inline
      const optsHtml = tiposOpts.map(t =>
        `<option value="${t}"${t===item.tipo?" selected":""}>${t}</option>`
      ).join("");
      html += `
      <tr class="table-warning">
        <td><input type="date" id="edit_lanc_data_${i}" class="form-control form-control-sm" value="${item.data}"></td>
        <td><select id="edit_lanc_tipo_${i}" class="form-select form-select-sm">${optsHtml}</select></td>
        <td><input type="text" id="edit_lanc_desc_${i}" class="form-control form-control-sm" value="${item.descricao||""}"></td>
        <td><input type="text" id="edit_lanc_valor_${i}" class="form-control form-control-sm" value="${item.valor}"></td>
        <td>
          <button type="button" class="btn btn-success btn-sm" onclick="confirmarEdicaoLancamento(${i})">✓ Salvar</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="cancelarEdicaoLancamento()">✕</button>
        </td>
      </tr>`;
    } else {
      html += `
      <tr>
        <td>${formatarData(item.data)}</td>
        <td>${item.tipo}</td>
        <td>${item.descricao||""}</td>
        <td>R$ ${item.valor}</td>
        <td>
          <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarLancamento(${i})">Editar</button>
          <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirLancamento(${i})">Excluir</button>
        </td>
      </tr>`;
    }
  });

  tbody.innerHTML = html;
  atualizarHidden();
}

// ---------------------------------------------------------------------------
// Lote
// ---------------------------------------------------------------------------
function gerarLote() {
  const tipo  = document.getElementById("lote_tipo").value;
  const di    = document.getElementById("lote_data").value;
  const nome  = document.getElementById("lote_nome").value || "Parcela";
  const valor = limparMoeda(document.getElementById("lote_valor").value);
  const qtd   = parseInt(document.getElementById("lote_qtd").value||"0");
  if (!di||!valor||qtd<=0) { alert("Informe data inicial, valor e quantidade."); return; }
  const p = di.split("-"); const ano=+p[0], mes=+p[1]-1, dia=+p[2];
  for (let i=0;i<qtd;i++) {
    let d = new Date(ano, mes+i, dia);
    if (d.getDate()!==dia) d = new Date(d.getFullYear(), d.getMonth()+1, 0);
    const yyyy=d.getFullYear(), mm=String(d.getMonth()+1).padStart(2,"0"), dd=String(d.getDate()).padStart(2,"0");
    lancamentos.push({ tipo, data:`${yyyy}-${mm}-${dd}`, descricao:`${nome} ${String(i+1).padStart(2,"0")}/${String(qtd).padStart(2,"0")}`, valor });
  }
  ["lote_data","lote_nome","lote_valor","lote_qtd"].forEach(id => document.getElementById(id).value="");
  renderLancamentos();
}

// ---------------------------------------------------------------------------
// Multas
// ---------------------------------------------------------------------------
function adicionarMulta() {
  const descricao  = document.getElementById("mul_descricao").value || "Multa";
  const tipo       = document.getElementById("mul_tipo").value;
  const valor      = limparMoeda(document.getElementById("mul_valor").value);
  const percentual = document.getElementById("mul_percentual").value || "0";
  if (tipo==="valor" && (!valor||valor==="0,00")) { alert("Informe o valor da multa."); return; }
  if (tipo==="percentual" && (!percentual||percentual==="0")) { alert("Informe o percentual da multa."); return; }
  const item = { descricao, tipo, valor, percentual };
  if (editandoMultaIndex !== null) {
    multas[editandoMultaIndex] = item;
    editandoMultaIndex = null;
    document.getElementById("mul_btn_add").textContent = "+";
  } else {
    multas.push(item);
  }
  document.getElementById("mul_descricao").value = "";
  document.getElementById("mul_valor").value = "";
  document.getElementById("mul_percentual").value = "";
  renderMultas();
}
function editarMulta(i) {
  const item = multas[i];
  document.getElementById("mul_descricao").value  = item.descricao;
  document.getElementById("mul_tipo").value       = item.tipo;
  document.getElementById("mul_valor").value      = item.valor;
  document.getElementById("mul_percentual").value = item.percentual;
  // Atualiza visibilidade dos campos
  document.getElementById("mul_campo_valor").classList.toggle("d-none", item.tipo==="percentual");
  document.getElementById("mul_campo_percentual").classList.toggle("d-none", item.tipo!=="percentual");
  editandoMultaIndex = i;
  document.getElementById("mul_btn_add").textContent = "✓";
}
function excluirMulta(i) {
  if (!confirm("Excluir esta multa?")) return;
  if (editandoMultaIndex===i) { editandoMultaIndex=null; document.getElementById("mul_btn_add").textContent="+"; }
  multas.splice(i,1); renderMultas();
}
function renderMultas() {
  const tbody = document.getElementById("tbodyMultas");
  if (!multas.length) { tbody.innerHTML=`<tr><td colspan="4" class="text-muted">Nenhuma multa adicionada.</td></tr>`; atualizarHidden(); return; }
  let html="";
  multas.forEach((item,i) => {
    const cls = editandoMultaIndex===i ? ' class="table-warning"' : "";
    const ref = item.tipo==="percentual" ? `${item.percentual}%` : `R$ ${item.valor}`;
    html+=`<tr${cls}><td>${item.descricao}</td><td>${item.tipo==="percentual"?"Percentual":"Valor fixo"}</td><td>${ref}</td><td>
      <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarMulta(${i})">Editar</button>
      <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirMulta(${i})">Excluir</button>
    </td></tr>`;
  });
  tbody.innerHTML=html; atualizarHidden();
}

// ---------------------------------------------------------------------------
// Honorários
// ---------------------------------------------------------------------------
function adicionarHonorario() {
  const descricao  = document.getElementById("hon_descricao").value || "Honorários";
  const tipo       = document.getElementById("hon_tipo").value;
  const valor      = limparMoeda(document.getElementById("hon_valor").value);
  const percentual = document.getElementById("hon_percentual").value || "0";
  if (tipo==="valor" && (!valor||valor==="0,00")) { alert("Informe o valor dos honorários."); return; }
  if (tipo==="percentual" && (!percentual||percentual==="0")) { alert("Informe o percentual dos honorários."); return; }
  const item = { descricao, tipo, valor, percentual };
  if (editandoHonorarioIndex !== null) {
    honorarios[editandoHonorarioIndex] = item;
    editandoHonorarioIndex = null;
    document.getElementById("hon_btn_add").textContent = "+";
  } else {
    honorarios.push(item);
  }
  document.getElementById("hon_descricao").value = "";
  document.getElementById("hon_valor").value = "";
  document.getElementById("hon_percentual").value = "";
  renderHonorarios();
}
function editarHonorario(i) {
  const item = honorarios[i];
  document.getElementById("hon_descricao").value  = item.descricao;
  document.getElementById("hon_tipo").value       = item.tipo;
  document.getElementById("hon_valor").value      = item.valor;
  document.getElementById("hon_percentual").value = item.percentual;
  document.getElementById("hon_campo_valor").classList.toggle("d-none", item.tipo==="percentual");
  document.getElementById("hon_campo_percentual").classList.toggle("d-none", item.tipo!=="percentual");
  editandoHonorarioIndex = i;
  document.getElementById("hon_btn_add").textContent = "✓";
}
function excluirHonorario(i) {
  if (!confirm("Excluir este honorário?")) return;
  if (editandoHonorarioIndex===i) { editandoHonorarioIndex=null; document.getElementById("hon_btn_add").textContent="+"; }
  honorarios.splice(i,1); renderHonorarios();
}
function renderHonorarios() {
  const tbody = document.getElementById("tbodyHonorarios");
  if (!honorarios.length) { tbody.innerHTML=`<tr><td colspan="4" class="text-muted">Nenhum honorário adicionado.</td></tr>`; atualizarHidden(); return; }
  let html="";
  honorarios.forEach((item,i) => {
    const cls = editandoHonorarioIndex===i ? ' class="table-warning"' : "";
    const ref = item.tipo==="percentual" ? `${item.percentual}%` : `R$ ${item.valor}`;
    html+=`<tr${cls}><td>${item.descricao}</td><td>${item.tipo==="percentual"?"Percentual":"Valor fixo"}</td><td>${ref}</td><td>
      <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarHonorario(${i})">Editar</button>
      <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirHonorario(${i})">Excluir</button>
    </td></tr>`;
  });
  tbody.innerHTML=html; atualizarHidden();
}

// ---------------------------------------------------------------------------
// Deduções
// ---------------------------------------------------------------------------
function adicionarDeducao() {
  const nome       = document.getElementById("ded_nome").value || "Dedução";
  const tipo       = document.getElementById("ded_tipo").value;
  const valor      = limparMoeda(document.getElementById("ded_valor").value);
  const percentual = document.getElementById("ded_percentual").value || "0";
  if (tipo==="valor" && (!valor||valor==="0,00")) { alert("Informe o valor da dedução."); return; }
  if (tipo==="percentual" && (!percentual||percentual==="0")) { alert("Informe o percentual da dedução."); return; }
  const item = { nome, tipo, valor, percentual };
  if (editandoDeducaoIndex !== null) {
    deducoes[editandoDeducaoIndex] = item;
    editandoDeducaoIndex = null;
    document.getElementById("ded_btn_add").textContent = "+";
  } else {
    deducoes.push(item);
  }
  document.getElementById("ded_nome").value="";
  document.getElementById("ded_valor").value="";
  document.getElementById("ded_percentual").value="";
  renderDeducoes();
}
function editarDeducao(i) {
  const item = deducoes[i];
  document.getElementById("ded_nome").value       = item.nome;
  document.getElementById("ded_tipo").value       = item.tipo;
  document.getElementById("ded_valor").value      = item.valor;
  document.getElementById("ded_percentual").value = item.percentual;
  editandoDeducaoIndex = i;
  document.getElementById("ded_btn_add").textContent = "✓";
}
function excluirDeducao(i) {
  if (!confirm("Excluir esta dedução?")) return;
  if (editandoDeducaoIndex===i) { editandoDeducaoIndex=null; document.getElementById("ded_btn_add").textContent="+"; }
  deducoes.splice(i,1); renderDeducoes();
}
function renderDeducoes() {
  const tbody = document.getElementById("tbodyDeducoes");
  if (!deducoes.length) { tbody.innerHTML=`<tr><td colspan="4" class="text-muted">Nenhuma dedução adicionada.</td></tr>`; atualizarHidden(); return; }
  let html="";
  deducoes.forEach((item,i) => {
    const cls = editandoDeducaoIndex===i ? ' class="table-warning"' : "";
    const ref = item.tipo==="percentual" ? `${item.percentual}%` : `R$ ${item.valor}`;
    html+=`<tr${cls}><td>${item.nome}</td><td>${item.tipo==="percentual"?"Percentual":"Valor fixo"}</td><td>${ref}</td><td>
      <button type="button" class="btn btn-outline-secondary btn-sm" onclick="editarDeducao(${i})">Editar</button>
      <button type="button" class="btn btn-outline-danger btn-sm" onclick="excluirDeducao(${i})">Excluir</button>
    </td></tr>`;
  });
  tbody.innerHTML=html; atualizarHidden();
}

// ---------------------------------------------------------------------------
// Submit
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("formCalculo");
  if (form) {
    form.addEventListener("submit", function () {
      editandoLancamentoIndex = editandoDeducaoIndex = editandoMultaIndex = editandoHonorarioIndex = null;
      atualizarHidden();
    });
  }
});