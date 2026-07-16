// Criativos Express — lógica do app desktop

const $ = (s) => document.querySelector(s);
const el = (id) => document.getElementById(id);

let produto = null;
let sessionId = null;     // sessão do chat de copies (multi-turno)
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

// ----------------------------------------------------------- Produtos ------
async function carregarProdutos() {
  const lista = await (await fetch("/api/produtos")).json();
  const ul = el("produtos");
  ul.innerHTML = "";
  if (!lista.length) {
    ul.innerHTML = '<li style="opacity:.6;cursor:default">Nenhum produto</li>';
    return;
  }
  lista.forEach((p) => {
    const li = document.createElement("li");
    li.dataset.nome = p.nome;
    const flags = [];
    if (p.tem_referencia) flags.push("📷");
    if (p.tem_copies) flags.push("✍️");
    if (p.tem_prompts) flags.push("🎨");
    li.innerHTML = `<span>${p.nome}</span><span class="badge">${flags.join(" ")}</span>`;
    li.addEventListener("click", () => selecionarProduto(p.nome));
    ul.appendChild(li);
  });
}

function selecionarProduto(nome) {
  produto = nome;
  sessionId = null;
  document.querySelectorAll(".produtos li").forEach((l) =>
    l.classList.toggle("ativo", l.dataset.nome === nome));
  el("tituloProduto").textContent = nome;
  el("subProduto").textContent = "pronto para trabalhar as copies";
  el("chat").innerHTML = "";
  addMsg("ai", `Vamos criar os criativos de "${nome}". Me diga o que você quer: quantas copies, foco/ângulos, ocasião... Eu proponho os ângulos e a gente refina.`);
  el("listaPrompts").innerHTML = "";
  el("grade").innerHTML = "";
  el("progresso").style.display = "none";
  trocarStep("copies");
  carregarStatus();
}

// --------------------------------------------------------------- Steps -----
el("steps").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  trocarStep(b.dataset.step);
});

function trocarStep(step) {
  if (!produto) { toast("Selecione um produto primeiro"); return; }
  stepAtual = step;
  document.querySelectorAll("#steps button").forEach((b) =>
    b.classList.toggle("sel", b.dataset.step === step));
  document.querySelectorAll(".step").forEach((s) => s.classList.remove("ativo"));
  el("step-" + step).classList.add("ativo");
  if (step === "prompts") carregarPrompts();
  if (step === "criativos") carregarStatus();
}

// ---------------------------------------------------------------- Chat -----
function addMsg(tipo, texto) {
  const div = document.createElement("div");
  div.className = "msg " + tipo;
  div.textContent = texto;
  el("chat").appendChild(div);
  el("chat").scrollTop = el("chat").scrollHeight;
  return div;
}

async function enviar() {
  if (!produto) { toast("Selecione um produto"); return; }
  const inp = el("chatInput");
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = "";
  inp.style.height = "auto";
  addMsg("user", msg);
  const pensando = addMsg("ai pensando", "pensando…");
  el("btnEnviar").disabled = true;
  try {
    const r = await (await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ produto, mensagem: msg, session_id: sessionId, modelo: modelo() }),
    })).json();
    pensando.remove();
    if (r.ok) {
      sessionId = r.session_id;
      addMsg("ai", r.resposta || "(sem resposta)");
    } else {
      addMsg("ai", "⚠ Erro: " + (r.erro || "falha"));
    }
  } catch (e) {
    pensando.remove();
    addMsg("ai", "⚠ Erro de conexão.");
  }
  el("btnEnviar").disabled = false;
}

el("btnEnviar").addEventListener("click", enviar);
el("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); }
});
el("chatInput").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

