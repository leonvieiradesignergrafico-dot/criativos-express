/* UGC Express — front (vanilla JS + polling de status a 1,5s) */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  produto: null,
  vid: null,
  modo: null,
  avatar: "",
  tipoProduto: null,
  copiesSelecionadas: [],
  cfg: {},
  poll: null,
  ultimo: null, // último payload de /api/status
};

/* ---------------------------------------------------------------- helpers */
const B = "/ugc"; // o fluxo de vídeo vive sob este prefixo no servidor compartilhado
async function api(url, body, metodo) {
  const opts = { method: metodo || (body ? "POST" : "GET"), headers: {} };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(B + url, opts);
  const dado = await r.json().catch(() => ({}));
  if (!r.ok || dado.ok === false) throw new Error(dado.erro || `Erro ${r.status}`);
  return dado;
}
function esc(t) {
  const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML;
}
function aviso(el, msg, erro) {
  el.textContent = msg; el.classList.remove("hidden"); el.classList.toggle("erro", !!erro);
}
/* toast não-bloqueante + confirmação em modal (substituem alert/confirm/prompt nativos) */
function toast(msg, erro) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (erro ? " erro" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = "toast"; }, erro ? 4200 : 2600);
}
function confirmar(msg, okLabel) {
  return new Promise(res => {
    const m = $("modalConfirm");
    $("mcMsg").textContent = msg;
    $("mcOk").textContent = okLabel || "Confirmar";
    m.classList.remove("hidden");
    const fim = (v) => { m.classList.add("hidden"); $("mcOk").onclick = $("mcCancel").onclick = null; res(v); };
    $("mcOk").onclick = () => fim(true);
    $("mcCancel").onclick = () => fim(false);
  });
}
/* rótulos amigáveis dos tipos de cena (o valor enviado continua sendo o slug) */
const LABELS_TIPO = {
  close_produto: "Close no produto", avatar_usa: "Pessoa usando",
  avatar_mostra: "Pessoa mostrando", avatar_fala: "Pessoa falando", unboxing: "Unboxing",
  tela_dispositivo: "Tela do dispositivo", avatar_aponta_tela: "Pessoa apontando a tela",
  mockup_resultado: "Resultado na tela",
};
const rotuloTipo = (t) => LABELS_TIPO[t] || t;
/* marca as etapas já concluídas no stepper, conforme o estado do vídeo */
function marcarSteps(estado) {
  const feitos = {
    roteiro_aprovado: ["roteiro"],
    keyframes_aprovados: ["roteiro", "keyframes"],
    clipes_gerados: ["roteiro", "keyframes", "clipes"],
    montado: ["roteiro", "keyframes", "clipes", "final"],
  }[estado] || [];
  document.querySelectorAll("#steps button").forEach(b =>
    b.classList.toggle("feito", feitos.includes(b.dataset.step)));
}

/* ---------------------------------------------------------------- views */
const VIEWS = ["copy", "novo", "roteiro", "keyframes", "clipes", "final", "avatares"];
function mostrar(view) {
  VIEWS.forEach(v => $("view-" + v).classList.toggle("hidden", v !== view));
  $("steps").classList.toggle("hidden", view === "avatares");
  document.querySelectorAll("#steps button").forEach(b =>
    b.classList.toggle("ativo", b.dataset.step === (view === "novo" ? "roteiro" : view)));
}
document.querySelectorAll("#steps button").forEach(b =>
  b.addEventListener("click", () => mostrar(b.dataset.step)));

/* ---------------------------------------------------------------- boot */
async function boot() {
  state.cfg = (await api("/api/config"));
  const tipoCtl = document.querySelector(".tipo-produto");
  const modosCtl = document.querySelector(".copy-modes");
  if (tipoCtl && modosCtl) modosCtl.appendChild(tipoCtl);
  $("btnRemontar").textContent = "Editar cortes";
  document.querySelectorAll(".copy-mode").forEach(b => b.classList.remove("ativo"));
  // Usa a mesma fonte da sidebar dos criativos estáticos, incluindo produtos
  // agrupados por cliente (cliente~produto) e suas miniaturas.
  const prods = await (await fetch("/api/produtos")).json();
  $("selProduto").innerHTML = prods.length ? prods.map(p => `<option value="${esc(p.nome)}">${esc(p.nome)}</option>`).join("") : `<option value="">Nenhum produto cadastrado</option>`;
  $("selProduto").disabled = !prods.length;
  renderProdutos(prods);
  state.produto = prods[0] ? prods[0].nome : null;
  if (state.produto) selecionarProdutoSidebar(state.produto, prods[0].label || state.produto, false);
  if ($("selMotor")) $("selMotor").value = state.cfg.motor || "api";
  await carregarVozes();
  await carregarAvatares();
  await carregarVideos();
  mostrar("copy");
}
$("selProduto").addEventListener("change", async () => {
  state.produto = $("selProduto").value; state.vid = null;
  document.querySelectorAll("#produtos .produto-item").forEach(li => li.classList.toggle("ativo", li.dataset.nome === state.produto));
  await carregarTipoProduto(); await carregarVideos(); mostrar("copy");
});

