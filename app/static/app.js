// Criativos Express — lógica do app desktop

const $ = (s) => document.querySelector(s);
const el = (id) => document.getElementById(id);

let produto = null;
let produtoLabel = null;   // nome exibível do produto (sem o prefixo cliente~)
let clientesConhecidos = [];  // clientes existentes (p/ "Atribuir a cliente…")
let sessionId = null;     // sessão do chat de copies (multi-turno)
let houveConversa = false; // houve troca real de mensagens nesta sessão? (gatilho do aprendizado)
let stepAtual = "copies";
let pollTimer = null;

const modelo = () => el("modelo").value;

// -------------------------------------------------------------- Toast ------
function toast(msg) {
  const t = el("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), 2400);
}

// ------------------------------------------------------------- Modelos -----
// O dropdown é montado a partir de /api/modelos: tiers do Claude (apelidos que
// seguem o CLI) + GPT lidos do cache do Codex, cada um com tag de consumo de cota.
// Assim, quando sair um modelo novo, ele aparece sem editar o HTML.
let MODELOS_INFO = [];
const TIER_LABEL = { baixo: "baixo", medio: "médio", alto: "alto" };

async function carregarModelos(preservarSel) {
  const anterior = preservarSel ? (el("modelo").value || null) : null;
  let data;
  try { data = await (await fetch("/api/modelos")).json(); } catch (e) { return; }
  MODELOS_INFO = data.modelos || [];
  construirMenuModelos();
  const valido = (id) => MODELOS_INFO.some((m) => m.id === id);
  const sel = (anterior && valido(anterior)) ? anterior
    : (valido(data.default) ? data.default : (MODELOS_INFO[0]?.id || ""));
  escolherModelo(sel);
}

function construirMenuModelos() {
  const menu = el("modeloMenu");
  menu.innerHTML = "";
  const grupos = [
    { prov: "claude", label: "Claude · recomendado p/ copy" },
    { prov: "gpt", label: "GPT · Codex (teste)" },
  ];
  grupos.forEach((g) => {
    const itens = MODELOS_INFO.filter((m) => m.provider === g.prov);
    if (!itens.length) return;
    const head = document.createElement("div");
    head.className = "modelo-grp";
    head.textContent = g.label;
    menu.appendChild(head);
    itens.forEach((m) => {
      const row = document.createElement("div");
      row.className = "modelo-opt";
      row.setAttribute("role", "option");
      row.dataset.id = m.id;
      row.innerHTML = `
        <span class="modelo-opt-nome">${escapeHtml(m.label)}</span>
        <span class="modelo-tag tag-${m.consumo}"><i class="modelo-dot"></i>${TIER_LABEL[m.consumo] || m.consumo}</span>
        <svg class="modelo-check" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12l5 5L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      row.addEventListener("click", () => { escolherModelo(m.id); fecharMenuModelos(); });
      menu.appendChild(row);
    });
  });
}

function escolherModelo(id) {
  const m = MODELOS_INFO.find((x) => x.id === id);
  el("modelo").value = id || "";
  el("modeloBtnNome").textContent = m ? m.label : "—";
  el("modeloBtnDot").className = "modelo-dot" + (m ? " tier-" + m.consumo : "");
  el("modeloMenu").querySelectorAll(".modelo-opt").forEach((o) =>
    o.classList.toggle("sel", o.dataset.id === id));
}

function fecharMenuModelos() {
  el("modeloWrap").classList.remove("aberto");
  el("modeloBtn").setAttribute("aria-expanded", "false");
}
el("modeloBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  const aberto = el("modeloWrap").classList.toggle("aberto");
  el("modeloBtn").setAttribute("aria-expanded", aberto ? "true" : "false");
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("#modeloWrap")) fecharMenuModelos();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("modeloWrap").classList.contains("aberto")) fecharMenuModelos();
});

// ----------------------------------------------------------- Produtos ------
// Sanfonas por cliente: os rascunhos vivem em products/<cliente>/<produto>/ e o
// endpoint devolve {nome:id, label, cliente}. Agrupamos por cliente numa seção
// colapsável; produtos soltos (sem cliente) caem em "Sem cliente".
const SEM_CLIENTE = "Sem cliente";
const _COLAPSO_KEY = "ce_clientes_colapsados";
// Sanfonas de cliente começam SEMPRE fechadas ao abrir a ferramenta. Guardamos só
// em memória (não em localStorage) quais o usuário abriu nesta sessão — assim um
// re-render não fecha o que está aberto, mas reabrir a ferramenta zera tudo.
let _clientesExpandidos = new Set();
function _lerColapsados() {
  try { return new Set(JSON.parse(localStorage.getItem(_COLAPSO_KEY) || "[]")); }
  catch (e) { return new Set(); }
}
function _salvarColapsados(set) {
  try { localStorage.setItem(_COLAPSO_KEY, JSON.stringify([...set])); } catch (e) {}
}
function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function carregarProdutos() {
  const lista = await (await fetch("/api/produtos")).json();
  // clientes existentes no disco (inclui os vazios, sem produtos ainda)
  let clientesVazios = [];
  try {
    const c = await (await fetch("/api/clientes")).json();
    clientesVazios = (c && c.clientes) || [];
  } catch (e) { /* sem endpoint/erro: segue só com os produtos */ }
  const ul = el("produtos");
  ul.innerHTML = "";
  if (!lista.length && !clientesVazios.length) {
    ul.innerHTML = '<li style="opacity:.6;cursor:default">Nenhum produto</li>';
    return;
  }

  // agrupa por cliente
  const grupos = new Map();
  // garante uma sanfona para cada cliente existente, mesmo sem produtos
  clientesVazios.forEach((cli) => { if (!grupos.has(cli)) grupos.set(cli, []); });
  lista.forEach((p) => {
    const cli = p.cliente || SEM_CLIENTE;
    if (!grupos.has(cli)) grupos.set(cli, []);
    grupos.get(cli).push(p);
  });
  // ordem: clientes nomeados (alfabético), "Sem cliente" por último
  const nomes = [...grupos.keys()].sort((a, b) => {
    if (a === SEM_CLIENTE) return 1;
    if (b === SEM_CLIENTE) return -1;
    return a.localeCompare(b, "pt");
  });

  // clientes existentes (p/ o "Atribuir a cliente…"); exclui o balde "Sem cliente"
  clientesConhecidos = nomes.filter((n) => n !== SEM_CLIENTE);

  const ICON_TRASH =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7m4 4v6m4-6v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ICON_ASSIGN =
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M15 19a4 4 0 0 0-8 0M11 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19 8v6M22 11h-6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  const linhaProduto = (p) => {
    const li = document.createElement("li");
    li.className = "produto-item";
    li.dataset.nome = p.nome;
    li.dataset.label = p.label || p.nome;
    li.dataset.cliente = p.cliente || "";
    const rotulo = p.label || p.nome;
    const inicial = (rotulo || "?").trim().charAt(0) || "?";
    const dot = (on, titulo) => `<span class="st${on ? " on" : ""}" title="${titulo}"></span>`;
    const avatar = p.thumb
      ? `<span class="avatar img"><img src="/referencia/${encodeURIComponent(p.nome)}/${encodeURIComponent(p.thumb)}" alt="${_esc(rotulo)}"></span>`
      : `<span class="avatar">${_esc(inicial)}</span>`;
    // ações só no HOVER (limpo em repouso): atribuir (só "sem cliente") + remover
    const btnAtribuir = p.cliente ? "" :
      `<button class="prod-act atribuir" type="button" title="Atribuir a um cliente">${ICON_ASSIGN}</button>`;
    li.innerHTML =
      avatar +
      `<span class="pnome">${_esc(rotulo)}</span>` +
      `<span class="badge">${dot(p.tem_referencia, "Fotos de referência")}` +
      `${dot(p.tem_copies, "Copies")}${dot(p.tem_prompts, "Prompts")}</span>` +
      `<span class="prod-actions">${btnAtribuir}` +
      `<button class="prod-act remover" type="button" title="Remover produto">${ICON_TRASH}</button></span>`;
    li.addEventListener("click", () => selecionarProduto(p.nome, p.label));
    const ba = li.querySelector(".prod-act.atribuir");
    if (ba) ba.addEventListener("click", (e) => { e.stopPropagation(); abrirAtribuir(li, p); });
    li.querySelector(".prod-act.remover").addEventListener("click", (e) => {
      e.stopPropagation(); removerProduto(p.nome, rotulo);
    });
    return li;
  };

  nomes.forEach((cli) => {
    const itens = grupos.get(cli);
    const grupo = document.createElement("li");
    grupo.className = "cli-grupo";
    if (!_clientesExpandidos.has(cli)) grupo.classList.add("colapsado");

    const head = document.createElement("button");
    head.type = "button";
    head.className = "cli-head";
    head.innerHTML =
      `<span class="cli-caret" aria-hidden="true">▾</span>` +
      `<span class="cli-nome">${_esc(cli)}</span>` +
      `<span class="cli-count">${itens.length}</span>`;
    head.addEventListener("click", () => {
      grupo.classList.toggle("colapsado");
      if (grupo.classList.contains("colapsado")) _clientesExpandidos.delete(cli);
      else _clientesExpandidos.add(cli);
    });

    const sub = document.createElement("ul");
    sub.className = "cli-lista";
    itens.forEach((p) => sub.appendChild(linhaProduto(p)));

    grupo.appendChild(head);
    grupo.appendChild(sub);
    ul.appendChild(grupo);
  });
}

async function renomearProduto() {
  if (!produto) return;
  const nomeAtual = produto;
  const novo = el("nomeProdutoTxt").value.trim();
  if (!novo || novo === nomeAtual) return;
  try {
    const r = await (await fetch(`/api/produtos/${encodeURIComponent(nomeAtual)}/renomear`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome: novo }),
    })).json();
    if (!r.ok) { toast(r.erro || "Não foi possível renomear"); return; }
    const eraAtual = produto === nomeAtual;
    if (eraAtual) {
      produto = r.nome;
      produtoLabel = novo;
      el("tituloProduto").textContent = novo;
      el("subProduto").textContent = "pronto para trabalhar as copies";
    }
    await carregarProdutos();
    document.querySelectorAll(".produtos li").forEach((li) =>
      li.classList.toggle("ativo", li.dataset.nome === produto));
    toast(`Produto renomeado para "${novo}" ✓`);
  } catch (e) { toast("Erro de conexão ao renomear"); }
}

// Reseta o painel principal quando o produto ativo deixa de existir (removido/movido).
function _limparProdutoAtivo() {
  produto = null; produtoLabel = null; sessionId = null; houveConversa = false;
  el("tituloProduto").textContent = "Nenhum produto";
  el("subProduto").textContent = "selecione um produto à esquerda";
  const chat = el("chat"); if (chat) chat.innerHTML = "";
}

// Remove o produto (ação destrutiva -> confirma). Apaga a pasta no disco via API.
async function removerProduto(id, rotulo) {
  if (!window.confirm(`Remover o produto "${rotulo}"? Isso apaga a pasta dele (copies, referências, tudo) e não dá pra desfazer.`)) return;
  try {
    const r = await (await fetch(`/api/produtos/${encodeURIComponent(id)}`, { method: "DELETE" })).json();
    if (!r.ok) { toast(r.erro || "Não foi possível remover"); return; }
    if (produto === id) _limparProdutoAtivo();
    await carregarProdutos();
    document.querySelectorAll(".produtos li").forEach((li) =>
      li.classList.toggle("ativo", li.dataset.nome === produto));
    toast(`Produto "${rotulo}" removido ✓`);
  } catch (e) { toast("Erro de conexão ao remover"); }
}

// Menu flutuante "Atribuir a cliente…" (produtos sem cliente). Atribuição direta.
function _fecharPopMenu() {
  document.querySelectorAll(".prod-popmenu").forEach((m) => m.remove());
}
function abrirAtribuir(li, p) {
  _fecharPopMenu();
  const menu = document.createElement("div");
  menu.className = "prod-popmenu";
  if (!clientesConhecidos.length) {
    menu.innerHTML = `<div class="ppm-vazio">Nenhum cliente ainda</div>`;
  } else {
    menu.innerHTML = `<div class="ppm-head">Atribuir a cliente</div>` +
      clientesConhecidos.map((c) => `<button class="ppm-opt" type="button" data-cli="${_esc(c)}">${_esc(c)}</button>`).join("");
  }
  document.body.appendChild(menu);
  const r = li.getBoundingClientRect();
  menu.style.top = `${Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8)}px`;
  menu.style.left = `${Math.min(r.left + 24, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.querySelectorAll(".ppm-opt").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const cliente = b.dataset.cli;
      _fecharPopMenu();
      await atribuirProduto(p.nome, p.label || p.nome, cliente);
    }));
  setTimeout(() => document.addEventListener("click", _fecharPopMenu, { once: true }), 0);
}
async function atribuirProduto(id, rotulo, cliente) {
  try {
    const r = await (await fetch(`/api/produtos/${encodeURIComponent(id)}/atribuir`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cliente }),
    })).json();
    if (!r.ok) { toast(r.erro || "Não foi possível atribuir"); return; }
    if (produto === id) { produto = r.nome; }   // mantém seleção após mover
    await carregarProdutos();
    document.querySelectorAll(".produtos li").forEach((li) =>
      li.classList.toggle("ativo", li.dataset.nome === produto));
    toast(`"${rotulo}" atribuído a ${cliente} ✓`);
  } catch (e) { toast("Erro de conexão ao atribuir"); }
}

// Ao fim de uma conversa (troca de produto ou fechar o app), destila o que foi
// dito na memória DAQUELE produto. Best-effort e fire-and-forget: não bloqueia nada.
function dispararAprendizado() {
  if (!produto || !sessionId || !houveConversa) return;
  const alvo = produto;
  const body = JSON.stringify({ session_id: sessionId, modelo: modelo() });
  houveConversa = false; // não destila a mesma conversa duas vezes
  try {
    fetch(`/api/aprender/${alvo}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body, keepalive: true,   // sobrevive à navegação/fechamento
    }).catch(() => {});
  } catch (e) { /* ignora */ }
}

function selecionarProduto(nome, label) {
  dispararAprendizado();     // aprende da conversa anterior antes de trocar
  produto = nome;
  produtoLabel = label || nome;
  sessionId = null;
  houveConversa = false;
  document.querySelectorAll(".produtos li").forEach((l) =>
    l.classList.toggle("ativo", l.dataset.nome === nome));
  el("tituloProduto").textContent = produtoLabel;
  el("subProduto").textContent = "pronto para trabalhar as copies";
  el("chat").innerHTML = "";
  estiloPendente = null;     // não vaza copies pendentes de um produto pro outro
  dadosVisuais = [];
  sessaoVisual = null;
  limparAnexosPendentes();
  carregarEstiloRefs();
  carregarFormatos();
  addMsg("ai", `Vamos criar os criativos de "${produtoLabel}". Me diga o que você quer: quantas copies, foco/ângulos, ocasião... Eu proponho os ângulos e a gente refina.`);
  el("listaPrompts").innerHTML = "";
  copiesUsadas = [];
  promptHistTemDados = false;
  const ph = el("promptHist");
  ph.style.display = "none";
  ph.classList.remove("aberto");
  el("grade").innerHTML = "";
  el("logosGrade").innerHTML = "";
  el("logoExportInfo").textContent = "";
  el("progresso").style.display = "none";
  const hist = el("historico");
  hist.style.display = "none";
  hist.classList.remove("aberto");
  trocarStep("copies");
  carregarStatus();
}

// Se ficou copy pendente de uma sessão anterior, ela reaparece como cards no chat.
async function mostrarCopiesPendentes() {
  let dados = [];
  try { dados = await (await fetch(`/api/copies_json/${produto}`)).json(); } catch (e) { return; }
  const pendentes = (dados || []).filter((c) => c.status !== "usada");
  if (!pendentes.length) return;
  addMsg("ai", `Você tem **${pendentes.length} copy(ies) pendentes** da última sessão. Selecione as que quer transformar em prompts, ou me peça ajustes.`);
  renderCopyGroup(pendentes);
}

// --------------------------------------------------------------- Steps -----
el("steps").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  trocarStep(b.dataset.step);
});

function trocarStep(step, skipLoad) {
  if (!produto) { toast("Selecione um produto primeiro"); return; }
  stepAtual = step;
  document.querySelectorAll("#steps button").forEach((b) =>
    b.classList.toggle("sel", b.dataset.step === step));
  document.querySelectorAll(".step").forEach((s) => s.classList.remove("ativo"));
  el("step-" + step).classList.add("ativo");
  aplicarVisPromptHist();
  if (skipLoad) return;
  if (step === "contexto") carregarContexto();
  if (step === "estilo") carregarEstiloVisual();
  if (step === "prompts") carregarPrompts();
  if (step === "criativos") { carregarStatus(); carregarHistorico(); }
  if (step === "logos") carregarLogos();
}

// -------------------------------------------------------------- Contexto ---
// Tipo do produto (físico/digital): definido aqui e lido pela ferramenta de
// vídeo. Persistido em config.md via endpoint do blueprint /ugc.
function _refletirTipoProduto(tipo) {
  document.querySelectorAll("#ctxTipoProduto button").forEach((b) =>
    b.classList.toggle("sel", b.dataset.tipo === tipo));
}
async function carregarTipoProdutoCtx() {
  _refletirTipoProduto(null);
  if (!produto) return;
  try {
    const r = await (await fetch(`/ugc/api/tipo_produto/${encodeURIComponent(produto)}`)).json();
    if (r.ok) _refletirTipoProduto(r.tipo || null);
  } catch (e) { /* sem tipo salvo ainda */ }
}
document.querySelectorAll("#ctxTipoProduto button").forEach((btn) =>
  btn.addEventListener("click", async () => {
    if (!produto) { toast("Selecione um produto primeiro."); return; }
    try {
      const r = await (await fetch(`/ugc/api/tipo_produto/${encodeURIComponent(produto)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: btn.dataset.tipo }),
      })).json();
      if (!r.ok) throw new Error(r.erro || "Falha ao salvar o tipo.");
      _refletirTipoProduto(r.tipo);
      toast(`Produto marcado como ${r.tipo === "digital" ? "digital" : "físico"}.`);
    } catch (e) { toast(e.message); }
  }));

async function carregarContexto() {
  const d = await (await fetch(`/api/contexto/${produto}`)).json();
  const produtoDetalhes = await fetch(`/api/referencia_produto/${produto}`).then((r) => r.json()).catch(() => ({}));
  const porNome = Object.fromEntries((produtoDetalhes.detalhes || []).map((x) => [x.arquivo, x]));
  el("nomeProdutoTxt").value = produto;
  el("configTxt").value = d.config || "";
  carregarTipoProdutoCtx();
  const refs = el("ctxRefs");
  refs.innerHTML = ((d.referencias || []).length || (d.referencias_estilo || []).length)
    ? "" : '<div class="ctx-vazio">Nenhuma foto em referencia/ ainda.</div>';
  const itensRef = (d.referencias || []).map((nome) => ({
    src: `/referencia/${produto}/${encodeURIComponent(nome)}`, nome, contexto: porNome[nome]?.contexto || "",
  }));
  itensRef.forEach((it, i) => {
    const fig = document.createElement("figure");
    fig.className = "ctx-ref";
    fig.title = "Clique para ampliar";
    fig.innerHTML = `<button class="anexo-x" title="Apagar esta foto">&times;</button>` +
      `<img src="${it.src}" alt="${it.nome}"><figcaption>${it.nome}</figcaption>` +
      `<textarea class="ctx-ref-contexto" placeholder="Quando considerar esta foto?">${escapeHtml(it.contexto)}</textarea>`;
    const contexto = fig.querySelector(".ctx-ref-contexto");
    contexto.addEventListener("click", (e) => e.stopPropagation());
    contexto.addEventListener("change", () => salvarContextoReferencia(it.nome, contexto.value));
    fig.querySelector(".anexo-x").addEventListener("click", (e) => {
      e.stopPropagation(); removerRefProduto(it.nome);
    });
    fig.addEventListener("click", () => abrirLightbox(itensRef, i, false));
    refs.appendChild(fig);
  });

  // Referências de ESTILO (anexadas na aba de copies) — direção visual, removíveis aqui.
  estiloRefs = d.referencias_estilo || [];
  if (false && estiloRefs.length) {
    const itensEst = estiloRefs.map((nome) => ({
      src: `/referencia_estilo/${produto}/${encodeURIComponent(nome)}`, nome,
    }));
    itensEst.forEach((it, i) => {
      const fig = document.createElement("figure");
      fig.className = "ctx-ref estilo";
      fig.title = "Referência de estilo (clique para ampliar)";
      fig.innerHTML = `<span class="estilo-tag">estilo</span><img src="${it.src}" alt="${it.nome}">` +
        `<button class="anexo-x" title="Remover">&times;</button><figcaption>${it.nome}</figcaption>`;
      fig.querySelector("img").addEventListener("click", () => abrirLightbox(itensEst, i, false));
      fig.querySelector(".anexo-x").addEventListener("click", (e) => {
        e.stopPropagation(); removerEstiloRef(it.nome).then(carregarContexto);
      });
      refs.appendChild(fig);
    });
  }
  carregarCtxRefsEstilo();
  renderAnexosBar();
  const box = el("ctxArquivos");
  box.innerHTML = "";
  const textos = (d.arquivos || []).filter((a) => a.tipo === "texto");
  const outros = (d.arquivos || []).filter((a) => a.tipo !== "texto");
  if (!textos.length && !outros.length) {
    box.innerHTML = '<div class="ctx-vazio">Nada em contexto/ ainda. Coloque página de vendas, transcrições, etc.</div>';
  }
  textos.forEach((a) => {
    const det = document.createElement("details");
    det.className = "ctx-file";
    det.innerHTML = `<summary><span>${a.nome}</span><span class="ctx-chars">${a.conteudo.length.toLocaleString("pt-BR")} chars</span></summary>` +
      `<pre>${escapeHtml(a.conteudo)}</pre>`;
    box.appendChild(det);
  });
  outros.forEach((a) => {
    const div = document.createElement("div");
    div.className = "ctx-file outro";
    div.innerHTML = `<span>${a.nome}</span><span class="ctx-chars">arquivo não-texto</span>`;
    box.appendChild(div);
  });
  carregarAprendizado();
  carregarVerdade();
  carregarInfluenciadores();
}

