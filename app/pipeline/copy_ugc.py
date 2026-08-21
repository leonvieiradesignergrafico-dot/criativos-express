"""Chat de copy/roteiro para o fluxo de vídeo UGC."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from workspace import (atomic_write_json, product_dir, ler_json, pessoa_dir,
                       BUNDLE_DIR, AVATARES, INFLUENCIADORES)
from app.pipeline import formatos_video as fv

# Prompt = asset só-leitura (vem do bundle quando congelado); avatares/influenciadores
# = dados do usuário (vão pra config/ via workspace). Não usar parents[2], que no .exe
# congelado apontaria pro bundle temporário.
CEREBRO = (BUNDLE_DIR / "app" / "prompts" / "copy_ugc.md").read_text(encoding="utf-8")


def _bridge(modelo: str | None):
    if modelo and str(modelo).lower().startswith("gpt"):
        from app import codex_text_bridge as bridge
    else:
        from app import claude_bridge as bridge
    return bridge


def _chat_path(produto: str) -> Path:
    return product_dir(produto) / "output" / "ugc_copy_chat.json"


def carregar_chat(produto: str) -> dict:
    dados = ler_json(_chat_path(produto)) or {}
    return dados if isinstance(dados, dict) else {}


def _personas() -> str:
    linhas = []
    for pasta, rotulo in ((AVATARES, "avatar UGC"),
                          (INFLUENCIADORES, "expert/influenciador oficial")):
        if pasta.exists():
            for d in sorted(pasta.iterdir()):
                perfil = d / "perfil.md"
                if d.is_dir() and perfil.exists():
                    linhas.append(f"- {rotulo} {d.name}: {perfil.read_text(encoding='utf-8', errors='replace')[:500]}")
    return "\n".join(linhas) or "(nenhum avatar UGC cadastrado ainda)"


def _contexto_produto(produto: str, limite: int = 30000) -> str:
    """Contexto comercial real; config sozinho costuma ser rascunho incompleto."""
    p = product_dir(produto)
    candidatos = [p / "config.md", p / "contexto" / "pagina-vendas.txt",
                  p / "contexto" / "aprendizado.md", p / "contexto" / "verdade_visual.md"]
    partes, usados = [], 0
    for f in candidatos:
        if not f.exists() or usados >= limite:
            continue
        txt = f.read_text(encoding="utf-8", errors="replace").strip()
        if not txt:
            continue
        trecho = txt[:limite - usados]
        partes.append(f"## {f.name}\n{trecho}")
        usados += len(trecho)
    return "\n\n".join(partes)


def _extrair(texto: str) -> list[dict]:
    blocos = re.findall(r"```(?:ugc-json|json)?\s*(.*?)```", texto or "", re.S | re.I)
    candidatos = list(reversed(blocos)) + [texto or ""]
    for bruto in candidatos:
        try:
            dado = json.loads(bruto.strip())
        except Exception:
            continue
        if isinstance(dado, dict):
            dado = dado.get("roteiros") or dado.get("opcoes") or dado.get("copies")
        if isinstance(dado, list):
            return [x for x in dado if isinstance(x, dict)]
    return []


def _resumo_resposta(texto: str) -> str:
    """Texto curto para o chat; o bloco JSON fica apenas para o parser interno."""
    limpo = re.sub(r"```(?:ugc-json|json)?\s*.*?```", "", texto or "", flags=re.S | re.I).strip()
    return limpo or "Encontrei algumas opções de roteiro. Escolha uma ou mais abaixo."


def conversar(produto: str, mensagem: str, modelo: str | None, modo: str,
              session_id: str | None = None, formato: str = "padrao") -> dict:
    contexto = _contexto_produto(produto)
    # Formato de vídeo (padrao/fala_faz/top5/...): troca o cérebro de copy e injeta
    # a diretiva do formato. "padrao" mantém o comportamento atual (CEREBRO base).
    fmt = formato if fv.existe(formato) else "padrao"
    cerebro = fv.copy_cerebro(fmt)
    pedido = f"""CONTEXTO DO PRODUTO ({produto}):
{contexto or '(sem configuração)'}