function renderProdutos(prods) {
  const ul = $("produtos");
  if (!prods.length) {
    ul.innerHTML = '<li class="produto-vazio">Nenhum produto cadastrado</li>';
    return;
  }
  const grupos = new Map();
  prods.forEach(p => {
    const cliente = p.cliente || "Sem cliente";
    if (!grupos.has(cliente)) grupos.set(cliente, []);
    grupos.get(cliente).push(p);
  });
  [...grupos.keys()].sort((a, b) => a === "Sem cliente" ? 1 : b === "Sem cliente" ? -1 : a.localeCompare(b, "pt")).forEach(cliente => {
    const grupo = document.createElement("li");
    grupo.className = "cli-grupo";
    const head = document.createElement("button");
    head.type = "button";
    head.className = "cli-head";
    head.innerHTML = `<span class="cli-caret">▾</span><span class="cli-nome">${esc(cliente)}</span><span class="cli-count">${grupos.get(cliente).length}</span>`;
    const lista = document.createElement("ul");
    lista.className = "cli-lista";
    head.addEventListener("click", () => grupo.classList.toggle("colapsado"));
    grupos.get(cliente).forEach(p => {
      const item = document.createElement("li");
      item.className = "produto-item";
      item.dataset.nome = p.nome;
      const label = p.label || p.nome;
      const inicial = label.trim().charAt(0) || "?";
      item.innerHTML = p.thumb
        ? `<span class="avatar img"><img src="/referencia/${encodeURIComponent(p.nome)}/${encodeURIComponent(p.thumb)}" alt=""></span><span class="pnome">${esc(label)}</span>`
        : `<span class="avatar">${esc(inicial)}</span><span class="pnome">${esc(label)}</span>`;
      item.addEventListener("click", () => selecionarProdutoSidebar(p.nome, label, true));
      lista.appendChild(item);
    });
    grupo.append(head, lista);
    ul.appendChild(grupo);
  });
}

async function selecionarProdutoSidebar(nome, label, trocarView) {
  state.produto = nome; state.vid = null;
  $("selProduto").value = nome;
  $("produtoAtual").textContent = label || nome;
  document.querySelectorAll("#produtos .produto-item").forEach(li => li.classList.toggle("ativo", li.dataset.nome === nome));
  await carregarTipoProduto(); await carregarVideos();
  if (trocarView) mostrar("copy");
}

async function carregarTipoProduto() {
  if (!state.produto) return;
  state.tipoProduto = null;
  document.querySelectorAll(".tipo-produto button").forEach(b => b.classList.remove("ativo"));
}
document.querySelectorAll(".tipo-produto button").forEach(btn => btn.addEventListener("click", async () => {
  if (!state.produto) return;
  try {
    const r = await api(`/api/tipo_produto/${encodeURIComponent(state.produto)}`, { tipo: btn.dataset.tipo });
    state.tipoProduto = r.tipo;
    document.querySelectorAll(".tipo-produto button").forEach(b => b.classList.toggle("ativo", b === btn));
    toast(`Produto marcado como ${r.tipo === "digital" ? "digital" : "físico"}.`);
  } catch (e) { toast(e.message, true); }
}));

async function carregarVideos() {
  if (!state.produto) {
    $("selVideo").innerHTML = `<option value="">Nenhum vídeo disponível</option>`;
    $("selVideo").disabled = true;
    return;
  }
  const vids = (await api(`/api/videos/${encodeURIComponent(state.produto)}`)).videos;
  $("selVideo").innerHTML = `<option value="">— vídeos —</option>` +
    vids.map(v => `<option value="${esc(v.id)}">${esc(v.id)} (${esc(v.estado)})</option>`).join("");
}
$("selVideo").addEventListener("change", () => {
  const v = $("selVideo").value;
  if (v) abrirVideo(v);
});
$("btnNovoVideo").addEventListener("click", () => {
  pararPoll(); state.vid = null; state.modo = null; state.tipoProduto = null;
  document.querySelectorAll(".copy-mode, .tipo-produto button").forEach(b => b.classList.remove("ativo"));
  mostrar("copy");
});
$("btnAvatares").addEventListener("click", async () => { await carregarAvatares(); mostrar("avatares"); });