// --- Memória do produto & Verdade visual: lista de itens editáveis ---------
// Mesmo endpoint de antes (conteúdo = itens juntados por \n). Cada edição,
// remoção ou adição salva na hora — antes o textarea não persistia nada.
const MEM_APR = {
  cont: "aprendizadoLista", badge: "memBadge", path: () => `/api/aprendizado/${produto}`,
  vazio: "Ainda sem memória. Vai se preenchendo conforme você refina as copies.",
};
const MEM_VER = {
  cont: "verdadeLista", badge: "verdadeBadge", path: () => `/api/verdade_visual/${produto}`,
  vazio: "Ainda sem verdade visual. Vai se preenchendo quando você corrige um erro visual num refino.",
};

function memLinha(txt, opts) {
  const row = document.createElement("div");
  row.className = "mem-item";
  row.innerHTML = `<input type="text" class="mem-inp"><button class="mem-del" type="button" title="Remover">&times;</button>`;
  row.querySelector(".mem-inp").value = txt;
  row.querySelector(".mem-inp").addEventListener("change", () => memSalvar(opts));
  row.querySelector(".mem-del").addEventListener("click", () => { row.remove(); memSalvar(opts); });
  return row;
}

function memRender(opts, itens) {
  const cont = el(opts.cont);
  cont.innerHTML = "";
  if (!itens.length) cont.innerHTML = `<div class="mem-vazio">${opts.vazio}</div>`;
  else itens.forEach((t) => cont.appendChild(memLinha(t, opts)));
  el(opts.badge).textContent = String(itens.length);
}

async function memSalvar(opts) {
  if (!produto) return;
  const linhas = [...el(opts.cont).querySelectorAll(".mem-inp")].map((i) => i.value.trim()).filter(Boolean);
  try {
    const r = await (await fetch(opts.path(), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conteudo: linhas.join("\n") }),
    })).json();
    el(opts.badge).textContent = String(r.total ?? linhas.length);
  } catch (e) { toast("Erro ao salvar"); }
}

function memAdicionar(opts) {
  if (!produto) { toast("Selecione um produto primeiro"); return; }
  const cont = el(opts.cont);
  cont.querySelector(".mem-vazio")?.remove();
  const row = memLinha("", opts);
  cont.appendChild(row);
  row.querySelector(".mem-inp").focus();
}

async function carregarAprendizado() {
  try {
    const d = await (await fetch(`/api/aprendizado/${produto}`)).json();
    memRender(MEM_APR, d.itens || []);
  } catch (e) { /* ignora */ }
}

async function carregarVerdade() {
  try {
    const d = await (await fetch(`/api/verdade_visual/${produto}`)).json();
    memRender(MEM_VER, d.itens || []);
  } catch (e) { /* ignora */ }
}

el("btnAddAprendizado")?.addEventListener("click", () => memAdicionar(MEM_APR));
el("btnAddVerdade")?.addEventListener("click", () => memAdicionar(MEM_VER));

function escapeHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

el("btnSalvarConfig").addEventListener("click", async () => {
  try {
    await fetch(`/api/contexto/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: el("configTxt").value }),
    });
    toast("Config salvo ✓");
  } catch (e) { toast("Erro ao salvar config"); }
});

el("btnRenomearProduto").addEventListener("click", renomearProduto);
el("nomeProdutoTxt").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); renomearProduto(); }
});

// ---------------------------------------------------------------- Chat -----
// Renderizador de markdown mínimo (offline): títulos, negrito, itálico,
// listas, hr e parágrafos. Escapa HTML antes de aplicar as marcações.
function mdToHtml(src) {
  const inline = (s) =>
    escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/`([^`]+?)`/g, "<code>$1</code>");

  const linhas = (src || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let lista = null; // "ul" | "ol" | null
  const fechaLista = () => { if (lista) { out.push(`</${lista}>`); lista = null; } };

  for (const raw of linhas) {
    const l = raw.trim();
    if (!l) { fechaLista(); continue; }
    if (/^(-{3,}|_{3,}|\*{3,})$/.test(l)) { fechaLista(); out.push("<hr>"); continue; }
    let m;
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) {
      fechaLista();
      const n = m[1].length;
      out.push(`<h${n}>${inline(m[2])}</h${n}>`);
      continue;
    }
    if ((m = l.match(/^\d+[.)]\s+(.*)$/))) {
      if (lista !== "ol") { fechaLista(); out.push("<ol>"); lista = "ol"; }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    if ((m = l.match(/^[-*]\s+(.*)$/))) {
      if (lista !== "ul") { fechaLista(); out.push("<ul>"); lista = "ul"; }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    fechaLista();
    out.push(`<p>${inline(l)}</p>`);
  }
  fechaLista();
  return out.join("\n");
}

function addMsg(tipo, texto) {
  const div = document.createElement("div");
  div.className = "msg " + tipo;
  // IA (menos o estado "pensando") vem em markdown; usuário fica como texto puro.
  if (tipo.includes("pensando")) {
    // Indicador de "digitando/pensando" estilo chat de IA: 3 bolinhas + label com shimmer.
    const label = (texto && texto !== "pensando…") ? texto : "Pensando";
    div.innerHTML = `<span class="thinking-orb" aria-hidden="true"></span>`
      + `<span class="thinking-label">${escapeHtml(label)}</span>`;
  } else if (tipo.startsWith("ai")) {
    div.innerHTML = mdToHtml(texto);
  } else {
    div.textContent = texto;
  }
  el("chat").appendChild(div);
  el("chat").scrollTop = el("chat").scrollHeight;
  return div;
}

async function enviar() {
  if (!produto) { toast("Selecione um produto"); return; }
  const inp = el("chatInput");
  const msg = inp.value.trim();
  const temAnexos = anexosPendentes.length > 0;
  if (!msg && !temAnexos) return;
  inp.value = "";
  inp.style.height = "auto";

  // Monta o corpo: multipart quando há anexos (imagens), JSON quando é só texto.
  let body, headers, fetchOpts;
  const legendaAnexo = temAnexos
    ? `📎 ${anexosPendentes.length} imagem(ns) · referência de copy`
    : "";
  if (temAnexos) {
    const fd = new FormData();
    fd.append("produto", produto);
    fd.append("mensagem", msg);
    if (sessionId) fd.append("session_id", sessionId);
    fd.append("modelo", modelo());
    fd.append("anexo_modo", "copy");
    anexosPendentes.forEach((f) => fd.append("anexos", f, f.name));
    fetchOpts = { method: "POST", body: fd };
  } else {
    fetchOpts = {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ produto, mensagem: msg, session_id: sessionId, modelo: modelo() }),
    };
  }

  if (msg || legendaAnexo) addMsg("user", [msg, legendaAnexo].filter(Boolean).join("\n"));
  limparAnexosPendentes();
  const pensando = addMsg("ai pensando", "pensando…");
  el("btnEnviar").disabled = true;

  let r = null;
  try {
    const resp = await fetch("/api/chat", fetchOpts);
    r = await resp.json();
  } catch (e) {
    pensando.remove();
    addMsg("ai", "⚠ Erro de conexão com o servidor. Ele está rodando? (" + (e.message || e) + ")");
    el("btnEnviar").disabled = false;
    return;
  }

  pensando.remove();
  if (!r.ok) {
    addMsg("ai", "⚠ Erro: " + (r.erro || "falha ao gerar resposta"));
    el("btnEnviar").disabled = false;
    return;
  }

  // Referência de estilo registrada: atualiza os chips ativos.
  if (r.estilo_refs) { estiloRefs = r.estilo_refs; renderAnexosBar(); }
  if (r.resposta === null && r.estilo_add) {
    addMsg("ai", `Referência de estilo adicionada (${r.estilo_add.length}). Ela vai valer nas próximas imagens deste produto até você remover.`);
    el("btnEnviar").disabled = false;
    return;
  }

  sessionId = r.session_id;
  houveConversa = true;   // já houve troca real: essa conversa pode virar memória
  addMsg("ai", r.resposta || (r.copies ? "Copies prontas:" : "(sem resposta)"));
  // Render dos cards fora do try do fetch: um erro aqui não vira "erro de conexão".
  if (r.copies) {
    // Nesta resposta, renderize o lote completo. Copies usadas continuam
    // visÃ­veis para revisÃ£o e seus checkboxes jÃ¡ ficam bloqueados no card.
    const pendentes = r.copies.filter((c) => c.status !== "usada");
    if (pendentes.length) {
      try { renderCopyGroup(pendentes); }
      catch (e) { addMsg("ai", "⚠ Falha ao exibir os cards de copy: " + (e.message || e)); }
    }
  }
  el("btnEnviar").disabled = false;
}

el("btnEnviar").addEventListener("click", enviar);
el("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); }
});

// ------------------------------------------------- Anexos de referência ----
// Dois modos por envio: "copy" (a imagem orienta o texto neste turno, efêmera) e
// "estilo" (vira referência de estilo do criativo, ativa até ser removida).
let anexosPendentes = [];   // File[] a enviar no próximo envio
let estiloRefs = [];        // nomes das referências de estilo ATIVAS do produto
const ANEXO_MAX = 15 * 1024 * 1024;

el("btnAnexar").addEventListener("click", () => {
  if (!produto) { toast("Selecione um produto primeiro"); return; }
  el("anexoInput").click();
});
el("anexoInput").addEventListener("change", (e) => {
  for (const f of e.target.files || []) {
    if (!/^image\/(png|jpe?g|webp)$/i.test(f.type)) { toast("Só imagem (png, jpg, webp)"); continue; }
    if (f.size > ANEXO_MAX) { toast(`${f.name}: máximo 15MB`); continue; }
    anexosPendentes.push(f);
  }
  e.target.value = "";  // permite reanexar o mesmo arquivo
  renderAnexosBar();
});
el("anexosModo")?.addEventListener("click", (e) => {
  const b = e.target.closest(".am-opt");
  if (!b) return;
  el("anexosModo").querySelectorAll(".am-opt").forEach((o) =>
    o.classList.toggle("sel", o.dataset.modo === "copy"));
});

function limparAnexosPendentes() {
  anexosPendentes.forEach((f) => { if (f._url) URL.revokeObjectURL(f._url); });
  anexosPendentes = [];
  renderAnexosBar();
}

function renderAnexosBar() {
  const bar = el("anexosBar");
  const pendWrap = el("anexosPendWrap");
  const pend = el("anexosPend");
  const est = el("anexosEstilo");

  // Pendentes (deste envio).
  pend.innerHTML = "";
  anexosPendentes.forEach((f, i) => {
    if (!f._url) f._url = URL.createObjectURL(f);
    const chip = document.createElement("div");
    chip.className = "anexo-chip";
    chip.innerHTML = `<img src="${f._url}" alt=""><button class="anexo-x" title="Remover">&times;</button>`;
    chip.querySelector(".anexo-x").addEventListener("click", () => {
      if (f._url) URL.revokeObjectURL(f._url);
      anexosPendentes.splice(i, 1);
      renderAnexosBar();
    });
    pend.appendChild(chip);
  });
  pendWrap.style.display = anexosPendentes.length ? "flex" : "none";

  // Referências de estilo ATIVAS (persistentes).
  est.innerHTML = "";
  estiloRefs.forEach((nome) => {
    const chip = document.createElement("div");
    chip.className = "anexo-chip estilo";
    const src = `/referencia_estilo/${produto}/${encodeURIComponent(nome)}`;
    chip.innerHTML = `<span class="estilo-tag">estilo</span><img src="${src}" alt="${escapeHtml(nome)}"><button class="anexo-x" title="Remover referência de estilo">&times;</button>`;
    chip.querySelector("img").addEventListener("click", () =>
      abrirLightbox([{ src, nome }], 0, false));
    chip.querySelector(".anexo-x").addEventListener("click", () => removerEstiloRef(nome));
    est.appendChild(chip);
  });
  est.style.display = "none";

  bar.style.display = anexosPendentes.length ? "flex" : "none";
}

async function carregarEstiloRefs() {
  estiloRefs = [];
  if (produto) {
    try {
      const d = await (await fetch(`/api/referencia_estilo/${produto}`)).json();
      estiloRefs = d.referencias || [];
    } catch (e) { /* ignora */ }
  }
  renderAnexosBar();
}

async function removerEstiloRef(nome) {
  try {
    const r = await (await fetch(`/api/referencia_estilo/${produto}`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: nome }),
    })).json();
    if (r.ok) {
      estiloRefs = r.referencias || estiloRefs.filter((n) => n !== nome);
      renderAnexosBar();
      if (typeof carregarContexto === "function" && stepAtual === "contexto") carregarContexto();
      toast("Referência de estilo removida ✓");
    } else { toast(r.erro || "erro"); }
  } catch (e) { toast("Erro de conexão"); }
}
el("chatInput").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

// ------------------------------------------- Copies (cards dentro do chat) --
let grupoCopiesAtivo = null; // só o grupo mais recente aceita seleção

// Selo discreto do formato (padrao/wikihow/noticia), exibido em copies, prompts e
// thumbs da grade. Ausente = 'padrao'. fmtLabel/formatosCatalogo definidos adiante.
function formatoSelo(formato) {
  const f = String(formato || "padrao");
  const cls = f.replace(/[^a-z0-9_-]/gi, "") || "padrao";
  return `<span class="fmt-selo fmt-${cls}">${escapeHtml(fmtLabel(f))}</span>`;
}
// Id base do arquivo (criativo_03.png / _refinado1 -> criativo_03), pra casar o
// formato vindo do status (mapa por id base dos prompts).
const idBaseArq = (nome) =>
  (String(nome).match(/^(criativo_\d+)/) || [null, String(nome).replace(/\.png$/i, "")])[1];

function renderCopyGroup(copies) {
  // Copies já usadas ficam no histórico, não misturadas ao lote selecionável.
  copies = (copies || []).filter((c) => c.status !== "usada");
  if (!copies.length) return null;
  // Desativa o grupo anterior (revisões substituem a seleção).
  if (grupoCopiesAtivo) {
    grupoCopiesAtivo.classList.add("desatualizado");
    grupoCopiesAtivo.querySelectorAll("input,button").forEach((x) => (x.disabled = true));
  }

  const wrap = document.createElement("div");
  wrap.className = "msg ai copy-group";
  const MUITAS = copies.length > 8;

  const cardHtml = (c) => `
    <label class="copy-card${c.status === "usada" ? " usada" : ""}">
      <div class="copy-meta">
        <input type="checkbox" class="chk-copy" data-id="${escapeHtml(c.id || "")}"${c.status === "usada" ? " disabled" : ""}>
        <span class="tag">${escapeHtml(c.id || "")}</span>
        <span class="tag angulo">${escapeHtml(c.angulo || "ângulo")}</span>
        ${formatoSelo(c.formato)}
      </div>
      <h4>${escapeHtml(c.headline || "")}</h4>
      <p>${escapeHtml(c.apoio || c.subheadline || c.corpo || "")}</p>
      <div class="cta">${escapeHtml(c.cta || "")}</div>
    </label>`;

  wrap.innerHTML = `
    <div class="copy-group-head">
      <strong>Copies (${copies.length})</strong>
      <label class="chk-label"><input type="checkbox" class="chk-todas"> todas</label>
    </div>
    <div class="copy-cards${MUITAS ? " colapsado" : ""}">${copies.map(cardHtml).join("")}</div>
    ${MUITAS ? `<button class="btn ghost btn-mais">mostrar todas (${copies.length})</button>` : ""}
    <div class="copy-bar">
      <span class="sub sel-copies">0 selecionadas</span>
    <button class="btn primary btn-confirmar-estilo" disabled>Confirmar (0)</button>
    </div>`;

  const btnGerar = wrap.querySelector(".btn-confirmar-estilo");
  const selInfo = wrap.querySelector(".sel-copies");
  const atualizar = () => {
    const n = wrap.querySelectorAll(".chk-copy:checked").length;
    btnGerar.textContent = `Confirmar (${n})`;
    btnGerar.disabled = n === 0;
    selInfo.textContent = `${n} selecionada(s)`;
  };
  wrap.querySelectorAll(".chk-copy").forEach((chk) => {
    chk.addEventListener("change", () => {
      chk.closest(".copy-card").classList.toggle("sel", chk.checked);
      atualizar();
    });
  });
  wrap.querySelector(".chk-todas").addEventListener("change", (e) => {
    wrap.querySelectorAll(".chk-copy").forEach((c) => {
      c.checked = e.target.checked;
      c.closest(".copy-card").classList.toggle("sel", c.checked);
    });
    atualizar();
  });
  const btnMais = wrap.querySelector(".btn-mais");
  if (btnMais) btnMais.addEventListener("click", () => {
    wrap.querySelector(".copy-cards").classList.remove("colapsado");
    btnMais.remove();
  });
  btnGerar.addEventListener("click", () => {
    const ids = [...wrap.querySelectorAll(".chk-copy:checked")].map((c) => c.dataset.id);
    confirmarEstiloDeCopies(ids, wrap);
  });

  el("chat").appendChild(wrap);
  el("chat").scrollTop = el("chat").scrollHeight;
  grupoCopiesAtivo = wrap;
  return wrap;
}

// Copies confirmadas: NÃO gera direções na hora. Leva pra aba Estilo visual e
// deixa o usuário escolher — clicar em "Gerar visual sugerido" ou mandar o
// próprio pedido pelo chat (com referências). A geração só roda quando ele quer.
function confirmarEstiloDeCopies(ids, grupo) {
  if (!ids.length) { toast("Selecione ao menos uma copy"); return; }
  estiloPendente = { ids: [...ids], grupo };
  dadosVisuais = [];
  sessaoVisual = null;
  el("visualChat").innerHTML = "";
  trocarStep("estilo", true);
  renderEstiloEscolha();
}

// Tela de escolha no Estilo visual quando há copies pendentes e nenhuma direção.
function renderEstiloEscolha() {
  const n = estiloPendente?.ids.length || 0;
  el("visualChat").innerHTML = "";
  el("listaVisuais").innerHTML =
    `<div class="visual-escolha">
       <div class="ve-titulo">${n} cop${n === 1 ? "y" : "ies"} pronta${n === 1 ? "" : "s"} pra virar direção visual</div>
       <label class="chk-label" style="margin:8px 0 4px">direções por copy
         <select id="visualQtdInicial" class="visual-variantes" aria-label="Quantidade de direções por copy">
           ${[2,3,4,5,6].map((n) => `<option value="${n}">${n}</option>`).join("")}
         </select>
       </label>
       <p class="ve-sub">Clique para eu sugerir as cenas — ou descreva no chat abaixo como você quer as imagens (pode anexar referências) e eu gero a partir do seu pedido.</p>
       <button class="btn primary ve-btn" id="btnGerarSugerido">Gerar visual sugerido</button>
     </div>`;
  el("listaVisuais").querySelector("#btnGerarSugerido")
    .addEventListener("click", () => {
      if (estiloPendente) gerarVisuais(estiloPendente.ids, "", Number(el("visualQtdInicial")?.value || 2));
    });
  el("visualChatInput").disabled = false;
  el("btnEnviarVisual").disabled = false;
  el("visualChatInput").placeholder = "Descreva como quer as cenas e envie — ou clique em Gerar visual sugerido…";
}

