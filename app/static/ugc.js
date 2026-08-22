/* UGC Express — front (vanilla JS + polling de status a 1,5s) */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  produto: null,
  vid: null,
  modo: null,
  formato: "padrao",   // formato de vídeo ativo (padrao/fala_faz/top5/...)
  formatosVideo: ["padrao"],
  loteVids: [],        // vídeos criados no último lote (mix) p/ keyframes/clipes em lote
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

/* --- Seletor de modelo Claude/Codex (espelho da tela de imagem) --- */
let MODELOS_INFO = [];
const _TIER_LABEL = { baixo: "baixo", medio: "médio", alto: "alto" };
function modeloSel() { return ($("modelo") && $("modelo").value) || "sonnet"; }
async function carregarModelos() {
  let data;
  try { data = await (await fetch("/api/modelos")).json(); } catch (e) { return; }
  MODELOS_INFO = data.modelos || [];
  _construirMenuModelos();
  const valido = (id) => MODELOS_INFO.some((m) => m.id === id);
  _escolherModelo(valido(data.default) ? data.default : ((MODELOS_INFO[0] && MODELOS_INFO[0].id) || ""));
}
function _construirMenuModelos() {
  const menu = $("modeloMenu"); if (!menu) return;
  menu.innerHTML = "";
  [{ prov: "claude", label: "Claude · recomendado p/ roteiro" }, { prov: "gpt", label: "GPT · Codex (teste)" }].forEach((g) => {
    const itens = MODELOS_INFO.filter((m) => m.provider === g.prov);
    if (!itens.length) return;
    const head = document.createElement("div"); head.className = "modelo-grp"; head.textContent = g.label; menu.appendChild(head);
    itens.forEach((m) => {
      const row = document.createElement("div"); row.className = "modelo-opt"; row.setAttribute("role", "option"); row.dataset.id = m.id;
      row.innerHTML = `<span class="modelo-opt-nome">${esc(m.label)}</span><span class="modelo-tag tag-${m.consumo}"><i class="modelo-dot"></i>${_TIER_LABEL[m.consumo] || m.consumo}</span><svg class="modelo-check" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 12l5 5L19 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      row.addEventListener("click", () => { _escolherModelo(m.id); _fecharMenuModelos(); });
      menu.appendChild(row);
    });
  });
}
function _escolherModelo(id) {
  const m = MODELOS_INFO.find((x) => x.id === id);
  if ($("modelo")) $("modelo").value = id || "";
  if ($("modeloBtnNome")) $("modeloBtnNome").textContent = m ? m.label : "—";
  if ($("modeloBtnDot")) $("modeloBtnDot").className = "modelo-dot" + (m ? " tier-" + m.consumo : "");
  const menu = $("modeloMenu");
  if (menu) menu.querySelectorAll(".modelo-opt").forEach((o) => o.classList.toggle("sel", o.dataset.id === id));
}
function _fecharMenuModelos() {
  if ($("modeloWrap")) $("modeloWrap").classList.remove("aberto");
  if ($("modeloBtn")) $("modeloBtn").setAttribute("aria-expanded", "false");
}
function _initModelo() {
  const btn = $("modeloBtn"); if (!btn) return;
  btn.addEventListener("click", (e) => { e.stopPropagation(); const a = $("modeloWrap").classList.toggle("aberto"); btn.setAttribute("aria-expanded", a ? "true" : "false"); });
  document.addEventListener("click", (e) => { if (!e.target.closest("#modeloWrap")) _fecharMenuModelos(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") _fecharMenuModelos(); });
  carregarModelos();
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", _initModelo); else _initModelo();

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
  // Modo LOTE: cada etapa (keyframes/clipes/final) mostra só o seu banner de lote e
  // esconde os controles de vídeo único (que só fazem sentido com 1 vídeo aberto).
  const lote = !!state.lote;
  const banners = { keyframes: "loteKf", clipes: "loteCl", final: "loteFn" };
  ["keyframes", "clipes", "final"].forEach(step => {
    const ativo = lote && view === step;
    $(banners[step])?.classList.toggle("hidden", !ativo);
    const sec = $("view-" + step);
    sec?.querySelector(".barra-acao")?.classList.toggle("hidden", ativo);
    sec?.querySelector(".grade")?.classList.toggle("hidden", ativo);
    sec?.querySelector(".card.centro")?.classList.toggle("hidden", ativo);
  });
  // (Re)desenha a prévia da etapa de lote ao entrar nela, pra a tela não ficar vazia
  // quando os keyframes/clipes já foram gerados (ex.: voltou pra etapa depois de gerar).
  if (lote && view === "keyframes") renderPreviaLote(null, "loteKfPrev");
  if (lote && view === "clipes") renderPreviaLote(null, "loteClPrev");
  if (lote && view === "final") atualizarFinalLote();   // (re)desenha editor de timeline / botão montar
  atualizarBotaoLote();
}
// Botão "← Voltar ao lote": aparece quando você abriu 1 vídeo pra revisar mas o lote
// (2+ vídeos) ainda existe em memória — recupera a visão geral do lote sem perder nada.
function atualizarBotaoLote() {
  const b = $("btnVoltarLote"); if (!b) return;
  b.classList.toggle("hidden", !(!state.lote && (state.loteVids || []).length >= 2));
}
$("btnVoltarLote")?.addEventListener("click", () => {
  if ((state.loteVids || []).length < 2) return;
  pararPoll();
  state.lote = true;
  state.vid = null;
  mostrar("keyframes");
});
document.querySelectorAll("#steps button").forEach(b =>
  b.addEventListener("click", () => {
    const step = b.dataset.step;
    // Se existe um LOTE (2+ vídeos), as etapas Keyframes/Clipes/Final SEMPRE voltam pra
    // visão do lote inteiro — mesmo que você tenha aberto 1 vídeo pra revisar. Assim
    // "voltar pra aba Keyframes" mostra TODOS os vídeos, não só 1.
    if (["keyframes", "clipes", "final"].includes(step) && (state.loteVids || []).length >= 2) {
      pararPoll();
      state.lote = true;
      state.vid = null;
    }
    mostrar(step);
  }));

/* ---------------------------------------------------------------- boot */
async function boot() {
  state.cfg = (await api("/api/config"));
  $("btnRemontar").textContent = "Editar cortes";
  document.querySelectorAll(".copy-mode").forEach(b => b.classList.remove("ativo"));
  // Usa a mesma fonte da sidebar dos criativos estáticos, incluindo produtos
  // agrupados por cliente (cliente~produto) e suas miniaturas.
  const prods = await (await fetch("/api/produtos")).json();
  $("selProduto").innerHTML = prods.length ? prods.map(p => `<option value="${esc(p.nome)}">${esc(p.nome)}</option>`).join("") : `<option value="">Nenhum produto cadastrado</option>`;
  $("selProduto").disabled = !prods.length;
  renderProdutos(prods);
  // Começa SEM produto selecionado — o usuário é OBRIGADO a escolher um na sidebar.
  state.produto = null;
  if ($("selMotor")) $("selMotor").value = state.cfg.motor || "api";
  await carregarVozes();
  await carregarAvatares();
  mostrar("copy");
}
$("selProduto").addEventListener("change", async () => {
  state.produto = $("selProduto").value; state.vid = null;
  document.querySelectorAll("#produtos .produto-item").forEach(li => li.classList.toggle("ativo", li.dataset.nome === state.produto));
  await carregarTipoProduto(); await carregarVideos(); mostrar("copy");
});

// Sanfonas de cliente começam fechadas ao abrir; guardamos em memória o que o
// usuário abriu nesta sessão (não persiste entre aberturas da ferramenta).
const _ugcExpandidos = new Set();
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
    if (!_ugcExpandidos.has(cliente)) grupo.classList.add("colapsado");
    const head = document.createElement("button");
    head.type = "button";
    head.className = "cli-head";
    head.innerHTML = `<span class="cli-caret">▾</span><span class="cli-nome">${esc(cliente)}</span><span class="cli-count">${grupos.get(cliente).length}</span>`;
    const lista = document.createElement("ul");
    lista.className = "cli-lista";
    head.addEventListener("click", () => {
      grupo.classList.toggle("colapsado");
      if (grupo.classList.contains("colapsado")) _ugcExpandidos.delete(cliente);
      else _ugcExpandidos.add(cliente);
    });
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
  await carregarTipoProduto(); await carregarVideos(); await carregarFormatosVideo();
  await detectarLote();   // se há um lote recente no disco, reativa o modo lote
  if (trocarView) mostrar("copy");
}

// Reconstrói o modo lote a partir do disco (o estado em memória se perde no reload).
// Se o produto tem um lote recente (2+ vídeos do mesmo batch), reativa state.lote pra
// as etapas Keyframes/Clipes mostrarem a prévia em vez de ficarem vazias.
async function detectarLote() {
  state.lote = false; state.loteVids = [];
  if (!state.produto) return;
  try {
    const r = await api(`/api/previa_lote/${encodeURIComponent(state.produto)}`);
    const vids = r.vids || [];
    if (vids.length >= 2) { state.lote = true; state.loteVids = vids; }
  } catch (e) { /* sem lote: segue em modo vídeo único */ }
}

// O tipo (físico/digital) é definido por produto na aba Imagem → Contexto.
// Aqui a ferramenta de vídeo apenas LÊ o valor salvo em config.md.
async function carregarTipoProduto() {
  state.tipoProduto = null;
  if (!state.produto) return;
  try {
    const r = await api(`/api/tipo_produto/${encodeURIComponent(state.produto)}`);
    state.tipoProduto = r.tipo || null;
  } catch (e) { /* sem tipo salvo: segue null e o guarda avisa */ }
}

async function carregarVideos() {
  if (!state.produto) {
    $("selVideo").innerHTML = `<option value="">Nenhum vídeo disponível</option>`;
    $("selVideo").disabled = true;
    return;
  }
  const vids = (await api(`/api/videos/${encodeURIComponent(state.produto)}`)).videos;
  $("selVideo").innerHTML = `<option value="">— vídeos —</option>` +
    vids.map(v => `<option value="${esc(v.id)}">${esc(v.id)} · ${esc(v.formato_label || "Padrão")} (${esc(v.estado)})</option>`).join("");
}
$("selVideo").addEventListener("change", () => {
  const v = $("selVideo").value;
  if (v) abrirVideo(v);
});
$("btnNovoVideo").addEventListener("click", () => {
  pararPoll(); state.vid = null; state.modo = null; state.tipoProduto = null;
  document.querySelectorAll(".copy-mode").forEach(b => b.classList.remove("ativo"));
  mostrar("copy");
});
$("btnAvatares").addEventListener("click", async () => { await carregarAvatares(); mostrar("avatares"); });

/* ---------------------------------------------------------------- novo vídeo */
let copySession = null;
// Formata o texto do roteiro em blocos legíveis: cada "[CENA ...]" vira uma linha
// com a direção destacada e a fala/ação em seguida (em vez de um parágrafo confuso).
function formatarCenasHtml(txt) {
  if (!txt) return "";
  const partes = String(txt).split(/(?=\[CENA)/i).map(s => s.trim()).filter(Boolean);
  if (partes.length <= 1) return `<p class="cena-linha">${esc(txt)}</p>`;
  return partes.map(p => {
    const m = p.match(/^\[([^\]]*)\]\s*([\s\S]*)$/);
    return m
      ? `<p class="cena-linha"><span class="cena-dir">[${esc(m[1])}]</span> ${esc(m[2])}</p>`
      : `<p class="cena-linha">${esc(p)}</p>`;
  }).join("");
}
function renderCopyOpcoes(opcoes) {
  opcoes = opcoes || [];
  const wrap = document.createElement("div");
  wrap.className = "msg assistente roteiro-opcoes";
  wrap.innerHTML = `<div class="roteiro-opcoes-head"><strong>Roteiros sugeridos (${opcoes.length})</strong><label class="chk-todas"><input type="checkbox" class="chk-todas-input"> todas</label></div>` +
    `<div class="roteiro-opcoes-grid">${opcoes.map((o, i) => `<label class="roteiro-opcao"><input type="checkbox" data-opcao="${i}"><span class="roteiro-opcao-body"><strong>${esc(o.titulo || `Opção ${i + 1}`)} <small>· ${esc(o.duracao_s || 30)}s</small></strong><span class="roteiro-cenas">${formatarCenasHtml(o.roteiro)}</span><button type="button" class="roteiro-vermais" hidden>ver tudo</button></span></label>`).join("")}</div>` +
    `<div class="roteiro-opcoes-actions"><span class="mini-label sel-opcoes">0 selecionados</span><button type="button" class="btn primary btn-usar-opcoes" disabled>Escolher e ir para roteiro</button></div>`;
  const checks = () => [...wrap.querySelectorAll("input[data-opcao]")];
  const atualizar = () => {
    state.copiesSelecionadas = checks().filter(x => x.checked).map(x => opcoes[Number(x.dataset.opcao)]);
    wrap.querySelector(".sel-opcoes").textContent = `${state.copiesSelecionadas.length} selecionado(s)`;
    wrap.querySelector(".btn-usar-opcoes").disabled = !state.copiesSelecionadas.length;
    const cards = wrap.querySelectorAll(".roteiro-opcao");
    checks().forEach((x, i) => cards[i].classList.toggle("selecionado", x.checked));
    const all = wrap.querySelector(".chk-todas-input");
    all.checked = checks().length > 0 && checks().every(x => x.checked);
  };
  checks().forEach(x => x.addEventListener("change", atualizar));
  wrap.querySelector(".chk-todas-input").addEventListener("change", (e) => {
    checks().forEach(x => { x.checked = e.target.checked; });
    atualizar();
  });
  wrap.querySelector(".btn-usar-opcoes").addEventListener("click", () => { renderRoteirosEscolhidos(); mostrar("novo"); });
  $("copyChatLog").appendChild(wrap);
  $("copyChatLog").scrollTop = $("copyChatLog").scrollHeight;
  // "ver tudo" só aparece quando as cenas estouram a altura — e a medição só vale
  // com o card JÁ no DOM (fora dele, scrollHeight/clientHeight vêm 0).
  requestAnimationFrame(() => {
    wrap.querySelectorAll(".roteiro-opcao").forEach(card => {
      const cenas = card.querySelector(".roteiro-cenas");
      const btn = card.querySelector(".roteiro-vermais");
      if (cenas && btn && cenas.scrollHeight > cenas.clientHeight + 4) {
        btn.hidden = false;
        btn.addEventListener("click", (ev) => {
          ev.preventDefault(); ev.stopPropagation();
          const exp = cenas.classList.toggle("expandido");
          btn.textContent = exp ? "recolher" : "ver tudo";
        });
      }
    });
  });
}
async function enviarCopyChat() {
  const mensagem = $("txtCopyChat").value.trim();
  if (!state.produto) return toast("Selecione um produto primeiro.", true);
  if (!mensagem) return toast("Descreva o que você quer criar.", true);
  $("copyChatEmpty")?.remove();
  const btn = $("btnCopyChat"), htmlBtn = btn.innerHTML; btn.disabled = true;
  $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg usuario">${esc(mensagem)}</div>`);
  $("txtCopyChat").value = ""; $("txtCopyChat").style.height = "auto";   // some do campo assim que envia
  $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg assistente pensando copy-pensando"><span class="thinking-orb"></span><span class="thinking-label">Roteirista pensando</span></div>`);
  $("copyChatLog").scrollTop = $("copyChatLog").scrollHeight;
  try {
    // Formato(s) vêm do popup; a QUANTIDADE de roteiros é reconhecida no texto do prompt.
    const r = await api(`/api/copy_chat/${encodeURIComponent(state.produto)}`, {
      mensagem, formato: state.formato,
      formatos: state.formatosVideo || [state.formato],
      modelo: modeloSel(), session_id: copySession,
    });
    copySession = r.session_id || copySession;
    $("copyChatLog").querySelector(".copy-pensando")?.remove();
    $("copyChatLog").insertAdjacentHTML("beforeend", `<div class="msg assistente">${esc(r.resposta || "Gerei opções ao lado.")}</div>`);
    renderCopyOpcoes(r.opcoes); $("txtCopyChat").value = "";
  } catch (e) { $("copyChatLog").querySelector(".copy-pensando")?.remove(); toast(e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = htmlBtn; }
}
$("btnCopyChat").addEventListener("click", enviarCopyChat);
$("txtCopyChat").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarCopyChat(); } });
$("txtCopyChat").addEventListener("input", e => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

$("btnCriarRoteiro").addEventListener("click", async () => {
  const opcoes = state.copiesSelecionadas || [];
  if (!opcoes.length) return aviso($("novoStatus"), "Selecione ao menos um roteiro no chat.", true);
  if (!state.tipoProduto) return aviso($("novoStatus"), "Defina o tipo do produto (Físico/Digital) na aba Imagem → Contexto antes de criar o roteiro.", true);
  $("btnCriarRoteiro").disabled = true;
  const inicio = Date.now();
  $("novoStatus").classList.add("hidden");
  $("novoLoader").classList.remove("hidden");   // loader animado (igual "gerar visuais")
  try {
    // Cria os roteiros UM DE CADA VEZ (sequencial). O claude em paralelo trava no app
    // empacotado (dá timeout); serializando, cada roteiro roda sozinho e conclui rápido.
    const resultados = [];
    for (const opcao of opcoes) {
      // Casting POR VÍDEO: cada roteiro manda o quem-aparece dele (default: solo=auto, multi=gerado).
      const cast = opcao.castingAvatar !== undefined ? opcao.castingAvatar : castingDefault(opcao.formato);
      try {
        resultados.push(await api(`/api/videos/${encodeURIComponent(state.produto)}`, {
          copy: copyComBrief(opcao), avatar: cast, modelo: modeloSel(),
          formato: opcao.formato || state.formato,
          tipo_produto: state.tipoProduto,
        }));
      } catch (e) {
        resultados.push({ __erro: (e && e.message) || "erro desconhecido" });
      }
    }
    const criados = resultados.filter((r) => r && r.roteiro && r.roteiro.id).map((r) => r.roteiro.id);
    await carregarVideos();
    state.loteVids = criados;
    $("novoLoader").classList.add("hidden");
    if (criados.length > 1) {
      // Lote: vai direto pra etapa 3 (Keyframes) com o banner do lote.
      state.lote = true;
      iniciarLote(criados);
    } else if (criados.length === 1) {
      state.lote = false;
      abrirVideo(criados[0]);
    } else {
      const err = (resultados.find((r) => r && r.__erro) || {}).__erro;
      aviso($("novoStatus"), err ? ("Não consegui criar o roteiro: " + err) : "Nenhum roteiro criado. Tente de novo.", true);
    }
  } catch (e) { $("novoLoader").classList.add("hidden"); aviso($("novoStatus"), e.message, true); }
  finally { $("btnCriarRoteiro").disabled = false; }
});

/* ---- LOTE: cada etapa (Keyframes → Clipes → Final) tem seu próprio botão ---- */
function iniciarLote(vids) {
  const n = (vids || []).length;
  $("loteKfInfo").textContent = `Lote de ${n} vídeos. Um clique gera os keyframes de TODOS os ${n} de uma vez (6 simultâneos, em fila automática — não precisa reclicar). Pra revisar um vídeo, use o botão "Abrir ↗".`;
  $("loteClInfo").textContent = `Um clique gera os clipes (Veo, pago) de TODOS os ${n} vídeos, 6 simultâneos em fila automática.`;
  $("loteFnInfo").textContent = `Monte o vídeo final de cada um dos ${n} anúncios (grátis) e baixe todos aqui.`;
  ["loteKfProg", "loteClProg", "loteFnProg"].forEach(id => $(id).textContent = "");
  mostrar("keyframes");   // vai pra etapa 3, onde ele gera os keyframes
}

async function pollLote(labelFeito, progEl, onTick, barEl) {
  return new Promise((resolve) => {
    const t = setInterval(async () => {
      let st;
      try { st = (await api(`/api/status_lote/${encodeURIComponent(state.produto)}`)).status || {}; }
      catch (e) { return; }
      const feitos = st.feitos || 0, total = st.total || 0;
      const pct = total ? Math.round(100 * feitos / total) : 0;
      if (barEl) { barEl.style.width = (st.em_andamento ? pct : 100) + "%"; barEl.classList.toggle("gerando", !!st.em_andamento); }
      if (progEl) progEl.textContent = st.em_andamento
        ? `${labelFeito}: ${feitos} de ${total}${st.atuais ? " · " + (Array.isArray(st.atuais) ? st.atuais.join(", ") : st.atuais) : ""}`
        : `${labelFeito}: ${feitos} de ${total} · concluído`;
      if (onTick) { try { await onTick(st); } catch (_) { /* ignora */ } }
      if (!st.em_andamento) { clearInterval(t); resolve(st); }
    }, 1500);
  });
}

$("btnLoteKeyframes")?.addEventListener("click", async () => {
  const vids = state.loteVids || [];
  if (!vids.length) return;
  $("btnLoteKeyframes").disabled = true;
  $("loteKfProgWrap")?.classList.remove("hidden");
  if ($("loteKfBar")) $("loteKfBar").style.width = "0%";
  await renderPreviaLote(vids, "loteKfPrev", true);   // skeleton imediato (não fica tela preta)
  try {
    await api(`/api/gerar_keyframes_lote/${encodeURIComponent(state.produto)}`, { vids });
    await pollLote("Keyframes", $("loteKfProg"), () => renderPreviaLote(vids, "loteKfPrev", true), $("loteKfBar"));
    await carregarVideos();
    await renderPreviaLote(vids, "loteKfPrev", false);
    toast("Keyframes prontos → indo pra Clipes.");
    mostrar("clipes");   // avança AUTOMATICAMENTE pra etapa Clipes ao terminar
  } catch (e) { toast(e.message, true); }
  finally { $("btnLoteKeyframes").disabled = false; }
});

$("btnLoteClipes")?.addEventListener("click", async () => {
  const vids = state.loteVids || [];
  if (!vids.length) return;
  if (!(await confirmar("Gerar os clipes (Veo, PAGO) de todos os vídeos do lote?", "Gerar clipes"))) return;
  $("btnLoteClipes").disabled = true;
  $("loteClProgWrap")?.classList.remove("hidden");
  if ($("loteClBar")) $("loteClBar").style.width = "0%";
  await renderPreviaLote(vids, "loteClPrev", true);   // skeleton imediato
  try {
    await api(`/api/gerar_clipes_lote/${encodeURIComponent(state.produto)}`, { vids });
    await pollLote("Clipes", $("loteClProg"), () => renderPreviaLote(vids, "loteClPrev", true), $("loteClBar"));
    await carregarVideos();
    await renderPreviaLote(vids, "loteClPrev", false);
    toast("Clipes gerados → indo pra Final.");
    mostrar("final");   // avança AUTOMATICAMENTE pra etapa Final ao terminar
  } catch (e) { toast(e.message, true); }
  finally { $("btnLoteClipes").disabled = false; }
});

// Monta o vídeo FINAL de cada anúncio do lote (ffmpeg local, grátis) + grade de entregas.
$("btnLoteMontar")?.addEventListener("click", async () => {
  const vids = state.loteVids || [];
  if (!vids.length) return;
  if (!(await confirmar("Montar o vídeo final de TODOS os anúncios do lote?", "Montar todos"))) return;
  $("btnLoteMontar").disabled = true;
  $("loteMontarWrap")?.classList.add("hidden");   // some o botão durante/após a montagem
  try {
    await api(`/api/montar_lote/${encodeURIComponent(state.produto)}`, { vids });
    await pollLote("Montagem", $("loteFnProg"));
    await renderEntregas(vids);
    await renderEditorFinal(vids);   // editor de timeline por vídeo (ajuste fino das gorduras)
    toast("Vídeos do lote montados ✓");
  } catch (e) { $("loteMontarWrap")?.classList.remove("hidden"); toast(e.message, true); }
  finally { $("btnLoteMontar").disabled = false; }
});
// Modal de vídeo: abre a entrega GRANDE, letterbox 9:16 (o fullscreen nativo corta o vertical).
function abrirVideoModal(src) {
  const m = $("videoModal"), v = $("videoModalVideo"); if (!m || !v) return;
  v.src = src; m.classList.remove("hidden"); v.currentTime = 0; v.play().catch(() => {});
}
function fecharVideoModal() {
  const m = $("videoModal"), v = $("videoModalVideo"); if (!m) return;
  if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
  m.classList.add("hidden");
}
document.addEventListener("click", (e) => {
  const amp = e.target.closest?.(".entrega-ampliar");
  if (amp && amp.dataset.src) { e.preventDefault(); abrirVideoModal(amp.dataset.src); }
});
$("videoModalX")?.addEventListener("click", fecharVideoModal);
$("videoModalBg")?.addEventListener("click", fecharVideoModal);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") fecharVideoModal(); });

async function renderEntregas(vids) {
  const box = $("loteEntregas"); if (!box) return;
  try {
    const r = await api(`/api/entregas_lote/${encodeURIComponent(state.produto)}?vids=${encodeURIComponent(vids.join(","))}`);
    const itens = r.entregas || [];
    const prontos = itens.filter(e => e.final_url).length;
    box.innerHTML = `<div class="lote-entregas-tit">Entregas do lote — ${prontos}/${itens.length} pronto(s)</div>` +
      `<div class="lote-entregas-grid">` + itens.map(e => e.final_url
        ? `<div class="entrega-card"><video src="${e.final_url}" controls playsinline preload="metadata"></video><div class="entrega-meta"><span class="entrega-tit" title="${esc(e.titulo)}">${esc(e.titulo)}</span><button type="button" class="btn mini ghost entrega-ampliar" data-src="${e.final_url}" title="Ver grande sem cortar">Ampliar ⛶</button><a class="btn mini ghost" href="${e.final_url}" download="${esc(e.titulo)}.mp4">Baixar</a></div></div>`
        : `<div class="entrega-card falhou"><div class="entrega-ph">sem vídeo (faltam clipes)</div><div class="entrega-meta"><span class="entrega-tit">${esc(e.titulo)}</span></div></div>`
      ).join("") + `</div>`;
  } catch (e) { /* silencioso */ }
}

/* =================================================================
   EDITOR DE TIMELINE (etapa Final, LOTE) — apara as "gorduras" de cada
   take arrastando as pontas. Cada take = 1 clipe; a largura do segmento é
   proporcional à DURAÇÃO TOTAL do clipe (lida no cliente via loadedmetadata).
   Alça esquerda corta o início (inicio_s), direita corta o fim (fim_s).
   ================================================================= */
const editorState = {};   // vid -> { takes: [{ n, dur, inicio, fim, clipe_url, keyframe_url, narracao, ready, _seg }] }
const tlClamp = (v, a, b) => Math.min(b, Math.max(a, v));
function cssq(s) { return (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, "\\$&"); }

// Decide o que mostrar na etapa Final (lote): se já há vídeos montados, esconde o
// botão "Montar todos" e desenha os timelines + entregas; senão, botão centralizado.
async function atualizarFinalLote() {
  const vids = state.loteVids || [];
  if (!vids.length) return;
  let montado = false;
  try {
    const r = await api(`/api/entregas_lote/${encodeURIComponent(state.produto)}?vids=${encodeURIComponent(vids.join(","))}`);
    montado = (r.entregas || []).some(e => e.final_url);
  } catch (_) { /* offline: mantém botão */ }
  $("loteMontarWrap")?.classList.toggle("hidden", montado);
  if (montado) {
    await renderEntregas(vids);
    await renderEditorFinal(vids);
  } else {
    if ($("loteEditor")) $("loteEditor").innerHTML = "";
    if ($("loteEntregas")) $("loteEntregas").innerHTML = "";
  }
}

// Monta os timelines: 1 seção por vídeo, faixa horizontal de segmentos (takes).
async function renderEditorFinal(vids) {
  const box = $("loteEditor"); if (!box) return;
  vids = (vids && vids.length) ? vids : (state.loteVids || []);
  if (!vids.length) { box.innerHTML = ""; return; }
  let itens = [];
  try {
    const r = await api(`/api/previa_lote/${encodeURIComponent(state.produto)}?durs=1&vids=${encodeURIComponent(vids.join(","))}`);
    itens = r.itens || [];
  } catch (e) { return; }
  box.innerHTML = `<div class="lote-editor-tit">Ajuste fino — arraste as pontas de cada cena pra aparar silêncios/gordura, depois "Renderizar edição".</div>` +
    itens.map(v => htmlTimelineVideo(v)).join("");
  itens.forEach(v => initTimelineVideo(v));
}

function htmlTimelineVideo(v) {
  return `<section class="tl-vid" data-vid="${esc(v.vid)}">
    <header class="tl-vid-head">
      <span class="tl-vid-nome">${esc(v.titulo)}</span>
      <div class="tl-vid-acoes">
        <span class="tl-status"></span>
        <button type="button" class="btn mini primary tl-render" data-vid="${esc(v.vid)}">Renderizar edição</button>
      </div>
    </header>
    <div class="tl-track"></div>
    <div class="tl-legenda">Clique numa cena pra pré-ouvir o trecho mantido · arraste ▮ nas pontas pra cortar.</div>
  </section>`;
}

function initTimelineVideo(v) {
  const vid = v.vid;
  const cenas = (v.cenas || []).filter(c => c.clipe_url);   // só takes com clipe (o que é concatenado)
  const takes = cenas.map(c => ({
    n: c.n, clipe_url: c.clipe_url, keyframe_url: c.keyframe_url,
    narracao: c.narracao || "", dur: Number(c.clipe_dur) || 0,   // duração REAL vinda do backend
    inicio: Math.max(0, Number(c.inicio_s) || 0),
    fim: (Number(c.fim_s) > 0 ? Number(c.fim_s) : null),   // null = "até o fim" (resolve com a duração)
    ready: false, _seg: null,
  }));
  editorState[vid] = { takes };
  const track = document.querySelector(`.tl-vid[data-vid="${cssq(vid)}"] .tl-track`);
  if (!track) return;
  track.innerHTML = "";
  if (!takes.length) { track.innerHTML = `<div class="tl-vazio">Sem clipes pra editar.</div>`; return; }
  takes.forEach((t) => {
    const seg = document.createElement("div");
    seg.className = "tl-seg loading";
    seg.style.flexGrow = "1";
    seg.dataset.n = String(t.n);
    seg.innerHTML =
      `${t.keyframe_url ? `<img class="tl-seg-bg" src="${esc(t.keyframe_url)}" alt="" loading="lazy">` : ""}` +
      `<div class="tl-cut tl-cut-l"></div>` +
      `<div class="tl-cut tl-cut-r"></div>` +
      `<div class="tl-kept"></div>` +
      `<div class="tl-handle l" data-lado="l" title="Cortar início"></div>` +
      `<div class="tl-handle r" data-lado="r" title="Cortar fim"></div>` +
      `<div class="tl-seg-info"><span class="tl-seg-n">${esc(t.n)}</span><span class="tl-seg-txt">${esc((t.narracao || "").slice(0, 70))}</span></div>` +
      `<div class="tl-time"></div>`;
    track.appendChild(seg);
    t._seg = seg;
    const finalizar = () => {
      if (!isFinite(t.dur) || t.dur <= 0) { seg.classList.remove("loading"); seg.classList.add("erro"); return; }
      if (t.fim == null || t.fim > t.dur) t.fim = t.dur;
      if (t.inicio > t.dur - 1.0) t.inicio = Math.max(0, t.dur - 1.0);
      if (t.fim - t.inicio < 1.0) t.fim = Math.min(t.dur, t.inicio + 1.0);
      t.ready = true;
      seg.classList.remove("loading");
      seg.style.flexGrow = String(Math.max(t.dur, 0.1));   // largura proporcional à duração
      posicionarSeg(t);
    };
    if (t.dur > 0) {
      finalizar();   // duração já veio do backend (robusto, sem depender do WebView)
    } else {
      // fallback: lê a duração no cliente (raro, se o backend não mandou)
      const probe = document.createElement("video");
      probe.preload = "metadata"; probe.muted = true; probe.src = t.clipe_url;
      probe.addEventListener("loadedmetadata", () => { t.dur = probe.duration || 0; finalizar(); }, { once: true });
      probe.addEventListener("error", () => { seg.classList.remove("loading"); seg.classList.add("erro"); }, { once: true });
    }
    // Alças arrastáveis
    seg.querySelectorAll(".tl-handle").forEach(h => attachDrag(h, seg, t));
    // Clique no corpo (fora das alças) = pré-ouvir o trecho mantido
    seg.addEventListener("click", (e) => {
      if (e.target.closest(".tl-handle")) return;
      if (seg._dragging || !t.ready) return;
      tocarTrecho(t.clipe_url, t.inicio, t.fim);
    });
  });
}

// Reposiciona alças / região mantida / gordura escurecida a partir de {inicio, fim, dur}.
function posicionarSeg(t) {
  const seg = t._seg; if (!seg || !t.dur) return;
  const li = tlClamp(t.inicio / t.dur * 100, 0, 100);
  const ri = tlClamp(t.fim / t.dur * 100, 0, 100);
  seg.querySelector(".tl-cut-l").style.width = li + "%";
  const cr = seg.querySelector(".tl-cut-r"); cr.style.left = ri + "%";
  const kept = seg.querySelector(".tl-kept"); kept.style.left = li + "%"; kept.style.right = (100 - ri) + "%";
  seg.querySelector(".tl-handle.l").style.left = li + "%";
  seg.querySelector(".tl-handle.r").style.left = ri + "%";
  seg.querySelector(".tl-time").textContent = `${t.inicio.toFixed(1)}s → ${t.fim.toFixed(1)}s`;
}

function attachDrag(handle, seg, t) {
  handle.addEventListener("pointerdown", (e) => {
    if (!t.ready) return;
    e.preventDefault(); e.stopPropagation();
    const lado = handle.dataset.lado;
    seg._dragging = true;
    seg.classList.add("arrastando");
    seg.querySelector(".tl-time").classList.add("show");
    try { handle.setPointerCapture(e.pointerId); } catch (_) { }
    const move = (ev) => {
      const rect = seg.getBoundingClientRect();   // recomputa (flex pode mudar se outro clipe carregar)
      if (!rect.width) return;
      const x = tlClamp((ev.clientX - rect.left) / rect.width, 0, 1);
      const sec = x * t.dur;
      if (lado === "l") t.inicio = tlClamp(sec, 0, t.fim - 1.0);
      else t.fim = tlClamp(sec, t.inicio + 1.0, t.dur);
      posicionarSeg(t);
    };
    const up = (ev) => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      try { handle.releasePointerCapture(ev.pointerId); } catch (_) { }
      seg.classList.remove("arrastando");
      seg.querySelector(".tl-time").classList.remove("show");
      setTimeout(() => { seg._dragging = false; }, 0);   // evita disparar o clique de preview logo após arrastar
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  });
}

// Toca só o trecho mantido (inicio→fim) no modal de vídeo já existente.
function tocarTrecho(src, inicio, fim) {
  const m = $("videoModal"), v = $("videoModalVideo"); if (!m || !v) return;
  v.src = src; m.classList.remove("hidden");
  const onMeta = () => { try { v.currentTime = inicio || 0; } catch (_) { } v.play().catch(() => { }); };
  v.addEventListener("loadedmetadata", onMeta, { once: true });
  if (v._trechoHandler) v.removeEventListener("timeupdate", v._trechoHandler);
  v._trechoHandler = () => { if (fim && v.currentTime >= fim) v.pause(); };
  v.addEventListener("timeupdate", v._trechoHandler);
}

// "Renderizar edição": salva os cortes desse vídeo e re-monta só ele; atualiza a grade.
document.addEventListener("click", (e) => {
  const btn = e.target.closest?.(".tl-render");
  if (btn && btn.dataset.vid) renderizarEdicao(btn.dataset.vid, btn);
});

async function pollVidMontagem(vid) {
  return new Promise((resolve) => {
    const t = setInterval(async () => {
      let d;
      try { d = await api(`/api/status/${encodeURIComponent(state.produto)}/${encodeURIComponent(vid)}`); }
      catch (_) { return; }
      const st = (d && d.status) || {};
      if (!st.em_andamento) { clearInterval(t); resolve(d); }
    }, 1200);
  });
}

async function renderizarEdicao(vid, btn) {
  const st = editorState[vid]; if (!st) return;
  if (st.takes.some(t => !t.ready)) { toast("Aguarde carregar as durações dos clipes…", true); return; }
  const cortes = st.takes.map(t => {
    const ini = Math.max(0, +t.inicio.toFixed(2));
    const fimBase = (t.fim != null ? t.fim : t.dur);
    return { n: t.n, inicio_s: ini, fim_s: Math.max(ini + 1.0, +fimBase.toFixed(2)), remover: false };
  });
  const secEl = btn.closest(".tl-vid");
  const statusEl = secEl?.querySelector(".tl-status");
  btn.disabled = true;
  secEl?.classList.add("renderizando");
  if (statusEl) statusEl.textContent = "Salvando cortes e remontando…";
  try {
    await api(`/api/edicao/${encodeURIComponent(state.produto)}/${encodeURIComponent(vid)}`, { cortes });
    await api(`/api/montar/${encodeURIComponent(state.produto)}/${encodeURIComponent(vid)}`, {});
    await pollVidMontagem(vid);
    if (statusEl) statusEl.textContent = "Pronto ✓";
    await renderEntregas(state.loteVids || []);   // atualiza o preview do vídeo final desse vídeo
    toast("Vídeo remontado ✓");
  } catch (err) {
    if (statusEl) statusEl.textContent = "";
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    secEl?.classList.remove("renderizando");
  }
}

// Prévia do LOTE (etapas Keyframes/Clipes): um PAINEL por vídeo (título + status +
// mini-progresso + grade de cenas), no espírito do review de vídeo único. Estados por
// cena: vazio / gerando (shimmer+spinner) / pronto. Na etapa Clipes, cena pronta faz
// preview do vídeo no hover. Sem isso a tela ficava em branco depois de gerar.
async function renderPreviaLote(vids, containerId, gerando) {
  const box = $(containerId); if (!box) return;
  const lista = (vids && vids.length ? vids : state.loteVids) || [];
  if (!lista.length) { box.innerHTML = ""; return; }
  const clipes = containerId === "loteClPrev";
  try {
    const r = await api(`/api/previa_lote/${encodeURIComponent(state.produto)}?vids=${encodeURIComponent(lista.join(","))}`);
    if ((!state.loteVids || !state.loteVids.length) && (r.vids || []).length) state.loteVids = r.vids;
    box.innerHTML = (r.itens || []).map(v => {
      const cenas = v.cenas || [];
      const total = cenas.length;
      const feito = cenas.filter(c => clipes ? c.clipe_ok : c.keyframe_url).length;
      const rotulo = clipes ? "clipes" : "keyframes";
      const completo = total > 0 && feito >= total;
      const pct = total ? Math.round(100 * feito / total) : 0;
      const estado = completo ? "pronto" : ((gerando || feito > 0) ? "gerando" : "vazio");
      const estadoTxt = completo ? `${total} ${rotulo} ✓` : `${feito}/${total} ${rotulo}`;
      const cenasHtml = cenas.map((c, i) => {
        const nCena = c.n != null ? c.n : i + 1;
        const pronto = clipes ? c.clipe_ok : c.keyframe_url;
        const carregando = gerando && !pronto;
        let cls = "lote-cena";
        if (pronto) cls += " ok";
        if (carregando) cls += " carregando";
        // Na etapa Clipes, cena pronta = vídeo real: poster do keyframe + preview no hover.
        if (clipes && c.clipe_ok && c.clipe_url) {
          cls += " clipe-ok";
          const poster = c.keyframe_url ? ` poster="${c.keyframe_url}"` : "";
          return `<div class="${cls}"><video src="${c.clipe_url}"${poster} muted loop playsinline preload="none"></video><span class="lote-cena-n">${nCena}</span></div>`;
        }
        const img = c.keyframe_url ? `<img src="${c.keyframe_url}" loading="lazy" alt="">` : "";
        const spin = carregando ? `<span class="lote-cena-spin"></span>` : "";
        const ph = (!c.keyframe_url && !carregando) ? `<span class="lote-cena-ph">${nCena}</span>` : "";
        return `<div class="${cls}">${img}${spin}${ph}<span class="lote-cena-n">${nCena}</span></div>`;
      }).join("");
      return `<section class="lote-vid ${estado}" data-vid="${esc(v.vid)}">
        <header class="lote-vid-head">
          <div class="lote-vid-tit"><span class="lote-vid-dot"></span><span class="lote-vid-nome">${esc(v.titulo)}</span></div>
          <div class="lote-vid-meta"><span class="lote-vid-badge ${estado}">${esc(estadoTxt)}</span>
            <button type="button" class="btn mini ghost lote-vid-abrir" data-vid="${esc(v.vid)}" title="Abrir este vídeo pra revisar/editar">Abrir ↗</button></div>
        </header>
        <div class="lote-vid-barra"><div class="lote-vid-barra-fill" style="width:${pct}%"></div></div>
        <div class="lote-cenas">${cenasHtml}</div>
      </section>`;
    }).join("");
  } catch (e) { /* silencioso */ }
}
// SÓ o botão "Abrir" abre o vídeo pra revisar/editar. Clicar numa miniatura/no painel
// NÃO colapsa mais o lote (era o bug: clique acidental na imagem abria 1 vídeo só).
document.addEventListener("click", (e) => {
  const btn = e.target.closest?.(".lote-vid-abrir");
  if (btn && btn.dataset.vid) abrirVideo(btn.dataset.vid);
});
// Preview do clipe no hover (etapa Clipes): toca o vídeo da cena; some o play overlay.
document.addEventListener("mouseover", (e) => {
  const cena = e.target.closest?.(".lote-cena.clipe-ok");
  if (!cena) return;
  const vid = cena.querySelector("video");
  if (vid) { cena.classList.add("tocando"); vid.play().catch(() => {}); }
});
document.addEventListener("mouseout", (e) => {
  const cena = e.target.closest?.(".lote-cena.clipe-ok");
  if (!cena || cena.contains(e.relatedTarget)) return;
  const vid = cena.querySelector("video");
  if (vid) { cena.classList.remove("tocando"); vid.pause(); vid.currentTime = 0; }
});

// ---- Elenco POR VÍDEO (casting): cada roteiro escolhe quem aparece ----
let avataresCast = [];   // avatares utilizáveis (com fotos); preenchido por carregarAvatares
function fmtMulti(formato) { return !!(fmtvCat.find(c => c.id === formato) || {}).multi_pessoa; }
function fmtLabelCast(formato) { return (fmtvCat.find(c => c.id === formato) || {}).label || formato || "vídeo"; }
function castingDefault(formato) { return fmtMulti(formato) ? "gerado" : "auto"; }
function opcoesCasting(multi) {
  const ugc = avataresCast.filter(a => (a.tipo || "avatar") !== "influenciador");
  const exp = avataresCast.filter(a => a.tipo === "influenciador");
  const optExperts = exp.map(a => `<option value="influenciador::${esc(a.nome)}">${esc(a.nome)}</option>`).join("");
  if (multi) {
    // Multi-pessoa: avatares de casa bugariam a cena -> elenco gerado. Expert só como autoridade.
    return `<option value="gerado">Elenco gerado (recomendado)</option>` +
      (exp.length ? `<optgroup label="Convidar expert (autoridade)">${optExperts}</optgroup>` : "");
  }
  return `<option value="auto">Automático (IA escolhe UGC)</option>` +
    (ugc.length ? `<optgroup label="Avatares UGC">${ugc.map(a => `<option value="avatar::${esc(a.nome)}">${esc(a.nome)}</option>`).join("")}</optgroup>` : "") +
    (exp.length ? `<optgroup label="Experts oficiais">${optExperts}</optgroup>` : "") +
    `<option value="">Sem pessoa (produto + mãos)</option>`;
}
function renderElenco() {
  const box = $("elencoTabela"); if (!box) return;
  const roteiros = state.copiesSelecionadas || [];
  if (!roteiros.length) { box.innerHTML = `<p class="dica">Escolha roteiros na etapa Copy primeiro.</p>`; return; }
  box.innerHTML = roteiros.map((o, i) => {
    const multi = fmtMulti(o.formato);
    if (o.castingAvatar === undefined) o.castingAvatar = castingDefault(o.formato);
    return `<div class="elenco-row">
      <div class="elenco-info"><strong>${esc(o.titulo || `Roteiro ${i + 1}`)}</strong>
        <span class="elenco-badge">${esc(fmtLabelCast(o.formato))}${multi ? " · 2 pessoas" : ""}</span></div>
      <label class="elenco-pick"><span class="elenco-lbl">Quem aparece</span>
        <select class="elenco-sel" data-i="${i}">${opcoesCasting(multi)}</select></label>
    </div>`;
  }).join("");
  box.querySelectorAll(".elenco-sel").forEach(sel => {
    sel.value = roteiros[Number(sel.dataset.i)].castingAvatar;
    sel.addEventListener("change", () => { roteiros[Number(sel.dataset.i)].castingAvatar = sel.value; });
  });
}
function renderRoteirosEscolhidos() { renderElenco(); }   // a tela "novo" agora é o ELENCO por vídeo

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

// Etapa a abrir: decide pelo PROGRESSO REAL do vídeo (existe keyframe? clipe? montagem?),
// não só pela string `estado`. No fluxo de LOTE os keyframes são gerados sem aprovar o
// roteiro, então `estado` fica "rascunho" mesmo com 6/6 keyframes prontos — e o vídeo caía
// de volta na etapa Roteiro (sem acesso a regerar/refinar cena). O que existe manda.
function etapaDoVideo(dado) {
  const est = (dado && dado.estado) || "rascunho";
  if (est === "montado") return "final";
  const cenas = (dado && dado.cenas) || [];
  const temClipe = cenas.some(c => c.clipe && (c.clipe.url || c.clipe.gerado));
  if (est === "clipes_gerados" || temClipe) return "clipes";
  const temKf = cenas.some(c => c.keyframe && (c.keyframe.url || c.keyframe.arquivo));
  if (est === "roteiro_aprovado" || est === "keyframes_aprovados" || temKf) return "keyframes";
  return "roteiro";
}

async function abrirVideo(vid) {
  state.lote = false;   // abrir 1 vídeo sai do modo lote (mostra os controles de vídeo único)
  state.vid = vid;
  $("selVideo").value = vid;
  pararPoll();
  await atualizar();
  mostrar(etapaDoVideo(state.ultimo));
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
          ${((dado.tipo_produto || state.tipoProduto) === "digital"
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
    `<div class="msg assistente pensando"><span class="thinking-orb"></span><span class="thinking-label">roteirista pensando</span></div>`);
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

function htmlQualidade(c) {
  const q = c.qualidade || {};
  const motivos = (q.motivos || []).map(m => esc(m.detalhe || m.codigo || String(m))).join("; ");
  const estado = q.estado || "pendente";
  let aviso = "";
  if (["gerando", "regenerando", "reprovado_regenerando"].includes(estado)) {
    aviso = `<div class="qa-aviso trabalhando"><b>${estado === "gerando" ? "Analisando geração" : "Regenerando automaticamente"}</b>`
      + ` · tentativa ${Number(q.tentativa || 1)}${motivos ? `<br>${motivos}` : ""}</div>`;
  } else if (estado === "reprovado") {
    aviso = `<div class="qa-aviso erro"><b>Reprovado pelo controle de qualidade</b>${motivos ? `<br>${motivos}` : ""}</div>`;
  } else if (estado === "aprovado") {
    aviso = `<div class="qa-aviso aprovado">✓ Controle de qualidade aprovado${q.descartes ? ` após ${q.descartes} descarte(s)` : ""}</div>`;
  }
  const descartados = c.descartados || [];
  if (!descartados.length) return aviso;
  const galeria = descartados.map(x => {
    const razoes = (x.motivos || []).map(m => esc(m.detalhe || m.codigo || String(m))).join("; ");
    const media = x.url ? (x.tipo === ".mp4"
      ? `<video src="${x.url}" controls playsinline preload="metadata"></video>`
      : `<img src="${x.url}" loading="lazy">`) : "";
    return `<div class="qa-descarte">${media}<small>${esc(x.tentativa)} · ${esc(x.etapa || "")}</small><span>${razoes}</span></div>`;
  }).join("");
  return aviso + `<details class="qa-descartados"><summary>Ver ${descartados.length} tentativa(s) descartada(s)</summary><div class="qa-grade">${galeria}</div></details>`;
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
  const sigK = JSON.stringify(cenas.map(c => [c.n, c.keyframe.url, c.keyframe.aprovado, c.qualidade, (c.descartados || []).length]))
    + "|" + gerando + "|" + (st.atuais || []).join(",") + "|" + (st.erros || []).length;
  if (sigK !== state._sigKf) {
   state._sigKf = sigK;
   $("gradeKeyframes").innerHTML = cenas.map(c => {
    const emVoo = gerando && (st.atuais || []).includes(`cena_${String(c.n).padStart(2, "0")}`);
    const midia = c.keyframe.url ? `<img src="${c.keyframe.url}">`
      : emVoo ? `<div class="spinner"></div>` : "sem keyframe";
    const erroKf = (st.erros || []).find(e => e.item === `cena_${String(c.n).padStart(2, "0")}`);
    const q = c.qualidade || {};
    const falhou = !c.keyframe.url && !emVoo && (erroKf || q.estado === "reprovado");
    const temDescarte = (c.descartados || []).length > 0;
    const botoes = c.keyframe.url ? `
      <button class="btn mini ghost" data-acao="refinar">Refinar</button>
      <button class="btn mini ghost" data-acao="regerar">Gerar de novo</button>`
      : falhou ? `
      <button class="btn mini primary" data-acao="regerar-falha">Gerar de novo</button>
      ${temDescarte ? `<button class="btn mini ghost" data-acao="aceitar">Aceitar assim mesmo</button>` : ""}`
      : "";
    const extra = (erroKf && st.etapa === "keyframes" ? `<div class="erro">${esc(erroKf.erro)}</div>` : "") + htmlQualidade(c);
    return cardCena(c, midia, botoes, extra);
   }).join("");
  }

  // Os keyframes presentes na grade já contam como aprovados: basta estarem prontos.
  const prontas = cenas.filter(c => c.keyframe.url).length;
  const todasProntas = cenas.length && prontas === cenas.length;
  const btn = $("btnGerarClipes");
  if (!todasProntas) {
    btn.innerHTML = `Gere as keyframes (${prontas}/${cenas.length})`;
  } else {
    const motor = $("selMotor").value;
    const custo = motor === "veo" ? "(grátis, no crédito)" :
      motor === "local" ? "(grátis, lento)" :
      dado.estimativa_usd ? `(~US$${dado.estimativa_usd.toFixed(2)})` : "";
    btn.innerHTML = `Gerar clipes <span id="custoEst">${custo}</span>`;
  }
  btn.disabled = !todasProntas || (st.em_andamento && ["clipes", "montagem"].includes(st.etapa));
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
    if (btn.dataset.acao === "regerar") {
      await api(`/api/refinar_keyframe${base}/${n}`, {});
      toast("Gerando a cena de novo…");
    }
    if (btn.dataset.acao === "regerar-falha") {
      // Cena que reprovou (sem keyframe): gera do zero de novo.
      await api(`/api/gerar_keyframes/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}`, { ns: [Number(n)] });
      toast("Gerando a cena de novo…");
    }
    if (btn.dataset.acao === "aceitar") {
      await api(`/api/aceitar_keyframe${base}/${n}`, {});
      toast("Cena aceita ✓");
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
  const sig = JSON.stringify(cenas.map(c => [c.n, c.tipo, c.clipe.gerado, c.clipe.url, c.clipe.erro, c.instrucao_clipe, c.qualidade, (c.descartados || []).length]))
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
      const extra = (c.clipe.erro ? `<div class="erro">${esc(c.clipe.erro)}</div>` : "") + htmlQualidade(c);
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
        ${htmlInsertTake(c)}
      </article>`;
    }).join("")}</div>
    <button type="button" class="btn primary" onclick="aplicarCortes()">Aplicar cortes e remontar</button>
  </div>`;
}

/* ---------------------------------------------------------------- inserts (B-roll/motion) */
function htmlInsertTake(c) {
  const ins = c.insert || {};
  const img = ins.imagem || {};
  const clp = ins.clipe || {};
  return `<div class="insert-bloco">
    <label><input class="insert-ativo" type="checkbox" ${ins.ativo ? "checked" : ""}
      onchange="toggleInsertAtivo(${c.n}, this.checked)"> Usar insert (B-roll/motion) nesta cena</label>
    <label>Conceito <input class="insert-conceito" type="text" placeholder="o que o insert deve ilustrar (ex: a dor de perder cliente por demora)"
      value="${esc(ins.conceito || "")}" onblur="salvarDirecaoInsert(${c.n})"></label>
    <div class="insert-acoes">
      <button type="button" class="btn mini ghost" onclick="gerarInsertImagem(${c.n})">Gerar imagem</button>
      ${img.url ? `<img class="insert-preview" src="${img.url}" alt="insert cena ${c.n}">
        <label><input class="insert-aprovado" type="checkbox" ${img.aprovado ? "checked" : ""}
          onchange="aprovarInsert(${c.n}, this.checked)"> Aprovar imagem</label>` : ""}
      <button type="button" class="btn mini ghost" ${img.aprovado ? "" : "disabled"} onclick="gerarInsertClipe(${c.n})">Animar (Veo)</button>
      ${clp.gerado ? `<span class="ok-insert">✓ clipe pronto</span>` : ""}
    </div>
  </div>`;
}

async function toggleInsertAtivo(n, ativo) {
  try {
    await api(`/api/insert/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}/${n}`, { ativo });
    toast(ativo ? "Insert ativado nesta cena." : "Insert desativado nesta cena.");
  } catch (e) { toast(e.message, true); }
}

async function salvarDirecaoInsert(n) {
  const el = document.querySelector(`#editorCortes .corte-take[data-n="${n}"] .insert-conceito`);
  try {
    await api(`/api/insert/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}/${n}`,
      { conceito: el ? el.value : "" });
  } catch (e) { toast(e.message, true); }
}

async function gerarInsertImagem(n) {
  try {
    await api(`/api/gerar_insert_imagem/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}/${n}`, {});
    toast("Gerando imagem do insert…");
  } catch (e) { toast(e.message, true); }
}

async function aprovarInsert(n, aprovado) {
  try {
    await api(`/api/aprovar_insert/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}/${n}`, { aprovado });
    toast(aprovado ? "Imagem do insert aprovada." : "Aprovação removida.");
  } catch (e) { toast(e.message, true); }
}

async function gerarInsertClipe(n) {
  try {
    await api(`/api/gerar_insert_clipe/${encodeURIComponent(state.produto)}/${encodeURIComponent(state.vid)}/${n}`, {});
    toast("Animando o insert no Veo…");
  } catch (e) { toast(e.message, true); }
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
      const versoes = dado.bruto_url ? `<div class="versoes-video"><a class="btn mini ghost" href="${dado.bruto_url}" download="video-bruto.mp4">Baixar bruto</a>`
        + (dado.ajustado_url ? `<a class="btn mini ghost" href="${dado.ajustado_url}" download="video-ajustado.mp4">Baixar ajustado</a>` : "") + `</div>` : "";
      p.innerHTML = `<video src="${dado.final_url}" data-src="${dado.final_url}" controls></video>${versoes}${htmlEditorCortes(dado.cenas)}`;
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
  avataresCast = avs.filter(a => a.referencias.length);   // usados pelo elenco por vídeo
  renderElenco();
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
  const ugc = avs.filter(a => (a.tipo || "avatar") === "avatar").map(card).join("");
  const experts = avs.filter(a => a.tipo === "influenciador").map(card).join("");
  const semPessoa = `<button type="button" class="avatar-pick none active" data-avatar=""><span class="avatar-thumb avatar-none"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="8.5" r="3.2"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/><path d="M3.5 3.5l17 17"/></svg></span><span class="avatar-pick-name">Sem pessoa</span><span class="avatar-pick-type">só produto + mãos</span></button>`;
  box.innerHTML =
    `<div class="avatar-grupo"><div class="avatar-grupo-titulo">Avatares UGC</div>` +
    `<div class="avatar-grid">${semPessoa}${ugc || "<span class='mini-label'>Nenhum avatar UGC gerado.</span>"}</div></div>` +
    `<div class="avatar-grupo"><div class="avatar-grupo-titulo">Experts oficiais</div>` +
    `<div class="avatar-grid">${experts || "<span class='mini-label'>Nenhum expert cadastrado.</span>"}</div></div>`;
  box.querySelectorAll(".avatar-pick").forEach(btn => btn.addEventListener("click", () => {
    state.avatar = btn.dataset.avatar;
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

/* ---------------------------------------------------------- Formatos de vídeo */
let fmtvCat = [
  { id: "padrao", label: "Padrão (UGC)", desc: "O fluxo atual: UGC/depoimento e nativo, uma pessoa falando pra câmera." },
];
let fmtvSel = new Set();
const fmtvLabel = (id) => (fmtvCat.find(x => x.id === id) || {}).label || id;
const fmtvOrd = () => fmtvCat.map(c => c.id).filter(id => fmtvSel.has(id));

function fmtvAtualizarBtn() {
  const ativo = state.formato || "padrao";
  const n = (state.formatosVideo || [ativo]).length;
  $("fmtvBtnLbl").textContent = fmtvLabel(ativo) + (n > 1 ? ` +${n - 1}` : "");
}

async function carregarFormatosVideo() {
  if (!state.produto) { state.formato = "padrao"; state.formatosVideo = ["padrao"]; fmtvAtualizarBtn(); return; }
  try {
    const d = await api(`/api/formatos_video/${encodeURIComponent(state.produto)}`);
    if (d.catalogo && d.catalogo.length) fmtvCat = d.catalogo;
    state.formatosVideo = (d.formatos && d.formatos.length) ? d.formatos : ["padrao"];
    state.formato = state.formatosVideo[0];
  } catch (e) { state.formato = "padrao"; state.formatosVideo = ["padrao"]; }
  fmtvAtualizarBtn();
}

function fmtvRender() {
  const ativo = fmtvOrd()[0];
  $("fmtvLista").innerHTML = fmtvCat.map(c => {
    const marcado = fmtvSel.has(c.id);
    const ehAtivo = marcado && c.id === ativo;
    return `<label class="fmtv-opt${marcado ? " sel" : ""}" data-id="${c.id}">
      <input type="checkbox" ${marcado ? "checked" : ""}>
      <span class="fmtv-txt"><span class="fmtv-nome">${esc(c.label)}${ehAtivo ? '<span class="fmtv-ativo">ativo</span>' : ""}</span>
      <span class="fmtv-desc">${esc(c.desc || "")}</span></span></label>`;
  }).join("");
  const salvar = $("fmtvSalvar");
  if (salvar) salvar.disabled = fmtvSel.size === 0;
}

function fmtvAbrir() {
  if (!state.produto) return toast("Selecione um produto primeiro.", true);
  fmtvSel = new Set(state.formatosVideo || ["padrao"]);
  fmtvRender();
  $("fmtvOverlay").hidden = false;
}
const fmtvFechar = () => { $("fmtvOverlay").hidden = true; };
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && $("fmtvOverlay") && !$("fmtvOverlay").hidden) fmtvFechar();
});

$("btnFormatosVideo")?.addEventListener("click", fmtvAbrir);
$("fmtvFechar")?.addEventListener("click", fmtvFechar);
$("fmtvCancelar")?.addEventListener("click", fmtvFechar);
$("fmtvOverlay")?.addEventListener("click", e => { if (e.target === $("fmtvOverlay")) fmtvFechar(); });
$("fmtvLista")?.addEventListener("change", e => {
  const lab = e.target.closest(".fmtv-opt"); if (!lab) return;
  if (e.target.checked) fmtvSel.add(lab.dataset.id); else fmtvSel.delete(lab.dataset.id);
  fmtvRender();
});
$("fmtvSalvar")?.addEventListener("click", async () => {
  let ord = fmtvOrd(); if (!ord.length) ord = ["padrao"];
  try {
    const r = await api(`/api/formatos_video/${encodeURIComponent(state.produto)}`, { formatos: ord });
    state.formatosVideo = (r.formatos && r.formatos.length) ? r.formatos : ord;
    state.formato = state.formatosVideo[0];
  } catch (e) { state.formatosVideo = ord; state.formato = ord[0]; }
  fmtvAtualizarBtn(); fmtvFechar();
  toast("Formato ativo: " + fmtvLabel(state.formato));
});