/* ---------------------------------------------------------------- novo vídeo */
let copySession = null;
function renderCopyOpcoes(opcoes) {
  const wrap = document.createElement("div");
  wrap.className = "msg assistente roteiro-opcoes";
  wrap.innerHTML = `<div class="roteiro-opcoes-head"><strong>Roteiros sugeridos (${(opcoes || []).length})</strong><span class="mini-label">selecione um ou mais</span></div>` +
    `<div class="roteiro-opcoes-grid">${(opcoes || []).map((o, i) => `<label class="roteiro-opcao"><input type="checkbox" data-opcao="${i}"><span class="roteiro-opcao-body"><strong>${esc(o.titulo || `Opção ${i + 1}`)}</strong><small>${esc(o.persona || "persona definida pelo roteirista")} · ${esc(o.duracao_s || 30)}s</small><em>Por que assistir: ${esc(o.promessa_editorial || o.gancho || "")}</em><em>Entrega: ${esc(o.payoff || "")}</em><span>${esc(o.roteiro || "")}</span></span></label>`).join("")}</div>` +
    `<div class="roteiro-opcoes-actions"><span class="mini-label sel-opcoes">0 selecionados</span><button type="button" class="btn primary btn-usar-opcoes" disabled>Escolher e ir para roteiro</button></div>`;
  const atualizar = () => {
    state.copiesSelecionadas = [...wrap.querySelectorAll("input:checked")].map(x => opcoes[Number(x.dataset.opcao)]);
    wrap.querySelector(".sel-opcoes").textContent = `${state.copiesSelecionadas.length} selecionado(s)`;
    wrap.querySelector(".btn-usar-opcoes").disabled = !state.copiesSelecionadas.length;
    wrap.querySelectorAll(".roteiro-opcao").forEach((card, i) => card.classList.toggle("selecionado", !!wrap.querySelector(`input[data-opcao="${i}"]:checked`)));
  };
  wrap.querySelectorAll("input").forEach(x => x.addEventListener("change", atualizar));
  wrap.querySelector(".btn-usar-opcoes").addEventListener("click", () => { renderRoteirosEscolhidos(); mostrar("novo"); });
  $("copyChatLog").appendChild(wrap);
  $("copyChatLog").scrollTop = $("copyChatLog").scrollHeight;
}
async function enviarCopyChat() {
  const mensagem = $("txtCopyChat").value.trim();
  if (!state.modo) return toast("Marque UGC ou Nativo antes de pedir os roteiros.", true);
  if (!mensagem) return toast("Descreva o que você quer criar.", true);
  $("copyChatEmpty")?.remove();
  const btn = $("btnCopyChat"), htmlBtn = btn.innerHTML; btn.disabled = true;
  $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg usuario">${esc(mensagem)}</div>`);
  $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg assistente pensando copy-pensando"><span class="spinner" style="position:static"></span><span>Roteirista pensando…</span></div>`);
  $("copyChatLog").scrollTop = $("copyChatLog").scrollHeight;
  try {
    const r = await api(`/api/copy_chat/${encodeURIComponent(state.produto)}`, { mensagem, modo: state.modo, modelo: "sonnet", session_id: copySession });
    copySession = r.session_id || copySession;
    $("copyChatLog").querySelector(".copy-pensando")?.remove();
    $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg assistente">${esc(r.resposta || "Gerei opções ao lado.")}</div>`);
    renderCopyOpcoes(r.opcoes); $("txtCopyChat").value = "";
  } catch (e) { $("copyChatLog").querySelector(".copy-pensando")?.remove(); toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = htmlBtn; }
}
document.querySelectorAll(".copy-mode").forEach(btn => btn.addEventListener("click", () => {
  state.modo = btn.dataset.modo;
  document.querySelectorAll(".copy-mode").forEach(b => b.classList.toggle("ativo", b === btn));
}));
$("btnCopyChat").addEventListener("click", enviarCopyChat);
$("txtCopyChat").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarCopyChat(); } });
$("txtCopyChat").addEventListener("input", e => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

$("btnCriarRoteiro").addEventListener("click", async () => {
  const opcoes = state.copiesSelecionadas || [];
  if (!opcoes.length) return aviso($("novoStatus"), "Selecione ao menos um roteiro no chat.", true);
  if (!state.modo) return aviso($("novoStatus"), "Marque UGC ou Nativo antes de criar o roteiro.", true);
  if (!state.tipoProduto) return aviso($("novoStatus"), "Marque Fisico ou Digital antes de criar o roteiro.", true);
  $("btnCriarRoteiro").disabled = true;
  const inicio = Date.now();
  aviso($("novoStatus"), "Roteirista trabalhando… a resposta pode levar alguns minutos.");
  try {
    let primeiro = null;
    for (const opcao of opcoes) {
      const r = await api(`/api/videos/${encodeURIComponent(state.produto)}`, {
        copy: copyComBrief(opcao), avatar: state.avatar || null, modelo: "sonnet", formato_video: state.modo,
        tipo_produto: state.tipoProduto,
      });
      primeiro = primeiro || r.roteiro;
    }
    await carregarVideos();
    aviso($("novoStatus"), `Roteiro pronto em ${Math.round((Date.now() - inicio) / 1000)}s.`);
    abrirVideo(primeiro.id);
  } catch (e) { aviso($("novoStatus"), e.message, true); }
  finally { $("btnCriarRoteiro").disabled = false; }
});

function renderRoteirosEscolhidos() {
  $("roteirosEscolhidos").innerHTML = state.copiesSelecionadas.map((o, i) => `<article class="roteiro-escolhido-item"><span>${i + 1}</span><div><strong>${esc(o.titulo || `Roteiro ${i + 1}`)}</strong><p>${esc(o.roteiro || "")}</p></div></article>`).join("");
}

function copyComBrief(opcao) {
  const ativos = (opcao.ativos_necessarios || []).join(", ") || "nenhum ativo adicional";
  return `BRIEF EDITORIAL E DE PRODUCAO:\n` +
    `Promessa editorial: ${opcao.promessa_editorial || opcao.gancho || ""}\n` +
    `Payoff obrigatorio: ${opcao.payoff || "entregar a promessa do gancho antes da oferta"}\n` +
    `Viabilidade: ${opcao.viabilidade || "executavel"}\n` +
    `Ativos necessarios: ${ativos}\n` +
    `Riscos/limitacoes: ${opcao.observacao || ""}\n\nROTEIRO APROVADO:\n${opcao.roteiro || ""}`;
}

/* ---------------------------------------------------------------- abrir vídeo + poll */
function pararPoll() { if (state.poll) { clearInterval(state.poll); state.poll = null; } }

async function abrirVideo(vid) {
  state.vid = vid;
  $("selVideo").value = vid;
  pararPoll();
  await atualizar();
  const est = state.ultimo ? state.ultimo.estado : "rascunho";
  mostrar(est === "montado" ? "final" :
          est === "clipes_gerados" ? "clipes" :
          est === "roteiro_aprovado" || est === "keyframes_aprovados" ? "keyframes" : "roteiro");
  state.poll = setInterval(atualizar, 1500);
}

async function atualizar() {
  if (!state.vid) return;
  let dado;
  try {
    dado = await api(`/api/status/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`);
  } catch (e) { return; }
  state.ultimo = dado;
  marcarSteps(dado.estado);
  renderRoteiro(dado);
  renderKeyframes(dado);
  renderClipes(dado);
  renderFinal(dado);
}

/* ---------------------------------------------------------------- roteiro */
function renderRoteiro(dado) {
  const cont = $("tabelaCenas");
  const foco = document.activeElement;
  if (cont.contains(foco) && (foco.tagName === "TEXTAREA" || foco.tagName === "SELECT")) return; // não clobbera edição
  cont.innerHTML = (dado.cenas || []).map(c => `
    <div class="cena-row" data-n="${c.n}">
      <div class="cab"><span class="num">Cena ${c.n}</span>
        <select class="f-tipo">
          ${(dado.tipo_produto === "digital"
            ? ["avatar_fala","tela_dispositivo","avatar_aponta_tela","mockup_resultado"]
            : ["close_produto","avatar_usa","avatar_mostra","avatar_fala","unboxing"]).map(t =>
            `<option value="${t}" ${t === c.tipo ? "selected" : ""}>${rotuloTipo(t)}</option>`).join("")}
        </select>
        <span class="badge ${c.tipo === "avatar_fala" ? "fala" : ""}">${c.tipo === "avatar_fala" ? "fala em cena" : "narração em off"}</span>
      </div>
      <span class="mini-label">Narração (${(c.narracao || "").split(/\s+/).filter(Boolean).length} palavras)</span>
      <textarea class="f-narracao" rows="1">${esc(c.narracao)}</textarea>
      <span class="mini-label">Prompt do keyframe</span>
      <textarea class="f-kf" rows="3">${esc(c.prompt_keyframe)}</textarea>
      <span class="mini-label">Movimento (i2v)</span>
      <textarea class="f-mov" rows="1">${esc(c.prompt_movimento)}</textarea>
    </div>`).join("");
  const log = $("chatLog");
  log.innerHTML = (dado.chat || []).map(m =>
    `<div class="msg ${esc(m.papel)}">${esc(m.texto)}</div>`).join("");
  log.scrollTop = log.scrollHeight;
}

$("btnSalvarCenas").addEventListener("click", async () => {
  const cenas = [...document.querySelectorAll("#tabelaCenas .cena-row")].map(r => ({
    n: parseInt(r.dataset.n, 10),
    tipo: r.querySelector(".f-tipo").value,
    narracao: r.querySelector(".f-narracao").value,
    prompt_keyframe: r.querySelector(".f-kf").value,
    prompt_movimento: r.querySelector(".f-mov").value,
  }));
  try {
    await api(`/api/roteiro/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, { cenas });
    toast("Roteiro salvo ✓");
  } catch (e) { toast(e.message, true); }
  await atualizar();
});

$("btnAprovarRoteiro").addEventListener("click", async () => {
  try {
    await api(`/api/aprovar_roteiro/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {});
    toast("Roteiro aprovado ✓");
    mostrar("keyframes");
  } catch (e) { toast(e.message, true); }
});

async function enviarChat() {
  const txt = $("txtChat").value.trim();
  if (!txt) return;
  $("txtChat").value = "";
  $("txtChat").disabled = $("btnChat").disabled = true;
  const log = $("chatLog");
  log.insertAdjacentHTML("beforeend", `<div class="msg usuario">${esc(txt)}</div>`);
  log.insertAdjacentHTML("beforeend",
    `<div class="msg assistente pensando"><span class="spinner" style="position:static"></span> roteirista pensando…</div>`);
  log.scrollTop = log.scrollHeight;
  try {
    await api(`/api/roteiro_chat/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`,
      { mensagem: txt });
  } catch (e) {
    toast(e.message, true);
    const p = log.querySelector(".pensando");
    if (p) p.textContent = "Erro: " + e.message;
  } finally {
    $("txtChat").disabled = $("btnChat").disabled = false;
  }
  await atualizar();
}
$("btnChat").addEventListener("click", enviarChat);
$("txtChat").addEventListener("keydown", e => { if (e.key === "Enter") enviarChat(); });

/* ---------------------------------------------------------------- keyframes */
function cardCena(c, midiaHtml, botoesHtml, extra) {
  return `
    <div class="cena-card ${c.keyframe.aprovado ? "aprovado" : ""}" data-n="${c.n}">
      <div class="midia">${midiaHtml}</div>
      <div class="info"><span class="badge">${esc(rotuloTipo(c.tipo))}</span>
        <div class="narr">${esc(c.narracao || "(sem narração)")}</div></div>
      ${extra || ""}
      <div class="botoes">${botoesHtml}</div>
    </div>`;
}

function renderKeyframes(dado) {
  const foco = document.activeElement;  // não clobbera um refino inline aberto durante o poll
  if ($("gradeKeyframes").contains(foco) && foco.tagName === "TEXTAREA") return;
  const st = dado.status || {};
  const gerando = st.em_andamento && st.etapa === "keyframes";
  $("kfProgresso").classList.toggle("hidden", !gerando);
  if (gerando) {
    $("kfBar").style.width = st.total ? `${Math.round(100 * st.feitos / st.total)}%` : "0";
    $("kfTexto").textContent = `${st.feitos}/${st.total} — ${(st.atuais || []).join(", ") || "..."}`;
  }
  const cenas = dado.cenas || [];
  const sigK = JSON.stringify(cenas.map(c => [c.n, c.keyframe.url, c.keyframe.aprovado]))
    + "|" + gerando + "|" + (st.atuais || []).join(",") + "|" + (st.erros || []).length;
  if (sigK !== state._sigKf) {
   state._sigKf = sigK;
   $("gradeKeyframes").innerHTML = cenas.map(c => {
    const emVoo = gerando && (st.atuais || []).includes(`cena_${String(c.n).padStart(2, "0")}`);
    const midia = c.keyframe.url ? `<img src="${c.keyframe.url}">`
      : emVoo ? `<div class="spinner"></div>` : "sem keyframe";
    const erroKf = (st.erros || []).find(e => e.item === `cena_${String(c.n).padStart(2, "0")}`);
    const botoes = c.keyframe.url ? `
      <button class="btn mini ${c.keyframe.aprovado ? "ghost" : "primary"}" data-acao="aprovar">
        ${c.keyframe.aprovado ? "✓ Aprovado" : "Aprovar"}</button>
      <button class="btn mini ghost" data-acao="refinar">Refinar</button>
      <button class="btn mini ghost" data-acao="regerar">Gerar de novo</button>` : "";
    const extra = erroKf && st.etapa === "keyframes" ? `<div class="erro">${esc(erroKf.erro)}</div>` : "";
    return cardCena(c, midia, botoes, extra);
   }).join("");
  }

  const aprovadas = cenas.filter(c => c.keyframe.aprovado).length;
  const todosAprovados = cenas.length && aprovadas === cenas.length;
  const btn = $("btnGerarClipes");
  if (!todosAprovados) {
    btn.innerHTML = `Aprove as keyframes (${aprovadas}/${cenas.length})`;
  } else {
    const motor = $("selMotor").value;
    const custo = motor === "veo" ? "(grátis, no crédito)" :
      motor === "local" ? "(grátis, lento)" :
      dado.estimativa_usd ? `(~US$${dado.estimativa_usd.toFixed(2)})` : "";
    btn.innerHTML = `Gerar clipes <span id="custoEst">${custo}</span>`;
  }
  btn.disabled = !todosAprovados || (st.em_andamento && ["clipes", "montagem"].includes(st.etapa));
}

$("gradeKeyframes").addEventListener("click", async (e) => {
  const base = `/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`;
  // refino inline: botões dentro do mini-textarea do card
  const ri = e.target.closest("button[data-ri]");
  if (ri) {
    const card = ri.closest(".cena-card");
    const box = card.querySelector(".refino-inline");
    if (ri.dataset.ri === "cancel") { box.remove(); return; }
    const instrucao = box.querySelector("textarea").value.trim();
    if (!instrucao) { toast("Escreva o que ajustar.", true); return; }
    box.remove();
    try {
      await api(`/api/refinar_keyframe${base}/${card.dataset.n}`, { instrucao });
      toast("Refinando a cena…");
    } catch (err) { toast(err.message, true); }
    await atualizar();
    return;
  }
  const btn = e.target.closest("button[data-acao]");
  if (!btn) return;
  const card = btn.closest(".cena-card");
  const n = card.dataset.n;
  // "Refinar" abre um textarea inline no próprio card (sem prompt() nativo)
  if (btn.dataset.acao === "refinar") {
    if (card.querySelector(".refino-inline")) return;
    const box = document.createElement("div");
    box.className = "refino-inline";
    box.innerHTML = `<textarea placeholder="O que ajustar nessa cena? (grátis)"></textarea>
      <div class="ri-acoes"><button class="btn mini primary" data-ri="ok">Refinar</button>
      <button class="btn mini ghost" data-ri="cancel">Cancelar</button></div>`;
    card.appendChild(box);
    box.querySelector("textarea").focus();
    return;
  }
  try {
    if (btn.dataset.acao === "aprovar") {
      const c = state.ultimo.cenas.find(x => x.n == n);
      await api(`/api/aprovar_keyframe${base}/${n}`, { aprovado: !c.keyframe.aprovado });
    } else if (btn.dataset.acao === "regerar") {
      await api(`/api/refinar_keyframe${base}/${n}`, {});
      toast("Gerando a cena de novo…");
    }
    await atualizar();
  } catch (err) { toast(err.message, true); }
});

$("btnGerarKeyframes").addEventListener("click", async () => {
  try {
    await api(`/api/gerar_keyframes/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {});
    toast("Gerando keyframes… (grátis)");
  } catch (e) { toast(e.message, true); }
});
$("btnPararKf").addEventListener("click", () =>
  api(`/api/parar/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {}));

$("selMotor").addEventListener("change", () => { if (state.ultimo) renderKeyframes(state.ultimo); });

$("btnGerarClipes").addEventListener("click", async () => {
  const motor = "veo";  // motor único (omni/Veo)
  const est = "Motor Google Veo (omni): sai do crédito de teste do Google.";
  if (!await confirmar(`Gerar os clipes das cenas pendentes?\n${est}`, "Gerar clipes")) return;
  try {
    await api(`/api/gerar_clipes/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`,
      { motor });
    toast("Gerando clipes…");
    mostrar("clipes");
  } catch (e) { toast(e.message, true); }
});

/* ---------------------------------------------------------------- clipes */
function renderClipes(dado) {
  const st = dado.status || {};
  const gerando = st.em_andamento && st.etapa === "clipes";
  $("clProgresso").classList.toggle("hidden", !gerando);
  if (gerando) {
    $("clBar").style.width = st.total ? `${Math.round(100 * st.feitos / st.total)}%` : "0";
    $("clTexto").textContent = `${st.feitos}/${st.total} — ${(st.atuais || []).join(", ") || "..."}`;
  }
  const cenas = dado.cenas || [];
  // Só reconstrói o grid quando o estado muda de verdade — senão o poll (1,5s) recarrega
  // os <video> e a tela fica piscando.
  const sig = JSON.stringify(cenas.map(c => [c.n, c.tipo, c.clipe.gerado, c.clipe.url, c.clipe.erro, c.instrucao_clipe]))
    + "|" + gerando + "|" + (st.atuais || []).join(",");
  if (sig !== state._sigClipes) {
    state._sigClipes = sig;
    $("gradeClipes").innerHTML = cenas.map(c => {
      const emVoo = gerando && (st.atuais || []).includes(`cena_${String(c.n).padStart(2, "0")}`);
      const midia = c.clipe.url ? `<video src="${c.clipe.url}" controls playsinline></video>`
        : emVoo ? `<div class="spinner"></div>`
        : c.keyframe.url ? `<img src="${c.keyframe.url}" style="opacity:.35">` : "aguardando";
      const botoes = `
        ${c.clipe.gerado ? `<button class="btn mini ghost" data-acao="refazer-take">Refazer take</button>` : ""}
        ${c.clipe.erro && c.clipe.fal_request_id ? `<button class="btn mini primary" data-acao="retomar">Retomar sem pagar</button>` : ""}
        ${c.clipe.erro && !c.clipe.fal_request_id ? `<button class="btn mini primary" data-acao="regerar-clipe">Tentar de novo</button>` : ""}`;
      const extra = c.clipe.erro ? `<div class="erro">${esc(c.clipe.erro)}</div>` : "";
      return cardCena(c, midia, botoes, extra);
    }).join("");
  }

  const todosGerados = cenas.length && cenas.every(c => c.clipe.gerado);
  $("btnMontar").disabled = !todosGerados || st.em_andamento;
}

$("gradeClipes").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-acao]");
  if (!btn) return;
  const n = btn.closest(".cena-card").dataset.n;
  const card = btn.closest(".cena-card");
  const base = `/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`;
  try {
    if (btn.dataset.acao === "refazer-take") {
      if (card.querySelector(".refino-take")) return;
      const box = document.createElement("div");
      box.className = "refino-inline refino-take";
      box.innerHTML = `<textarea placeholder="O que corrigir? Ex.: a fala saiu errada; use a mesma voz masculina do take 2; menos pausa no final"></textarea>
        <div class="ri-acoes"><button class="btn mini ghost" data-acao="cancelar-refazer-take">Cancelar</button><button class="btn mini primary" data-acao="confirmar-refazer-take">Gerar novamente (paga 1 take)</button></div>`;
      card.appendChild(box);
      box.querySelector("textarea").focus();
      return;
    } else if (btn.dataset.acao === "cancelar-refazer-take") {
      card.querySelector(".refino-take")?.remove();
      return;
    } else if (btn.dataset.acao === "confirmar-refazer-take") {
      const instrucao = card.querySelector(".refino-take textarea")?.value.trim();
      if (!instrucao) return toast("Diga o que precisa ser corrigido neste take.", true);
      if (!await confirmar("Gerar novamente apenas este take? Esta chamada consome 1 geracao do Veo.", "Refazer take")) return;
      await api(`/api/regerar_clipe${base}/${n}`, { motor: $("selMotor").value, instrucao });
      toast("Refazendo o take com seu ajuste...");
    } else if (btn.dataset.acao === "regerar-clipe") {
      if (!await confirmar("Regerar o clipe desta cena? (paga só esta cena)", "Regerar")) return;
      await api(`/api/regerar_clipe${base}/${n}`, { motor: $("selMotor").value });
      toast("Regerando o clipe…");
    } else if (btn.dataset.acao === "retomar") {
      await api(`/api/regerar_clipe${base}/${n}`, { retomar: true });
      toast("Retomando sem pagar…");
    }
    await atualizar();
  } catch (err) { toast(err.message, true); }
});
$("btnPararCl").addEventListener("click", () =>
  api(`/api/parar/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {}));

$("btnMontar").addEventListener("click", async () => {
  try {
    await api(`/api/montar/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {});
    toast("Montando o vídeo final…");
    mostrar("final");
  } catch (e) { toast(e.message, true); }
});
$("btnRemontar").addEventListener("click", () => {
  const ed = $("editorCortes");
  if (ed) ed.classList.toggle("hidden");
});