// Gera as direções para as copies pendentes. instrucoes vazio = sugestão da IA;
// instrucoes preenchido = gera a partir do pedido do usuário.
async function gerarVisuais(ids, instrucoes, variantes = 1) {
  if (!ids || !ids.length) { toast("Nenhuma copy pendente"); return; }
  const grupo = estiloPendente?.grupo || null;
  dadosVisuais = [];
  el("listaVisuais").innerHTML = "";
  setVisualBusy(true, instrucoes ? "gerando as direções a partir do seu pedido…"
                                 : `sugerindo visuais para ${ids.length} copy(ies)…`);
  if (grupo) grupo.querySelectorAll("input,button").forEach((x) => (x.disabled = true));
  try {
    const r = await (await fetch(`/api/confirmar_estilo/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo(), copy_ids: ids, instrucoes: instrucoes || "", variantes_por_copy: variantes }),
    })).json();
    if (r.ok) {
      estiloPendente = null;
      setVisuais(r.visuais, r.resposta, r.session_id);
      toast("Direções visuais prontas ✓ — revise e envie para Prompts");
      carregarProdutos();
      if (grupo) {
        const usadas = new Set(ids);
        grupo.querySelectorAll(".copy-card").forEach((card) => {
          const chk = card.querySelector(".chk-copy");
          if (chk && usadas.has(chk.dataset.id)) card.classList.add("usada");
        });
        const restantes = [...grupo.querySelectorAll(".chk-copy")]
          .filter((c) => !usadas.has(c.dataset.id) && !c.disabled);
        if (restantes.length) {
          grupo.querySelectorAll("input,button").forEach((x) => (x.disabled = false));
          grupo.querySelectorAll(".copy-card.usada .chk-copy").forEach((x) => (x.disabled = true));
          grupo.querySelectorAll(".chk-copy").forEach((c) => { c.checked = false; });
          grupo.querySelectorAll(".copy-card.sel").forEach((c) => c.classList.remove("sel"));
          const btn = grupo.querySelector(".btn-confirmar-estilo");
          if (btn) { btn.textContent = "Confirmar (0)"; btn.disabled = true; }
          const si = grupo.querySelector(".sel-copies"); if (si) si.textContent = "0 selecionada(s)";
        } else {
          grupo.classList.add("desatualizado");
        }
      }
    } else {
      toast("Erro: " + (r.erro || "falha"));
      renderEstiloEscolha();
      if (grupo) grupo.querySelectorAll("input,button").forEach((x) => (x.disabled = false));
    }
  } catch (e) {
    toast("Erro de conexão");
    renderEstiloEscolha();
    if (grupo) grupo.querySelectorAll("input,button").forEach((x) => (x.disabled = false));
  }
  setVisualBusy(false);
}

// --------------------------------------------------------- Estilo visual ----
let dadosVisuais = [];
let sessaoVisual = null;
let estiloPendente = null;  // { ids, grupo }: copies confirmadas aguardando geração
let visualSalvarTimer = null;
let visualBusyTimer = null;
let visualBusyStarted = 0;

function setVisualBusy(on, msg) {
  clearInterval(visualBusyTimer);
  el("visualChatInput").disabled = on;
  el("btnEnviarVisual").disabled = on || !dadosVisuais.length;
  if (!on) {
    // Remove só o indicador de loading, preservando mensagens reais do chat.
    ["visualChat", "listaVisuais"].forEach((id) => el(id).querySelector(".visual-carregando")?.remove());
    return;
  }
  // Geração inicial (sem cards ainda): loading centralizado na área principal.
  // Refino (já há cards): loading na conversa, abaixo da mensagem enviada.
  const naLista = !dadosVisuais.length;
  const alvo = naLista ? el("listaVisuais") : el("visualChat");
  visualBusyStarted = Date.now();
  const atualizar = () => {
    const segundos = Math.floor((Date.now() - visualBusyStarted) / 1000);
    const html = `<div class="carregando visual-carregando${naLista ? " grande" : ""}"><span class="spin big"></span><div>${msg || "pensando…"}</div><small>O diretor de arte está revisando as cenas. Tempo decorrido: <b>${segundos}s</b><br>Normalmente leva de 20 a 90 segundos.</small></div>`;
    const box = alvo.querySelector(".visual-carregando");
    if (box) box.outerHTML = html;
    // Geração inicial: o loading SUBSTITUI o conteúdo da lista (a escolha "Gerar
    // visual sugerido" some — o usuário mandou seu próprio pedido/já disparou).
    else if (naLista) alvo.innerHTML = html;
    else alvo.insertAdjacentHTML("beforeend", html);
  };
  atualizar();
  visualBusyTimer = setInterval(atualizar, 1000);
}

function addVisualMsg(tipo, texto) {
  const div = document.createElement("div");
  div.className = `msg ${tipo}`;
  div.textContent = texto || "";
  el("visualChat").appendChild(div);
  el("visualChat").scrollTop = el("visualChat").scrollHeight;
}

function setVisuais(visuais, resposta, sessionIdVisual) {
  dadosVisuais = Array.isArray(visuais) ? visuais : [];
  sessaoVisual = sessionIdVisual || sessaoVisual;
  el("visualChat").innerHTML = "";
  // Prosa da IA suprimida de propósito: no Estilo Visual mostramos só os cards
  // de direção visual (o texto explicativo poluía a tela).
  // if (resposta) addVisualMsg("ai", resposta);
  renderVisuais();
}

async function carregarEstiloVisual() {
  // Há copies confirmadas aguardando decisão: mantém a tela de escolha.
  if (estiloPendente && estiloPendente.ids.length) {
    dadosVisuais = [];
    renderEstiloEscolha();
    await carregarReferenciasVisuais();
    return;
  }
  try {
    const dados = await (await fetch(`/api/estilo_visual/${produto}`)).json();
    setVisuais(dados, "");
    await carregarReferenciasVisuais();
  } catch (e) { toast("Erro ao carregar direções visuais"); }
}

let refsEstiloPendentes = [];
let refsProdutoPendentes = [];

function renderPendentesVisuais(tipo) {
  const lista = tipo === "estilo" ? refsEstiloPendentes : refsProdutoPendentes;
  const box = el(tipo === "estilo" ? "refsEstiloPendentes" : "refsProdutoPendentes");
  if (!box) return;
  box.innerHTML = "";
  lista.forEach((item, i) => {
    if (tipo === "estilo") {
      const nome = document.createElement("div");
      nome.className = "visual-ref-nome";
      nome.innerHTML = `<span>📎 ${escapeHtml(item.file.name)}</span><button class="anexo-x" type="button" title="Remover">&times;</button>`;
      nome.querySelector("button").addEventListener("click", () => { lista.splice(i, 1); renderPendentesVisuais(tipo); });
      box.appendChild(nome);
      return;
    }
    if (!item.url) item.url = URL.createObjectURL(item.file);
    const card = document.createElement("div");
    card.className = "visual-ref-card";
    card.innerHTML = `<img src="${item.url}" alt=""><div><small>${escapeHtml(item.file.name)}</small><textarea placeholder="Quando considerar esta imagem? Ex.: use somente em close-up"></textarea><button class="btn ghost" type="button">Remover</button></div>`;
    const area = card.querySelector("textarea");
    area.value = item.contexto || "";
    area.addEventListener("input", () => { item.contexto = area.value; });
    card.querySelector("button").addEventListener("click", () => {
      URL.revokeObjectURL(item.url); lista.splice(i, 1); renderPendentesVisuais(tipo);
    });
    box.appendChild(card);
  });
  if (lista.length && tipo !== "estilo") {
    const enviar = document.createElement("button");
    enviar.className = "btn primary"; enviar.type = "button"; enviar.textContent = "Enviar referências";
    enviar.addEventListener("click", () => enviarReferenciasVisuais(tipo));
    box.appendChild(enviar);
  }
}

function adicionarPendentesVisuais(tipo, files) {
  const lista = tipo === "estilo" ? refsEstiloPendentes : refsProdutoPendentes;
  for (const file of files || []) {
    if (!/^image\/(png|jpe?g|webp)$/i.test(file.type)) { toast("SÃ³ imagem (png, jpg, webp)"); continue; }
    if (file.size > ANEXO_MAX) { toast(`${file.name}: mÃ¡ximo 15MB`); continue; }
    lista.push({ file, contexto: "", url: "" });
  }
  renderPendentesVisuais(tipo);
}

async function enviarReferenciasVisuais(tipo) {
  const lista = tipo === "estilo" ? refsEstiloPendentes : refsProdutoPendentes;
  if (!produto || !lista.length) return;
  const fd = new FormData();
  lista.forEach((item) => fd.append("anexos", item.file, item.file.name));
  fd.append("contextos", JSON.stringify(lista.map((item) => item.contexto || "")));
  try {
    const rota = tipo === "estilo" ? "referencia_estilo" : "referencia_produto";
    const r = await (await fetch(`/api/${rota}/${produto}`, { method: "POST", body: fd })).json();
    if (!r.ok) { toast(r.erro || "Erro ao anexar referências"); return; }
    lista.forEach((item) => item.url && URL.revokeObjectURL(item.url));
    if (tipo === "estilo") refsEstiloPendentes = []; else refsProdutoPendentes = [];
    renderPendentesVisuais(tipo);
    if (tipo === "estilo") renderReferenciasSalvas(tipo, r.detalhes || []);
    else carregarContexto();
    toast("Referência(s) anexada(s) ✓");
  } catch (e) { toast("Erro de conexão ao anexar imagem"); }
}

function renderReferenciasSalvas(tipo, detalhes) {
  const box = el(tipo === "estilo" ? "refsEstiloSalvas" : "refsProdutoSalvas");
  if (!box) return;
  box.innerHTML = "";
  const rota = tipo === "estilo" ? "referencia_estilo" : "referencia";
  (detalhes || []).forEach((item) => {
    if (tipo === "estilo") {
      const nome = document.createElement("div");
      nome.className = "visual-ref-nome salvo";
      nome.innerHTML = `<span>📎 ${escapeHtml(item.arquivo)}</span>`;
      box.appendChild(nome);
      return;
    }
    const card = document.createElement("div"); card.className = "visual-ref-card salva";
    card.innerHTML = `<img src="/${rota}/${produto}/${encodeURIComponent(item.arquivo)}" alt=""><div><small>${escapeHtml(item.arquivo)}</small><span class="sub">${escapeHtml(item.contexto || "Sem contexto específico")}</span></div>`;
    box.appendChild(card);
  });
}

async function carregarReferenciasVisuais() {
  const estilo = await fetch(`/api/referencia_estilo/${produto}`).then((r) => r.json()).catch(() => ({}));
  renderReferenciasSalvas("estilo", estilo.detalhes || []);
}

async function salvarContextoReferencia(arquivo, contexto) {
  try {
    const r = await (await fetch(`/api/referencia_produto/${produto}/contexto`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo, contexto }),
    })).json();
    if (!r.ok) toast(r.erro || "Erro ao salvar comentário");
  } catch (e) { toast("Erro ao salvar comentário da foto"); }
}

async function removerRefProduto(nome) {
  if (!window.confirm(`Apagar a foto "${nome}"? Esta ação não pode ser desfeita.`)) return;
  try {
    const r = await (await fetch(`/api/referencia_produto/${produto}`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: nome }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao apagar foto"); return; }
    toast("Foto apagada ✓");
    carregarContexto();      // atualiza a grade de referências
    carregarProdutos();      // atualiza o avatar do produto na sidebar
  } catch (e) { toast("Erro ao apagar foto"); }
}

// --- Cenários/estilo na aba Contexto: imagem + nota, entram em TODA geração -----
async function carregarCtxRefsEstilo() {
  try {
    const d = await (await fetch(`/api/referencia_estilo/${produto}`)).json();
    renderCtxRefsEstilo(d.detalhes || []);
  } catch (e) { /* ignora */ }
}

function renderCtxRefsEstilo(detalhes) {
  const box = el("ctxRefsEstilo");
  if (!box) return;
  box.innerHTML = detalhes.length ? "" :
    '<div class="ctx-vazio">Nenhum estilo ainda. Adicione fundos, estádios ou estilos de imagem.</div>';
  const itens = detalhes.map((it) => ({
    src: `/referencia_estilo/${produto}/${encodeURIComponent(it.arquivo)}`,
    nome: it.arquivo, contexto: it.contexto || "",
  }));
  itens.forEach((it, i) => {
    const fig = document.createElement("figure");
    fig.className = "ctx-ref estilo";
    fig.title = "Clique na imagem para ampliar";
    fig.innerHTML =
      `<span class="estilo-tag">estilo</span>` +
      `<button class="anexo-x" title="Remover">&times;</button>` +
      `<img src="${it.src}" alt="${escapeHtml(it.nome)}">` +
      `<figcaption>${escapeHtml(it.nome)}</figcaption>` +
      `<textarea class="ctx-ref-contexto" placeholder="O que é? (ex.: fundo de estádio à noite)">${escapeHtml(it.contexto)}</textarea>`;
    fig.querySelector("img").addEventListener("click", () => abrirLightbox(itens, i, false));
    const ta = fig.querySelector(".ctx-ref-contexto");
    ta.addEventListener("click", (e) => e.stopPropagation());
    ta.addEventListener("change", () => salvarContextoRefEstilo(it.nome, ta.value));
    fig.querySelector(".anexo-x").addEventListener("click", (e) => {
      e.stopPropagation();
      removerCtxRefEstilo(it.nome);
    });
    box.appendChild(fig);
  });
}

async function salvarContextoRefEstilo(arquivo, contexto) {
  try {
    const r = await (await fetch(`/api/referencia_estilo/${produto}/contexto`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo, contexto }),
    })).json();
    if (!r.ok) toast(r.erro || "Erro ao salvar comentário");
  } catch (e) { toast("Erro ao salvar comentário do estilo"); }
}

async function removerCtxRefEstilo(arquivo) {
  try {
    await fetch(`/api/referencia_estilo/${produto}`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo }),
    });
    carregarCtxRefsEstilo();
  } catch (e) { toast("Erro ao remover estilo"); }
}

// --- Influenciador: pessoa real ativada por criativo via "@Nome" no prompt ------
let influLista = [];   // [{nome, fotos, principais, perfil}]
let influSel = "";     // qual influenciador está aberto para ver/editar (só UI)
let influPadrao = "";  // padrão do produto: entra em >=1/3 das sugestões de cena

async function carregarInfluenciadores() {
  try {
    const [lst, pad] = await Promise.all([
      fetch("/api/influenciadores").then((r) => r.json()),
      fetch(`/api/influenciador_produto/${produto}`).then((r) => r.json()).catch(() => ({})),
    ]);
    influLista = lst.influenciadores || [];
    influPadrao = pad.nome || "";
    if (!influLista.some((i) => i.nome === influSel)) influSel = "";
    renderInfluenciador();
  } catch (e) { /* ignora */ }
}

function renderInfluenciador() {
  const sel = el("influSelect");
  if (!sel) return;
  const opcoes = influLista.map((i) =>
    `<option value="${escapeHtml(i.nome)}">@${escapeHtml(i.nome)}</option>`).join("");
  const selPadrao = el("influPadraoSelect");
  if (selPadrao) {
    selPadrao.innerHTML = '<option value="">Nenhum</option>' + opcoes;
    selPadrao.value = influPadrao;
  }
  sel.innerHTML = '<option value="">Selecione...</option>' + opcoes;
  sel.value = influSel;
  const atual = influLista.find((i) => i.nome === influSel);
  el("influDetalhe").style.display = atual ? "" : "none";
  el("btnApagarInflu").style.display = atual ? "" : "none";
  if (!atual) return;
  el("influPerfilTxt").value = atual.perfil || "";
  const box = el("ctxRefsInflu");
  box.innerHTML = atual.fotos.length ? "" :
    '<div class="ctx-vazio">Nenhuma foto ainda. Adicione 2-3 fotos nítidas (rosto de frente, corpo inteiro, ângulo 3/4).</div>';
  // Sem estrela marcada, as 2 primeiras são as usadas — a estrela mostra isso.
  const usadas = atual.principais.length ? atual.principais : atual.fotos.slice(0, 2);
  const itens = atual.fotos.map((nome) => ({
    src: `/influenciador_media/${encodeURIComponent(atual.nome)}/${encodeURIComponent(nome)}`, nome,
  }));
  itens.forEach((it, i) => {
    const fig = document.createElement("figure");
    fig.className = "ctx-ref influ";
    const principal = usadas.includes(it.nome);
    fig.innerHTML =
      `<button class="influ-star${principal ? " sel" : ""}" title="Foto principal: entra na geração (até 3)">${principal ? "★" : "☆"}</button>` +
      `<button class="anexo-x" title="Apagar foto">&times;</button>` +
      `<img src="${it.src}" alt="${escapeHtml(it.nome)}">` +
      `<figcaption>${escapeHtml(it.nome)}</figcaption>`;
    fig.querySelector("img").addEventListener("click", () => abrirLightbox(itens, i, false));
    fig.querySelector(".influ-star").addEventListener("click", (e) => {
      e.stopPropagation(); alternarPrincipalInflu(atual, it.nome);
    });
    fig.querySelector(".anexo-x").addEventListener("click", (e) => {
      e.stopPropagation(); apagarFotoInflu(atual.nome, it.nome);
    });
    box.appendChild(fig);
  });
}

function atualizarInflu(dados) {
  const item = { nome: dados.nome, fotos: dados.fotos || [],
                 principais: dados.principais || [], perfil: dados.perfil || "" };
  const i = influLista.findIndex((x) => x.nome === dados.nome);
  if (i >= 0) influLista[i] = item; else influLista.push(item);
  renderInfluenciador();
}

async function alternarPrincipalInflu(influ, nome) {
  const atuais = influ.principais.length ? [...influ.principais] : influ.fotos.slice(0, 2);
  const i = atuais.indexOf(nome);
  if (i >= 0) atuais.splice(i, 1);
  else if (atuais.length >= 3) { toast("Máximo de 3 fotos principais"); return; }
  else atuais.push(nome);
  try {
    const r = await (await fetch(`/api/influenciadores/${encodeURIComponent(influ.nome)}/principais`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivos: atuais }),
    })).json();
    if (r.ok) atualizarInflu(r); else toast(r.erro || "Erro ao marcar principal");
  } catch (e) { toast("Erro ao marcar principal"); }
}

async function apagarFotoInflu(nome, arquivo) {
  if (!window.confirm(`Apagar a foto "${arquivo}" do influenciador?`)) return;
  try {
    const r = await (await fetch(`/api/influenciadores/${encodeURIComponent(nome)}/fotos`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo }),
    })).json();
    if (r.ok) atualizarInflu(r); else toast(r.erro || "Erro ao apagar foto");
  } catch (e) { toast("Erro ao apagar foto"); }
}

el("influSelect")?.addEventListener("change", (e) => {
  influSel = e.target.value;
  renderInfluenciador();
});

el("influPadraoSelect")?.addEventListener("change", async (e) => {
  const nome = e.target.value;
  try {
    const r = await (await fetch(`/api/influenciador_produto/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao definir padrão"); e.target.value = influPadrao; return; }
    influPadrao = nome;
    toast(nome ? `@${nome} vira padrão: pelo menos 1/3 das sugestões de cena com ela ✓`
               : "Produto sem influenciador padrão");
  } catch (err) { toast("Erro de conexão"); e.target.value = influPadrao; }
});

el("btnNovoInflu")?.addEventListener("click", async () => {
  const nome = (window.prompt("Nome do influenciador:") || "").trim();
  if (!nome) return;
  try {
    const r = await (await fetch("/api/influenciadores", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao criar influenciador"); return; }
    influSel = r.nome;   // abre o painel pra subir as fotos
    atualizarInflu(r);
    toast(`"@${r.nome}" criado — use @${r.nome} no prompt do criativo pra ativar ✓`);
  } catch (e) { toast("Erro de conexão"); }
});

el("btnApagarInflu")?.addEventListener("click", async () => {
  if (!influSel) return;
  if (!window.confirm(`Apagar o influenciador "${influSel}" e todas as fotos dele? Vale para todos os produtos que o usam.`)) return;
  const nome = influSel;
  try {
    const r = await (await fetch(`/api/influenciadores/${encodeURIComponent(nome)}`, { method: "DELETE" })).json();
    if (!r.ok) { toast(r.erro || "Erro ao apagar influenciador"); return; }
    influLista = influLista.filter((i) => i.nome !== nome);
    influSel = "";
    renderInfluenciador();
    toast("Influenciador apagado ✓");
  } catch (e) { toast("Erro ao apagar influenciador"); }
});

el("influPerfilTxt")?.addEventListener("change", async () => {
  if (!influSel) return;
  try {
    const r = await (await fetch(`/api/influenciadores/${encodeURIComponent(influSel)}/perfil`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ perfil: el("influPerfilTxt").value }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao salvar descrição"); return; }
    const it = influLista.find((i) => i.nome === influSel);
    if (it) it.perfil = el("influPerfilTxt").value;
    toast("Descrição salva ✓");
  } catch (e) { toast("Erro ao salvar descrição"); }
});

el("btnAddFotosInflu")?.addEventListener("click", () => el("influFotosInput").click());
el("influFotosInput")?.addEventListener("change", async (e) => {
  const files = [...(e.target.files || [])];
  e.target.value = "";
  if (!files.length || !influSel) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("anexos", f, f.name));
  try {
    const r = await (await fetch(`/api/influenciadores/${encodeURIComponent(influSel)}/fotos`, { method: "POST", body: fd })).json();
    if (!r.ok) { toast(r.erro || "Erro ao enviar fotos"); return; }
    atualizarInflu(r);
    toast(`${(r.salvos || []).length} foto(s) adicionada(s) ✓`);
  } catch (err) { toast("Erro de conexão ao enviar fotos"); }
});

el("btnAnexarCenario")?.addEventListener("click", () => el("ctxEstiloInput").click());
el("ctxEstiloInput")?.addEventListener("change", async (e) => {
  const files = [...(e.target.files || [])];
  e.target.value = "";
  if (!files.length || !produto) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("anexos", f, f.name));
  fd.append("contextos", JSON.stringify(files.map(() => "")));
  try {
    const r = await (await fetch(`/api/referencia_estilo/${produto}`, { method: "POST", body: fd })).json();
    if (!r.ok) { toast(r.erro || "Erro ao anexar"); return; }
    renderCtxRefsEstilo(r.detalhes || []);
    toast(`${files.length} estilo(s) adicionado(s) ✓`);
  } catch (err) { toast("Erro de conexão ao anexar"); }
});

el("btnAnexarEstiloVisual")?.addEventListener("click", () => el("visualEstiloInput").click());
el("visualEstiloInput")?.addEventListener("change", async (e) => { adicionarPendentesVisuais("estilo", e.target.files); e.target.value = ""; await enviarReferenciasVisuais("estilo"); });
el("btnAnexarEstiloVisualChat")?.addEventListener("click", () => el("visualEstiloInputChat").click());
el("visualEstiloInputChat")?.addEventListener("change", async (e) => {
  const nomes = Array.from(e.target.files || []).map((f) => f.name);
  adicionarPendentesVisuais("estilo", e.target.files);
  e.target.value = "";
  if (nomes.length) addVisualMsg("user", `📎 Referência(s) de estilo anexada(s): ${nomes.join(", ")}`);
  await enviarReferenciasVisuais("estilo");
});
el("btnAnexarFotoProduto")?.addEventListener("click", () => el("visualProdutoInput").click());
el("visualProdutoInput")?.addEventListener("change", (e) => { adicionarPendentesVisuais("produto", e.target.files); e.target.value = ""; });
function renderVisuais() {
  const box = el("listaVisuais");
  const temCards = dadosVisuais.length > 0;
  if (!temCards) {
    if (estiloPendente && estiloPendente.ids.length) {
      renderEstiloEscolha();  // copies confirmadas: mostra a escolha (habilita o chat)
    } else {
      box.innerHTML = `<div class="visual-escolha vazio"><p class="ve-sub">Selecione copies na aba <b>Copies</b> e confirme para começar as direções visuais aqui.</p></div>`;
      el("visualChatInput").disabled = true;
      el("btnEnviarVisual").disabled = true;
    }
    return;
  }
  box.innerHTML = "";
  el("visualChatInput").disabled = false;
  el("btnEnviarVisual").disabled = false;
  el("visualChatInput").placeholder = "Refine as direções visuais... (ex.: deixe o produto maior, troque o fundo da imagem 2)";

  // Barra de seleção (topo, sticky): revisar → selecionar → enviar p/ Prompts.
  const bar = document.createElement("div");
  bar.className = "visual-bar";
  bar.innerHTML =
    `<label class="chk-label"><input type="checkbox" class="chk-todas-vis"> todas</label>` +
    `<span class="visual-titulo">Direções visuais (${dadosVisuais.length})</span>` +
    `<span class="spacer"></span>` +
    `<span class="sub sel-visuais">0 selecionada(s)</span>` +
    `<button class="btn primary btn-enviar-prompts" disabled title="Envia as direções marcadas para a aba Prompts">Enviar para Prompts (0)</button>`;
  box.appendChild(bar);

  function atualizarSelVis() {
    const n = box.querySelectorAll(".chk-visual:checked").length;
    const btn = bar.querySelector(".btn-enviar-prompts");
    btn.textContent = `Enviar para Prompts (${n})`;
    btn.disabled = n === 0;
    bar.querySelector(".sel-visuais").textContent = `${n} selecionada(s)`;
  }

  dadosVisuais.forEach((v) => {
    const row = document.createElement("div");
    row.className = "visual-card";
    row.dataset.copyId = v.id || v.copy_id || "";
    let copyVisual = v.copy || "";
    const papelVisual = v.papel === "produto" ? "produto" : (v.papel === "expert" ? "expert + produto" : "criativa");
    if (copyVisual && typeof copyVisual === "string" && copyVisual.trim().startsWith("{")) {
      try {
        const obj = JSON.parse(copyVisual);
        copyVisual = obj.headline || obj.titulo || obj.title || copyVisual;
      } catch (e) { /* mantém o texto original */ }
    } else if (copyVisual && typeof copyVisual === "object") {
      copyVisual = copyVisual.headline || copyVisual.titulo || copyVisual.title || "";
    }
    row.innerHTML = `<div class="visual-card-head">` +
      `<input type="checkbox" class="chk-visual" data-id="${escapeHtml(v.id || v.copy_id || "")}">` +
      `<span class="tag">${escapeHtml(v.id || v.copy_id || "")}</span>` +
      `<span class="tag angulo">${escapeHtml(papelVisual)}</span>` +
      `<span class="tag angulo">${escapeHtml(v.angulo || "ângulo")}</span>` +
      `<strong title="${escapeHtml(copyVisual)}">${escapeHtml(copyVisual)}</strong>` +
      `<span class="visual-chevron" aria-hidden="true">›</span></div>` +
      `<textarea>${escapeHtml(v.visual || "")}</textarea>`;
    // Sanfona (igual aos Prompts): card começa FECHADO; clicar no cabeçalho abre/fecha.
    // Clicar no checkbox só seleciona, não abre.
    row.querySelector(".visual-card-head").addEventListener("click", (e) => {
      if (e.target.closest(".chk-visual")) return;
      row.classList.toggle("aberto");
    });
    row.querySelector("textarea").addEventListener("input", (e) => {
      v.visual = e.target.value;
      clearTimeout(visualSalvarTimer);
      visualSalvarTimer = setTimeout(() => fetch(`/api/estilo_visual/${produto}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visuais: dadosVisuais }),
      }), 700);
    });
    const chk = row.querySelector(".chk-visual");
    chk.addEventListener("change", () => { row.classList.toggle("sel", chk.checked); atualizarSelVis(); });
    box.appendChild(row);
  });

  bar.querySelector(".chk-todas-vis").addEventListener("change", (e) => {
    box.querySelectorAll(".chk-visual").forEach((c) => {
      c.checked = e.target.checked;
      c.closest(".visual-card").classList.toggle("sel", c.checked);
    });
    atualizarSelVis();
  });
  bar.querySelector(".btn-enviar-prompts").addEventListener("click", () => {
    const ids = [...box.querySelectorAll(".chk-visual:checked")].map((c) => c.dataset.id);
    enviarParaPrompts(ids, box);
  });
}

async function enviarParaPrompts(copyIds, box) {
  if (!copyIds.length) return;
  const btn = box.querySelector(".btn-enviar-prompts");
  btn.disabled = true;
  const totalPrompts = copyIds.length;
  btn.innerHTML = `<span class="spin"></span> Gerando ${totalPrompts} prompt(s)…`;
  try {
    const r = await (await fetch(`/api/promover_prompts/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ copy_ids: copyIds, variantes_por_copy: 1, modelo: modelo() }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao enviar"); btn.disabled = false; return; }
    const enviados = new Set(copyIds);
    box.querySelectorAll(".visual-card").forEach((card) => {
      if (enviados.has(card.dataset.copyId)) {
        card.classList.add("enviado");
        if (!card.querySelector(".tag.ok")) {
          card.querySelector(".visual-card-head").insertAdjacentHTML("beforeend", '<span class="tag ok">nos Prompts ✓</span>');
        }
      }
      const c = card.querySelector(".chk-visual");
      if (c) c.checked = false;
      card.classList.remove("sel");
    });
    const todas = box.querySelector(".chk-todas-vis");
    if (todas) todas.checked = false;
    box.querySelector(".sel-visuais").textContent = "0 selecionada(s)";
    btn.textContent = "Enviar para Prompts (0)";
    carregarProdutos();  // atualiza badges do produto na sidebar
    toast(`Enviado para Prompts (${r.adicionados ?? copyIds.length}) ✓`);
  } catch (e) { toast("Erro de conexão"); btn.disabled = false; }
}

async function enviarMensagemVisual() {
  const input = el("visualChatInput");
  const mensagem = input.value.trim();
  if (!mensagem) return;
  // Ainda sem direções, mas com copies pendentes → gera A PARTIR do pedido do usuário.
  if (!dadosVisuais.length) {
    if (estiloPendente && estiloPendente.ids.length) {
      input.value = "";
      gerarVisuais(estiloPendente.ids, mensagem, Number(el("visualQtdInicial")?.value || 2));
    }
    return;
  }
  input.value = "";
  addVisualMsg("user", mensagem);
  setVisualBusy(true, "ajustando as direções visuais…");
  try {
    const r = await (await fetch(`/api/estilo_visual_chat/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo(), mensagem, session_id: sessaoVisual, visuais: dadosVisuais }),
    })).json();
    if (!r.ok) { toast(r.erro || "Erro ao refinar"); return; }
    sessaoVisual = r.session_id || sessaoVisual;
    // Prosa da IA suprimida: só os cards de direção visual aparecem.
    dadosVisuais = r.visuais || dadosVisuais;
    renderVisuais();
  } catch (e) { toast("Erro de conexão"); }
  finally { setVisualBusy(false); }
}

el("btnEnviarVisual").addEventListener("click", enviarMensagemVisual);
el("visualChatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarMensagemVisual(); }
});

// ------------------------------------------------------------- Prompts -----
// Cache local dos prompts: fonte da verdade da aba (edições, seleção).
// A lista só mostra os PENDENTES; os já gerados vão para o Histórico do rodapé.
let dadosPrompts = [];
let copiesUsadas = [];   // cache das copies já viradas prompt (para o Histórico)
let salvarTimer = null;

async function carregarPrompts() {
  const [dados, copies] = await Promise.all([
    fetch(`/api/prompts/${produto}`).then((r) => r.json()).catch(() => []),
    fetch(`/api/copies_json/${produto}`).then((r) => r.json()).catch(() => []),
  ]);
  copiesUsadas = (Array.isArray(copies) ? copies : []).filter((c) => c.status === "usada");
  setDadosPrompts(Array.isArray(dados) ? dados : (dados.criativos || []));
}

function setDadosPrompts(dados) {
  dadosPrompts = dados || [];
  renderPrompts();
}

function promptsVisiveis() {
  return dadosPrompts.filter((p) => p.status !== "gerado");
}

function renderPrompts() {
  const box = el("listaPrompts");
  box.innerHTML = "";
  el("chkTodosPrompts").checked = false;

  const visiveis = promptsVisiveis();
  el("promptsTitulo").textContent = `Pendentes (${visiveis.length})`;
  el("promptsInfo").textContent = visiveis.length
    ? "" : (dadosPrompts.length
        ? "nenhum prompt pendente — os já gerados estão no Histórico abaixo"
        : "nenhum prompt ainda — selecione copies no chat e clique em Gerar prompts");

  visiveis.forEach((p) => {
    const row = document.createElement("div");
    row.className = "prompt-row" + (p.status === "gerado" ? " gerado" : "");
    row.dataset.id = p.id;
    row.innerHTML = `
      <div class="prompt-head">
        <input type="checkbox" class="chk-prompt" data-id="${escapeHtml(p.id || "")}">
        <span class="tag">${escapeHtml(p.id || "")}</span>
        <span class="tag angulo">${escapeHtml(p.angulo || "ângulo")}</span>
        ${formatoSelo(p.formato)}
        <span class="prompt-headline">${escapeHtml(p.copy || "")}</span>
        ${p.status === "gerado" ? '<span class="tag ok">gerado ✓</span>' : ""}
        <svg class="ic chev" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <button class="btn-x" title="Apagar este prompt">&times;</button>
      </div>
      <div class="prompt-body"><textarea data-campo="prompt">${escapeHtml(p.prompt || "")}</textarea></div>`;

    const chk = row.querySelector(".chk-prompt");
    chk.addEventListener("click", (e) => e.stopPropagation());
    chk.addEventListener("change", () => {
      row.classList.toggle("sel", chk.checked);
      atualizarSelecaoPrompts();
    });
    row.querySelector(".btn-x").addEventListener("click", (e) => {
      e.stopPropagation();
      apagarPrompt(p.id);
    });
    // Clique no cabeçalho expande/colapsa a edição (accordion: um por vez).
    row.querySelector(".prompt-head").addEventListener("click", () => {
      const aberto = row.classList.contains("aberto");
      box.querySelectorAll(".prompt-row.aberto").forEach((r) => r.classList.remove("aberto"));
      if (!aberto) row.classList.add("aberto");
    });
    // Autosave com debounce ao editar.
    row.querySelector("textarea").addEventListener("input", (e) => {
      const alvo = dadosPrompts.find((d) => d.id === p.id);
      if (alvo) {
        alvo.prompt = e.target.value;
        const visual = dadosVisuais.find((v) => v.id === alvo.visual_id);
        if (visual) visual.visual = e.target.value;
      }
      clearTimeout(salvarTimer);
      el("promptsInfo").textContent = "editando…";
      salvarTimer = setTimeout(async () => {
        await persistirPrompts();
        if (dadosVisuais.length) {
          await fetch(`/api/estilo_visual/${produto}`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ visuais: dadosVisuais }),
          });
        }
        el("promptsInfo").textContent = "salvo ✓";
        setTimeout(() => { if (el("promptsInfo").textContent === "salvo ✓") el("promptsInfo").textContent = ""; }, 2000);
      }, 800);
    });
    box.appendChild(row);
  });
  atualizarSelecaoPrompts();
  renderPromptHist();
}

// ------------------------------------------------- Histórico de prompts ----
// Gaveta no rodapé da aba Prompts: prompts já gerados + copies já usadas,
// guardados para consulta/reuso. Nada disso fica exposto na lista principal.
let promptHistTemDados = false;

// Mostra a pílula flutuante só quando há histórico E estamos na aba Prompts.
function aplicarVisPromptHist() {
  const wrap = el("promptHist");
  const mostrar = promptHistTemDados && stepAtual === "prompts";
  wrap.style.display = mostrar ? "block" : "none";
  if (!mostrar) wrap.classList.remove("aberto");
}

function renderPromptHist() {
  const gerados = dadosPrompts.filter((p) => p.status === "gerado");
  const nG = gerados.length, nC = copiesUsadas.length;
  promptHistTemDados = !!(nG || nC);
  if (!promptHistTemDados) { aplicarVisPromptHist(); return; }
  el("promptHistCount").textContent = String(nG + nC);
  el("promptHistTitulo").textContent = "Histórico — "
    + `${nG} prompt(s) gerado(s)` + (nC ? ` · ${nC} copy(ies) usada(s)` : "");

  const body = el("promptHistBody");
  body.innerHTML = "";
  if (nG) {
    const sec = document.createElement("div");
    sec.className = "hist-sec";
    sec.innerHTML = '<div class="hist-data">Prompts já gerados</div>';
    gerados.forEach((p) => sec.appendChild(promptHistRow(p)));
    body.appendChild(sec);
  }
  if (nC) {
    const sec = document.createElement("div");
    sec.className = "hist-sec";
    sec.innerHTML = '<div class="hist-data">Copies já usadas</div>';
    copiesUsadas.forEach((c) => sec.appendChild(copyHistRow(c)));
    body.appendChild(sec);
  }
  aplicarVisPromptHist();
}

// Só expande/colapsa se o clique não foi num botão de ação.
function ligarToggleHistRow(row) {
  row.querySelector(".hist-row-head").addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    row.classList.toggle("aberto");
  });
}

function promptHistRow(p) {
  const row = document.createElement("div");
  row.className = "hist-row";
  row.innerHTML = `
    <div class="hist-row-head">
      <span class="tag">${escapeHtml(p.id || "")}</span>
      <span class="tag angulo">${escapeHtml(p.angulo || "ângulo")}</span>
      <span class="hist-row-txt">${escapeHtml(p.copy || "")}</span>
      <span class="tag ok">gerado ✓</span>
      <button class="btn ghost btn-mini btn-reusar">Reaproveitar</button>
      <svg class="ic chev" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <div class="hist-row-body"><pre>${escapeHtml(p.prompt || "")}</pre></div>`;
  ligarToggleHistRow(row);
  row.querySelector(".btn-reusar").addEventListener("click", (e) => {
    e.stopPropagation();
    reaproveitarPrompt(p);
  });
  return row;
}

function copyHistRow(c) {
  const row = document.createElement("div");
  row.className = "hist-row";
  const sub = (c.subheadline || "").trim()
    ? `<div class="hist-copy-sub">${escapeHtml(c.subheadline)}</div>` : "";
  const apoio = (c.apoio || "").trim()
    ? `<div class="hist-copy-sub">${escapeHtml(c.apoio)}</div>` : "";
  const corpo = (c.corpo || "").trim()
    ? `<p>${escapeHtml(c.corpo)}</p>` : "";
  row.innerHTML = `
    <div class="hist-row-head">
      <span class="tag">${escapeHtml(c.id || "")}</span>
      <span class="tag angulo">${escapeHtml(c.angulo || "ângulo")}</span>
      <span class="hist-row-txt">${escapeHtml(c.headline || "")}</span>
      <span class="tag ok">usada ✓</span>
      <svg class="ic chev" viewBox="0 0 24 24" fill="none"><path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <div class="hist-row-body">
      ${sub}
      ${apoio}
      ${corpo}
      <div class="hist-copy-cta">${escapeHtml(c.cta || "")}</div>
    </div>`;
  ligarToggleHistRow(row);
  return row;
}

// Clona um prompt já gerado de volta para a fila de pendentes (novo id).
async function reaproveitarPrompt(p) {
  let maior = 0;
  dadosPrompts.forEach((d) => {
    const m = /criativo_(\d+)/.exec(String(d.id || ""));
    if (m) maior = Math.max(maior, Number(m[1]));
  });
  const novoId = `criativo_${String(maior + 1).padStart(2, "0")}`;
  const clone = { ...p, id: novoId };
  delete clone.status;   // volta a ser pendente
  dadosPrompts.push(clone);
  await persistirPrompts();
  renderPrompts();
  carregarProdutos();
  toast(`Reaproveitado como ${novoId} (pendente) ✓`);
}

el("btnPromptHistToggle").addEventListener("click", (e) => {
  e.stopPropagation();
  el("promptHist").classList.toggle("aberto");
});
el("btnPromptHistClose").addEventListener("click", () => {
  el("promptHist").classList.remove("aberto");
});
// Clique fora do painel flutuante o fecha.
document.addEventListener("click", (e) => {
  const wrap = el("promptHist");
  if (wrap.classList.contains("aberto") && !e.target.closest("#promptHist")) {
    wrap.classList.remove("aberto");
  }
});
// Esc fecha o painel (sem interferir no lightbox/modal, que retornam antes).
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") el("promptHist").classList.remove("aberto");
});

function atualizarSelecaoPrompts() {
  const n = document.querySelectorAll("#listaPrompts .chk-prompt:checked").length;
  el("selInfo").textContent = n ? `${n} selecionado(s)` : "";
  const btnGerar = el("btnGerarSelecionados");
  btnGerar.textContent = `Gerar imagens (${n})`;
  btnGerar.disabled = n === 0;
  const btnDescartar = el("btnDescartarSelecionados");
  btnDescartar.textContent = `Descartar (${n})`;
  btnDescartar.disabled = n === 0;
}

async function persistirPrompts() {
  await fetch(`/api/prompts/${produto}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompts: dadosPrompts }),
  });
  return dadosPrompts.length;
}

async function apagarPrompt(id) {
  const prompt = dadosPrompts.find((d) => d.id === id);
  if (!prompt || !window.confirm("Descartar este prompt? Esta ação não pode ser desfeita.")) return;
  dadosPrompts = dadosPrompts.filter((d) => d.id !== id);
  await persistirPrompts();
  renderPrompts();
  toast("Prompt apagado ✓");
  carregarProdutos();
}

async function descartarPromptsSelecionados() {
  const ids = [...document.querySelectorAll("#listaPrompts .chk-prompt:checked")]
    .map((checkbox) => checkbox.dataset.id)
    .filter(Boolean);
  if (!ids.length) return;
  const plural = ids.length === 1 ? "prompt selecionado" : "prompts selecionados";
  if (!window.confirm(`Descartar ${ids.length} ${plural}? Esta ação não pode ser desfeita.`)) return;

  dadosPrompts = dadosPrompts.filter((prompt) => !ids.includes(String(prompt.id)));
  await persistirPrompts();
  renderPrompts();
  toast(`${ids.length} ${ids.length === 1 ? "prompt descartado" : "prompts descartados"} ✓`);
  carregarProdutos();
}

// Loading visível durante a geração de prompts (chamada única ao Claude).
function setPromptsBusy(on, msg) {
  el("btnGerarSelecionados").disabled = on;
  if (on) {
    // Só um spinner discreto na barra (o texto completo fica no centro, sem duplicar).
    el("promptsInfo").innerHTML = `<span class="spin"></span>`;
    el("listaPrompts").innerHTML =
      `<div class="carregando"><span class="spin big"></span><div>${msg || "gerando…"}</div>` +
      `<small>O Claude está escrevendo as direções de arte. Leva alguns segundos.</small></div>`;
  }
}

el("chkTodosPrompts").addEventListener("change", (e) => {
  document.querySelectorAll("#listaPrompts .chk-prompt").forEach((c) => {
    c.checked = e.target.checked;
    c.closest(".prompt-row").classList.toggle("sel", c.checked);
  });
  atualizarSelecaoPrompts();
});

el("btnDescartarSelecionados").addEventListener("click", descartarPromptsSelecionados);

function atualizarFaseCriativos(texto, carregando = false) {
  el("criativosInfo").innerHTML = carregando
    ? `<span class="spin"></span> ${texto}` : (texto || "");
}

el("btnGerarSelecionados").addEventListener("click", async () => {
  if (!produto) return;
  pararTudoSolicitado = false;
  escreverConsole("Solicitando geracao dos prompts selecionados");
  const ids = [...document.querySelectorAll("#listaPrompts .chk-prompt:checked")]
    .map((c) => c.dataset.id);
  if (!ids.length) { toast("Selecione ao menos um prompt"); return; }
  try {
    // Os prompts já são finais (vieram prontos de "Enviar para Prompts"); só
    // garantimos que edições recentes na textarea foram salvas antes de gerar.
    clearTimeout(salvarTimer);
    await persistirPrompts();
    const r = await (await fetch(`/api/gerar_imagens/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    })).json();
    if (!r.ok) { toast(r.erro || "erro"); return; }
    atualizarFaseCriativos("Geração iniciada. Acompanhe o progresso abaixo.", true);
    trocarStep("criativos", true); // skipLoad: o polling cuida do status
    carregarHistorico();
    el("btnParar").style.display = "";
    iniciarPolling(true);
    toast(`Gerando ${ids.length} criativo(s)…`);
  } catch (e) { toast("Erro de conexão"); }
});

// ------------------------------------------------------------ Criativos ----
el("btnGerarImagens").addEventListener("click", async () => {
  if (!produto) return;
  pararTudoSolicitado = false;
  escreverConsole("Solicitando geracao dos criativos pendentes");
  const r = await (await fetch(`/api/gerar_imagens/${produto}`, { method: "POST" })).json();
  if (!r.ok) { toast(r.erro || "erro"); return; }
  el("btnParar").style.display = "";
  iniciarPolling(true);
});

el("btnRodarFilaRefino")?.addEventListener("click", () => {
  if (!filaRefino.length) return;
  pararTudoSolicitado = false;
  filaRefinoArmada = true;
  processarFilaRefino();
});

el("btnParar").textContent = "Parar tudo";
el("btnParar").title = "Interrompe tudo: geracao atual e fila de refinamentos";
el("btnParar").addEventListener("click", async () => {
  if (!produto) return;
  pararTudoSolicitado = true;
  filaRefinoArmada = false;
  const itensCancelados = filaRefino.length;
  filaRefino = [];
  atualizarRefinoUI();
  el("btnParar").disabled = true;
  try {
    await fetch(`/api/parar/${produto}`, { method: "POST" });
    toast("Interrompendo… a imagem atual é abortada.");
  } catch (e) { toast("Erro ao parar"); el("btnParar").disabled = false; }
});

// aguardarInicio=true: acabamos de disparar uma geração — o status.json em disco
// ainda é o da rodada ANTERIOR. Ignora status "parado" até a nova thread escrever
// o dela (senão o polling se mata lendo dado velho e a tela congela em 0/0).
let pollAguardando = false;
let pollInicio = 0;
let geracaoInicio = 0;
let consoleLinhas = [];
let consoleUltimoAtual = null;
let consoleUltimoFeitos = 0;
let consoleUltimoErro = 0;

function escreverConsole(texto, tipo = "info") {
  const agora = new Date().toLocaleTimeString("pt-BR");
  consoleLinhas.push(`[${agora}] ${tipo === "erro" ? "ERRO" : tipo === "ok" ? "OK" : "INFO"}  ${texto}`);
  if (consoleLinhas.length > 300) consoleLinhas = consoleLinhas.slice(-300);
  el("consoleGeracao").textContent = consoleLinhas.join("\n");
  el("consoleGeracao").scrollTop = el("consoleGeracao").scrollHeight;
}

function resetarConsole() {
  consoleLinhas = [];
  consoleUltimoAtual = null;
  consoleUltimoFeitos = 0;
  consoleUltimoErro = 0;
  el("consoleGeracao").textContent = "";
  el("consoleEstado").textContent = "aguardando";
}

el("consoleHead").addEventListener("click", (e) => {
  if (e.target.closest("button:not(#btnConsoleToggle)")) return;
  const box = el("consoleBox");
  const aberto = box.classList.toggle("aberto");
  el("btnConsoleToggle").setAttribute("aria-expanded", aberto ? "true" : "false");
});
el("btnConsoleToggle").addEventListener("click", (e) => {
  e.stopPropagation();
  el("consoleHead").click();
});

el("btnCopiarConsole").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(consoleLinhas.join("\n"));
    toast("Console copiado");
  } catch (e) { toast("Nao foi possivel copiar o console"); }
});
el("btnLimparConsole").addEventListener("click", resetarConsole);

function iniciarPolling(aguardarInicio) {
  if (pollTimer) clearInterval(pollTimer);
  pollAguardando = !!aguardarInicio;
  pollInicio = Date.now();
  geracaoInicio = Date.now();
  if (aguardarInicio) {
    el("progresso").style.display = "block";
    el("progStatus").innerHTML = '<span class="spin"></span> iniciando geração…';
    el("progBar").style.width = "0%";
    el("progContagem").textContent = "…";
    el("progErros").textContent = "";
  }
  pollTimer = setInterval(carregarStatus, 1500);
  carregarStatus();
}

async function carregarStatus() {
  if (!produto) return;
  let s;
  try { s = await (await fetch(`/api/status/${produto}`)).json(); } catch (e) { return; }

  // Nova geração disparada mas o status em disco ainda é o antigo: espera.
  if (pollAguardando && !s.em_andamento) {
    if (Date.now() - pollInicio > 30000) { // não começou em 30s: desiste do modo espera
      pollAguardando = false;
      el("progStatus").textContent = "a geração não iniciou — veja o console do app";
    }
    return;
  }
  if (s.em_andamento) pollAguardando = false;

  if (s.em_andamento && s.atual && s.atual !== consoleUltimoAtual) {
    consoleUltimoAtual = s.atual;
    el("consoleEstado").textContent = `gerando ${s.atual}`;
    escreverConsole(`Gerando ${s.atual}`);
  }
  if ((s.feitos || 0) > consoleUltimoFeitos) {
    escreverConsole(`${s.feitos} de ${s.total || 0} concluido(s)` , "ok");
    consoleUltimoFeitos = s.feitos || 0;
  }
  if ((s.erros || []).length > consoleUltimoErro) {
    (s.erros || []).slice(consoleUltimoErro).forEach((e) => escreverConsole(`${e.id}: ${e.erro}`, "erro"));
    consoleUltimoErro = s.erros.length;
  }

  const total = s.total || 0, feitos = s.feitos || 0;
  if (total > 0) el("progresso").style.display = "block";
  el("progBar").style.width = (total ? Math.round((feitos / total) * 100) : 0) + "%";
  el("progContagem").textContent = `${feitos} / ${total}`;
  geracaoEmAndamento = !!s.em_andamento;
  if (s.em_andamento) {
    const elapsed = Math.max(1, (Date.now() - geracaoInicio) / 1000);
    const media = feitos ? elapsed / feitos : 0;
    const restante = media ? Math.max(1, Math.ceil((total - feitos) * media)) : null;
    atualizarFaseCriativos(`Gerando criativos: ${feitos} de ${total}${restante ? ` · estimativa: ~${restante}s` : " · calculando tempo…"}`, true);
    el("progStatus").innerHTML = `gerando: <span class="atual">${s.atual || "…"}</span>`;
    el("btnGerarImagens").disabled = true;
    el("btnParar").style.display = "";
  } else {
    atualizarFaseCriativos(s.cancelado ? "Geração interrompida." : (feitos && feitos === total ? "Geração concluída ✓" : ""));
    if (s.cancelado) escreverConsole("Geracao interrompida pelo usuario", "erro");
    else if (feitos && feitos === total) escreverConsole("Lote concluido", "ok");
    el("consoleEstado").textContent = s.cancelado ? "interrompido" : (feitos ? "concluido" : "aguardando");
    el("progStatus").textContent = s.cancelado ? "interrompido" : (feitos && feitos === total ? "concluído ✓" : "");
    el("btnGerarImagens").disabled = false;
    el("btnParar").style.display = "none";
    el("btnParar").disabled = false;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    // Um refino pode ter virado verdade visual durável (destilada em background).
    // Recarrega o card pra aparecer o que foi aprendido, sem o usuário trocar de aba.
    if (produto) setTimeout(carregarVerdade, 1500);
    // Liberou o lock: dispara a próxima alteração da fila, se houver.
    refinoTerminou();
  }
  // grade
  const grade = el("grade");
  const mtimes = s.mtimes || {};
  const versao = (arq) => mtimes[arq] || 0;  // cache-buster: muda quando o PNG é regerado
  const existentes = new Set([...grade.querySelectorAll("img")].map((i) => i.dataset.arq));
  const naLista = new Set(s.arquivos || []);
  // Remove thumbs que saíram da lista; atualiza os que foram REGERADOS (mesmo nome, novo mtime).
  grade.querySelectorAll("img").forEach((img) => {
    const arq = img.dataset.arq;
    if (!naLista.has(arq)) { img.closest(".thumb").remove(); return; }
    const v = String(versao(arq));
    if (v !== "0" && img.dataset.v !== v) {
      img.dataset.v = v;
      img.src = `/criativos/${produto}/${encodeURIComponent(arq)}?t=${v}`;
      // Se o lightbox está mostrando esta imagem, reflete a nova versão na hora.
      const alvo = lbItens[lbIdx];
      if (lightboxAberto() && lbComAcoes && alvo && alvo.arq === arq) renderLightbox();
    }
  });
  (s.arquivos || []).forEach((arq) => {
    if (existentes.has(arq)) return;
    const v = versao(arq) || Date.now();
    const src = `/criativos/${produto}/${encodeURIComponent(arq)}?t=${v}`;
    const fmt = (s.formatos && s.formatos[idBaseArq(arq)]) || "padrao";
    const d = document.createElement("div");
    d.className = "thumb";
    d.innerHTML = `
      <div class="thumb-img">
        <img data-arq="${arq}" data-v="${v}" src="${src}">
        <div class="thumb-acoes">
          <button class="btn primary btn-mini" data-acao="refinar">Refinar</button>
          <button class="btn ghost btn-mini" data-acao="refazer">Refazer</button>
          <button class="btn danger btn-mini" data-acao="descartar">Descartar</button>
        </div>
      </div>
      <div class="rod">${formatoSelo(fmt)}<span>${arq}</span><button class="btn ghost btn-mini" data-acao="refinar-fora">Refinar</button></div>`;
    d.querySelector('[data-acao="refinar"]').addEventListener("click", (e) => {
      e.stopPropagation(); abrirRefino(arq);
    });
    d.querySelector('[data-acao="refazer"]').addEventListener("click", (e) => {
      e.stopPropagation(); abrirRefazer(arq);
    });
    d.querySelector('[data-acao="descartar"]').addEventListener("click", (e) => {
      e.stopPropagation(); descartarCriativo(arq, d);
    });
    d.querySelector('[data-acao="refinar-fora"]').addEventListener("click", (e) => {
      e.stopPropagation(); abrirRefino(arq);
    });
    // Clique na imagem (fora dos botões) amplia no lightbox.
    d.querySelector(".thumb-img").addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      const itens = itensDaGrade();
      abrirLightbox(itens, itens.findIndex((i) => i.arq === arq), true);
    });
    // Insere os thumbs reais ANTES dos placeholders shimmer (que ficam no fim).
    const primeiroSkel = grade.querySelector(".thumb-skel");
    if (primeiroSkel) grade.insertBefore(d, primeiroSkel);
    else grade.appendChild(d);
  });
  atualizarSkeletons(grade, s);
  el("criativosInfo").textContent = "";  // orientação de vazio vem do estado-vazio central
  const erros = s.erros || [];
  el("progErros").textContent = erros.length ? "⚠ " + erros.map((e) => `${e.id}: ${e.erro.split("\n")[0]}`).join("\n") : "";
  if (lightboxAberto()) atualizarRefinoUI();
  atualizarFerramentasCriativos(s);
}

// Mostra a barra de ferramentas de IA (ideias / verificação) só quando há
// criativos prontos na tela e nada está gerando agora.
function atualizarFerramentasCriativos(s) {
  const bar = el("criativosFerramentas");
  if (!bar) return;
  const temImgs = !!el("grade").querySelector("img[data-arq]");
  const ocupado = !!(s && s.em_andamento);
  bar.style.display = temImgs ? "flex" : "none";
  // "Sugerir novas ideias" é só análise de texto (copy/conceito) — não usa o lock de
  // geração de imagem, então pode rodar durante a geração. "Verificar imagens" inspeciona
  // as próprias imagens; enquanto elas ainda estão sendo geradas/refinadas não faz sentido,
  // então esse fica travado até terminar.
  if (el("btnSugerirIdeias")) el("btnSugerirIdeias").disabled = false;
  if (el("btnVerificarImagens")) el("btnVerificarImagens").disabled = ocupado;
}

// Placeholders "shimmer" (skeleton loading): enquanto a geração está em
// andamento, mostra um tile por imagem que ainda não chegou (mín. 1 pro atual).
// Some assim que `em_andamento` fica false.
function criarSkeleton() {
  const d = document.createElement("div");
  d.className = "thumb thumb-skel";
  // Placeholder de geração de imagem: glow que morfa dentro do tile + badge de
  // resolução + label com shimmer, e uma linha de legenda (o prompt) shimmerando.
  const res = (typeof tamanhoPadrao === "function" ? tamanhoPadrao() : "1024x1024").replace("x", " × ");
  d.innerHTML = `<div class="skel-img gen-img">`
    + `<span class="gen-glow"></span>`
    + `<span class="gen-res">${res}</span>`
    + `<span class="gen-label">Gerando</span>`
    + `</div><div class="skel-rod"><span class="skel-line"></span></div>`;
  return d;
}

function atualizarSkeletons(grade, s) {
  const skels = [...grade.querySelectorAll(".thumb-skel")];
  if (!s.em_andamento) { skels.forEach((k) => k.remove()); return; }
  const faltam = Math.max(0, (s.total || 0) - (s.feitos || 0));
  // Só mostra shimmer para as imagens REALMENTE em geração agora (status.atuais =
  // a fila em voo, ~= nº de workers), não para todas as que ainda faltam. Conforme
  // uma termina, o tile vira imagem real e outra entra em voo com seu shimmer.
  const emVoo = Array.isArray(s.atuais) ? s.atuais.length : 0;
  const desejado = faltam <= 0 ? 0 : Math.max(1, Math.min(faltam, emVoo || 1));
  // Remove os excedentes...
  for (let i = skels.length - 1; i >= desejado; i--) skels[i].remove();
  // ...e cria os que faltam, sempre ao final da grade.
  for (let i = skels.length; i < desejado; i++) grade.appendChild(criarSkeleton());
}

async function descartarCriativo(arq, thumbEl) {
  // Pode descartar mesmo com uma geração/refino rolando: o arquivo só é MOVIDO para
  // descartados/ (nunca apagado) e a geração reconcilia a grade com o disco, então o
  // thumb descartado não volta. Se este criativo estiver sendo refinado, tudo bem —
  // ele continua existindo no disco enquanto a nova versão é gerada.
  if (!confirm(`Descartar ${arq}? Ele vai para a pasta descartados/ (não é apagado).`)) return false;
  try {
    const r = await (await fetch(`/api/descartar_criativo/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: arq }),
    })).json();
    if (!r.ok) { toast(r.erro || "erro"); return false; }
    if (thumbEl) thumbEl.remove();
    // Tira da fila alterações pendentes desta imagem (o arquivo não existe mais).
    filaRefino = filaRefino.filter((i) => i.arq !== arq);
    delete refinoDrafts[arq];
    atualizarRefinoUI();
    toast("Criativo descartado ✓");
    return true;
  } catch (e) { toast("Erro de conexão"); return false; }
}

// Descarte SEM confirmação individual (usado pela oferta em lote pós-correção do
// QA, onde o usuário já confirmou uma vez). Move o arquivo pra descartados/ e tira
// o thumb da grade. Devolve true/false.
async function descartarSilencioso(arq) {
  try {
    const r = await (await fetch(`/api/descartar_criativo/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arquivo: arq }),
    })).json();
    if (!r.ok) return false;
    const img = el("grade").querySelector(`img[data-arq="${CSS.escape(arq)}"]`);
    if (img) { const t = img.closest(".thumb"); if (t) t.remove(); }
    filaRefino = filaRefino.filter((i) => i.arq !== arq);
    delete refinoDrafts[arq];
    return true;
  } catch (e) { return false; }
}

// -------------------------------------------------------------- Refino -----
let refinoArquivo = null;
let geracaoEmAndamento = false;

// Fila de alterações: o backend só processa uma geração/refino por vez (lock por
// produto), então mantemos a fila no cliente. Cada pedido de alteração entra na
// fila; assim que a geração/refino atual termina, o próximo item é disparado.
let filaRefino = [];      // [{ arq, instrucao }] aguardando a vez
let refinoEmVoo = null;   // { arq, instrucao } sendo gerado agora, ou null
let pararTudoSolicitado = false;
const refinoDrafts = {};  // texto digitado por imagem (preserva ao navegar)
let filaRefinoExecutando = false;
let filaRefinoArmada = false;

// Enfileira uma alteração e tenta processar. Se algo já está gerando, aguarda a vez.
function enfileirarRefino(arq, instrucao) {
  instrucao = (instrucao || "").trim();
  if (!instrucao) { toast("Descreva o ajuste desejado"); return; }
  if (!arq) return;
  pararTudoSolicitado = false;
  filaRefino.push({ arq, instrucao });
  const ocupado = refinoEmVoo || geracaoEmAndamento;
  toast(ocupado
    ? `Na fila — ${filaRefino.length} alteração(ões) aguardando`
    : `Alterando ${arq}…`);
  atualizarRefinoUI();
  // Execução manual: o usuário adiciona todos os refinamentos e roda o lote.
}

// Dispara o próximo item da fila, se houver e nada estiver ocupando o lock.
function processarFilaRefino() {
  if (pararTudoSolicitado) return;
  if (!filaRefinoArmada) return;
  if (refinoEmVoo || filaRefinoExecutando) return;
  if (geracaoEmAndamento) { toast("A geração atual termina antes da fila de refinamentos"); return; }
  if (!filaRefino.length) return;
  const items = filaRefino.splice(0);
  filaRefinoArmada = false;
  refinoEmVoo = { items };
  filaRefinoExecutando = true;
  atualizarRefinoUI();
  dispararRefino(items);
}

async function dispararRefino(items) {
  try {
    const r = await (await fetch(`/api/refinar_fila/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ itens: items, modelo: modelo() }),
    })).json();
    if (!r.ok) {
      toast(r.erro || "erro ao alterar");
      refinoEmVoo = null;
      filaRefinoExecutando = false;
      filaRefino = items.concat(filaRefino);
      atualizarRefinoUI();
      processarFilaRefino();   // tenta o próximo mesmo assim
      return;
    }
    el("btnParar").style.display = "";
    iniciarPolling(true);
  } catch (e) {
    toast("Erro de conexão");
    refinoEmVoo = null;
    filaRefinoExecutando = false;
    filaRefino = items.concat(filaRefino);
    atualizarRefinoUI();
  }
}