PERSONAS/AVATARES DISPONÍVEIS:
{_personas()}

MODO ESCOLHIDO: {modo}{fv.diretiva(fmt)}

PEDIDO DO USUÁRIO:
{mensagem}

Gere opções de roteiro de vídeo adequadas a este produto, persona, promessa e contexto. Não invente
características, provas, resultados ou ingredientes que não estejam no contexto. Se faltar informação,
faça uma suposição conservadora ou sinalize o ponto no campo observacao.

Não invente nomes próprios para personagens ou personas. O campo persona deve ser descritivo e genérico
(por exemplo, "criador que grava em casa"), nunca "Vini", "Diego" ou outro nome de avatar. O avatar
será escolhido pelo usuário depois; portanto, não amarre nenhuma opção a uma pessoa específica.
"""
    historico = carregar_chat(produto)
    msgs = (historico.get("mensagens") or [])[-30:]
    # Retry: às vezes o modelo devolve o bloco fora do formato (drift transitório). Uma 2ª
    # tentativa FRESH (sem session) quase sempre resolve — antes isso virava erro pro usuário.
    res, opcoes = {}, []
    for tent in range(2):
        sess = (session_id or historico.get("session_id")) if tent == 0 else None
        res = _bridge(modelo).conversar(pedido, session_id=sess, modelo=modelo,
                                        system_prompt=cerebro, timeout=300)
        opcoes = _extrair(res.get("resposta", ""))
        if opcoes:
            break
    if not opcoes:
        raise RuntimeError("O roteirista não devolveu opções em formato válido.")
    historico.update({"session_id": res.get("session_id"), "modo": modo})
    historico["mensagens"] = (msgs + [{"papel": "usuario", "texto": mensagem},
                                      {"papel": "assistente", "texto": res.get("resposta", "")}])[-40:]
    atomic_write_json(_chat_path(produto), historico)
    return {"resposta": _resumo_resposta(res.get("resposta", "")), "opcoes": opcoes,
            "session_id": res.get("session_id")}


# --------------------------------------------------------------- geração paralela
# Ângulos de venda DISTINTOS. Numa chamada única o modelo garante variedade sozinho;
# ao paralelizar (1 worker = 1 opção) precisamos forçar essa diversidade dando a cada
# worker um ângulo diferente, senão as opções saem repetidas/parecidas.
_ANGULOS = [
    "a DOR/problema imediato que o público sente hoje",
    "a PROVA/demonstração concreta do resultado (antes e depois)",
    "quebrar a principal OBJEÇÃO (preço, ceticismo, falta de tempo)",
    "uma HISTÓRIA pessoal de transformação em 1ª pessoa",
    "a COMPARAÇÃO com a alternativa que a pessoa já usa hoje",
    "a CURIOSIDADE do mecanismo único (como funciona por dentro)",
    "URGÊNCIA/escassez e o gatilho da oferta",
    "IDENTIFICAÇÃO com a rotina e o dia a dia do público",
]


def _pedido_uma(produto: str, contexto: str, mensagem: str, modo: str,
                fmt: str, angulo: str) -> str:
    """Monta o pedido de UMA opção comprometida com um ângulo específico."""
    return f"""CONTEXTO DO PRODUTO ({produto}):
{contexto or '(sem configuração)'}

PERSONAS/AVATARES DISPONÍVEIS:
{_personas()}

MODO ESCOLHIDO: {modo}{fv.diretiva(fmt)}

PEDIDO DO USUÁRIO:
{mensagem}

Gere EXATAMENTE UMA opção de roteiro (um único item na lista de saída). Comprometa a
opção inteira (gancho, promessa, payoff e roteiro) com ESTE ângulo específico: {angulo}.
Não misture com outros ângulos nem devolva variações genéricas.

Não invente características, provas, resultados ou ingredientes que não estejam no contexto.
Se faltar informação, faça uma suposição conservadora ou sinalize no campo observacao.