async function aplicarCortes() {
  const cortes = [...document.querySelectorAll("#editorCortes .corte-take")].map(el => ({
    n: Number(el.dataset.n),
    inicio_s: Number(el.querySelector(".corte-inicio").value || 0),
    fim_s: Number(el.querySelector(".corte-fim").value || 0),
    remover: el.querySelector(".corte-remover").checked,
  }));
  try {
    await api(`/api/edicao/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, { cortes });
    await api(`/api/montar/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, {});
    toast("Aplicando cortes e remontando...");
  } catch (e) { toast(e.message, true); }
}

function htmlEditorCortes(cenas) {
  return `<div id="editorCortes" class="editor-cortes hidden">
    <h3>Editor de cortes</h3>
    <p class="dica">Ajuste a entrada e a saida de cada take. Fim 0 usa o clipe inteiro.</p>
    <div class="editor-timeline">${(cenas || []).filter(c => c.clipe && c.clipe.url).map(c => {
      const e = c.edicao || {};
      return `<article class="corte-take" data-n="${c.n}">
        <video src="${c.clipe.url}" controls preload="metadata"></video>
        <strong>Take ${c.n}</strong><span>${esc(c.narracao || "")}</span>
        <label>Inicio <input class="corte-inicio" type="number" min="0" step="0.05" value="${e.inicio_s || 0}"></label>
        <label>Fim <input class="corte-fim" type="number" min="0" step="0.05" value="${e.fim_s || 0}"></label>
        <label><input class="corte-remover" type="checkbox" ${e.remover ? "checked" : ""}> Remover take</label>
        <button type="button" class="btn mini ghost" onclick="abrirRefinoTake(${c.n})">Refazer fala/voz/animação</button>
      </article>`;
    }).join("")}</div>
    <button type="button" class="btn primary" onclick="aplicarCortes()">Aplicar cortes e remontar</button>
  </div>`;
}