// Chamado pelo polling quando a geração/refino atual termina: libera e avança a fila.
function refinoTerminou() {
  if (refinoEmVoo) { refinoEmVoo = null; filaRefinoExecutando = false; }
  atualizarRefinoUI();
  if (!pararTudoSolicitado) processarFilaRefino();
}

// Estado de uma imagem na fila: "gerando" | "fila" | "idle".
function estadoRefino(arq) {
  if (refinoEmVoo && refinoEmVoo.items.some((i) => i.arq === arq)) return "gerando";
  if (filaRefino.some((i) => i.arq === arq)) return "fila";
  return "idle";
}

// Atualiza a linha de status do lightbox conforme o estado da imagem atual + fila.
function atualizarRefinoUI() {
  const status = el("lbRefinoStatus");
  const btn = el("lbRefinoBtn");
  if (!status || !btn) return;
  const item = lbItens[lbIdx];
  const arq = item && item.arq;
  const naFila = filaRefino.length;
  const btnFila = el("btnRodarFilaRefino");
  if (btnFila) {
    btnFila.style.display = naFila ? "inline-flex" : "none";
    btnFila.disabled = !!refinoEmVoo || geracaoEmAndamento;
    btnFila.textContent = `Rodar fila de refinamentos (${naFila})`;
  }
  const ocupado = !!(refinoEmVoo || geracaoEmAndamento);
  btn.textContent = ocupado || naFila ? "Adicionar à fila" : "Alterar";

  if (!arq) { status.innerHTML = ""; return; }
  const est = estadoRefino(arq);
  if (est === "gerando") {
    status.innerHTML = `<span class="spin"></span> Gerando a alteração desta imagem…`;
  } else if (est === "fila") {
    // Quantos itens (incluindo o em voo) vêm antes deste na ordem de processamento.
    const idxNaFila = filaRefino.findIndex((i) => i.arq === arq);
    const antes = (refinoEmVoo ? refinoEmVoo.items.length : 0) + idxNaFila;
    status.innerHTML = antes > 0
      ? `Na fila — ${antes} alteração(ões) antes desta.`
      : `Na fila — próxima a ser gerada.`;
  } else if (ocupado || naFila) {
    const total = (refinoEmVoo ? refinoEmVoo.items.length : 0) + naFila;
    status.innerHTML = `${total} alteração(ões) na fila. O que você pedir aqui entra na fila.`;
  } else {
    status.innerHTML = "";
  }
}