el("btnSalvarCopies").addEventListener("click", async () => {
  if (!sessionId) { toast("Converse e aprove as copies primeiro"); return; }
  toast("Exportando copies…");
  const instr = "Gere AGORA o conteúdo final do arquivo copies.md com TODAS as copies aprovadas, "
    + "organizadas por ângulo (headline, corpo, CTA). Responda apenas com o markdown, sem comentários.";
  try {
    const r = await (await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ produto, mensagem: instr, session_id: sessionId, modelo: modelo() }),
    })).json();
    if (!r.ok) { toast("Erro ao exportar"); return; }
    await fetch(`/api/copies/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conteudo: r.resposta }),
    });
    toast("Copies salvas ✓");
    carregarProdutos();
  } catch (e) { toast("Erro ao salvar"); }
});

// ------------------------------------------------------------- Prompts -----
async function carregarPrompts() {
  const dados = await (await fetch(`/api/prompts/${produto}`)).json();
  renderPrompts(dados);
  el("promptsInfo").textContent = dados.length ? `${dados.length} criativos` : "nenhum prompt ainda";
}

function renderPrompts(dados) {
  const box = el("listaPrompts");
  box.innerHTML = "";
  dados.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.id = p.id || `criativo_${String(i + 1).padStart(2, "0")}`;
    card.innerHTML = `
      <div class="meta">
        <span class="tag">${card.dataset.id}</span>
        <span class="tag" style="background:rgba(48,209,88,.16);color:#30d158">${p.angulo || "ângulo"}</span>
        <h4>${(p.copy || "").slice(0, 90)}</h4>
      </div>
      <textarea data-campo="prompt">${p.prompt || ""}</textarea>`;
    box.appendChild(card);
  });
}

el("btnGerarPrompts").addEventListener("click", async () => {
  if (!produto) return;
  el("btnGerarPrompts").disabled = true;
  el("promptsInfo").textContent = "gerando prompts com o Claude…";
  try {
    const r = await (await fetch(`/api/gerar_prompts/${produto}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modelo: modelo() }),
    })).json();
    if (r.ok) { renderPrompts(r.prompts); el("promptsInfo").textContent = `${r.prompts.length} criativos`; toast("Prompts gerados ✓"); carregarProdutos(); }
    else { el("promptsInfo").textContent = "erro: " + (r.erro || ""); }
  } catch (e) { el("promptsInfo").textContent = "erro de conexão"; }
  el("btnGerarPrompts").disabled = false;
});

el("btnSalvarPrompts").addEventListener("click", async () => {
  const cards = [...document.querySelectorAll("#listaPrompts .card")];
  const atuais = await (await fetch(`/api/prompts/${produto}`)).json();
  const prompts = cards.map((c, i) => ({
    ...(atuais[i] || {}),
    id: c.dataset.id,
    prompt: c.querySelector('[data-campo="prompt"]').value,
  }));
  await fetch(`/api/prompts/${produto}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompts }),
  });
  toast("Prompts salvos ✓");
});

// ------------------------------------------------------------ Criativos ----
el("btnGerarImagens").addEventListener("click", async () => {
  if (!produto) return;
  const r = await (await fetch(`/api/gerar_imagens/${produto}`, { method: "POST" })).json();
  if (!r.ok) { toast(r.erro || "erro"); return; }
  el("progresso").style.display = "block";
  iniciarPolling();
});

function iniciarPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(carregarStatus, 1500);
}

async function carregarStatus() {
  if (!produto) return;
  let s;
  try { s = await (await fetch(`/api/status/${produto}`)).json(); } catch (e) { return; }
  const total = s.total || 0, feitos = s.feitos || 0;
  if (total > 0) el("progresso").style.display = "block";
  el("progBar").style.width = (total ? Math.round((feitos / total) * 100) : 0) + "%";
  el("progContagem").textContent = `${feitos} / ${total}`;
  if (s.em_andamento) {
    el("progStatus").innerHTML = `gerando: <span class="atual">${s.atual || "…"}</span>`;
    el("btnGerarImagens").disabled = true;
  } else {
    el("progStatus").textContent = feitos && feitos === total ? "concluído ✓" : "";
    el("btnGerarImagens").disabled = false;
    if (pollTimer && !s.em_andamento && feitos >= total && total > 0) { clearInterval(pollTimer); pollTimer = null; }
  }
  // grade
  const grade = el("grade");
  const existentes = new Set([...grade.querySelectorAll("img")].map((i) => i.dataset.arq));
  (s.arquivos || []).forEach((arq) => {
    if (existentes.has(arq)) return;
    const src = `/criativos/${produto}/${encodeURIComponent(arq)}?t=${Date.now()}`;
    const d = document.createElement("div");
    d.className = "thumb";
    d.innerHTML = `<img data-arq="${arq}" src="${src}"><div class="rod"><span>${arq}</span><a href="${src}" download>baixar</a></div>`;
    grade.appendChild(d);
  });
  el("criativosInfo").textContent = total ? "" : "gere os prompts antes, depois clique em Gerar criativos";
  const erros = s.erros || [];
  el("progErros").textContent = erros.length ? "⚠ " + erros.map((e) => `${e.id}: ${e.erro.split("\n")[0]}`).join("\n") : "";
}

el("btnRecarregar").addEventListener("click", carregarProdutos);

// Início
carregarProdutos();