function abrirRefinoTake(n) {
  mostrar("clipes");
  setTimeout(() => document.querySelector(`#gradeClipes .cena-card[data-n="${n}"] [data-acao="refazer-take"]`)?.click(), 0);
}

/* ---------------------------------------------------------------- final */
function renderFinal(dado) {
  const st = dado.status || {};
  const montando = st.em_andamento && st.etapa === "montagem";
  const p = $("playerFinal");
  if (montando) {
    p.innerHTML = `<p class="dica">Montando o vídeo (ffmpeg)...</p>`;
  } else if (dado.final_url) {
    if (!p.querySelector("video") || p.querySelector("video").dataset.src !== dado.final_url) {
      p.innerHTML = `<video src="${dado.final_url}" data-src="${dado.final_url}" controls></video>${htmlEditorCortes(dado.cenas)}`;
      $("btnBaixar").href = dado.final_url;
    }
  } else {
    p.innerHTML = `<p class="dica">O vídeo final aparece aqui depois da montagem.</p>`;
  }
  const erroM = (st.erros || []).find(e => e.item === "montagem");
  if (erroM && !montando && !p.querySelector(".erro")) {
    p.insertAdjacentHTML("beforeend", `<div class="erro aviso erro">${esc(erroM.erro)}</div>`);
  }
}