// Modal de refino (botão "Refinar" nos thumbs da grade) — agora enfileira também.
function abrirRefino(arq) {
  refinoArquivo = arq;
  el("refinoTitulo").textContent = `Refinar ${arq}`;
  el("refinoImg").src = `/criativos/${produto}/${encodeURIComponent(arq)}?t=${Date.now()}`;
  el("refinoInstrucao").value = "";
  el("modalRefino").style.display = "flex";
  el("refinoInstrucao").focus();
}

function fecharRefino() {
  el("modalRefino").style.display = "none";
  refinoArquivo = null;
}

el("btnRefinoCancelar").addEventListener("click", fecharRefino);
el("modalRefino").addEventListener("click", (e) => {
  if (e.target === el("modalRefino")) fecharRefino();
});
document.addEventListener("keydown", (e) => {
  // Lightbox tem prioridade: Esc fecha, setas navegam — MENOS quando o foco está
  // no campo de alteração (aí as setas movem o cursor e Esc só sai do campo).
  if (lightboxAberto()) {
    const emCampo = document.activeElement === el("lbRefinoInput");
    if (e.key === "Escape") {
      e.preventDefault();
      if (emCampo) { el("lbRefinoInput").blur(); return; }
      fecharLightbox();
      return;
    }
    if (emCampo) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); lbNavegar(-1); }
    if (e.key === "ArrowRight") { e.preventDefault(); lbNavegar(1); }
    return;
  }
  if (e.key === "Escape" && el("modalRefino").style.display !== "none") fecharRefino();
});