Não invente nomes próprios para personagens ou personas. O campo persona deve ser descritivo
e genérico (por exemplo, "criador que grava em casa"), nunca um nome de avatar. O avatar será
escolhido pelo usuário depois; não amarre a opção a uma pessoa específica.
"""


def _uma_opcao(produto: str, contexto: str, mensagem: str, modelo: str | None,
               fmt: str, angulo: str) -> dict:
    """Worker: produz UMA opção pro formato/ângulo dados. Sem session_id (cada worker
    é uma conversa independente; reaproveitar sessão serializaria/corromperia entre
    threads). Retry 1x contra throttle transitório."""
    modo = fv.modo_do_formato(fmt)
    cerebro = fv.copy_cerebro(fmt)
    pedido = _pedido_uma(produto, contexto, mensagem, modo, fmt, angulo)
    ultimo: Exception | None = None
    for _tentativa in range(2):
        try:
            res = _bridge(modelo).conversar(pedido, session_id=None, modelo=modelo,
                                            system_prompt=cerebro, timeout=300)
            ops = _extrair(res.get("resposta", ""))
            if ops:
                return ops[0]
            ultimo = RuntimeError("worker não devolveu opção em formato válido")
        except Exception as e:  # noqa: BLE001
            ultimo = e
        time.sleep(2)
    raise ultimo or RuntimeError("worker falhou sem detalhe")


def _resumo_lote(opcoes: list) -> str:
    n = len(opcoes)
    if not n:
        return "Não consegui gerar opções agora. Tente de novo."
    return f"Gerei {n} opção(ões) de roteiro. Escolha uma ou mais abaixo."


def gerar_opcoes_paralelo(produto: str, mensagem: str, modelo: str | None,
                          plano: list[str]) -> dict:
    """Gera UMA opção por item de `plano` (lista de formato ids), EM PARALELO, cada
    worker com um ângulo distinto (garante diversidade). Serve tanto para N opções do
    MESMO formato (plano = [fmt]*N) quanto para o mix de formatos (plano = distribuição).

    Devolve no MESMO formato de conversar(): {resposta, opcoes, session_id, erros}.
    Erros por item não derrubam os demais — voltam listados em `erros`."""
    plano = [f for f in (plano or []) if f]
    if not plano:
        return {"resposta": _resumo_lote([]), "opcoes": [], "session_id": None, "erros": []}
    contexto = _contexto_produto(produto)                 # lido 1x, compartilhado
    n = len(plano)
    tarefas = []
    for i, fmt in enumerate(plano):
        fmt = fmt if fv.existe(fmt) else "padrao"
        tarefas.append((i, fmt, _ANGULOS[i % len(_ANGULOS)]))
    opcoes: list = [None] * n                             # preserva a ordem do plano
    erros: list = []
    with ThreadPoolExecutor(max_workers=min(n, 6)) as ex:
        fut = {ex.submit(_uma_opcao, produto, contexto, mensagem, modelo, fmt, ang): (i, fmt)
               for (i, fmt, ang) in tarefas}
        for f in as_completed(fut):
            i, fmt = fut[f]
            try:
                o = f.result()
                o["formato"] = fmt
                o["formato_label"] = fv.info(fmt).get("label", fmt)
                opcoes[i] = o
            except Exception as e:  # noqa: BLE001
                erros.append({"formato": fmt, "erro": str(e)})
    opcoes = [o for o in opcoes if o]
    # Escreve o histórico do chat UMA única vez, fora das threads (evita corromper o
    # arquivo com escritas concorrentes). Cada worker teve sessão própria, então aqui
    # não guardamos session_id (a próxima mensagem começa uma sessão nova).
    if opcoes:
        historico = carregar_chat(produto)
        msgs = (historico.get("mensagens") or [])[-30:]
        resumo = _resumo_lote(opcoes)
        historico["mensagens"] = (msgs + [{"papel": "usuario", "texto": mensagem},
                                          {"papel": "assistente", "texto": resumo}])[-40:]
        atomic_write_json(_chat_path(produto), historico)
    return {"resposta": _resumo_lote(opcoes), "opcoes": opcoes,
            "session_id": None, "erros": erros}