/* ---------------------------------------------------------------- avatares */
async function carregarVozes() {
  const vozes = (await api("/api/vozes")).vozes;
  $("avVoz").innerHTML = vozes.map(v => `<option>${esc(v)}</option>`).join("");
}
async function carregarAvatares() {
  const avs = (await api("/api/avatares")).avatares;
  renderAvatarPicker(avs.filter(a => a.referencias.length));
  const gerenciaveis = avs.filter(a => (a.tipo || "avatar") !== "influenciador");
  $("listaAvatares").innerHTML = gerenciaveis.length ? gerenciaveis.map(a => `
    <div class="avatar-item">
      <div class="fotos">${a.referencias.slice(0, 3).map(r =>
        `<img src="${B}/avatar_media/${encodeURIComponent(a.nome)}/referencia/${encodeURIComponent(r)}">`).join("")
        || (a.gerando ? '<div class="spinner" style="position:static"></div>' : "")}</div>
      <div class="meta">
        <div class="nome">${esc(a.nome)} ${a.gerando ? "· gerando fotos..." : ""}</div>
        <div class="voz">${esc((a.voz || {}).edge_voice || "")}</div>
        ${(a.erros || []).length ? `<div class="erro">${esc(a.erros[0].erro)}</div>` : ""}
      </div>
      <button class="btn mini ghost" data-av="${esc(a.nome)}">Regerar fotos</button>
    </div>`).join("") : `<p class="dica">Nenhum avatar ainda.</p>`;
  if (avs.some(a => a.gerando)) setTimeout(carregarAvatares, 3000);
}
function renderAvatarPicker(avs) {
  const box = $("avatarPicker");
  if (!box) return;
  const card = (a) => {
    const tipo = a.tipo || "avatar", ref = (a.referencias || [])[0];
    const src = ref
      ? (tipo === "influenciador"
        ? `/influenciador_media/${encodeURIComponent(a.nome)}/${encodeURIComponent(ref)}`
        : `${B}/avatar_media/${encodeURIComponent(a.nome)}/referencia/${encodeURIComponent(ref)}`)
      : "";
    return `<button type="button" class="avatar-pick ${tipo === "influenciador" ? "expert" : "ugc"}" data-avatar="${esc(tipo + "::" + a.nome)}"><span class="avatar-thumb">${src ? `<img src="${src}" alt="">` : "<span>?</span>"}</span><span class="avatar-pick-name">${esc(a.nome)}</span><span class="avatar-pick-type">${tipo === "influenciador" ? "expert oficial" : "avatar UGC"}</span></button>`;
  };
  box.innerHTML = `<button type="button" class="avatar-pick none active" data-avatar=""><span class="avatar-thumb avatar-none">Sem pessoa</span><span class="avatar-pick-name">Sem pessoa</span><span class="avatar-pick-type">produto, tela e mãos</span></button><div class="avatar-pick-group"><div class="avatar-pick-heading">Avatares UGC</div>${avs.filter(a => (a.tipo || "avatar") === "avatar").map(card).join("") || "<span class='mini-label'>Nenhum avatar UGC gerado.</span>"}</div><div class="avatar-pick-group"><div class="avatar-pick-heading">Experts oficiais</div>${avs.filter(a => a.tipo === "influenciador").map(card).join("") || "<span class='mini-label'>Nenhum expert cadastrado.</span>"}</div>`;
  box.querySelectorAll(".avatar-pick").forEach(btn => btn.addEventListener("click", () => {
    state.avatar = btn.dataset.avatar;
    $("avatarSelectionHint").textContent = state.avatar ? `Selecionado: ${state.avatar.split("::").slice(-1)[0]}` : "Produto + mãos, sem pessoa identificada";
    box.querySelectorAll(".avatar-pick").forEach(b => b.classList.toggle("active", b === btn));
  }));
}
$("listaAvatares").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-av]");
  if (!btn) return;
  if (!await confirmar("Regerar as fotos deste avatar? (grátis, substitui as atuais)", "Regerar")) return;
  await api(`/api/avatar_refs/${encodeURIComponent(btn.dataset.av)}`, {});
  toast("Regerando as fotos do avatar…");
  carregarAvatares();
});
function vozPayload() {
  const engine = $("avEngine").value;
  if (engine === "eleven") return { engine, voice_id: $("avVoiceId").value.trim() || null };
  if (engine === "f5") return { engine };
  return { engine: "edge", edge_voice: $("avVoz").value };
}
function trocarEngineVoz() {
  const e = $("avEngine").value;
  $("vozEdge").classList.toggle("hidden", e !== "edge");
  $("vozEleven").classList.toggle("hidden", e !== "eleven");
  $("vozF5").classList.toggle("hidden", e !== "f5");
}
$("avEngine").addEventListener("change", trocarEngineVoz);

async function ouvirVoz(btn) {
  btn.disabled = true;
  try {
    const r = await api("/api/voz_preview", vozPayload());
    const a = $("audioPreview"); a.src = r.url; a.play();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
}
$("btnOuvirVoz").addEventListener("click", () => ouvirVoz($("btnOuvirVoz")));
$("btnOuvirVozEleven").addEventListener("click", () => ouvirVoz($("btnOuvirVozEleven")));

$("btnCriarAvatar").addEventListener("click", async () => {
  const nome = $("avNome").value.trim(), desc = $("avDesc").value.trim();
  if (!nome || !desc) return aviso($("avStatus"), "Preencha nome e descrição.", true);
  $("btnCriarAvatar").disabled = true;
  try {
    await api("/api/avatares", { nome, descricao: desc, ...vozPayload() });
    aviso($("avStatus"), "Avatar criado. Gerando as 3 fotos de referência em background (grátis)...");
    $("avNome").value = ""; $("avDesc").value = "";
    carregarAvatares();
  } catch (e) { aviso($("avStatus"), e.message, true); }
  finally { $("btnCriarAvatar").disabled = false; }
});

boot().catch(e => toast("Falha ao iniciar: " + e.message, true));