el("btnRefinoConfirmar").addEventListener("click", () => {
  const instrucao = el("refinoInstrucao").value.trim();
  if (!instrucao) { toast("Descreva o ajuste desejado"); return; }
  if (!refinoArquivo) return;
  enfileirarRefino(refinoArquivo, instrucao);
  fecharRefino();
});

// ------------------------------------------------------------ Lightbox -----
// Visualização ampliada de qualquer imagem. itens = [{src, nome, arq?}].
// comAcoes=true habilita Refinar/Descartar (só faz sentido na grade de criativos).
let lbItens = [];
let lbIdx = 0;
let lbComAcoes = false;

function abrirLightbox(itens, idx, comAcoes) {
  if (!itens || !itens.length) return;
  lbItens = itens;
  lbIdx = Math.max(0, Math.min(idx || 0, itens.length - 1));
  lbComAcoes = !!comAcoes;
  const lb = el("lightbox");
  lb.classList.toggle("sem-acoes", !lbComAcoes);
  lb.classList.add("aberto");
  lb.setAttribute("aria-hidden", "false");
  renderLightbox();
}

// Fonte mais recente da imagem: na grade de criativos o thumb pode ter sido
// regerado (novo cache-buster), então lê o src atual da grade quando existir.
function srcAtualDe(item) {
  if (lbComAcoes && item && item.arq) {
    const img = el("grade").querySelector(`img[data-arq="${CSS.escape(item.arq)}"]`);
    if (img) return img.src;
  }
  return item ? item.src : "";
}

function renderLightbox() {
  const item = lbItens[lbIdx];
  if (!item) { fecharLightbox(); return; }
  const lb = el("lightbox");
  const src = srcAtualDe(item);
  item.src = src;   // mantém a lista em dia (navegação/baixar usam o mais recente)
  el("lbImg").src = src;
  el("lbNome").textContent = item.nome || "";
  el("lbContagem").textContent = lbItens.length > 1 ? `${lbIdx + 1} de ${lbItens.length}` : "";
  const unica = lbItens.length <= 1;
  el("lbPrev").disabled = unica || lbIdx === 0;
  el("lbNext").disabled = unica || lbIdx === lbItens.length - 1;
  // Restaura o rascunho de alteração desta imagem (sem clobber se estiver digitando).
  const inp = el("lbRefinoInput");
  if (inp && document.activeElement !== inp) {
    inp.value = (item.arq && refinoDrafts[item.arq]) || "";
    inp.style.height = "auto";
  }
  atualizarRefinoUI();
  // Micro-transição ao trocar de imagem.
  lb.classList.remove("trocando");
  void lb.offsetWidth; // reinicia a animação
  lb.classList.add("trocando");
}

function fecharLightbox() {
  const lb = el("lightbox");
  lb.classList.remove("aberto", "trocando");
  lb.setAttribute("aria-hidden", "true");
  el("lbImg").src = "";
  lbItens = [];
}

function lbNavegar(delta) {
  const novo = lbIdx + delta;
  if (novo < 0 || novo >= lbItens.length) return;
  lbIdx = novo;
  renderLightbox();
}

function lightboxAberto() {
  return el("lightbox").classList.contains("aberto");
}

// Monta a lista a partir das imagens atualmente na grade de criativos.
function itensDaGrade() {
  return [...el("grade").querySelectorAll("img")].map((img) => ({
    src: img.src, nome: img.dataset.arq, arq: img.dataset.arq,
  }));
}

el("lbFechar").addEventListener("click", fecharLightbox);
el("lbPrev").addEventListener("click", () => lbNavegar(-1));
el("lbNext").addEventListener("click", () => lbNavegar(1));
// Clique no fundo (fora da imagem e dos controles) fecha.
el("lightbox").addEventListener("click", (e) => {
  if (e.target === el("lightbox") || e.target.classList.contains("lb-palco")) fecharLightbox();
});

// Campo de alteração inline: enfileira o pedido para a imagem em foco.
el("lbRefino").addEventListener("submit", (e) => {
  e.preventDefault();
  const item = lbItens[lbIdx];
  if (!item || !item.arq) return;
  const inp = el("lbRefinoInput");
  const instrucao = inp.value.trim();
  if (!instrucao) { toast("Descreva o ajuste desejado"); return; }
  enfileirarRefino(item.arq, instrucao);
  delete refinoDrafts[item.arq];
  inp.value = "";
  inp.style.height = "auto";
});
// Enter envia; Shift+Enter quebra linha. Guarda o rascunho por imagem enquanto digita.
el("lbRefinoInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    el("lbRefino").requestSubmit();
  }
});
el("lbRefinoInput").addEventListener("input", (e) => {
  const item = lbItens[lbIdx];
  if (item && item.arq) refinoDrafts[item.arq] = e.target.value;
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
});

el("lbDescartar").addEventListener("click", async () => {
  const item = lbItens[lbIdx];
  if (!item || !item.arq) return;
  const img = el("grade").querySelector(`img[data-arq="${CSS.escape(item.arq)}"]`);
  const thumbEl = img ? img.closest(".thumb") : null;
  const ok = await descartarCriativo(item.arq, thumbEl);
  if (!ok) return;
  lbItens.splice(lbIdx, 1);
  if (!lbItens.length) { fecharLightbox(); return; }
  if (lbIdx >= lbItens.length) lbIdx = lbItens.length - 1;
  renderLightbox();
});

// -------------------------------------------------------------- Refazer -----
// Regenera o criativo do zero com referências novas + prompt (mantém a copy).
let rfArq = null;
let rfFiles = [];

function abrirRefazer(arq) {
  if (!arq) return;
  rfArq = arq;
  rfFiles = [];
  const img = el("grade").querySelector(`img[data-arq="${CSS.escape(arq)}"]`);
  el("rfImg").src = img ? img.src : `/criativos/${produto}/${encodeURIComponent(arq)}`;
  el("rfPrompt").value = "";
  renderRfRefs();
  el("modalRefazer").style.display = "flex";
  setTimeout(() => el("rfPrompt").focus(), 40);
}

function fecharRefazer() {
  el("modalRefazer").style.display = "none";
  rfFiles = [];
  rfArq = null;
}

function renderRfRefs() {
  const box = el("rfRefs");
  box.innerHTML = "";
  rfFiles.forEach((f, i) => {
    const chip = document.createElement("div");
    chip.className = "rf-chip";
    const url = URL.createObjectURL(f);
    chip.innerHTML = `<img src="${url}" alt=""><button class="anexo-x" title="Remover" type="button">&times;</button>`;
    chip.querySelector("img").addEventListener("load", () => URL.revokeObjectURL(url));
    chip.querySelector(".anexo-x").addEventListener("click", () => { rfFiles.splice(i, 1); renderRfRefs(); });
    box.appendChild(chip);
  });
}

el("rfAnexar")?.addEventListener("click", () => el("rfInput").click());
el("rfInput")?.addEventListener("change", (e) => {
  rfFiles.push(...[...(e.target.files || [])]);
  e.target.value = "";
  renderRfRefs();
});
el("rfCancelar")?.addEventListener("click", fecharRefazer);
el("modalRefazer")?.addEventListener("click", (e) => { if (e.target === el("modalRefazer")) fecharRefazer(); });
el("lbRefazer")?.addEventListener("click", () => {
  const item = lbItens[lbIdx];
  if (item && item.arq) { fecharLightbox(); abrirRefazer(item.arq); }
});

el("rfConfirmar")?.addEventListener("click", async () => {
  const instrucao = el("rfPrompt").value.trim();
  if (!instrucao) { toast("Descreva o que você quer no refazer"); return; }
  if (!rfArq || !produto) return;
  if (geracaoEmAndamento || refinoEmVoo) { toast("Aguarde a geração atual terminar"); return; }
  const btn = el("rfConfirmar");
  btn.disabled = true; btn.textContent = "Enviando…";
  const fd = new FormData();
  fd.append("arquivo", rfArq);
  fd.append("instrucao", instrucao);
  rfFiles.forEach((f) => fd.append("anexos", f, f.name));
  try {
    const r = await (await fetch(`/api/refazer_criativo/${produto}`, { method: "POST", body: fd })).json();
    if (!r.ok) { toast(r.erro || "erro ao refazer"); btn.disabled = false; btn.textContent = "Refazer"; return; }
    fecharRefazer();
    el("btnParar").style.display = "";
    iniciarPolling(true);
    toast("Refazendo criativo…");
  } catch (e) { toast("Erro de conexão"); }
  btn.disabled = false; btn.textContent = "Refazer";
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("modalRefazer").style.display !== "none") fecharRefazer();
});

// ------------------------------------------------------------ Histórico ----
// "+ Novas imagens" (toolbar) delega pra "Nova rodada": arquiva o lote atual e limpa a tela.
el("btnNovasImagens")?.addEventListener("click", () => el("btnNovaRodada")?.click());
el("btnNovaRodada").addEventListener("click", async () => {
  if (!produto) return;
  const temImagens = el("grade").querySelector("img");
  if (temImagens && !confirm("Arquivar a rodada atual no histórico e limpar a tela?")) return;
  try {
    const r = await (await fetch(`/api/criativos/${produto}/arquivar`, { method: "POST" })).json();
    if (!r.ok) { toast("Erro ao arquivar"); return; }
    el("grade").innerHTML = "";
    el("progresso").style.display = "none";
    el("progErros").textContent = "";
    toast(r.arquivados ? `Rodada arquivada (${r.arquivados}) ✓` : "Tela limpa ✓");
    carregarHistorico();
    carregarProdutos();
  } catch (e) { toast("Erro ao arquivar"); }
});

async function carregarHistorico() {
  if (!produto) return;
  let rodadas = [];
  try { rodadas = await (await fetch(`/api/historico/${produto}`)).json(); } catch (e) { return; }
  const wrap = el("historico");
  if (!rodadas.length) { wrap.style.display = "none"; return; }
  wrap.style.display = "block";
  const totalImgs = rodadas.reduce((s, r) => s + r.total, 0);
  el("histTitulo").textContent = `Histórico — ${rodadas.length} rodada(s), ${totalImgs} imagens`;
  const body = el("histBody");
  body.innerHTML = "";
  rodadas.forEach((r) => {
    const bloco = document.createElement("div");
    bloco.className = "hist-rodada";
    const itens = r.arquivos.map((arq) => ({
      src: `/criativos/${produto}/historico/${encodeURIComponent(r.id)}/${encodeURIComponent(arq)}`,
      nome: arq,
    }));
    const grade = itens.map((it, i) =>
      `<a class="hist-thumb" href="${it.src}" data-idx="${i}" title="${it.nome} — clique para ampliar"><img src="${it.src}" loading="lazy"></a>`
    ).join("");
    bloco.innerHTML = `<div class="hist-data">${formatarData(r.id)} · ${r.total} imagens</div>` +
      `<div class="hist-grade">${grade}</div>`;
    // Clique amplia no lightbox (o download fica no botão Baixar de lá).
    bloco.querySelectorAll(".hist-thumb").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        abrirLightbox(itens, Number(a.dataset.idx), false);
      });
    });
    body.appendChild(bloco);
  });
}

function formatarData(id) {
  // id = "2026-07-16_14-30-05"
  const m = id.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : id;
}

el("btnHistToggle").addEventListener("click", () => {
  el("historico").classList.toggle("aberto");
});

// ------------------------------------------------ Assistente: novo produto -
// Wizard guiado (5 passos) para criar um produto do zero: nome, fotos de
// referência, página de vendas, criativos validados (estáticos + transcrições),
// e revisão. Tudo além do nome é opcional e pode ser completado depois.
const NP = { step: 1, total: 5, ref: [], pv: [], est: [], tr: [] };
const NP_TITULOS = { 1: "Nome", 2: "Referência", 3: "Página de vendas", 4: "Validados", 5: "Revisão" };

function abrirNovoProduto(clientePre) {
  NP.step = 1; NP.ref.length = 0; NP.pv.length = 0; NP.est.length = 0; NP.tr.length = 0;
  el("npNome").value = ""; el("npNomeErro").textContent = "";
  el("npPvTexto").value = ""; el("npTrTexto").value = "";
  ["npRefChips", "npPvChips", "npEstChips", "npTrChips"].forEach((id) => (el(id).innerHTML = ""));
  // dropdown de cliente (existentes) — permite já criar o produto dentro de um cliente
  const sel = el("npCliente");
  sel.innerHTML = '<option value="">Sem cliente</option>' +
    clientesConhecidos.map((c) => `<option value="${_esc(c)}">${_esc(c)}</option>`).join("");
  sel.value = (clientePre && clientesConhecidos.includes(clientePre)) ? clientePre : "";
  el("modalNovoProduto").style.display = "flex";
  mostrarPasso(1);
  setTimeout(() => el("npNome").focus(), 60);
}
function fecharNovoProduto() { el("modalNovoProduto").style.display = "none"; }

// ---- Escolha inicial: Adicionar Cliente ou Adicionar Produto -------------
function abrirEscolha() { el("modalEscolha").style.display = "flex"; }
function fecharEscolha() { el("modalEscolha").style.display = "none"; }

// ---- Novo cliente (form mínimo: nome) -----------------------------------
function abrirNovoCliente() {
  el("ncNome").value = ""; el("ncErro").textContent = "";
  el("modalNovoCliente").style.display = "flex";
  setTimeout(() => el("ncNome").focus(), 60);
}
function fecharNovoCliente() { el("modalNovoCliente").style.display = "none"; }

async function criarCliente() {
  const nome = el("ncNome").value.trim();
  const erro = el("ncErro");
  if (!nome) { erro.textContent = "Dê um nome ao cliente."; return; }
  erro.textContent = "";
  const btn = el("ncCriar");
  btn.disabled = true; btn.textContent = "Criando…";
  try {
    const r = await (await fetch("/api/clientes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome }),
    })).json();
    if (!r.ok) { erro.textContent = r.erro || "Não foi possível criar."; return; }
    fecharNovoCliente();
    // garante a sanfona aberta para o cliente novo aparecer expandido nesta sessão
    _clientesExpandidos.add(r.cliente);
    await carregarProdutos();
    toast(r.existente ? `Cliente "${r.cliente}" já existia ✓` : `Cliente "${r.cliente}" criado ✓`);
  } catch (e) {
    erro.textContent = "Erro de conexão.";
  } finally {
    btn.disabled = false; btn.textContent = "Criar cliente";
  }
}

function mostrarPasso(n) {
  NP.step = n;
  document.querySelectorAll("#modalNovoProduto .np-step").forEach((s) =>
    s.classList.toggle("ativo", Number(s.dataset.step) === n));
  el("npProgBar").style.width = (n / NP.total) * 100 + "%";
  el("npPassoNum").textContent = n;
  el("npPassoTit").textContent = NP_TITULOS[n];
  el("npVoltar").style.visibility = n === 1 ? "hidden" : "visible";
  const ultimo = n === NP.total;
  el("npAvancar").style.display = ultimo ? "none" : "";
  el("npCriar").style.display = ultimo ? "" : "none";
  el("npPular").style.display = (n >= 2 && n <= 4) ? "" : "none"; // só nos opcionais
  if (ultimo) renderRevisao();
}

function validarPasso1() {
  const nome = el("npNome").value.trim();
  const erro = el("npNomeErro");
  if (!nome) { erro.textContent = "Dê um nome ao produto."; return false; }
  if (/[<>:"/\\|?*]/.test(nome)) { erro.textContent = 'Evite os caracteres / \\ : * ? " < > |'; return false; }
  const existe = [...document.querySelectorAll(".produtos li")].some((li) =>
    (li.dataset.nome || "").toLowerCase() === nome.toLowerCase());
  if (existe) { erro.textContent = "Já existe um produto com esse nome."; return false; }
  erro.textContent = "";
  return true;
}

function npAvancar() {
  if (NP.step === 1 && !validarPasso1()) return;
  if (NP.step < NP.total) mostrarPasso(NP.step + 1);
}

// Renderiza os "chips" de arquivos de um store, com miniatura para imagens.
function renderChips(store, chipsId, comThumb) {
  const box = el(chipsId);
  box.innerHTML = "";
  store.forEach((f, i) => {
    const chip = document.createElement("div");
    chip.className = "np-chip";
    const thumb = (comThumb && /^image\//.test(f.type))
      ? `<img class="thumb-mini" src="${URL.createObjectURL(f)}" alt="">` : "";
    chip.innerHTML = `${thumb}<span>${escapeHtml(f.name)}</span><button title="Remover">&times;</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      store.splice(i, 1); renderChips(store, chipsId, comThumb);
    });
    box.appendChild(chip);
  });
}

// Liga uma zona de drop (clique + arrastar) a um store, filtrando por tipo.
function ligarDrop(dropId, inputId, store, chipsId, { imagem = false, multi = true } = {}) {
  const drop = el(dropId), input = el(inputId);
  const aceita = (f) => imagem
    ? (/^image\//.test(f.type) || /\.(png|jpe?g|webp|avif|heic|heif)$/i.test(f.name))
    : (/^text\//.test(f.type) || /\.(txt|md)$/i.test(f.name));
  const adicionar = (files) => {
    let arr = [...files].filter(aceita);
    if (!arr.length) return;
    if (!multi) { store.length = 0; arr = arr.slice(0, 1); }
    arr.forEach((f) => store.push(f));
    renderChips(store, chipsId, imagem);
  };
  drop.addEventListener("click", () => input.click());
  input.addEventListener("change", (e) => { adicionar(e.target.files); e.target.value = ""; });
  ["dragover", "dragenter"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer.files) adicionar(e.dataTransfer.files); });
}

function renderRevisao() {
  const nome = el("npNome").value.trim();
  const pvTxt = el("npPvTexto").value.trim();
  const trTxt = el("npTrTexto").value.trim();
  const pvDesc = [pvTxt ? "texto colado" : "", NP.pv.length ? "arquivo" : ""].filter(Boolean).join(" + ");
  const nTr = (trTxt ? 1 : 0) + NP.tr.length;
  const linhas = [
    ["Nome", nome || "—", !nome],
    ["Fotos de referência", NP.ref.length ? `${NP.ref.length} foto(s)` : "nenhuma (opcional)", false],
    ["Página de vendas", pvDesc || "não informada", !pvDesc],
    ["Estáticos validados", NP.est.length ? `${NP.est.length} imagem(ns)` : "nenhum", !NP.est.length],
    ["Transcrições", nTr ? `${nTr} transcrição(ões)` : "nenhuma", !nTr],
  ];
  el("npReview").innerHTML = linhas.map(([k, v, vazio]) =>
    `<div class="np-review-row"><span class="k">${k}</span><span class="v${vazio ? " vazio" : ""}">${escapeHtml(v)}</span></div>`).join("");
}

async function criarProduto() {
  const nome = el("npNome").value.trim();
  if (!nome) { mostrarPasso(1); validarPasso1(); return; }
  const fd = new FormData();
  fd.append("nome", nome);
  fd.append("modelo", modelo());
  const cliente = el("npCliente").value;
  if (cliente) fd.append("cliente", cliente);
  NP.ref.forEach((f) => fd.append("referencia", f));
  const pvTxt = el("npPvTexto").value.trim();
  if (pvTxt) fd.append("pagina_vendas_texto", pvTxt);
  NP.pv.forEach((f) => fd.append("pagina_vendas_arquivo", f));
  NP.est.forEach((f) => fd.append("estaticos", f));
  const trTxt = el("npTrTexto").value.trim();
  if (trTxt) fd.append("transcricao_texto", trTxt);
  NP.tr.forEach((f) => fd.append("transcricao_arquivo", f));

  const btn = el("npCriar");
  btn.disabled = true; btn.textContent = "Criando…";
  try {
    const r = await (await fetch("/api/criar_produto", { method: "POST", body: fd })).json();
    if (!r.ok) {
      toast(r.erro || "erro ao criar");
      if ((r.erro || "").toLowerCase().includes("nome")) mostrarPasso(1);
      btn.disabled = false; btn.textContent = "Criar produto";
      return;
    }
    fecharNovoProduto();
    const rotulo = r.label || r.nome;
    toast(r.config_gerada
      ? `Produto "${rotulo}" criado e configurado ✓`
      : `Produto "${rotulo}" criado. A configuração precisa ser revisada.`);
    await carregarProdutos();
    selecionarProduto(r.nome, r.label);
    if (!NP.ref.length) trocarStep("contexto");  // sem referência: leva pro contexto pra completar
  } catch (e) {
    toast("Erro de conexão");
  }
  btn.disabled = false; btn.textContent = "Criar produto";
}

el("btnNovoProduto").addEventListener("click", abrirEscolha);
// Escolha inicial: cliente ou produto
el("escFechar").addEventListener("click", fecharEscolha);
el("escProduto").addEventListener("click", () => { fecharEscolha(); abrirNovoProduto(); });
el("escCliente").addEventListener("click", () => { fecharEscolha(); abrirNovoCliente(); });
el("modalEscolha").addEventListener("click", (e) => {
  if (e.target === el("modalEscolha")) fecharEscolha();
});
// Novo cliente
el("ncFechar").addEventListener("click", fecharNovoCliente);
el("ncCriar").addEventListener("click", criarCliente);
el("modalNovoCliente").addEventListener("click", (e) => {
  if (e.target === el("modalNovoCliente")) fecharNovoCliente();
});
el("ncNome").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); criarCliente(); }
});
el("npFechar").addEventListener("click", fecharNovoProduto);
el("npAvancar").addEventListener("click", npAvancar);
el("npVoltar").addEventListener("click", () => { if (NP.step > 1) mostrarPasso(NP.step - 1); });
el("npPular").addEventListener("click", () => { if (NP.step < NP.total) mostrarPasso(NP.step + 1); });
el("npCriar").addEventListener("click", criarProduto);
el("modalNovoProduto").addEventListener("click", (e) => {
  if (e.target === el("modalNovoProduto")) fecharNovoProduto();
});
el("npNome").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); npAvancar(); }
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (el("modalNovoProduto").style.display !== "none") fecharNovoProduto();
  if (el("modalNovoCliente").style.display !== "none") fecharNovoCliente();
  if (el("modalEscolha").style.display !== "none") fecharEscolha();
});
ligarDrop("npRefDrop", "npRefInput", NP.ref, "npRefChips", { imagem: true, multi: true });
ligarDrop("npPvDrop", "npPvInput", NP.pv, "npPvChips", { imagem: false, multi: false });
ligarDrop("npEstDrop", "npEstInput", NP.est, "npEstChips", { imagem: true, multi: true });
ligarDrop("npTrDrop", "npTrInput", NP.tr, "npTrChips", { imagem: false, multi: true });

// Colar imagem (Ctrl+V) direto no wizard: passo 2 -> referência, passo 4 -> estáticos.
function _npAlvoColar() {
  if (NP.step === 2) return { store: NP.ref, chips: "npRefChips" };
  if (NP.step === 4) return { store: NP.est, chips: "npEstChips" };
  return null;
}
function adicionarImagensColadas(imgs, alvo) {
  imgs.forEach((f, i) => {
    // A área de transferência costuma nomear tudo de "image.png"; dá um nome único.
    const nome = (f.name && f.name.toLowerCase() !== "image.png") ? f.name : `colado-${i + 1}.png`;
    alvo.store.push(new File([f], nome, { type: f.type || "image/png" }));
  });
  renderChips(alvo.store, alvo.chips, true);
}
document.addEventListener("paste", (e) => {
  if (el("modalNovoProduto").style.display === "none") return;
  const alvo = _npAlvoColar();
  if (!alvo) return;
  const imgs = [...((e.clipboardData && e.clipboardData.items) || [])]
    .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
    .map((it) => it.getAsFile())
    .filter(Boolean);
  if (!imgs.length) return;  // sem imagem no clipboard: deixa o paste normal (texto) seguir
  e.preventDefault();
  adicionarImagensColadas(imgs, alvo);
  toast(`${imgs.length} imagem(ns) colada(s) ✓`);
});

// Ao fechar/ocultar o app, aprende da conversa em aberto (keepalive garante o envio).
window.addEventListener("pagehide", dispararAprendizado);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") dispararAprendizado();
});

// -------------------------------------------------------------- Logos ------
// Etapa 5: sobrepor o logo (PNG) nos criativos. Preview e composicao final
// acontecem no navegador (canvas); o servidor so guarda o logo/config e recebe
// os PNGs prontos. Posicoes: 8 ancoras (cantos, meios das bordas); centro = sem logo.
// escala/margem = padrao global (sliders do topo, "aplicar a todos");
// escalas/margens = valor individual por criativo (sobrepoe o padrao).
let logoConfig = { escala: 15, margem: 4, posicoes: {}, escalas: {}, margens: {} };
let logoExiste = false;
let logoVersao = Date.now();   // cache-buster do /logo/<produto> apos upload
let ultimaPos = "";            // ultima posicao escolhida (para "aplicar em todos")
let salvarLogoTimer = null;

const POS_GRID = [
  ["top-left", "top", "top-right"],
  ["left", "", "right"],
  ["bottom-left", "bottom", "bottom-right"],
];

// Escala/margem efetivas de um criativo: valor individual, ou o padrao global.
function escalaDe(arq) { return logoConfig.escalas[arq] != null ? logoConfig.escalas[arq] : logoConfig.escala; }
function margemDe(arq) { return logoConfig.margens[arq] != null ? logoConfig.margens[arq] : logoConfig.margem; }

async function carregarLogos() {
  if (!produto) return;
  el("logoExportInfo").textContent = "";
  try {
    const [lg, cfg, lista] = await Promise.all([
      fetch(`/api/logo/${produto}`).then((r) => r.json()).catch(() => ({ existe: false })),
      fetch(`/api/logo_config/${produto}`).then((r) => r.json()).catch(() => ({})),
      fetch(`/api/criativos_lista/${produto}`).then((r) => r.json()).catch(() => []),
    ]);
    logoExiste = !!lg.existe;
    logoConfig = {
      escala: cfg.escala || 15, margem: cfg.margem == null ? 4 : cfg.margem,
      posicoes: cfg.posicoes || {},
      escalas: cfg.escalas || {}, margens: cfg.margens || {},
    };
    logoVersao = Date.now();
    renderLogoDrop();
    renderLogosGrade(Array.isArray(lista) ? lista : []);
  } catch (e) { toast("Erro ao carregar logos"); }
}

function renderLogoDrop() {
  const prev = el("logoPreview"), ph = el("logoPlaceholder"), btn = el("btnRemoverLogo");
  if (logoExiste) {
    prev.src = `/logo/${produto}?t=${logoVersao}`;
    prev.style.display = "block";
    ph.style.display = "none";
    btn.style.display = "";
  } else {
    prev.style.display = "none";
    ph.style.display = "";
    btn.style.display = "none";
  }
}

function renderLogosGrade(lista) {
  const box = el("logosGrade");
  box.innerHTML = "";
  if (!lista.length) {
    box.innerHTML = '<div class="ctx-vazio">Nenhum criativo ainda. Gere os criativos na etapa anterior.</div>';
    return;
  }
  lista.forEach((arq) => {
    const pos = logoConfig.posicoes[arq] || "";
    const card = document.createElement("div");
    card.className = "logo-card";
    card.dataset.arq = arq;
    card.dataset.pos = pos;

    const picker = POS_GRID.map((linha) => linha.map((p) => {
      const sel = p === pos ? " sel" : "";
      const centro = p === "" ? " centro" : "";
      const titulo = p === "" ? "Sem logo" : p;
      return `<button class="pos-cel${sel}${centro}" data-pos="${p}" title="${titulo}"></button>`;
    }).join("")).join("");

    const esc = escalaDe(arq), mg = margemDe(arq);
    card.innerHTML = `
      <div class="logo-canvas-wrap">
        <img class="logo-base" src="/criativos/${produto}/${encodeURIComponent(arq)}?t=${logoVersao}" alt="${arq}">
        <img class="logo-over" src="/logo/${produto}?t=${logoVersao}" alt="logo" style="display:none">
      </div>
      <div class="logo-info">
        <span class="logo-arq">${arq}</span>
        <div class="logo-card-main">
          <div class="logo-pos-picker">${picker}</div>
          <div class="logo-card-sliders">
            <label>Escala <b class="cvE">${esc}%</b>
              <input type="range" class="cardEscala" min="4" max="45" value="${esc}"></label>
            <label>Margem <b class="cvM">${mg}%</b>
              <input type="range" class="cardMargem" min="0" max="20" value="${mg}"></label>
          </div>
        </div>
      </div>`;

    card.querySelectorAll(".pos-cel").forEach((b) => {
      b.addEventListener("click", () => {
        const p = b.dataset.pos;
        card.dataset.pos = p;
        if (p) { logoConfig.posicoes[arq] = p; ultimaPos = p; }
        else delete logoConfig.posicoes[arq];
        card.querySelectorAll(".pos-cel").forEach((x) =>
          x.classList.toggle("sel", x.dataset.pos === p));
        aplicarOverlay(card);
        salvarLogoConfigDebounced();
      });
    });
    // Sliders individuais (sobrepoem o padrao global so deste criativo).
    const cE = card.querySelector(".cardEscala"), cM = card.querySelector(".cardMargem");
    cE.addEventListener("input", () => {
      logoConfig.escalas[arq] = Number(cE.value);
      card.querySelector(".cvE").textContent = cE.value + "%";
      aplicarOverlay(card);
      salvarLogoConfigDebounced();
    });
    cM.addEventListener("input", () => {
      logoConfig.margens[arq] = Number(cM.value);
      card.querySelector(".cvM").textContent = cM.value + "%";
      aplicarOverlay(card);
      salvarLogoConfigDebounced();
    });
    box.appendChild(card);
    aplicarOverlay(card);
  });
}

// Posiciona o logo sobreposto (mesma matematica do export em canvas → WYSIWYG).
function aplicarOverlay(card) {
  const over = card.querySelector(".logo-over");
  const pos = card.dataset.pos;
  if (!logoExiste || !pos) { over.style.display = "none"; return; }
  const arq = card.dataset.arq;
  over.style.display = "block";
  over.style.width = escalaDe(arq) + "%";
  const m = margemDe(arq) + "%";
  over.style.top = over.style.bottom = over.style.left = over.style.right = "auto";
  over.style.transform = "none";
  if (pos.includes("top")) over.style.top = m;
  if (pos.includes("bottom")) over.style.bottom = m;
  if (pos.includes("left")) over.style.left = m;
  if (pos.includes("right")) over.style.right = m;
  if (pos === "top" || pos === "bottom") { over.style.left = "50%"; over.style.transform = "translateX(-50%)"; }
  if (pos === "left" || pos === "right") { over.style.top = "50%"; over.style.transform = "translateY(-50%)"; }
}

function atualizarTodosOverlays() {
  document.querySelectorAll("#logosGrade .logo-card").forEach(aplicarOverlay);
}

el("btnAplicarTodos").addEventListener("click", () => {
  if (!ultimaPos) { toast("Escolha uma posição em um criativo primeiro"); return; }
  document.querySelectorAll("#logosGrade .logo-card").forEach((card) => {
    card.dataset.pos = ultimaPos;
    logoConfig.posicoes[card.dataset.arq] = ultimaPos;
    card.querySelectorAll(".pos-cel").forEach((x) =>
      x.classList.toggle("sel", x.dataset.pos === ultimaPos));
    aplicarOverlay(card);
  });
  salvarLogoConfigDebounced();
  toast(`Logo posicionado em todos (${ultimaPos})`);
});

function salvarLogoConfigDebounced() {
  clearTimeout(salvarLogoTimer);
  salvarLogoTimer = setTimeout(async () => {
    try {
      await fetch(`/api/logo_config/${produto}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(logoConfig),
      });
    } catch (e) { /* silencioso */ }
  }, 600);
}

// Upload do logo (clique ou drag/drop)
el("logoDrop").addEventListener("click", () => el("logoInput").click());
el("logoInput").addEventListener("change", (e) => {
  if (e.target.files && e.target.files[0]) enviarLogo(e.target.files[0]);
  e.target.value = "";
});
["dragover", "dragenter"].forEach((ev) =>
  el("logoDrop").addEventListener(ev, (e) => { e.preventDefault(); el("logoDrop").classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  el("logoDrop").addEventListener(ev, (e) => { e.preventDefault(); el("logoDrop").classList.remove("drag"); }));
el("logoDrop").addEventListener("drop", (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) enviarLogo(f);
});

async function enviarLogo(file) {
  if (!produto) { toast("Selecione um produto"); return; }
  if (file.type !== "image/png") { toast("O logo precisa ser um PNG"); return; }
  const fd = new FormData();
  fd.append("logo", file, "logo.png");
  try {
    const r = await (await fetch(`/api/logo/${produto}`, { method: "POST", body: fd })).json();
    if (!r.ok) { toast(r.erro || "erro no upload"); return; }
    logoExiste = true;
    logoVersao = Date.now();
    renderLogoDrop();
    // Recarrega os overlays com o novo logo.
    document.querySelectorAll("#logosGrade .logo-over").forEach((img) => {
      img.src = `/logo/${produto}?t=${logoVersao}`;
    });
    atualizarTodosOverlays();
    toast("Logo enviado ✓");
  } catch (e) { toast("Erro ao enviar logo"); }
}

el("btnRemoverLogo").addEventListener("click", async () => {
  if (!confirm("Remover o logo deste produto?")) return;
  try {
    await fetch(`/api/logo/${produto}`, { method: "DELETE" });
    logoExiste = false;
    renderLogoDrop();
    atualizarTodosOverlays();
    toast("Logo removido");
  } catch (e) { toast("Erro ao remover"); }
});

// Carrega uma imagem (mesma origem → canvas não fica tainted).
function carregarImg(src) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("falha ao carregar " + src));
    img.src = src;
  });
}

// Desenha o logo no canvas com a MESMA matemática do overlay (WYSIWYG).
function desenharLogo(ctx, W, H, logoImg, pos, escalaPct, margemPct) {
  const lw = (escalaPct / 100) * W;
  const lh = lw * (logoImg.naturalHeight / logoImg.naturalWidth);
  const m = (margemPct / 100) * W;
  let x, y;
  if (pos.includes("left")) x = m;
  else if (pos.includes("right")) x = W - lw - m;
  else x = (W - lw) / 2;
  if (pos.includes("top")) y = m;
  else if (pos.includes("bottom")) y = H - lh - m;
  else y = (H - lh) / 2;
  ctx.drawImage(logoImg, x, y, lw, lh);
}

el("btnExportarLogos").addEventListener("click", exportarLogos);

async function exportarLogos() {
  if (!produto) return;
  if (!logoExiste) { toast("Envie um logo primeiro"); return; }
  const cards = [...document.querySelectorAll("#logosGrade .logo-card")]
    .filter((c) => c.dataset.pos);
  if (!cards.length) { toast("Escolha a posição do logo em ao menos um criativo"); return; }

  const btn = el("btnExportarLogos");
  btn.disabled = true;
  el("logoExportInfo").innerHTML = `<span class="spin"></span> compondo ${cards.length} criativo(s)…`;
  try {
    const logoImg = await carregarImg(`/logo/${produto}?t=${logoVersao}`);
    const fd = new FormData();
    for (const card of cards) {
      const arq = card.dataset.arq;
      const base = await carregarImg(`/criativos/${produto}/${encodeURIComponent(arq)}?t=${logoVersao}`);
      const cv = document.createElement("canvas");
      cv.width = base.naturalWidth || 1024;
      cv.height = base.naturalHeight || 1024;
      const ctx = cv.getContext("2d");
      ctx.drawImage(base, 0, 0, cv.width, cv.height);
      desenharLogo(ctx, cv.width, cv.height, logoImg, card.dataset.pos, escalaDe(arq), margemDe(arq));
      const blob = await new Promise((r) => cv.toBlob(r, "image/png"));
      fd.append(arq, blob, arq);
    }
    const r = await (await fetch(`/api/exportar_logos/${produto}`, { method: "POST", body: fd })).json();
    const n = (r.salvos || []).length;
    el("logoExportInfo").innerHTML = n
      ? `✓ ${n} criativo(s) exportado(s) com logo em <code>output/criativos/finais/</code>. `
        + `<a href="#" id="lnkBaixarFinais">baixar todos</a>`
      : "nada exportado";
    const lnk = el("lnkBaixarFinais");
    if (lnk) lnk.addEventListener("click", (e) => { e.preventDefault(); baixarFinais(r.salvos); });
    toast(n ? `${n} exportado(s) ✓` : "nada exportado");
  } catch (e) {
    el("logoExportInfo").textContent = "erro ao exportar: " + (e.message || e);
    toast("Erro ao exportar");
  }
  btn.disabled = false;
}

// Baixa os finais (um download por arquivo).
function baixarFinais(nomes) {
  (nomes || []).forEach((nome, i) => {
    setTimeout(() => {
      const a = document.createElement("a");
      a.href = `/criativos/${produto}/finais/${encodeURIComponent(nome)}?t=${Date.now()}`;
      a.download = nome;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }, i * 250);
  });
}

// ------------------------------------------------- Agente de ideias -------
// Coleta os arquivos de criativo que estão na tela agora (a grade).
function arqsNaTela() {
  return [...el("grade").querySelectorAll("img[data-arq]")].map((i) => i.dataset.arq);
}
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

function abrirModalIdeias() { el("modalIdeias").style.display = "flex"; }
function fecharModalIdeias() { el("modalIdeias").style.display = "none"; }

async function carregarIdeias(adicionar = false) {
  const body = el("ideiasBody");
  const btnMais = el("btnIdeiasRefazer");
  if (!adicionar) {
    ideiasAtuais = [];
    atualizarSelecaoIdeias();
    body.innerHTML = `<div class="painel-ia-estado"><span class="spin"></span> Analisando os criativos e pensando em novas ideias…</div>`;
  }
  if (btnMais) { btnMais.disabled = true; btnMais.textContent = adicionar ? "Gerando…" : "Gerar mais"; }
  try {
    const qtd = Math.max(1, Math.min(parseInt(el("ideiasQtd")?.value, 10) || 3, 8));
    const evitar = ideiasAtuais.map((i) => i.titulo).filter(Boolean);
    const r = await (await fetch(`/api/sugerir_ideias/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo(), arquivos: arqsNaTela(), quantidade: qtd, evitar }),
    })).json();
    if (!r.ok) {
      if (adicionar) toast(r.erro || "erro"); else body.innerHTML = `<div class="painel-ia-estado">${escapeHtml(r.erro || "erro")}</div>`;
      return;
    }
    const novas = Array.isArray(r.ideias) ? r.ideias : [];
    if (adicionar) {
      // Só adiciona ideias com título ainda não visto (evita repetição).
      const vistos = new Set(ideiasAtuais.map((i) => (i.titulo || "").trim().toLowerCase()));
      const frescas = novas.filter((i) => { const t = (i.titulo || "").trim().toLowerCase(); if (!t || vistos.has(t)) return false; vistos.add(t); return true; });
      if (!frescas.length) { toast("Nenhuma ideia nova veio — tente aumentar a quantidade"); return; }
      ideiasAtuais = ideiasAtuais.concat(frescas);
      renderIdeias();
      toast(`+${frescas.length} ideia(s)`);
    } else {
      ideiasAtuais = novas;
      renderIdeias();
    }
  } catch (e) {
    if (adicionar) toast("Erro de conexão"); else body.innerHTML = `<div class="painel-ia-estado">Erro de conexão ao gerar ideias.</div>`;
  } finally {
    if (btnMais) { btnMais.disabled = false; btnMais.textContent = "Gerar mais"; }
  }
}

let ideiasAtuais = [];   // ideias na tela; a seleção mora em cada objeto (i._sel)

function renderIdeias() {
  const body = el("ideiasBody");
  if (!Array.isArray(ideiasAtuais)) ideiasAtuais = [];
  atualizarSelecaoIdeias();
  if (!ideiasAtuais.length) { body.innerHTML = `<div class="painel-ia-estado">Não veio nenhuma ideia. Tente "Gerar mais".</div>`; return; }
  const grupos = [
    { chave: "padrao", titulo: "Mantendo o padrão" },
    { chave: "disruptivo", titulo: "Disruptivas" },
  ];
  body.innerHTML = grupos.map((g) => {
    const doGrupo = ideiasAtuais
      .map((i, idx) => ({ i, idx }))
      .filter(({ i }) => (i.caminho || "").toLowerCase().startsWith(g.chave.slice(0, 6)));
    if (!doGrupo.length) return "";
    return `
      <div class="ideia-grupo">
        <div class="ideia-grupo-head">
          <span class="ideia-badge ${g.chave}">${g.chave === "padrao" ? "Padrão" : "Disruptivo"}</span>
          <h4>${escapeHtml(g.titulo)} <span class="ideia-cont">${doGrupo.length}</span></h4>
        </div>
        <div class="ideia-grade">
          ${doGrupo.map(({ i, idx }) => cardIdeia(i, idx)).join("")}
        </div>
      </div>`;
  }).join("") || `<div class="painel-ia-estado">Não consegui separar as ideias nos dois caminhos.</div>`;
  // Seleção por checkbox: clicar no card também marca (menos nos textos/details).
  body.querySelectorAll(".ideia-card").forEach((card) => {
    const chk = card.querySelector(".chk-ideia");
    if (!chk) return;
    chk.addEventListener("change", () => {
      const it = ideiasAtuais[Number(chk.dataset.idx)];
      if (it) it._sel = chk.checked;
      card.classList.toggle("sel", chk.checked);
      atualizarSelecaoIdeias();
    });
    card.addEventListener("click", (e) => {
      if (e.target.closest("label, input, a, button, details")) return;
      chk.checked = !chk.checked;
      chk.dispatchEvent(new Event("change"));
    });
  });
}

function cardIdeia(i, idx) {
  const c = i.copy || {};
  const detalhes = [
    c.apoio ? `<div class="ideia-secao">${escapeHtml(c.apoio)}</div>` : "",
    i.conceito_imagem ? `<div class="ideia-secao"><b>Imagem:</b> ${escapeHtml(i.conceito_imagem)}</div>` : "",
    i.porque ? `<div class="ideia-secao"><b>Por quê:</b> ${escapeHtml(i.porque)}</div>` : "",
  ].join("");
  return `
    <div class="ideia-card${i._sel ? " sel" : ""}">
      <label class="ideia-pick">
        <input type="checkbox" class="chk-ideia" data-idx="${idx}"${i._sel ? " checked" : ""}>
        <span>${escapeHtml(i.titulo || "Ideia")}</span>
      </label>
      ${(c.headline || c.cta) ? `
      <div class="ideia-copy">
        ${c.headline ? `<span class="hl">${escapeHtml(c.headline)}</span>` : ""}
        ${c.cta ? `<span class="cta">${escapeHtml(c.cta)}</span>` : ""}
      </div>` : ""}
      ${detalhes ? `<details class="ideia-mais"><summary>detalhes</summary>${detalhes}</details>` : ""}
    </div>`;
}

function ideiasSelecionadas() {
  return ideiasAtuais.filter((i) => i && i._sel);
}

function atualizarSelecaoIdeias() {
  const total = ideiasAtuais.length;
  const n = ideiasAtuais.filter((i) => i && i._sel).length;
  const btn = el("btnIdeiasGerar");
  if (btn) {
    btn.textContent = `Gerar selecionadas (${n})`;
    btn.disabled = n === 0;
  }
  const btnTodos = el("btnIdeiasTodos");
  if (btnTodos) {
    btnTodos.disabled = total === 0;
    btnTodos.textContent = (total && n === total) ? "Limpar seleção" : "Selecionar todos";
  }
}

function alternarTodasIdeias() {
  if (!ideiasAtuais.length) return;
  const marcar = ideiasAtuais.some((i) => !i._sel); // falta algum → marca todos; senão limpa
  ideiasAtuais.forEach((i) => { i._sel = marcar; });
  renderIdeias();
}

// Vira as ideias marcadas em prompts e dispara a geração em lote (paralelizada).
async function gerarIdeiasSelecionadas() {
  if (!produto) return;
  const sel = ideiasSelecionadas();
  if (!sel.length) { toast("Marque ao menos uma ideia"); return; }
  const btn = el("btnIdeiasGerar");
  btn.disabled = true;
  btn.textContent = `Gerando ${sel.length}…`;
  try {
    const r = await (await fetch(`/api/gerar_ideias/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ideias: sel }),
    })).json();
    if (!r.ok) { toast(r.erro || "erro"); btn.disabled = false; atualizarSelecaoIdeias(); return; }
    fecharModalIdeias();
    pararTudoSolicitado = false;
    atualizarFaseCriativos("Geração iniciada. Acompanhe o progresso abaixo.", true);
    trocarStep("criativos", true);
    carregarHistorico();
    el("btnParar").style.display = "";
    iniciarPolling(true);
    toast(`Gerando ${sel.length} criativo(s)…`);
  } catch (e) {
    toast("Erro de conexão");
    btn.disabled = false;
    atualizarSelecaoIdeias();
  }
}

el("btnSugerirIdeias")?.addEventListener("click", () => {
  if (!produto) { toast("Abra um produto primeiro"); return; }
  abrirModalIdeias();
  carregarIdeias();
});
el("btnIdeiasTodos")?.addEventListener("click", alternarTodasIdeias);
el("btnIdeiasFechar")?.addEventListener("click", fecharModalIdeias);
el("btnIdeiasRefazer")?.addEventListener("click", () => carregarIdeias(true));
el("btnIdeiasGerar")?.addEventListener("click", gerarIdeiasSelecionadas);
el("modalIdeias")?.addEventListener("click", (e) => { if (e.target === el("modalIdeias")) fecharModalIdeias(); });

// ------------------------------------------------- Verificação (QA) --------
let qaDiagnostico = [];   // último diagnóstico renderizado

function abrirModalQA() { el("modalQA").style.display = "flex"; }
function fecharModalQA() { el("modalQA").style.display = "none"; }

async function carregarQA() {
  const body = el("qaBody");
  el("btnQACorrigir").style.display = "none";
  el("btnQAReverificar").style.display = "none";
  body.innerHTML = `<div class="painel-ia-estado"><span class="spin"></span> Inspecionando cada imagem (texto, dedos, embalagem)… isso leva alguns instantes.</div>`;
  try {
    const r = await (await fetch(`/api/diagnosticar_criativos/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo(), arquivos: arqsNaTela() }),
    })).json();
    if (!r.ok) { body.innerHTML = `<div class="painel-ia-estado">${escapeHtml(r.erro || "erro")}</div>`; return; }
    qaDiagnostico = r.diagnostico || [];
    renderQA();
  } catch (e) {
    body.innerHTML = `<div class="painel-ia-estado">Erro de conexão ao verificar as imagens.</div>`;
  }
}

function sevClasse(d) {
  const s = (d.severidade || "").toLowerCase();
  if (d.ok === true || s === "ok") return "ok";
  if (s === "grave") return "grave";
  return "leve";
}

function renderQA() {
  const body = el("qaBody");
  if (!qaDiagnostico.length) { body.innerHTML = `<div class="painel-ia-estado">Nada para mostrar.</div>`; return; }
  const problemas = qaDiagnostico.filter((d) => sevClasse(d) !== "ok");
  const resumo = problemas.length
    ? `Encontrei possíveis problemas em <b>${problemas.length}</b> de ${qaDiagnostico.length} imagem(ns). Marque as que quer corrigir e clique em "Corrigir problemas".`
    : `Tudo certo ✓ Nenhum erro evidente nas ${qaDiagnostico.length} imagem(ns) verificada(s).`;
  const cards = qaDiagnostico.map((d, idx) => {
    const cls = sevClasse(d);
    const arq = d.arquivo;
    const src = `/criativos/${produto}/${encodeURIComponent(arq)}?t=${Date.now()}`;
    const probs = Array.isArray(d.problemas) ? d.problemas.filter(Boolean) : [];
    const podeCorrigir = cls !== "ok" && (d.instrucao_correcao || "").trim();
    return `
      <div class="qa-card ${cls}">
        <img src="${src}" alt="${escapeHtml(arq)}" loading="lazy">
        <div class="qa-info">
          <span class="qa-arq">${escapeHtml(arq)}</span>
          <span class="qa-sev ${cls}">${cls === "ok" ? "✓ Sem erros" : (cls === "grave" ? "⚠ Problema grave" : "⚠ Problema leve")}</span>
          ${probs.length ? `<ul class="qa-probs">${probs.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>` : ""}
          ${podeCorrigir ? `<div class="qa-fix"><b>Correção:</b> ${escapeHtml(d.instrucao_correcao)}</div>` : ""}
        </div>
        <label class="qa-check">
          <input type="checkbox" data-qa-idx="${idx}" ${podeCorrigir ? "checked" : ""} ${podeCorrigir ? "" : "disabled"}>
          corrigir
        </label>
      </div>`;
  }).join("");
  body.innerHTML = `<div class="qa-resumo">${resumo}</div><div class="qa-lista">${cards}</div>`;
  el("btnQAReverificar").style.display = "";
  el("btnQACorrigir").style.display = problemas.length ? "" : "none";
  el("btnQACorrigir").disabled = false;
  el("btnQACorrigir").textContent = "Corrigir problemas";
}

// Espera a geração/refino atual terminar (observa o /api/status do produto).
// onProgresso(feitos, total) é chamado a cada leitura, pra alimentar um loading.
async function aguardarRefinoTerminar(timeoutMs = 15 * 60 * 1000, onProgresso) {
  const inicio = Date.now();
  let viuAndando = false;
  while (Date.now() - inicio < timeoutMs) {
    await dormir(1600);
    let s;
    try { s = await (await fetch(`/api/status/${produto}`)).json(); } catch (e) { continue; }
    if (onProgresso) onProgresso(s.feitos || 0, s.total || 0, s);
    if (s.em_andamento) { viuAndando = true; continue; }
    if (viuAndando) return true;                     // rodou e terminou
    if (Date.now() - inicio > 25000) return true;    // nunca começou em 25s: para de esperar
  }
  return true;
}

async function corrigirQA() {
  if (geracaoEmAndamento || refinoEmVoo) { toast("Aguarde a geração atual terminar"); return; }
  const marcados = [...el("qaBody").querySelectorAll("input[data-qa-idx]:checked")]
    .map((c) => qaDiagnostico[Number(c.dataset.qaIdx)])
    .filter((d) => d && (d.instrucao_correcao || "").trim());
  if (!marcados.length) { toast("Marque ao menos uma imagem para corrigir"); return; }

  const total = marcados.length;
  const btn = el("btnQACorrigir");
  btn.disabled = true;
  btn.textContent = `Corrigindo ${total}…`;
  // Fotografa os arquivos ANTES da correção: as versões corrigidas nascem com nome
  // novo (criativo_NN_refinadoK.png), então o que aparecer a mais depois é o corrigido.
  const antes = new Set(arqsNaTela());
  // As correções rodam em LOTE (até 6 em paralelo, config `workers`), não 1 a 1.
  const linhaProgresso = (feitos) =>
    `<span class="spin"></span> Corrigindo em lote — ${Math.min(feitos, total)} de ${total} pronta(s)…`;
  el("qaBody").insertAdjacentHTML("afterbegin",
    `<div class="painel-ia-estado" id="qaCorrigindo">${linhaProgresso(0)}</div>`);

  // Enfileira os refinos com a instrução cirúrgica de cada um e roda o lote (até 6 em paralelo).
  marcados.forEach((d) => enfileirarRefino(d.arquivo, d.instrucao_correcao));
  filaRefinoArmada = true;
  processarFilaRefino();

  await aguardarRefinoTerminar(15 * 60 * 1000, (feitos, tot) => {
    const box = el("qaCorrigindo");
    if (box) box.innerHTML = linhaProgresso(feitos);
    btn.textContent = `Corrigindo ${Math.min(feitos, total)}/${total}…`;
  });
  const box = el("qaCorrigindo");
  if (box) box.innerHTML = `<span class="spin"></span> Re-verificando só as imagens corrigidas…`;

  // Descobre os arquivos NOVOS (as versões corrigidas) e casa cada um com o original
  // que foi mandado corrigir, pelo id base (criativo_NN).
  let s;
  try { s = await (await fetch(`/api/status/${produto}`)).json(); } catch (e) { s = {}; }
  const todos = (s && s.arquivos) || arqsNaTela();
  const novos = todos.filter((a) => !antes.has(a));
  const corrigidos = [];  // { original, novo }
  marcados.forEach((d) => {
    const base = idBaseArq(d.arquivo);
    const cands = novos.filter((a) => idBaseArq(a) === base).sort();
    if (cands.length) corrigidos.push({ original: d.arquivo, novo: cands[cands.length - 1] });
  });

  // Nenhuma versão nova saiu (falha na correção): mostra a verificação geral e sai.
  if (!corrigidos.length) {
    if (box) box.remove();
    toast("Nenhuma versão corrigida foi gerada");
    await carregarQA();
    return;
  }

  // Roda o MESMO QA só nos arquivos corrigidos (o endpoint aceita lista de arquivos).
  let diag = [];
  try {
    const r = await (await fetch(`/api/diagnosticar_criativos/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo(), arquivos: corrigidos.map((c) => c.novo) }),
    })).json();
    if (r.ok) diag = r.diagnostico || [];
  } catch (e) { /* sem diagnóstico: trata tudo como incerto (não oferece descarte) */ }
  const porArq = {};
  diag.forEach((d) => { porArq[d.arquivo] = d; });

  // Classifica: correção CONFIRMADA (re-QA sem erro) x AINDA com erro.
  const confirmadas = [];  // { original, novo }
  const aindaErro = [];    // { original, novo, diag }
  corrigidos.forEach((c) => {
    const d = porArq[c.novo];
    if (d && sevClasse(d) === "ok") confirmadas.push(c);
    else aindaErro.push({ ...c, diag: d });
  });

  if (box) box.remove();
  renderResultadoCorrecao(confirmadas, aindaErro);
}

// Painel pós-correção: confirma o que a re-verificação aprovou, mantém sinalizado o
// que ainda tem erro e OFERECE descartar as versões antigas erradas (com confirmação).
function renderResultadoCorrecao(confirmadas, aindaErro) {
  const body = el("qaBody");
  el("btnQACorrigir").style.display = "none";
  el("btnQAReverificar").style.display = "";

  const partes = [];
  if (confirmadas.length)
    partes.push(`✓ Correção confirmada em <b>${confirmadas.length}</b> imagem(ns).`);
  if (aindaErro.length)
    partes.push(`⚠ <b>${aindaErro.length}</b> imagem(ns) ainda com erro após a correção — mantidas sinalizadas.`);
  const resumo = partes.join(" ") || "Sem imagens corrigidas.";

  const cardConfirmada = (c) => `
    <div class="qa-card ok">
      <img src="/criativos/${produto}/${encodeURIComponent(c.novo)}?t=${Date.now()}" alt="${escapeHtml(c.novo)}" loading="lazy">
      <div class="qa-info">
        <span class="qa-arq">${escapeHtml(c.novo)}</span>
        <span class="qa-sev ok">✓ Correção confirmada</span>
        <div class="qa-fix">Versão antiga a descartar: <b>${escapeHtml(c.original)}</b></div>
      </div>
    </div>`;
  const cardErro = (c) => {
    const probs = (c.diag && Array.isArray(c.diag.problemas)) ? c.diag.problemas.filter(Boolean) : [];
    return `
    <div class="qa-card grave">
      <img src="/criativos/${produto}/${encodeURIComponent(c.novo)}?t=${Date.now()}" alt="${escapeHtml(c.novo)}" loading="lazy">
      <div class="qa-info">
        <span class="qa-arq">${escapeHtml(c.novo)}</span>
        <span class="qa-sev grave">⚠ Ainda com erro</span>
        ${probs.length ? `<ul class="qa-probs">${probs.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>` : ""}
      </div>
    </div>`;
  };

  const cards = confirmadas.map(cardConfirmada).join("") + aindaErro.map(cardErro).join("");
  const acao = confirmadas.length
    ? `<div class="qa-pos-acoes"><button class="btn primary btn-mini" id="btnQADescartarAntigas">Descartar ${confirmadas.length} versão(ões) antiga(s)</button></div>`
    : "";
  body.innerHTML = `<div class="qa-resumo">${resumo}</div>${acao}<div class="qa-lista">${cards}</div>`;

  const btnDesc = el("btnQADescartarAntigas");
  if (btnDesc) btnDesc.addEventListener("click", async () => {
    const antigos = confirmadas.map((c) => c.original);
    if (!confirm(`Descartar ${antigos.length} versão(ões) antiga(s) errada(s)? Elas vão para a pasta descartados/ (não são apagadas).`)) return;
    btnDesc.disabled = true;
    btnDesc.textContent = "Descartando…";
    let ok = 0;
    for (const arq of antigos) { if (await descartarSilencioso(arq)) ok++; }
    toast(`${ok} versão(ões) antiga(s) descartada(s) ✓`);
    await carregarQA();
  });
}

el("btnVerificarImagens")?.addEventListener("click", () => {
  if (!produto) { toast("Abra um produto primeiro"); return; }
  if (!arqsNaTela().length) { toast("Nenhuma imagem na tela para verificar"); return; }
  abrirModalQA();
  carregarQA();
});
el("btnQAFechar")?.addEventListener("click", fecharModalQA);
el("btnQAReverificar")?.addEventListener("click", carregarQA);
el("btnQACorrigir")?.addEventListener("click", corrigirQA);
el("modalQA")?.addEventListener("click", (e) => { if (e.target === el("modalQA")) fecharModalQA(); });

// Esc fecha os painéis de IA (quando abertos e o lightbox não está no topo).
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (el("modalIdeias")?.style.display === "flex") { fecharModalIdeias(); return; }
  if (el("modalQA")?.style.display === "flex") fecharModalQA();
});

// ------------------------------------------------------------ Formatos -----
// Popup do chat: escolhe os formatos do lote (padrao/wikihow/noticia). O 1º da
// lista (ordem do catálogo entre os marcados) é o formato ATIVO, que decide qual
// cérebro de copy/arte o backend usa. Multi-seleção fica salva no produto.
let formatosCatalogo = [
  { id: "padrao", label: "Padrão", desc: "Criativo publicitário com o produto como herói (o modo de sempre)." },
  { id: "wikihow", label: "WikiHow", desc: "Ilustração native de mecanismo (estilo artigo de saúde), copy de conteúdo." },
  { id: "noticia", label: "Notícia", desc: "Print de matéria de portal (tarja, manchete, assinatura), copy editorial." },
];
let formatosAtivos = ["padrao"];
let fmtSel = new Set();

const fmtLabel = (id) => (formatosCatalogo.find((x) => x.id === id) || {}).label || id;
const fmtOrdenados = () => formatosCatalogo.map((c) => c.id).filter((id) => fmtSel.has(id));

function atualizarFormatosBtn() {
  const ativo = formatosAtivos[0] || "padrao";
  const extra = formatosAtivos.length > 1 ? ` +${formatosAtivos.length - 1}` : "";
  el("formatosBtnLbl").textContent = fmtLabel(ativo) + extra;
}

async function carregarFormatos() {
  if (!produto) { formatosAtivos = ["padrao"]; atualizarFormatosBtn(); return; }
  try {
    const d = await (await fetch(`/api/formatos/${produto}`)).json();
    if (d.catalogo && d.catalogo.length) formatosCatalogo = d.catalogo;
    formatosAtivos = (d.formatos && d.formatos.length) ? d.formatos : ["padrao"];
  } catch (e) { formatosAtivos = ["padrao"]; }
  atualizarFormatosBtn();
}

function renderFmt() {
  const ativo = fmtOrdenados()[0];
  el("formatosLista").innerHTML = formatosCatalogo.map((c) => {
    const marcado = fmtSel.has(c.id);
    const ehAtivo = marcado && c.id === ativo;
    return `<label class="fmt-opt${marcado ? " sel" : ""}" data-id="${c.id}">
      <input type="checkbox" ${marcado ? "checked" : ""}>
      <span class="fmt-txt">
        <span class="fmt-nome">${c.label}${ehAtivo ? '<span class="fmt-ativo">ativo</span>' : ""}</span>
        <span class="fmt-desc">${c.desc || ""}</span>
      </span></label>`;
  }).join("");
}

function abrirFormatos() {
  if (!produto) { toast("Selecione um produto primeiro"); return; }
  fmtSel = new Set(formatosAtivos);
  renderFmt();
  el("formatosOverlay").hidden = false;
}
const fecharFormatos = () => { el("formatosOverlay").hidden = true; };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el("formatosOverlay") && !el("formatosOverlay").hidden) fecharFormatos();
});

el("btnFormatos").addEventListener("click", abrirFormatos);
el("formatosFechar").addEventListener("click", fecharFormatos);
el("formatosCancelar").addEventListener("click", fecharFormatos);
el("formatosOverlay").addEventListener("click", (e) => {
  if (e.target === el("formatosOverlay")) fecharFormatos();
});
el("formatosLista").addEventListener("change", (e) => {
  const lab = e.target.closest(".fmt-opt");
  if (!lab) return;
  if (e.target.checked) fmtSel.add(lab.dataset.id); else fmtSel.delete(lab.dataset.id);
  renderFmt();
});
el("formatosSalvar").addEventListener("click", async () => {
  let ord = fmtOrdenados();
  if (!ord.length) ord = ["padrao"];
  try {
    const r = await (await fetch(`/api/formatos/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formatos: ord }),
    })).json();
    formatosAtivos = (r.formatos && r.formatos.length) ? r.formatos : ord;
  } catch (e) { formatosAtivos = ord; }
  atualizarFormatosBtn();
  fecharFormatos();
  toast("Formato ativo: " + fmtLabel(formatosAtivos[0]));
});

// Início
carregarModelos();
carregarProdutos();
