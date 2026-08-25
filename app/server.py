"""Servidor local do Criativos Express (backend do app desktop).

Expõe uma API que o front consome via fetch. Toda a inteligência usa `claude -p`
(plano Claude) e a geração de imagem usa o Codex (plano ChatGPT). Custo de API = zero.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gerar  # noqa: E402
from app import claude_bridge  # noqa: E402
from app import nosleep
from app import codex_text_bridge  # noqa: E402


def _bridge(modelo):
    """Escolhe a ponte de texto pelo modelo do dropdown.

    'gpt*' -> Codex (plano ChatGPT, GPT-5); o resto -> Claude (`claude -p`).
    Ambas expõem a mesma API (conversar/pedir_texto).
    """
    if str(modelo or "").lower().startswith("gpt"):
        return codex_text_bridge
    return claude_bridge
from workspace import (JOBS, GERADOS_DIR, INFLUENCIADORES, PRODUCTS,  # noqa: E402
                       BUNDLE_DIR, atomic_write_json, atomic_write_text,
                       criativos_dir, ensure_user_config, gerados_dir_de_id,
                       influencer_dir, ler_json, mirror_saida_cliente, product_dir,
                       safe_child, safe_descendant)

# Templates/estáticos/prompts são só-leitura: no .exe congelado vivem no bundle
# (BUNDLE_DIR/app/...); no código-fonte, ao lado deste arquivo. Origem única.
_APP_ASSETS = (BUNDLE_DIR / "app") if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PROMPTS_DIR = _APP_ASSETS / "prompts"

# Primeira execução do app empacotado: materializa config/config.toml gravável.
ensure_user_config()

# Referências de ESTILO por produto: imagens que o usuário anexa na aba de copies
# marcando "estilo da imagem". Ficam ativas até serem removidas e entram na geração
# do criativo como direção visual FORTE (paleta, composição, layout), sem NUNCA
# alterar a identidade do produto (que vem sempre de referencia/).
REF_ESTILO_DIR = "referencia_estilo"
REF_ESTILO_INFO = "referencias_estilo.json"
REF_PRODUTO_INFO = "referencias_produto.json"
# Anexos EFÊMEROS do chat de copy (modo "copy"): o Claude os lê no turno em que
# são enviados; ficam sob output/ e são limpos a cada nova conversa.
ANEXOS_CHAT_DIR = ".anexos_chat"

if getattr(sys, "frozen", False):
    app = Flask(__name__,
                template_folder=str(_APP_ASSETS / "templates"),
                static_folder=str(_APP_ASSETS / "static"))
else:
    app = Flask(__name__)

# Fluxo de Vídeo UGC: segundo caminho da ferramenta, montado sob /ugc (não colide
# com nenhuma rota de imagem). Toda a lógica vive em app/ugc_web.py.
from app.ugc_web import ugc as _ugc_bp  # noqa: E402
app.register_blueprint(_ugc_bp)

# Console de diagnóstico embutido (captura logs/erros/stderr; visível em /console).
# Essencial no Mac, onde o .app windowed engole o stderr.
from app import console_log  # noqa: E402
console_log.instalar(app)
# Vigia de sono: compara relogio monotonico x de parede pra DETECTAR que a maquina
# suspendeu, e registra no console. Antes, um job morto pelo sono parecia 'travou do nada'.
nosleep.iniciar_vigia()


@app.route("/console")
def pagina_console():
    return render_template("console.html")


@app.route("/api/console")
def api_console():
    return jsonify({"linhas": console_log.linhas()})


@app.route("/api/console/limpar", methods=["POST"])
def api_console_limpar():
    console_log.limpar()
    return jsonify({"ok": True})


def _cerebro(nome: str, fallback: str = "") -> str:
    """Lê o 'cérebro' especializado (expertise) de app/prompts/<nome>.md."""
    f = PROMPTS_DIR / nome
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    return fallback

# ---------------------------------------------------------------- formatos ----
# Formatos de criativo (modos). Cada um troca o "cérebro" de copy e de arte, sem
# tocar no fluxo Padrão (que continua idêntico). A seleção é do PRODUTO e fica em
# output/formatos.json (lista; o PRIMEIRO é o formato ativo do lote atual).
FORMATOS_VALIDOS = ("padrao", "wikihow", "noticia")

_CEREBRO_COPY = {
    "padrao": "copywriter.md",
    "wikihow": "copywriter_wikihow.md",
    "noticia": "copywriter_noticia.md",
}
_CEREBRO_ARTE = {
    "padrao": "diretor_arte.md",
    "wikihow": "diretor_arte_wikihow.md",
    "noticia": "diretor_arte_noticia.md",
}


def _formatos_path(produto: str) -> Path:
    return product_dir(produto) / "output" / "formatos.json"


def _ler_formatos(produto: str) -> list[str]:
    """Lista de formatos ativos do produto; o 1º é o ativo. Default: ['padrao']."""
    f = _formatos_path(produto)
    if f.exists():
        try:
            dados = json.loads(f.read_text(encoding="utf-8"))
            fs = [x for x in (dados.get("formatos") or []) if x in FORMATOS_VALIDOS]
            if fs:
                # sem duplicar, preservando a ordem (1º = ativo)
                vistos, out = set(), []
                for x in fs:
                    if x not in vistos:
                        vistos.add(x)
                        out.append(x)
                return out
        except Exception:  # noqa: BLE001 — arquivo corrompido: cai no default
            pass
    return ["padrao"]


def _escrever_formatos(produto: str, formatos: list[str]) -> list[str]:
    fs = [x for x in formatos if x in FORMATOS_VALIDOS] or ["padrao"]
    vistos, limpos = set(), []
    for x in fs:
        if x not in vistos:
            vistos.add(x)
            limpos.append(x)
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_formatos_path(produto), {"formatos": limpos})
    return limpos


def _formato_ativo(produto: str) -> str:
    return _ler_formatos(produto)[0]


_FORMATO_LABEL = {"padrao": "Padrão", "wikihow": "WikiHow", "noticia": "Notícia"}


def _info_formato(fmt: str) -> str:
    return _FORMATO_LABEL.get(fmt, fmt)


def _cerebro_copy(produto: str) -> str:
    return _cerebro(_CEREBRO_COPY.get(_formato_ativo(produto), "copywriter.md"), SYSTEM_COPY)


def _cerebro_arte(produto: str) -> str:
    return _cerebro(_CEREBRO_ARTE.get(_formato_ativo(produto), "diretor_arte.md"))


def _cerebro_arte_de(fmt: str) -> str:
    return _cerebro(_CEREBRO_ARTE.get(fmt, "diretor_arte.md"))


def _data_noticia_str() -> str:
    """Data/hora de publicação FICTÍCIA, sempre dentro dos últimos 7 dias e nunca
    no futuro. Formato do print de portal: 'DD/MM/AAAA HHhMM · Atualizado há X'."""
    now = datetime.now()
    dias = random.randint(0, 6)
    horas = random.randint(1, 23)
    pub = now - timedelta(days=dias, hours=horas)
    data_fmt = pub.strftime("%d/%m/%Y %Hh%M")
    if dias >= 1:
        atual = f"Atualizado há {dias} dia{'s' if dias > 1 else ''}"
    else:
        atual = f"Atualizado há {horas} hora{'s' if horas > 1 else ''}"
    return f"{data_fmt} · {atual}"


def _bloco_data_noticia(produto: str, formato: str | None = None) -> str:
    """Bloco a injetar no contexto quando o formato é Notícia: entrega a string de
    data LITERAL que o print deve exibir (o modelo não inventa data). `formato` None
    usa o ativo do produto (compat); no MIX, passa o formato do grupo."""
    fmt = formato or _formato_ativo(produto)
    if fmt != "noticia":
        return ""
    return ("\n\n[FORMATO NOTÍCIA] Data/hora LITERAL para o print (use EXATAMENTE esta string, "
            "não invente outra, não altere): '" + _data_noticia_str() + "'.\n")


def _lock(produto: str) -> threading.Lock:
    return JOBS.lock(produto)


def _cancel_event(produto: str) -> threading.Event:
    return JOBS.cancel(produto)


@app.before_request
def validar_produto_da_rota():
    nome = (request.view_args or {}).get("produto")
    if nome is not None:
        try:
            product_dir(nome)
        except ValueError as exc:
            abort(404, description=str(exc))


# ---------------------------------------------------------------- contexto ----

def montar_contexto_produto(produto: str) -> str:
    """Junta config.md + arquivos de texto de contexto/ num bloco de contexto."""
    pdir = product_dir(produto)
    partes = []
    cfg = pdir / "config.md"
    if cfg.exists():
        partes.append("## CONFIG DO PRODUTO\n" + cfg.read_text(encoding="utf-8", errors="replace"))
    ctx_dir = pdir / "contexto"
    if ctx_dir.exists():
        for f in sorted(ctx_dir.iterdir()):
            if f.suffix.lower() in {".md", ".txt"} and f.name != ".gitkeep":
                partes.append(f"## CONTEXTO: {f.name}\n"
                              + f.read_text(encoding="utf-8", errors="replace")[:12000])
    refs_produto = _referencias_com_contexto(produto, "produto") if "IMG_EXTS" in globals() else []
    refs_com_contexto = [f"- {i['arquivo']}: {i['contexto']}" for i in refs_produto if i.get("contexto")]
    if refs_com_contexto:
        partes.append("## QUANDO USAR CADA FOTO REAL DO PRODUTO\n" + "\n".join(refs_com_contexto))
    return "\n\n".join(partes) if partes else "(sem config/contexto preenchidos)"


# Guardrail curto (vai via --append-system-prompt). A expertise pesada vai no
# preâmbulo/prompt (stdin), sem limite de linha de comando.
SYSTEM_COPY = ("Você é um copywriter sênior de resposta direta, com liderança estratégica. "
               "Responda SEMPRE direto, usando o contexto do produto já na conversa; nunca "
               "peça briefing genérico nem mencione ferramentas, skills ou comandos. Só copy. "
               "ENTREGA DIRETA: se o pedido já for específico, escreva a copy JÁ, na mesma "
               "resposta, sempre terminando com o bloco ```copies-json```. NUNCA responda só "
               "'copy pronta' nem descreva o que vai fazer sem entregar a copy no mesmo turno. "
               "LEGENDA É OPT-IN: por padrão entregue só a copy de imagem (headline, "
               "subheadline/apoio, cta) e deixe o campo 'corpo' vazio; só escreva a legenda "
               "longa do post se o usuário pedir explicitamente. "
               "OCASIÃO NÃO SE INVENTA: nunca amarre a copy a data comemorativa (Dia dos Pais, "
               "Natal, Black Friday, Dia das Maes etc.) se o usuario nao pediu a data. Sem pedido, "
               "escreva copy atemporal (identidade, pertencimento, escassez real, beneficio). "
               "REGRA ABSOLUTA: o texto das copias NUNCA pode conter hifen ou travessao "
               "(os caracteres -, –, —). Use virgula, ponto, dois-pontos, parenteses "
               "ou duas frases no lugar. Isso vale para toda copy de todo produto.")

SYSTEM_PROMPTS_IMG = ("Você é diretor de arte de publicidade. Responda SOMENTE com o array JSON "
                      "pedido, sem nenhum texto fora dele. JSON válido: dentro dos valores de "
                      "texto use apenas aspas simples ('), nunca aspas duplas, que quebram o JSON.")

SYSTEM_ESTILO = ("Você é o DIRETOR CRIATIVO de uma campanha de publicidade, não apenas um gerador "
                 "de fundos. Antes de responder, pense como um diretor que precisa criar uma série "
                 "de anúncios vendáveis, com produto como protagonista, ideias memoráveis e variedade "
                 "real de composição. Preserve rigorosamente a identidade, embalagem, forma, cor, "
                 "marca e rótulos do produto nas fotos reais. Referências de estilo definem linguagem "
                 "visual, paleta, luz, acabamento, tipografia e composição, mas nunca substituem o "
                 "produto nem devem ser copiados literalmente. Não caia no padrão automático de colocar "
                 "uma mulher ou modelo em toda cena: pessoas são opcionais e só entram quando a ideia "
                 "precisar delas. Priorize publicidade centrada no produto, como vitrine de loja, balcão "
                 "ou ponto de venda, produto em exposição, still life com objetos que reforcem a promessa, "
                 "prateleira, display, composição editorial, close hero e outras soluções de merchandising "
                 "e campanha. Seja objetivo. Quando precisar atualizar as direções, responda com uma "
                 "breve explicação seguida de um bloco ```visuais-json``` contendo um array JSON válido.")

SYSTEM_IDEIAS = (
    "Você é um ESTRATEGISTA CRIATIVO sênior de anúncios de resposta direta. Recebe os criativos "
    "que ACABARAM de ser gerados (copy + conceito visual de cada um) mais o contexto do produto, "
    "analisa o que já foi explorado e propõe NOVAS ideias de criativo — copy E imagem juntas. "
    "Trabalhe SEMPRE em dois caminhos, claramente rotulados: (1) PADRÃO — variações que mantêm a "
    "linha do que já existe, lateralizando ângulo, oferta, prova ou cena, seguras e coerentes com a "
    "marca; (2) DISRUPTIVO — ideias realmente diferentes, ângulos e formatos ainda não explorados, "
    "mas que AINDA fazem sentido para este produto e público (nada de viagem: precisa ser plausível "
    "de rodar). Baseie tudo no que foi feito e no contexto; não repita conceitos já presentes. "
    "VARIE O RACIOCÍNIO entre as ideias — cada uma ataca um EIXO diferente (objeção, prova/autoridade, "
    "emoção/pertencimento, oferta/escassez, contexto de uso, público específico, comparação, medo/urgência, "
    "identidade). NÃO gere N ideias com a mesma lógica trocando só as palavras; se duas partem do mesmo "
    "gancho, descarte uma. "
    "CONCEITO DE IMAGEM (o 'conceito_imagem' vira prompt de arte direto, então cuide da anatomia): o "
    "PRODUTO é o herói; NÃO coloque pessoas por padrão. Se a ideia pedir pessoa, use UMA pessoa num gesto "
    "simples e nítido — NUNCA várias mãos juntas, dedos entrelaçados, brinde/aperto em grupo, multidão em "
    "primeiro plano nem poses complexas (o gerador de imagem deforma dedos e membros nessas cenas). Prefira "
    "produto em destaque, still com clima, vitrine/ponto de venda, uso simples. "
    "Respeite as regras da marca: PROIBIDO hífen ou travessão (-, –, —) em qualquer copy; não invente "
    "datas comemorativas nem provas/objetos que não existam. Responda SOMENTE com um array JSON VÁLIDO "
    "(as chaves e as strings SEMPRE entre aspas duplas), sem nenhum texto fora dele. Dentro do TEXTO "
    "dos valores use apenas aspas simples ('), nunca aspas duplas, para não quebrar o JSON.")

SYSTEM_QA = (
    "Você é um REVISOR DE QUALIDADE (QA) rigoroso de criativos publicitários. Sua função é OLHAR cada "
    "imagem gerada e caçar defeitos, com PRIORIDADE MÁXIMA para ERROS DE TEXTO na arte: palavras "
    "escritas errado, letras trocadas/faltando/repetidas, texto cortado, texto sem sentido ou "
    "'embolado', acentuação errada, presença de hífen ou travessão (proibidos), e divergência entre o "
    "texto que aparece na arte e a copy pretendida. Depois disso, cheque incoerências visuais: mãos com "
    "número errado de dedos, membros duplicados ou deformados, rostos distorcidos, objetos derretidos, e "
    "ERROS NA EMBALAGEM/PRODUTO (forma, cor, logo, rótulo diferentes das fotos reais de referência). "
    "Seja honesto e conservador: só marque um problema que você REALMENTE consegue ver; não invente. "
    "Para cada imagem, se houver defeito, escreva também uma instrução de correção CIRÚRGICA para o "
    "refino, deixando explícito que TODO o resto da imagem deve permanecer idêntico e que a correção "
    "NÃO pode estragar o texto que já está certo. Responda SOMENTE com um array JSON VÁLIDO (as chaves "
    "e as strings SEMPRE entre aspas duplas), sem nenhum texto fora dele. Dentro do TEXTO dos valores "
    "use apenas aspas simples ('), nunca aspas duplas, para não quebrar o JSON.")

# ---- Memória por produto (aprendizado acumulado, tipo RAG só que sempre no contexto) ----
# Cada produto tem um contexto/aprendizado.md. Ele já entra em TODA conversa
# (montar_contexto_produto varre contexto/*.md). Ao fim de cada conversa, destilamos
# o que foi dito num punhado de aprendizados duráveis e fazemos merge aqui.
APRENDIZADO_ARQ = "aprendizado.md"
APRENDIZADO_HEADER = (
    "# COMO O USUÁRIO REFINA AS COPIES (memória de estilo deste produto)\n"
    "# Preenchido ao fim de cada conversa. NÃO é conteúdo de campanha nem pedido pontual: "
    "são as PREFERÊNCIAS DURÁVEIS de refino (tom, tamanho, o que ele corta, o que aprova ou "
    "rejeita como padrão). Serve pra copy ficar cada vez mais assertiva. Edite/apague à vontade.\n")

SYSTEM_APRENDER = ("Você extrai preferências DURÁVEIS de refino de copy de uma conversa. "
                   "Responda SOMENTE com um array JSON de strings, sem nenhum texto fora dele. "
                   "Use apenas aspas simples (') dentro dos valores.")

PROMPT_APRENDER = (
    "[MODO MEMÓRIA] Pare de escrever copy agora. Reveja TODA a nossa conversa acima e extraia "
    "apenas o que ensina a te servir MELHOR nas PRÓXIMAS copies deste produto, ou seja, o PADRÃO "
    "de como o usuário refina: preferências duráveis de tom, tamanho e estilo; o que ele "
    "consistentemente manda cortar, encurtar ou mudar; correções que ele fez; tipos de ângulo "
    "ou abordagem que ele aprova ou rejeita como padrão; palavras, clichês ou promessas que ele "
    "não quer. \n"
    "NÃO registre (isto é o mais importante): pedidos pontuais de campanha ou ocasião (ex.: 'quis "
    "copies de Dia dos Pais' NÃO é memória, foi só o pedido daquele dia), headlines ou textos "
    "específicos, nem nada que só valia para aquela leva. Só entra o que vai valer em QUALQUER "
    "copia futura deste produto. \n"
    "Cada item é UMA frase curta de preferência de estilo/refino (ex.: 'prefere headline de até 5 "
    "palavras', 'manda sempre cortar adjetivo vazio', 'rejeita tom institucional', 'gosta de "
    "escassez com número real'). Ignore o óbvio e o que já está no config do produto. Se não "
    "houver preferência durável nova, responda []. Responda SOMENTE com um array JSON de strings.")


def _aprendizado_path(produto: str) -> Path:
    return product_dir(produto) / "contexto" / APRENDIZADO_ARQ


def _ler_aprendizado_itens(produto: str) -> list[str]:
    """Lê os bullets (linhas '- ...') do aprendizado.md do produto."""
    f = _aprendizado_path(produto)
    if not f.exists():
        return []
    itens = []
    for linha in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = linha.strip()
        if s.startswith("- "):
            itens.append(s[2:].strip())
    return itens


def _escrever_aprendizado_itens(produto: str, itens: list[str]) -> None:
    corpo = APRENDIZADO_HEADER + "\n" + "\n".join(f"- {i}" for i in itens if i.strip()) + "\n"
    f = _aprendizado_path(produto)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, corpo)


def _merge_aprendizado(produto: str, novos: list[str]) -> int:
    """Faz append dos aprendizados novos, sem duplicar (case-insensitive). Retorna quantos entraram."""
    atuais = _ler_aprendizado_itens(produto)
    vistos = {i.strip().lower() for i in atuais}
    adicionados = 0
    for n in novos:
        chave = str(n or "").strip()
        if not chave or chave.lower() in vistos:
            continue
        atuais.append(chave)
        vistos.add(chave.lower())
        adicionados += 1
    if adicionados:
        _escrever_aprendizado_itens(produto, atuais)
    return adicionados

# ---- Verdade visual por produto (memória de IMAGEM) ----
# Espelho do aprendizado de copy, mas para os refinos de criativo. Enquanto a memória de copy
# guarda ESTILO, esta guarda a VERDADE VISUAL do produto: correções duráveis que o usuário faz
# ao refinar (ex.: "vem sempre numa caixinha preta, nunca embalagem transparente"). gerar.py lê
# esse arquivo e injeta em TODO prompt de imagem, então o erro não se repete em criativo nenhum.
VERDADE_ARQ = "verdade_visual.md"
VERDADE_HEADER = (
    "# VERDADE VISUAL DO PRODUTO (memória de imagem)\n"
    "# Correções DURÁVEIS de como o produto realmente é/aparece, aprendidas quando você refina "
    "um criativo (ex.: 'vem sempre numa caixinha preta', 'não existe versão transparente'). "
    "Entram automaticamente em TODA geração de imagem deste produto. Edite/apague à vontade.\n")

SYSTEM_VERDADE = ("Você extrai FATOS VISUAIS DURÁVEIS de um produto a partir de uma correção que o "
                  "usuário pediu ao refinar um criativo. Responda SOMENTE com um array JSON de "
                  "strings, sem nenhum texto fora dele. Use apenas aspas simples (') dentro dos valores.")

PROMPT_VERDADE = (
    "[MODO MEMÓRIA] O usuário refinou um criativo de imagem deste produto com a instrução abaixo. "
    "Extraia APENAS fatos DURÁVEIS sobre como o produto realmente é ou como sempre deve aparecer "
    "(embalagem, cor, material, formato, acabamento, o que ele NÃO tem ou NÃO é) que valham para "
    "QUALQUER imagem futura deste produto.\n"
    "NÃO registre (isto é o mais importante) ajustes pontuais de composição desta arte específica: "
    "mover ou trocar texto, mudar o fundo/cenário desta cena, reenquadrar, trocar cor de headline, "
    "aproximar ou afastar o produto. Isso não é verdade do produto, foi só um retoque daquela arte.\n"
    "Cada item é UMA frase curta e declarativa em português (ex.: 'vem sempre numa caixinha preta, "
    "nunca em embalagem transparente'; 'a pulseira é de aço prateado, não dourada'). Se a instrução "
    "for só um retoque pontual sem nenhum fato durável do produto, responda [].\n\n"
    "Instrução do usuário ao refinar:\n---\n{instrucao}\n---\n\n"
    "Responda SOMENTE com um array JSON de strings.")


def _verdade_path(produto: str) -> Path:
    return product_dir(produto) / "contexto" / VERDADE_ARQ


def _ler_verdade_itens(produto: str) -> list[str]:
    f = _verdade_path(produto)
    if not f.exists():
        return []
    itens = []
    for linha in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = linha.strip()
        if s.startswith("- "):
            itens.append(s[2:].strip())
    return itens


def _escrever_verdade_itens(produto: str, itens: list[str]) -> None:
    corpo = VERDADE_HEADER + "\n" + "\n".join(f"- {i}" for i in itens if i.strip()) + "\n"
    f = _verdade_path(produto)
    f.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(f, corpo)


def _merge_verdade_sem_lock(produto: str, novos: list[str]) -> int:
    """Append dos fatos visuais novos, sem duplicar (case-insensitive). Retorna quantos entraram."""
    atuais = _ler_verdade_itens(produto)
    vistos = {i.strip().lower() for i in atuais}
    adicionados = 0
    for n in novos:
        chave = str(n or "").strip()
        if not chave or chave.lower() in vistos:
            continue
        atuais.append(chave)
        vistos.add(chave.lower())
        adicionados += 1
    if adicionados:
        _escrever_verdade_itens(produto, atuais)
    return adicionados


_verdade_locks: dict[str, threading.Lock] = {}


def _merge_verdade(produto: str, novos: list[str]) -> int:
    # Refinamentos em paralelo podem aprender fatos simultaneamente; serializa
    # o read-modify-write para nenhum aprendizado ser perdido.
    lock = _verdade_locks.setdefault(produto, threading.Lock())
    with lock:
        return _merge_verdade_sem_lock(produto, novos)


def _aprender_verdade_visual(produto: str, instrucao: str, modelo: str = "haiku") -> int:
    """Best-effort: destila a instrução de refino num fato visual durável e faz merge.

    Roda em background após disparar o refino; falha aqui nunca afeta o usuário.
    """
    try:
        instrucao = (instrucao or "").strip()
        if not instrucao:
            return 0
        res = _bridge(modelo).conversar(
            PROMPT_VERDADE.format(instrucao=instrucao[:4000]),
            session_id=None, modelo=modelo, system_prompt=SYSTEM_VERDADE, timeout=120)
        try:
            itens = _extrair_json(res.get("resposta", ""))
        except Exception:  # noqa: BLE001 — sem JSON: nada durável a aprender
            itens = []
        if not isinstance(itens, list):
            itens = []
        limpos = [str(i).strip() for i in itens
                  if isinstance(i, (str, int, float)) and str(i).strip()][:10]
        return _merge_verdade(produto, limpos)
    except Exception:  # noqa: BLE001 — best-effort, silencioso
        return 0

# O "cérebro" completo do copywriter é carregado de app/prompts/copywriter.md e injetado
# na PRIMEIRA mensagem (via stdin). Nas mensagens seguintes ele já está no contexto da sessão.
PREAMBULO_COPY = """{cerebro}

Agora vamos trabalhar as copies deste produto específico. O contexto real dele está abaixo —
use-o como verdade; nunca contradiga.

===== CONTEXTO DO PRODUTO =====
{contexto}
===============================

Mensagem do usuário: {mensagem}"""


# ------------------------------------------------------------------ rotas -----

# Marcas (skins). Mesma lógica, visual diferente. A marca sai do env
# CRIATIVOS_BRAND (definido pelo launcher) e pode ser sobrescrita por ?brand=.
# "default" = visual atual; "collab" = skin premium claro (cliente Collab Store).
BRANDS = {
    "default": {"nome": "Ads Express", "logo": None},
    "collab": {"nome": "Criativos Collab Store", "logo": "/static/brand-collab-logo.png"},
}


@app.route("/")
def landing():
    """Tela inicial: escolha entre o fluxo de Imagem e o de Vídeo UGC."""
    return render_template("landing.html")


@app.route("/api/logins")
def api_logins():
    """Estado das 3 contas (Claude, ChatGPT, Google Cloud) pros botões da tela inicial."""
    from app import logins
    return jsonify(logins.status_todos())


@app.route("/api/login/<tool>", methods=["POST"])
def api_login(tool):
    """Dispara o login interativo da ferramenta numa janela de terminal."""
    from app import logins
    return jsonify(logins.iniciar_login(tool))


@app.route("/api/veo_project", methods=["GET", "POST"])
def api_veo_project():
    """Lê/grava o VEO_PROJECT (id do projeto GCP) usado no fluxo de vídeo."""
    from app import logins
    if request.method == "POST":
        pid = (request.get_json(silent=True) or {}).get("veo_project", "")
        return jsonify(logins.set_veo_project(pid))
    return jsonify({"veo_project": logins.get_veo_project()})


@app.route("/imagem")
def index():
    brand = request.args.get("brand") or os.environ.get("CRIATIVOS_BRAND") or "default"
    if brand not in BRANDS:
        brand = "default"
    cfg = BRANDS[brand]
    return render_template("index.html", brand=brand,
                           brand_nome=cfg["nome"], brand_logo=cfg["logo"])


def _primeira_referencia(pdir: Path) -> str | None:
    """Nome da 1ª referência exibível no navegador (png/jpg/jpeg/webp), ou None."""
    ref_dir = pdir / "referencia"
    if not ref_dir.exists():
        return None
    for f in sorted(ref_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in IMG_EXTS:
            return f.name
    return None


# Tiers de copy do Claude (apelidos que seguem o CLI) + tag de consumo de cota.
_CLAUDE_TIERS = [
    {"id": "haiku", "label": "Haiku", "consumo": "baixo"},
    {"id": "sonnet", "label": "Sonnet", "consumo": "medio"},
    {"id": "opus", "label": "Opus", "consumo": "alto"},
]


@app.route("/api/modelos")
def modelos():
    """Lista de modelos do dropdown: Claude (apelidos) + GPT (lidos do cache do Codex).

    Cada item traz a tag de consumo e, quando conhecida, a versão REAL resolvida
    (pro Claude só aparece depois do 1º uso; pro GPT é o próprio slug do cache).
    """
    itens = [{**t, "provider": "claude",
              "resolvido": claude_bridge.modelo_resolvido(t["id"])}
             for t in _CLAUDE_TIERS]
    try:
        for g in codex_text_bridge.modelos_disponiveis():
            itens.append({"id": g["id"], "label": g["label"], "provider": "gpt",
                          "consumo": g["consumo"], "resolvido": g["id"]})
    except Exception:  # noqa: BLE001
        pass  # sem Codex/cache: mostra só os Claude
    return jsonify({"modelos": itens, "default": "sonnet"})


# Catálogo de formatos exibido no popup do chat. A ordem é a de exibição.
_FORMATOS_CATALOGO = [
    {"id": "padrao", "label": "Padrão",
     "desc": "Criativo publicitário com o produto como herói (o modo de sempre)."},
    {"id": "wikihow", "label": "WikiHow",
     "desc": "Ilustração native de mecanismo (estilo artigo de saúde), copy de conteúdo."},
    {"id": "noticia", "label": "Notícia",
     "desc": "Print de matéria de portal (tarja, manchete, assinatura), copy editorial."},
]


@app.route("/api/formatos/<produto>", methods=["GET", "POST"])
def formatos(produto):
    """Formatos ativos do produto (padrao/wikihow/noticia). O 1º da lista é o ativo
    do lote atual e decide qual cérebro de copy/arte o pipeline usa."""
    if request.method == "GET":
        return jsonify({"catalogo": _FORMATOS_CATALOGO, "formatos": _ler_formatos(produto)})
    body = request.get_json(silent=True) or {}
    escolhidos = [str(x) for x in (body.get("formatos") or [])]
    salvos = _escrever_formatos(produto, escolhidos)
    return jsonify({"ok": True, "formatos": salvos})


def _is_product_dir(d: Path) -> bool:
    """Uma pasta é um PRODUTO (folha) se tem config/contexto/output/referencia direto.
    Caso contrário, é uma pasta de CLIENTE cujos filhos são produtos (auto-cadastro)."""
    return any((d / n).exists() for n in ("config.md", "contexto", "output", "referencia"))


def _produto_item(pdir: Path, nome_id: str, label: str, cliente: str) -> dict:
    out = pdir / "output"
    thumb = _primeira_referencia(pdir)
    return {
        "nome": nome_id,          # id usado nas rotas (cliente~produto ou produto solto)
        "label": label,           # nome exibido (só o produto)
        "cliente": cliente,       # "" = produto solto (sem cliente)
        "tem_copies": (out / "copies.md").exists() or (out / "copies.json").exists(),
        "tem_prompts": (out / "prompts.json").exists(),
        "tem_referencia": thumb is not None or (
            any((pdir / "referencia").glob("*")) if (pdir / "referencia").exists() else False),
        "thumb": thumb,
    }


@app.route("/api/produtos")
def produtos():
    """Lista produtos. Suporta 2 layouts no disco, agrupando por cliente:
      products/<produto>/              -> produto solto (cliente="")
      products/<cliente>/<produto>/    -> agrupado (id = cliente~produto)
    """
    itens = []
    if PRODUCTS.exists():
        for d in sorted(PRODUCTS.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            if _is_product_dir(d):
                # produto solto (legado / criado manualmente no app)
                itens.append(_produto_item(d, d.name, d.name, ""))
            else:
                # pasta de cliente: cada subpasta é um produto
                cliente = d.name
                for sub in sorted(d.iterdir(), key=lambda p: p.name.lower()):
                    if not sub.is_dir() or sub.name.startswith("_"):
                        continue
                    itens.append(_produto_item(sub, f"{cliente}~{sub.name}", sub.name, cliente))
    return jsonify(itens)


# --- Movimentação/remoção resiliente de pastas (robusta no Windows) -----------
# No Windows, os.rename/shutil.move e shutil.rmtree falham com WinError 5 (acesso
# negado) quando algum arquivo dentro da pasta está com atributo read-only ou foi
# aberto/travado por outro processo momentaneamente (antivírus, handle não fechado,
# marcador de lock). Estes helpers limpam marcadores conhecidos, forçam a remoção do
# read-only via chmod e re-tentam algumas vezes — o padrão clássico pra Windows.

# Marcadores internos que podem viajar junto na pasta e travar operações seguintes.
_LOCK_MARKERS = (".generation.lock", "output/.generation.lock")


def _limpar_marcadores(base: Path) -> None:
    """Remove marcadores de lock conhecidos dentro da pasta antes de mover/apagar."""
    for rel in _LOCK_MARKERS:
        try:
            (base / rel).unlink(missing_ok=True)
        except OSError:
            pass


def _on_rm_error(func, path, exc_info):
    """onerror do rmtree: tira o read-only e re-tenta a operação que falhou.

    Padrão clássico no Windows para PermissionError (WinError 5) causado por
    arquivos/pastas marcados como somente-leitura.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    try:
        func(path)
    except OSError:
        # última tentativa: se ainda travar, propaga na chamada de cima (retry externo)
        raise


def _rmtree_resiliente(alvo: Path, tentativas: int = 3) -> None:
    """shutil.rmtree robusto: limpa read-only via onerror e re-tenta em handle momentâneo."""
    _limpar_marcadores(alvo)
    ultimo_erro: Exception | None = None
    for n in range(tentativas):
        try:
            shutil.rmtree(alvo, onerror=_on_rm_error)
            return
        except OSError as e:
            ultimo_erro = e
            time.sleep(0.25 * (n + 1))
    if alvo.exists() and ultimo_erro is not None:
        raise ultimo_erro


def _limpar_readonly_recursivo(base: Path) -> None:
    """Remove o atributo read-only de toda a árvore (arquivos e pastas)."""
    try:
        os.chmod(base, stat.S_IWRITE)
    except OSError:
        pass
    for raiz, dirs, arquivos in os.walk(base):
        for nome in dirs + arquivos:
            try:
                os.chmod(os.path.join(raiz, nome), stat.S_IWRITE)
            except OSError:
                pass


def _move_dir_resiliente(origem: Path, destino: Path, tentativas: int = 3) -> None:
    """Move uma pasta de forma robusta no Windows.

    Tenta shutil.move (rename rápido no mesmo drive); em PermissionError/WinError 5
    cai para copytree + rmtree manual, limpando read-only antes. Re-tenta algumas
    vezes para o caso de um handle momentâneo (antivírus, escrita recém-fechada).
    """
    _limpar_marcadores(origem)
    ultimo_erro: Exception | None = None
    for n in range(tentativas):
        try:
            shutil.move(str(origem), str(destino))
            return
        except (PermissionError, OSError) as e:
            ultimo_erro = e
            # tira read-only da árvore inteira e re-tenta o move rápido
            _limpar_readonly_recursivo(origem)
            time.sleep(0.25 * (n + 1))
            try:
                shutil.move(str(origem), str(destino))
                return
            except (PermissionError, OSError) as e2:
                ultimo_erro = e2
    # Fallback final: copytree + rmtree resiliente (funciona mesmo com read-only).
    try:
        shutil.copytree(str(origem), str(destino), dirs_exist_ok=False)
    except FileExistsError:
        # destino apareceu no meio do caminho — deixa o chamador tratar colisão
        raise
    _rmtree_resiliente(origem)
    if origem.exists():
        raise ultimo_erro or OSError(f"Não foi possível mover {origem} -> {destino}")


def _mover_gerados(old_id: str, new_id: str) -> None:
    """Acompanha o rename/atribuição do produto movendo a pasta de imagens em
    gerados/ (as imagens vivem separadas do config, então precisam viajar junto)."""
    old_g = gerados_dir_de_id(old_id)
    new_g = gerados_dir_de_id(new_id)
    if not old_g.exists() or new_g.exists():
        return
    new_g.parent.mkdir(parents=True, exist_ok=True)
    _move_dir_resiliente(old_g, new_g)
    # limpa o bucket de cliente antigo em gerados/ se ficou vazio
    try:
        if old_g.parent.resolve() != GERADOS_DIR.resolve() and not any(old_g.parent.iterdir()):
            old_g.parent.rmdir()
    except OSError:
        pass


def _remover_gerados(produto: str) -> None:
    """Remove a pasta de imagens em gerados/ do produto (e o bucket de cliente vazio)."""
    g = gerados_dir_de_id(produto)
    if not g.exists():
        return
    parent = g.parent
    _rmtree_resiliente(g)
    try:
        if parent.resolve() != GERADOS_DIR.resolve() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


@app.route("/api/produtos/<produto>/renomear", methods=["POST"])
def renomear_produto(produto):
    """Renomeia a pasta inteira do produto, preservando todo o conteúdo."""
    body = request.get_json(silent=True) or {}
    novo = str(body.get("nome") or "").strip().rstrip(". ")
    if not novo or len(novo) > 80 or _ILEGAIS.search(novo) or "~" in novo or novo in {".", ".."} \
            or novo.split(".")[0].lower() in _RESERVADOS:
        return jsonify({"ok": False, "erro": "Nome inválido (evite / \\ ~ : * ? \" < > | e nomes reservados)."}), 400

    origem = product_dir(produto)
    # Preserva o agrupamento: se o produto está dentro de products/<cliente>/, o
    # novo id mantém o prefixo cliente~; produtos soltos continuam soltos.
    cliente = produto.partition("~")[0] if "~" in produto else ""
    novo_id = f"{cliente}~{novo}" if cliente else novo
    if novo_id == produto:
        return jsonify({"ok": True, "nome": novo_id})
    destino = origem.parent / novo
    if destino.exists():
        return jsonify({"ok": False, "erro": "Já existe um produto com esse nome."}), 409

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Não é possível renomear enquanto há uma geração em andamento."}), 409
    try:
        _move_dir_resiliente(origem, destino)
        # O marcador de lock (output/.generation.lock) viaja junto na renomeação; o
        # release() só limpa o caminho antigo. Remove o que foi para o destino, senão
        # o próximo lock (com o novo id) bate num marcador de PID vivo e falha (409).
        (destino / "output" / ".generation.lock").unlink(missing_ok=True)
        _mover_gerados(produto, novo_id)  # as imagens em gerados/ seguem o novo id
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": f"Não foi possível renomear: {e}. "
                        "Feche visualizadores/exportações abertos dessa pasta e tente de novo."}), 500
    finally:
        lock.release()
    return jsonify({"ok": True, "nome": novo_id})


@app.route("/api/produtos/<produto>", methods=["DELETE"])
def remover_produto(produto):
    """Apaga a pasta INTEIRA do produto (products/<cliente>/<produto>/ ou
    products/<produto>/). Ação destrutiva — o front confirma antes. Se a pasta do
    cliente ficar vazia depois, ela também é removida (mantém a sanfona limpa)."""
    alvo = product_dir(produto)   # resolve ~ e valida traversal/existência
    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Não é possível remover enquanto há uma geração em andamento."}), 409
    try:
        parent = alvo.parent
        _rmtree_resiliente(alvo)
        _remover_gerados(produto)  # remove também as imagens em gerados/ do produto
        # remove a pasta do cliente se esvaziou (só se for subpasta de PRODUCTS, não a própria PRODUCTS)
        try:
            if parent.resolve() != PRODUCTS.resolve() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": f"Não foi possível remover: {e}. "
                        "Feche visualizadores/exportações abertos dessa pasta e tente de novo."}), 500
    finally:
        lock.release()
    return jsonify({"ok": True})


@app.route("/api/produtos/<produto>/atribuir", methods=["POST"])
def atribuir_produto(produto):
    """Move um produto SOLTO (products/<produto>/) para dentro de um cliente
    (products/<cliente>/<produto>/). Idempotente; trata colisão de nome sufixando."""
    if "~" in produto:
        return jsonify({"ok": False, "erro": "Este produto já está atribuído a um cliente."}), 400
    body = request.get_json(silent=True) or {}
    cliente = str(body.get("cliente") or "").strip().rstrip(". ")
    if not cliente or len(cliente) > 80 or _ILEGAIS.search(cliente) or "~" in cliente \
            or cliente in {".", ".."} or cliente.split(".")[0].lower() in _RESERVADOS:
        return jsonify({"ok": False, "erro": "Cliente inválido."}), 400

    origem = product_dir(produto)   # produto solto existente
    cli_dir = (PRODUCTS / cliente)
    if cli_dir.exists() and _is_product_dir(cli_dir):
        return jsonify({"ok": False, "erro": "Já existe um produto solto com o nome desse cliente."}), 409

    # nome de destino, sufixando em caso de colisão (produto de mesmo nome já no cliente)
    base_nome = origem.name
    destino = cli_dir / base_nome
    nome_final = base_nome
    i = 2
    while destino.exists():
        nome_final = f"{base_nome}_{i}"
        destino = cli_dir / nome_final
        i += 1

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Não é possível mover enquanto há uma geração em andamento."}), 409
    try:
        cli_dir.mkdir(parents=True, exist_ok=True)
        _move_dir_resiliente(origem, destino)
        # remove o marcador de lock que viajou junto (ver nota em renomear_produto)
        (destino / "output" / ".generation.lock").unlink(missing_ok=True)
        _mover_gerados(produto, f"{cliente}~{nome_final}")  # imagens seguem o novo id
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": f"Não foi possível mover: {e}. "
                        "Feche visualizadores/exportações abertos dessa pasta e tente de novo."}), 500
    finally:
        lock.release()
    return jsonify({"ok": True, "nome": f"{cliente}~{nome_final}", "cliente": cliente, "label": nome_final})


def _slugify_cliente(nome: str) -> str:
    """Nome de cliente -> slug de pasta: minúsculo, sem acento, hífens no lugar de
    espaços/pontuação. É o nome exibido na sanfona e o prefixo do id cliente~produto."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80]


@app.route("/api/clientes", methods=["GET"])
def listar_clientes():
    """Lista as pastas de CLIENTE em products/ (inclui clientes ainda sem produtos).
    Um cliente é uma pasta que NÃO é, ela mesma, um produto (sem config/output/etc.)."""
    nomes = []
    if PRODUCTS.exists():
        for d in sorted(PRODUCTS.iterdir(), key=lambda p: p.name.lower()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            if not _is_product_dir(d):
                nomes.append(d.name)
    return jsonify({"clientes": nomes})


@app.route("/api/clientes", methods=["POST"])
def criar_cliente():
    """Cria um cliente = uma pasta products/<slug>/ (vira uma sanfona nova na sidebar,
    mesmo vazia). Reaproveita a pasta se já for um cliente; sufixa em caso de colisão."""
    body = request.get_json(silent=True) or {}
    slug = _slugify_cliente(body.get("nome"))
    if not slug or slug in {".", ".."} or slug.split(".")[0].lower() in _RESERVADOS:
        return jsonify({"ok": False, "erro": "Nome de cliente inválido."}), 400
    destino = PRODUCTS / slug
    # já existe uma sanfona com esse slug (cliente, não produto solto): reusa.
    if destino.exists() and not _is_product_dir(destino):
        return jsonify({"ok": True, "cliente": slug, "existente": True})
    final = slug
    i = 2
    while (PRODUCTS / final).exists():
        final = f"{slug}-{i}"
        i += 1
    try:
        (PRODUCTS / final).mkdir(parents=True)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": f"Não foi possível criar: {e}"}), 500
    return jsonify({"ok": True, "cliente": final})


# ---- Limpeza determinística de hífen/travessão (regra absoluta do projeto) ----
# O modelo é instruído a não usar, mas isto garante: nenhum travessão/hífen de
# pontuação sobrevive no texto das copies, aconteça o que acontecer.
_RE_BULLET = re.compile(r"(?m)^[ \t]*[-—–•][ \t]+")   # marcador de lista no início da linha
_RE_TRAVESSAO = re.compile(r"[ \t]*[—–][ \t]*")        # em/en dash (sem engolir quebra de linha)
_RE_HIFEN_PONTUACAO = re.compile(r"[ \t]+-[ \t]+")     # hífen usado como travessão ( - )
_RE_HIFEN_FIM = re.compile(r"(?m)[ \t]+-[ \t]*$")      # hífen pendurado no fim da linha


def _sem_travessoes(s):
    """Remove travessões e hífens de pontuação do texto de copy.

    Mantém hífens internos de palavras compostas (ex.: 'e-mail'), que são
    ortografia legítima, não marca d'água de IA.
    """
    if not isinstance(s, str):
        return s
    t = _RE_BULLET.sub("", s)
    t = _RE_HIFEN_FIM.sub("", t)
    t = _RE_TRAVESSAO.sub(", ", t)
    t = _RE_HIFEN_PONTUACAO.sub(", ", t)
    t = re.sub(r"\s+,", ",", t)          # espaço órfão antes de vírgula
    t = re.sub(r",\s*,+", ",", t)        # vírgulas duplicadas
    t = re.sub(r",\s*([.!?;:])", r"\1", t)  # vírgula colada em pontuação final
    t = re.sub(r"(?m),\s*$", "", t)      # vírgula pendurada no fim da linha
    return t.strip()


def _limpar_copies(copies: list) -> list:
    for c in copies:
        if isinstance(c, dict):
            for k in ("angulo", "headline", "subheadline", "apoio", "corpo", "cta"):
                if k in c:
                    c[k] = _sem_travessoes(c[k])
    return copies


_RE_BLOCO_COPIES = re.compile(r"```copies-json\s*(.*?)```", re.DOTALL)
# Autocrítica de lote (Passo 4 do copywriter): forçada na resposta do modelo, mas
# NÃO deve poluir a UI. Removida da resposta antes de exibir (como o copies-json).
_RE_BLOCO_AUDIT = re.compile(r"```checklist-lote\s*.*?```", re.DOTALL)


def _sem_bloco_audit(s: str) -> str:
    return _RE_BLOCO_AUDIT.sub("", s).strip() if isinstance(s, str) else s


def _parse_copies_bloco(resposta: str):
    """Só EXTRAI o bloco ```copies-json``` (sem salvar). Retorna (texto_limpo, copies|None)."""
    m = _RE_BLOCO_COPIES.search(resposta)
    if not m:
        return _sem_bloco_audit(resposta), None
    try:
        copies = _extrair_json(m.group(1))
        if not isinstance(copies, list) or not copies:
            raise ValueError("bloco copies-json não é uma lista")
    except Exception:  # noqa: BLE001 — bloco malformado: segue como texto normal
        return _sem_bloco_audit(resposta), None
    _limpar_copies(copies)  # garantia dura: nenhum hífen/travessão de pontuação passa
    limpo = _sem_bloco_audit(_RE_BLOCO_COPIES.sub("", resposta))
    return limpo, copies


def _salvar_copies_lista(produto: str, copies: list, preservar_usadas: bool = True):
    """Salva a lista de copies (já parseada/taggeada) em copies.json/md, preservando 'usada'."""
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    # Preserva "usada" por CONTEÚDO da headline (não por id): ids se repetem entre
    # conversas diferentes, então casar por id marcaria copies novas como usadas.
    usadas_headlines: set[str] = set()
    f = out / "copies.json"
    if preservar_usadas and f.exists():
        try:
            for c in json.loads(f.read_text(encoding="utf-8")):
                if c.get("status") == "usada":
                    usadas_headlines.add(str(c.get("headline", "")).strip().lower())
        except Exception:  # noqa: BLE001
            pass
    for c in copies:
        if not preservar_usadas:
            c.pop("status", None)
        elif str(c.get("headline", "")).strip().lower() in usadas_headlines:
            c["status"] = "usada"
    atomic_write_json(f, copies)
    atomic_write_text(out / "copies.md", _copies_md_do_json(copies))
    return copies


def _processar_bloco_copies(produto: str, resposta: str, preservar_usadas: bool = True):
    """Extrai o bloco ```copies-json```, TAGGEIA cada copy com o formato ativo e salva.

    Retorna (resposta_sem_bloco, copies | None). Preserva status "usada".
    """
    limpo, copies = _parse_copies_bloco(resposta)
    if copies is None:
        return limpo, None
    fmt = _formato_ativo(produto)
    for c in copies:
        c.setdefault("formato", fmt)
    _salvar_copies_lista(produto, copies, preservar_usadas)
    return limpo, copies


def _cerebro_copy_fmt(fmt: str) -> str:
    """Cérebro de copy de um formato específico (não o ativo). Usado no MIX."""
    return _cerebro(_CEREBRO_COPY.get(fmt, "copywriter.md"), SYSTEM_COPY)


# Quantos criativos o usuário pediu (o número é o TOTAL do lote, repartido entre os
# formatos selecionados — 3 pedidas + 3 formatos = 1 de cada). A variação por copy vem
# depois, na etapa de Estilo visual ("direções por copy").
_RE_QTD_COPIES = re.compile(r"(\d{1,3})\s*cop", re.IGNORECASE)


def _qtd_pedida(mensagem: str) -> int | None:
    m = _RE_QTD_COPIES.search(mensagem or "")
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return max(1, min(n, 60)) if n > 0 else None


def _repartir(total: int, k: int) -> list[int]:
    """Divide `total` em `k` partes o mais parelho possível; o resto vai pros primeiros
    (o 1º formato é o ativo). Ex.: 3/3 -> [1,1,1]; 5/3 -> [2,2,1]; 3/4 -> [1,1,1,0]."""
    if k <= 0:
        return []
    base, rem = divmod(max(0, total), k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def _gerar_copies_um_formato(produto, mensagem, modelo, fmt, add_dirs, qtd=None):
    """Gera copies de UM formato (chamada fresca), taggeadas com esse formato.
    Se `qtd` vier, instrui o modelo a gerar exatamente essa quantidade neste formato.
    Retorna (texto_resposta_limpo, copies|[])."""
    if qtd:
        plural = "copy" if qtd == 1 else "copies"
        mensagem = (f"{mensagem}\n\n[INSTRUÇÃO OBRIGATÓRIA] Gere EXATAMENTE {qtd} {plural} "
                    f"neste formato — nem mais, nem menos. Responda SEMPRE terminando com o bloco "
                    f"```copies-json``` (as copies vivem só dentro dele; nunca como texto solto), "
                    f"senão este formato sai vazio.")
    base = PREAMBULO_COPY.replace("{cerebro}", "\x00CEREBRO\x00")
    texto = base.format(contexto=montar_contexto_produto(produto), mensagem=mensagem)
    texto = texto.replace("\x00CEREBRO\x00", _cerebro_copy_fmt(fmt))
    res = _bridge(modelo).conversar(texto, session_id=None, modelo=modelo,
                                    system_prompt=SYSTEM_COPY, timeout=420, add_dirs=add_dirs)
    limpo, copies = _parse_copies_bloco(res.get("resposta", ""))
    if not copies:
        # Resposta veio mas sem bloco ```copies-json``` válido (ex.: JSON quebrado por
        # aspas duplas, ou o modelo não entregou copies). NÃO tratar como "throttle":
        # levanta com o trecho real pra causa aparecer no banner em vez de ser mascarada.
        trecho = (res.get("resposta", "") or "").strip().replace("\n", " ")[:180]
        raise RuntimeError(f"sem bloco copies-json válido na resposta: {trecho!r}")
    for c in copies:
        c["formato"] = fmt
    return limpo, copies


def _copies_prontas(mensagem: str) -> list[dict] | None:
    """Reconhece copies coladas pelo usuario e apenas as normaliza para o fluxo."""
    texto = (mensagem or "").strip()
    if not texto:
        return None
    if texto.startswith("```"):
        texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE | re.DOTALL).strip()
    dados = None
    try:
        bruto = json.loads(texto)
        dados = bruto.get("copies") if isinstance(bruto, dict) else bruto
    except (json.JSONDecodeError, TypeError):
        pass
    # Aceita o formato visual da interface: copy_11 seguido de headline, apoio e CTA.
    if not isinstance(dados, list):
        marcadores = list(re.finditer(r"(?im)^\s*(?:[-*•]\s*)?(copy\s*[_-]?\s*\d+)\s*:?[\s]*$", texto))
        if marcadores:
            dados = []
            for i, marcador in enumerate(marcadores):
                fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(texto)
                linhas = [linha.strip() for linha in texto[marcador.end():fim].splitlines() if linha.strip()]
                if len(linhas) >= 2:
                    copy_id = re.sub(r"copy\s*[_-]?\s*(\d+)", r"copy_\1", marcador.group(1), flags=re.I)
                    dados.append({"id": copy_id,
                                  "headline": linhas[0], "apoio": " ".join(linhas[1:-1]),
                                  "cta": linhas[-1]})
    if not isinstance(dados, list):
        chaves = re.findall(r"(?im)^\s*(?:copy\s*\d+\s*)?(headline|titulo|angulo|ângulo|apoio|subheadline|cta)\s*:", texto)
        if len(set(k.lower() for k in chaves)) < 2:
            return None
        blocos = re.split(r"(?im)(?=^\s*(?:copy\s*\d+\s*)?headline\s*:)", texto)
        dados = []
        for bloco in blocos:
            if not bloco.strip():
                continue
            item = {}
            for chave, valor in re.findall(r"(?im)^\s*(?:copy\s*\d+\s*)?(headline|titulo|angulo|ângulo|apoio|subheadline|cta)\s*:\s*(.+?)(?=\n\s*(?:copy\s*\d+\s*)?(?:headline|titulo|angulo|ângulo|apoio|subheadline|cta)\s*:|$)", bloco, re.DOTALL):
                item[chave.lower().replace("título", "headline").replace("titulo", "headline").replace("ângulo", "angulo")] = valor.strip()
            if item:
                dados.append(item)
    # Formato colado da própria interface: copy_11 em uma linha e, abaixo,
    # headline, apoio e CTA sem rótulos ou dois-pontos.
    if not isinstance(dados, list):
        marcadores = list(re.finditer(r"(?im)^\s*(?:[-*•]\s*)?(copy\s*[_-]?\s*\d+)\s*:?[\s]*$", texto))
        if marcadores:
            dados = []
            for i, marcador in enumerate(marcadores):
                fim = marcadores[i + 1].start() if i + 1 < len(marcadores) else len(texto)
                linhas = [linha.strip() for linha in texto[marcador.end():fim].splitlines() if linha.strip()]
                if len(linhas) < 2:
                    continue
                dados.append({
                    "id": re.sub(r"copy\s*[_-]?\s*(\d+)", r"copy_\1", marcador.group(1), flags=re.I),
                    "headline": linhas[0],
                    "apoio": " ".join(linhas[1:-1]),
                    "cta": linhas[-1],
                })
    if not isinstance(dados, list) or not dados:
        return None
    saida = []
    for i, item in enumerate(dados, 1):
        if not isinstance(item, dict):
            continue
        def campo(*nomes):
            for nome in nomes:
                if str(item.get(nome, "")).strip():
                    return str(item[nome]).strip()
            return ""
        headline = campo("headline", "titulo", "title")
        if not headline:
            continue
        saida.append({
            "id": str(item.get("id") or f"copy_{i:02d}"),
            "angulo": campo("angulo", "ângulo") or "Copy pronta",
            "headline": headline,
            "subheadline": campo("subheadline"),
            "apoio": campo("apoio", "texto", "descricao", "descrição"),
            "corpo": campo("corpo", "legenda"),
            "cta": campo("cta", "botao", "botão"),
        })
    return saida or None


def _ref_estilo_dir(produto: str) -> Path:
    return product_dir(produto) / REF_ESTILO_DIR


def _listar_ref_estilo(produto: str) -> list[str]:
    d = _ref_estilo_dir(produto)
    if not d.exists():
        return []
    return sorted(f.name for f in d.iterdir()
                  if f.is_file() and f.suffix.lower() in IMG_EXTS)


def _salvar_ref_estilo(produto: str, files) -> list[str]:
    """Salva imagens de referência de ESTILO (persistentes) e retorna os nomes salvos."""
    d = _ref_estilo_dir(produto)
    salvos = []
    for f in files or []:
        # overwrite: reanexar a mesma imagem substitui, não acumula cópias.
        nome = _salvar_upload(f, d, IMG_EXTS, _MAX_IMG, "estilo.png", overwrite=True)
        if nome:
            salvos.append(nome)
    return salvos


def _ref_info_path(produto: str, tipo: str) -> Path:
    nome = REF_ESTILO_INFO if tipo == "estilo" else REF_PRODUTO_INFO
    return product_dir(produto) / "output" / nome


def _ler_ref_info(produto: str, tipo: str) -> list[dict]:
    f = _ref_info_path(produto, tipo)
    if not f.exists():
        return []
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(dados, list):
            return []
        for item in dados:
            if isinstance(item, dict) and "copy" in item:
                item["copy"] = _texto_copy_visual(item.get("copy"))
        return dados
    except Exception:  # noqa: BLE001
        return []


def _salvar_ref_info(produto: str, tipo: str, itens: list[dict]) -> None:
    atomic_write_json(_ref_info_path(produto, tipo), itens[:500])


def _referencias_com_contexto(produto: str, tipo: str) -> list[dict]:
    pasta = _ref_estilo_dir(produto) if tipo == "estilo" else product_dir(produto) / "referencia"
    antigos = _ler_ref_info(produto, tipo)
    por_nome = {str(i.get("arquivo")): i for i in antigos if isinstance(i, dict)}
    nomes = [f.name for f in pasta.iterdir()] if pasta.exists() else []
    return [{"arquivo": n, "contexto": str(por_nome.get(n, {}).get("contexto", ""))} for n in sorted(nomes)
            if Path(n).suffix.lower() in IMG_EXTS]


def _bloco_anexos_copy(produto: str, files, session_id) -> tuple[str, list[str]]:
    """Salva os anexos EFÊMEROS do chat (modo copy) e devolve (bloco_de_instrucao, add_dirs).

    Numa conversa nova (session_id vazio) limpa os anexos antigos antes de salvar,
    para o Claude nunca reler imagem de outra conversa.
    """
    d = product_dir(produto) / "output" / ANEXOS_CHAT_DIR
    if not session_id and d.exists():
        for f in d.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass
    caminhos = []
    for f in files or []:
        nome = _salvar_upload(f, d, IMG_EXTS, _MAX_IMG, "anexo.png")
        if nome:
            caminhos.append(str(d / nome))
    if not caminhos:
        return "", []
    lista = "\n".join(f"- {c}" for c in caminhos)
    bloco = (
        "\n\n[IMAGEM(NS) DE REFERÊNCIA ANEXADA(S) PELO USUÁRIO — modo copy]\n"
        "Antes de escrever, use a ferramenta Read para VER cada imagem nestes caminhos:\n"
        + lista + "\n"
        "O usuário anexou essa(s) referência(s) DE PROPÓSITO: pesa forte. Siga o que ele pedir "
        "sobre ela (estilo de texto, tom, ângulo, ideia, layout da copy). Ela COMPLEMENTA o "
        "contexto do produto, não o substitui: identidade, oferta, tom e proibições do produto "
        "continuam valendo. Nunca invente número/preço/estoque só porque apareceu na imagem.\n")
    return bloco, [str(d)]


@app.route("/api/chat", methods=["POST"])
def chat():
    # Tudo dentro do try: garante que o front SEMPRE receba JSON (nunca um 500 HTML,
    # que viraria "Erro de conexão" e esconderia a causa real).
    try:
        # Com anexos de imagem o front manda multipart; sem anexos, JSON (como antes).
        multipart = bool(request.content_type and request.content_type.startswith("multipart/"))
        if multipart:
            produto = request.form.get("produto")
            mensagem = request.form.get("mensagem", "")
            session_id = request.form.get("session_id") or None
            modelo = request.form.get("modelo") or "sonnet"
            anexos = request.files.getlist("anexos")
        else:
            body = request.get_json(force=True)
            produto = body["produto"]
            mensagem = body.get("mensagem", "")
            session_id = body.get("session_id")
            modelo = body.get("modelo") or "sonnet"
            anexos = []
        product_dir(produto)
        if not isinstance(mensagem, str) or len(mensagem) > 30000:
            return jsonify({"ok": False, "erro": "Mensagem grande demais."}), 400

        # Anexos em modo "estilo": salva como referência de estilo PERSISTENTE do produto
        # e NÃO injeta no chat de copy (o produto/texto não muda; ela é pra imagem).
        bloco_anexos, add_dirs = "", None
        if anexos:
            bloco_anexos, add_dirs = _bloco_anexos_copy(produto, anexos, session_id)

        # Anexou só referência de estilo, sem texto: registra e responde sem chamar o modelo.
        prontas = _copies_prontas(mensagem) if not anexos else None
        if prontas:
            resposta, copies = _processar_bloco_copies(
                produto, "Copies prontas reconhecidas e formatadas.\n```copies-json\n"
                + json.dumps(prontas, ensure_ascii=False) + "\n```", preservar_usadas=False)
            return jsonify({"ok": True, "resposta": resposta, "session_id": session_id,
                            "copies": copies})

        # MIX de formatos: se há +1 formato marcado e é geração nova (sem sessão),
        # gera copies de CADA formato e junta, taggeando cada copy com seu formato.
        # Cada criativo do lote nasce no formato certo; o refino multi-turno (com
        # session_id) e o formato único seguem o caminho simples de sempre.
        formatos_sel = _ler_formatos(produto)
        if not session_id and len(formatos_sel) > 1:
            # O número pedido é o TOTAL do lote, repartido entre os formatos marcados
            # (3 copies + 3 formatos = 1 de cada). Sem número explícito → 1 por formato.
            total = _qtd_pedida(mensagem) or len(formatos_sel)
            cotas = _repartir(total, len(formatos_sel))
            todas, textos, vazios = [], [], []
            for idx, fmt in enumerate(formatos_sel):
                cota = cotas[idx]
                if cota <= 0:
                    continue   # não sobrou cota pra este formato (total < nº de formatos)
                copies_f, erro_fmt = [], ""
                # Retry 1x: chamadas em sequência às vezes tomam throttle transitório;
                # não deixamos o formato sumir silenciosamente do mix. O erro real (se
                # houver) é guardado pra aparecer no banner em vez de virar "throttle".
                for tentativa in range(2):
                    try:
                        _, copies_f = _gerar_copies_um_formato(
                            produto, mensagem + bloco_anexos, modelo, fmt, add_dirs, qtd=cota)
                    except Exception as e:  # noqa: BLE001
                        copies_f, erro_fmt = [], str(e)
                    if copies_f:
                        erro_fmt = ""
                        break
                    time.sleep(2)
                if copies_f:
                    copies_f = copies_f[:cota]   # capa pra o lote bater com o total pedido
                    textos.append(f"**{_info_formato(fmt)}**: {len(copies_f)} copies")
                    todas.extend(copies_f)
                else:
                    rotulo = _info_formato(fmt)
                    if erro_fmt:
                        rotulo += f" ({erro_fmt[:180]})"
                    vazios.append(rotulo)
            if not todas:
                detalhe = ("; ".join(vazios)) or "o modelo pode estar sob limite"
                return jsonify({"ok": True, "session_id": None,
                                "resposta": "Não consegui gerar copies neste lote: " + detalhe + ". Tente de novo."})
            for i, c in enumerate(todas, 1):
                c["id"] = f"copy_{i:02d}"
            _salvar_copies_lista(produto, todas, preservar_usadas=True)
            resposta = "Mix gerado: " + ", ".join(textos) + "."
            if vazios:
                resposta += (" ⚠️ Não vieram: " + ", ".join(vazios)
                             + ". Reenvie pra completar o mix.")
            return jsonify({"ok": True, "resposta": resposta, "session_id": None, "copies": todas})

        # Formato único (ou refino): troca o cérebro de copy pelo ativo. A data
        # literal da Notícia NÃO entra aqui (a copy é atemporal); ela é injetada só
        # no passo de imagem, onde o print realmente renderiza a data.
        if session_id:
            texto = mensagem + bloco_anexos
        else:
            # PREAMBULO_COPY usa .format; o cérebro tem chaves { } do bloco de exemplo,
            # então injetamos por replace (não por format) pra não quebrar.
            base = PREAMBULO_COPY.replace("{cerebro}", "\x00CEREBRO\x00")
            texto = base.format(
                contexto=montar_contexto_produto(produto),
                mensagem=mensagem + bloco_anexos)
            texto = texto.replace("\x00CEREBRO\x00", _cerebro_copy(produto))

        res = _bridge(modelo).conversar(
            texto, session_id=session_id, modelo=modelo,
            system_prompt=SYSTEM_COPY, timeout=420, add_dirs=add_dirs)
        resposta, copies = _processar_bloco_copies(produto, res.get("resposta", ""))
        payload = {"ok": True, **res, "resposta": resposta}
        if copies is not None:
            payload["copies"] = copies
        return jsonify(payload)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/aprender/<produto>", methods=["POST"])
def aprender(produto):
    """Destila a conversa (via --resume da própria sessão) em aprendizados duráveis.

    É disparado automaticamente pelo front ao fim de uma conversa. Falha aqui NUNCA
    é fatal para o usuário: é best-effort, então devolvemos ok:false silencioso.
    """
    try:
        body = request.get_json(force=True)
        session_id = body.get("session_id")
        modelo = body.get("modelo") or "sonnet"
        if not session_id:
            return jsonify({"ok": False, "erro": "sem sessão para aprender"}), 200

        res = _bridge(modelo).conversar(
            PROMPT_APRENDER, session_id=session_id, modelo=modelo,
            system_prompt=SYSTEM_APRENDER, timeout=180)
        try:
            itens = _extrair_json(res.get("resposta", ""))
        except Exception:  # noqa: BLE001 — resposta sem JSON: nada a aprender
            itens = []
        if not isinstance(itens, list):
            itens = []
        # Só strings curtas, limpas e não vazias.
        limpos = [str(i).strip() for i in itens
                  if isinstance(i, (str, int, float)) and str(i).strip()][:40]
        adicionados = _merge_aprendizado(produto, limpos)
        return jsonify({"ok": True, "adicionados": adicionados})
    except Exception as e:  # noqa: BLE001 — best-effort, não quebra o fluxo do usuário
        return jsonify({"ok": False, "erro": str(e)}), 200


@app.route("/api/aprendizado/<produto>", methods=["GET"])
def get_aprendizado(produto):
    f = _aprendizado_path(produto)
    itens = _ler_aprendizado_itens(produto)
    return jsonify({"conteudo": f.read_text(encoding="utf-8", errors="replace") if f.exists() else "",
                    "itens": itens, "total": len(itens)})


@app.route("/api/aprendizado/<produto>", methods=["POST"])
def salvar_aprendizado(produto):
    """Salva a memória editada na aba de contexto (uma linha por aprendizado)."""
    body = request.get_json(force=True)
    conteudo = str(body.get("conteudo", ""))[:100000]
    # Normaliza para bullets: cada linha não-vazia (sem '# ' de cabeçalho) vira um item.
    itens: list[str] = []
    vistos: set[str] = set()
    for linha in conteudo.replace("\r\n", "\n").split("\n"):
        s = linha.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        if s and s.lower() not in vistos:
            itens.append(s)
            vistos.add(s.lower())
    _escrever_aprendizado_itens(produto, itens)
    return jsonify({"ok": True, "total": len(itens)})


@app.route("/api/verdade_visual/<produto>", methods=["GET"])
def get_verdade_visual(produto):
    f = _verdade_path(produto)
    itens = _ler_verdade_itens(produto)
    return jsonify({"conteudo": f.read_text(encoding="utf-8", errors="replace") if f.exists() else "",
                    "itens": itens, "total": len(itens)})


@app.route("/api/verdade_visual/<produto>", methods=["POST"])
def salvar_verdade_visual(produto):
    """Salva a verdade visual editada na aba de contexto (uma linha por fato)."""
    body = request.get_json(force=True)
    conteudo = str(body.get("conteudo", ""))[:100000]
    itens: list[str] = []
    vistos: set[str] = set()
    for linha in conteudo.replace("\r\n", "\n").split("\n"):
        s = linha.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- "):
            s = s[2:].strip()
        if s and s.lower() not in vistos:
            itens.append(s)
            vistos.add(s.lower())
    _escrever_verdade_itens(produto, itens)
    return jsonify({"ok": True, "total": len(itens)})


@app.route("/api/copies/<produto>", methods=["GET"])
def get_copies(produto):
    f = product_dir(produto) / "output" / "copies.md"
    return jsonify({"conteudo": f.read_text(encoding="utf-8") if f.exists() else ""})


@app.route("/api/copies/<produto>", methods=["POST"])
def salvar_copies(produto):
    body = request.get_json(force=True)
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out / "copies.md", str(body.get("conteudo", ""))[:100000])
    return jsonify({"ok": True})


def _copies_md_do_json(copies: list[dict]) -> str:
    """Deriva um copies.md legível a partir do copies.json (compatibilidade)."""
    blocos = []
    for c in copies:
        sub = str(c.get('subheadline', '') or '').strip()
        sub_md = f"{sub}\n\n" if sub else ""
        apoio = str(c.get('apoio', '') or '').strip()
        apoio_md = f"{apoio}\n\n" if apoio else ""
        blocos.append(f"## {c.get('angulo', c.get('id', ''))}\n\n"
                      f"**{c.get('headline', '')}**\n\n"
                      f"{sub_md}"
                      f"{apoio_md}"
                      f"{c.get('corpo', '')}\n\n"
                      f"_{c.get('cta', '')}_")
    return "\n\n---\n\n".join(blocos) + "\n"


@app.route("/api/copies_json/<produto>", methods=["GET"])
def get_copies_json(produto):
    f = product_dir(produto) / "output" / "copies.json"
    if not f.exists():
        return jsonify([])
    try:
        return jsonify(json.loads(f.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return jsonify([])


def _maior_num_criativo(prompts: list[dict]) -> int:
    maior = 0
    for p in prompts:
        m = re.match(r"criativo_(\d+)", str(p.get("id", "")))
        if m:
            maior = max(maior, int(m.group(1)))
    return maior


def _num_de_copy(copy_id) -> int | None:
    """Extrai o número de um id de copy (ex.: 'copy_01' -> 1, 'copy_12' -> 12)."""
    m = re.search(r"(\d+)", str(copy_id or ""))
    return int(m.group(1)) if m else None


def _visuais_path(produto: str) -> Path:
    return product_dir(produto) / "output" / "visuais.json"


def _estilo_chat_path(produto: str) -> Path:
    return product_dir(produto) / "output" / "estilo_visual_chat.json"


def _ler_estilo_chat(produto: str) -> dict:
    f = _estilo_chat_path(produto)
    if not f.exists():
        return {"ultimo_prompt": "", "mensagens": []}
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {"ultimo_prompt": "", "mensagens": []}
    except Exception:  # noqa: BLE001
        return {"ultimo_prompt": "", "mensagens": []}


def _ler_visuais(produto: str) -> list[dict]:
    f = _visuais_path(produto)
    if not f.exists():
        return []
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except Exception:  # noqa: BLE001
        return []


def _bloco_influenciadores() -> str:
    """Bloco injetado em TODA etapa que escreve cena/prompt (direções visuais, chat
    de estilo, prompts finais, agente de ideias): ensina a convenção @Nome, que é o
    que liga as fotos reais do influenciador na geração. Vazio se não houver nenhum."""
    nomes = gerar.influenciadores_registrados()
    if not nomes:
        return ""
    lista = ", ".join("@" + n for n in nomes)
    return (
        "\n===== INFLUENCIADORES CADASTRADOS =====\n"
        f"Influenciadores reais disponíveis nesta ferramenta: {lista}.\n"
        "Se o usuário pedir um deles numa cena (com ou sem o @), escreva o token @Nome "
        "LITERAL (com o @) na direção visual/prompt daquele criativo — é esse token que "
        "anexa as fotos reais da pessoa na geração da imagem. NUNCA troque por 'uma "
        "influenciadora' nem remova o @. Use o token SÓ nos criativos em que o usuário "
        "pediu essa pessoa; 'uma pessoa/cliente/modelo' genérica continua genérica, sem @. "
        "Não invente @nomes fora desta lista.\n"
    )


def _texto_copy_visual(valor, fallback="") -> str:
    if isinstance(valor, dict):
        return str(valor.get("headline") or valor.get("titulo") or valor.get("title") or fallback).strip()
    texto = str(valor or "").strip()
    if texto.startswith("{"):
        try:
            obj = json.loads(texto)
            if isinstance(obj, dict):
                return str(obj.get("headline") or obj.get("titulo") or obj.get("title") or fallback).strip()
        except Exception:  # noqa: BLE001
            pass
    return texto or str(fallback or "").strip()


def _normalizar_visuais(dados, copies: list[dict]) -> list[dict]:
    por_copy = {str(c.get("id")): c for c in copies}
    contagens: dict[str, int] = {}
    saida = []
    for i, item in enumerate(dados if isinstance(dados, list) else []):
        if not isinstance(item, dict):
            continue
        copy_id = str(item.get("copy_id") or "")
        if copy_id not in por_copy and i < len(copies):
            copy_id = str(copies[i].get("id") or "")
        if not copy_id or copy_id not in por_copy:
            continue
        c = por_copy[copy_id]
        contagens[copy_id] = contagens.get(copy_id, 0) + 1
        variante = contagens[copy_id]
        visual_id = str(item.get("id") or "").strip()
        if not visual_id:
            visual_id = f"visual_{copy_id}" if variante == 1 else f"visual_{copy_id}_v{variante}"
        saida.append({
            "id": visual_id, "copy_id": copy_id,
            "variacao": variante,
            "papel": ("produto" if variante == 1 else
                       "expert" if variante == 2 else "criativa"),
            "angulo": str(item.get("angulo") or c.get("angulo") or "ângulo"),
            "copy": _texto_copy_visual(item.get("copy"), c.get("headline") or ""),
            "visual": str(item.get("visual") or item.get("direcao") or "").strip(),
        })
    return saida


@app.route("/api/confirmar_estilo/<produto>", methods=["POST"])
def confirmar_estilo(produto):
    body = request.get_json(silent=True) or {}
    modelo = body.get("modelo") or "sonnet"
    ids = [str(i) for i in (body.get("copy_ids") or [])]
    instrucoes = str(body.get("instrucoes") or "").strip()[:12000]
    try:
        variantes = max(2, min(6, int(body.get("variantes_por_copy") or 2)))
    except (TypeError, ValueError):
        variantes = 2
    copies_f = product_dir(produto) / "output" / "copies.json"
    if not copies_f.exists():
        return jsonify({"ok": False, "erro": "Gere as copies primeiro."}), 400
    todas = json.loads(copies_f.read_text(encoding="utf-8"))
    copies = [c for c in todas if str(c.get("id")) in set(ids)]
    if not copies:
        return jsonify({"ok": False, "erro": "Nenhuma copy corresponde à seleção."}), 400
    def _bloco_formato(fmt):
        if fmt == "wikihow":
            return """
DIREÇÃO DE ARTE (FORMATO WIKIHOW):
Cada direção é uma ILUSTRAÇÃO estilo wikiHow / artigo de saúde: contorno preto grosso, cor
chapada (cel-shading), corpo/cena em CINZA dessaturado com UM acento de cor saturada no
mecanismo. NÃO é foto, still de produto nem cena publicitária. Para cada direção escolha:
- o MECANISMO a desenhar e ONDE (o ponto de dor, o nervo, o órgão, a toxina), coerente com o ângulo da copy;
- o FORMATO visual entre: inset_lupa, inflamacao_localizada, nervo_destacado, x_vilao, antes_depois, comparativo, detox, pressao;
- se mostra o produto (REGRA 1 A CADA 2: alterne, metade das direções COM o produto redesenhado no mesmo estilo de ilustração, metade SEM produto);
- onde entra o TÍTULO embutido na arte.
CÓDIGO DE CORES POR FUNÇÃO (regra dura): amarelo=nervo, vermelho=inflamação/órgão irritado,
rosa/magenta=dor irradiando ou toxina, verde/teal=toxina ou alívio, ciano=músculo ativado/zona
em foco. Detalhe ampliado vive DENTRO de um inset (lupa/bolha), nunca solto.
VARIEDADE: cada direção do grupo usa um mecanismo/formato visual diferente. Nada de foto realista.
"""
        if fmt == "noticia":
            return """
DIREÇÃO DE ARTE (FORMATO NOTÍCIA):
Cada direção é um PRINT de artigo de portal em fundo BRANCO, layout FIXO na ordem: tarja
VERMELHA de categoria no topo (texto branco caixa alta); manchete preta pesada à esquerda;
subtítulo cinza; linha 'Por <jornalista>' (nome em vermelho) e, abaixo, a data literal em cinza;
três botões cinza de compartilhar (Facebook, WhatsApp, share); e embaixo uma imagem relacionada
ao produto num retângulo de cantos arredondados. Texto nítido e legível.
O que VARIA entre as direções é só a imagem de baixo (REGRA 1 A CADA 2: metade com o PRODUTO real,
metade com uma CENA realista relacionada ao tema). PROIBIDO qualquer marca de portal (g1, Globo,
UOL), ícone de vídeo, mudo ou timestamp. Use a data literal fornecida no contexto, nunca invente.
""" + _bloco_influenciadores()
        # padrao
        bloco = """
DIREÇÃO CRIATIVA OBRIGATÓRIA:
Não trate cada copy como uma sessão de fotos com uma mulher por padrão. O produto é o herói.

VARIEDADE É REGRA DURA (não sugestão). Antes de escrever a primeira direção, distribua as cenas do
lote INTEIRO. Cada direção precisa diferir das outras em pelo menos DOIS eixos:
- cenário/locação (vitrine, ponto de venda, balcão, prateleira/display, sala de casa, rua, mesa, estúdio com clima)
- momento/luz (fim de tarde pela janela, noite com neon, manhã na rua, luz dramática de campanha)
- ângulo/enquadramento (close hero, plano aberto, top-down, produto em uso, still life, cena com pessoa)
- layout do texto (topo largo, lateral, faixa inferior)
PROIBIDO duas direções que pareçam takes da mesma foto. Se ao reler o lote duas se repetem, troque uma.
Puxe entre: vitrine/ponto de venda, prateleira ou display, still life com objetos ligados à promessa,
close hero, composição editorial, produto em uso, oferta gráfica e outros cenários de campanha real.

ANATOMIA (regra dura): pessoas são opcionais e o produto é sempre o herói. Se uma direção usar pessoa,
descreva UMA pessoa num gesto simples e nítido, NUNCA várias mãos juntas, dedos entrelaçados, brinde em
grupo ou multidão em primeiro plano (o gerador de imagem deforma dedos e membros nessas cenas).

Cada direção explica uma ideia visual diferente, mantendo o produto real, o contexto e a linguagem das referências.
""" + _bloco_influenciadores()
        influ_padrao = _influ_do_produto(produto)
        if influ_padrao:
            bloco += (
                f"\nINFLUENCIADORA PADRÃO DESTE PRODUTO: @{influ_padrao}. Regra de distribuição do "
                f"lote: PELO MENOS 1/3 das direções (arredonde para cima) tem essa pessoa em cena, "
                f"nessas escreva o token @{influ_padrao} LITERAL dentro do campo visual (ex.: "
                f"'@{influ_padrao} no balcão da loja, erguendo o produto...'). Nas direções com ela, "
                "ela é a protagonista humana (a regra de evitar pessoas não se aplica a elas). As "
                "DEMAIS direções ficam SEM ela: produto como herói ou pessoa genérica sem @. Se o "
                "usuário pedir explicitamente outra distribuição, o pedido dele manda.\n")
        bloco += f"""
SLOTS OBRIGATÓRIOS POR COPY (na ordem):
1. A primeira direção é FOCADA NO PRODUTO: produto como herói, sem pessoa, em close hero,
   still life, vitrine, display ou composição publicitária equivalente.
2. A segunda direção é FOCADA NO EXPERT COM O PRODUTO: o expert aparece claramente em um gesto
   simples usando, segurando ou apresentando o produto. Se houver expert padrão cadastrado, use-o.
3. As direções 3 até {variantes} são CRIATIVAS: ideias próprias da IA, diferentes das duas primeiras,
   explorando metáfora visual, contexto de uso, merchandising, editorial, prova visual ou outra
   solução publicitária forte. Não repita a estrutura da direção 1 ou 2.
Respeite rigorosamente essa ordem dentro de cada grupo de copy. Mantenha exatamente os campos pedidos.
"""
        return bloco

    # MIX: agrupa as copies pelo FORMATO de cada uma e gera as direções por grupo
    # (cada formato com seu bloco de direção + refs). Formato único = 1 grupo só.
    por_fmt: dict[str, list] = {}
    for c in copies:
        por_fmt.setdefault(c.get("formato") or _formato_ativo(produto), []).append(c)
    refs_estilo = _referencias_com_contexto(produto, "estilo") if "IMG_EXTS" in globals() else []
    try:
        visuais_all, textos = [], []
        for fmt, grupo in por_fmt.items():
            contexto_fmt = montar_contexto_produto(produto) + _bloco_data_noticia(produto, fmt)
            pedido = (f"""Defina {variantes} direção(ões) visual(is) para cada copy abaixo. Não escreva o prompt final ainda.
Crie uma cena, enquadramento, composição, paleta, clima e distribuição do texto claramente
diferentes para cada item, sempre mantendo o produto real das fotos de referência.
Responda com uma explicação curta e depois ```visuais-json``` com um array agrupado por copy,
com exatamente {variantes} itens para cada copy. Cada item deve ter os campos copy_id, angulo,
copy e visual. As direções do mesmo grupo precisam ser ideias realmente diferentes.

CONTEXTO DO PRODUTO:
{contexto_fmt}

COPIES:
{json.dumps(grupo, ensure_ascii=False, indent=2)}""" + _bloco_formato(fmt))
            if instrucoes:
                pedido += ("\n\nDIREÇÃO DO USUÁRIO (siga à risca ao criar as cenas; é o que ele "
                           f"quer ver nas imagens):\n{instrucoes}")
            dirs = [str(product_dir(produto) / "referencia")]
            if refs_estilo:
                dirs.append(str(_ref_estilo_dir(produto)))
            if fmt == "wikihow" and (PROMPTS_DIR / "wikihow_ref").exists():
                dirs.append(str(PROMPTS_DIR / "wikihow_ref"))
            res = _bridge(modelo).conversar(pedido, session_id=None, modelo=modelo,
                                            system_prompt=SYSTEM_ESTILO, timeout=420, add_dirs=dirs)
            texto = res.get("resposta", "")
            vis = _normalizar_visuais(_extrair_json(texto), grupo)
            for v in vis:
                v["formato"] = fmt
            visuais_all += vis
            limpo = re.sub(r"```visuais-json.*?```", "", texto, flags=re.S).strip()
            if len(por_fmt) > 1:
                textos.append(f"**{_info_formato(fmt)}**: {limpo}")
            else:
                textos.append(limpo)
        if not visuais_all:
            raise ValueError("A IA não retornou direções visuais válidas.")
        atomic_write_json(_visuais_path(produto), visuais_all)
        return jsonify({"ok": True, "resposta": "\n\n".join(t for t in textos if t),
                        "visuais": visuais_all, "session_id": None})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/promover_prompts/<produto>", methods=["POST"])
def promover_prompts(produto):
    """Portão entre a aba Estilo visual e a aba Prompts. Pega as direções visuais
    SELECIONADAS e gera, numa única chamada ao modelo, os PROMPTS FINAIS de imagem
    prontos para gerar. Com 'versões por copy' = N, produz N prompts CLARAMENTE
    diferentes por copy (criativo_NN_v1..vN); com N = 1, um por copy (criativo_NN).
    A aba Prompts então só revisa e gera as imagens — sem reprocessar o modelo."""
    body = request.get_json(silent=True) or {}
    modelo = body.get("modelo") or "sonnet"
    copy_ids = {str(i) for i in (body.get("copy_ids") or [])}
    if not copy_ids:
        return jsonify({"ok": False, "erro": "Selecione ao menos uma direção."}), 400
    try:
        variantes = max(1, min(6, int(body.get("variantes_por_copy") or 1)))
    except (TypeError, ValueError):
        variantes = 1

    sel = [v for v in _ler_visuais(produto)
           if str(v.get("copy_id")) in copy_ids or str(v.get("id")) in copy_ids]
    if not sel:
        return jsonify({"ok": False, "erro": "Nenhuma direção corresponde à seleção."}), 400
    # Cada direção visual selecionada deve produzir um prompt.
    por_copy_sel: dict[str, int] = {}
    for visual in sel:
        cid = str(visual.get("copy_id") or "")
        por_copy_sel[cid] = por_copy_sel.get(cid, 0) + 1
    if por_copy_sel:
        variantes = max(por_copy_sel.values())

    copies_json_f = product_dir(produto) / "output" / "copies.json"
    if not copies_json_f.exists():
        return jsonify({"ok": False, "erro": "Salve as copies primeiro."}), 400
    todas = json.loads(copies_json_f.read_text(encoding="utf-8"))
    ids_copy = {str(v.get("copy_id")) for v in sel}
    selecionadas = [c for c in todas if str(c.get("id")) in ids_copy]
    if not selecionadas:
        return jsonify({"ok": False, "erro": "Nenhuma copy corresponde à seleção."}), 400

    existentes = _ler_prompts_existentes(produto)
    antes = {str(p.get("id")) for p in existentes if isinstance(p, dict)}
    try:
        # MIX: agrupa as copies selecionadas pelo FORMATO de cada uma e gera os
        # prompts por grupo (cada formato com seu cérebro de arte/refs/data). Encadeia
        # em `acc` pra cada grupo preservar os prompts dos outros. Formato único = 1 grupo.
        por_fmt: dict[str, list] = {}
        for c in selecionadas:
            por_fmt.setdefault(c.get("formato") or _formato_ativo(produto), []).append(c)
        acc = existentes
        for fmt, grupo in por_fmt.items():
            grupo_ids = {str(c.get("id")) for c in grupo}
            sel_grupo = [v for v in sel if str(v.get("copy_id")) in grupo_ids]
            acc = _gerar_prompts_finais(produto, modelo, grupo, sel_grupo,
                                        variantes, "", acc, formato=fmt)
        dados = acc
        out = product_dir(produto) / "output"
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out / "prompts.json", dados[:1000])
        _marcar_copies_usadas(produto, ids_copy)
        adicionados = sum(1 for p in dados
                          if isinstance(p, dict) and str(p.get("id")) not in antes)
        return jsonify({"ok": True, "total": len(dados), "adicionados": adicionados})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/estilo_visual/<produto>", methods=["GET", "POST"])
def estilo_visual(produto):
    if request.method == "GET":
        return jsonify(_ler_visuais(produto))
    body = request.get_json(force=True)
    visuais = body.get("visuais", [])
    atomic_write_json(_visuais_path(produto), visuais[:1000])
    return jsonify({"ok": True, "visuais": visuais[:1000]})


@app.route("/api/estilo_visual_chat/<produto>", methods=["GET", "POST"])
def estilo_visual_chat(produto):
    if request.method == "GET":
        return jsonify(_ler_estilo_chat(produto))
    body = request.get_json(force=True)
    mensagem = str(body.get("mensagem") or "").strip()[:30000]
    modelo = body.get("modelo") or "sonnet"
    session_id = body.get("session_id") or None
    visuais = body.get("visuais") or _ler_visuais(produto)
    if not mensagem:
        return jsonify({"ok": False, "erro": "Escreva um ajuste para continuar."}), 400
    historico = _ler_estilo_chat(produto)
    historico["ultimo_prompt"] = mensagem
    historico["mensagens"] = (historico.get("mensagens") or [])[-99:] + [{"texto": mensagem}]
    atomic_write_json(_estilo_chat_path(produto), historico)
    pedido = mensagem + "\n\nDIREÇÕES VISUAIS ATUAIS:\n" + json.dumps(visuais, ensure_ascii=False)
    refs_estilo = _referencias_com_contexto(produto, "estilo") if "IMG_EXTS" in globals() else []
    refs_produto = _referencias_com_contexto(produto, "produto") if "IMG_EXTS" in globals() else []
    pedido += "\n\nREFERENCIAS VISUAIS E CONTEXTO:\n" + "\n".join(
        f"- {i['arquivo']}: {i['contexto']}" for i in refs_estilo + refs_produto)
    pedido += _bloco_influenciadores()
    dirs = [str(product_dir(produto) / "referencia")]
    if refs_estilo:
        dirs.append(str(_ref_estilo_dir(produto)))
    try:
        res = _bridge(modelo).conversar(pedido, session_id=session_id, modelo=modelo,
                                        system_prompt=SYSTEM_ESTILO, timeout=420, add_dirs=dirs)
        texto = res.get("resposta", "")
        try:
            copies = [{"id": v.get("copy_id"), "headline": v.get("copy"), "angulo": v.get("angulo")}
                      for v in visuais]
            novos = _normalizar_visuais(_extrair_json(texto), copies)
        except Exception:
            novos = []
        if novos:
            atomic_write_json(_visuais_path(produto), novos)
            visuais = novos
            texto = re.sub(r"```visuais-json.*?```", "", texto, flags=re.S).strip()
        return jsonify({"ok": True, "resposta": texto, "visuais": visuais,
                        "session_id": res.get("session_id") or session_id})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


def _gerar_prompts_finais(produto, modelo, selecionadas, visuais_sel,
                          variantes_por_copy, instrucoes_usuario, existentes, formato=None):
    """Transforma as copies selecionadas (e suas direções visuais aprovadas) em
    prompts finais de imagem, gerando N variações CLARAMENTE diferentes por copy
    quando variantes_por_copy > 1. A numeração espelha a copy de origem
    (copy_01 -> criativo_01, ou criativo_01_v1..vN quando há variações).
    Devolve a lista completa: os prompts novos + os existentes que permanecem
    (os das copies que não foram regeradas agora). Faz UMA chamada ao modelo.
    `formato` None usa o ativo; no MIX, o caller passa o formato do grupo (cada
    grupo de copies do mesmo formato roda com seu cérebro de arte/refs/data)."""
    formato = formato or _formato_ativo(produto)
    copy_ids = [c.get("id") for c in selecionadas]
    copies = json.dumps(selecionadas, ensure_ascii=False, indent=2)
    instrucao_extra = (
        f"Gere EXATAMENTE {variantes_por_copy} entradas por copy do array acima, agrupadas "
        "por copy e na mesma ordem. Cada entrada do mesmo grupo deve ter uma IDEIA DE IMAGEM "
        "claramente diferente, mudando cena, ação/uso, ambiente, enquadramento ou metáfora visual "
        "e não apenas trocando sinônimos, sempre preservando a copy. "
        "Gere todas as ideias da primeira copy, depois todas da segunda e assim por diante. "
        "inclua o campo \"copy_id\" com o id EXATO da copy correspondente "
        "(ex.: \"copy_01\"). Não se preocupe com o campo \"id\"/numeração do criativo — "
        "ela é definida automaticamente depois a partir do copy_id."
    )
    if variantes_por_copy > 1:
        instrucao_extra += """

MODO DAS VARIAÇÕES:
Para cada copy, a VARIAÇÃO 1 é a versão segura: siga a direção visual aprovada e a lógica atual,
com produto fiel, composição publicitária clara e texto bem diagramado.
As VARIAÇÕES 2 em diante são explorações de DIREÇÃO CRIATIVA. Elas precisam vender a mesma copy
por uma ideia visual realmente diferente, não por sinônimos nem por uma simples troca de cor.
Pense em soluções como produto em vitrine de loja, balcão ou ponto de venda, prateleira ou display
de merchandising, still life com objetos ligados ao benefício, produto em destaque numa cena de
campanha, composição editorial, embalagem em arranjo hero, close de material e acabamento, ou uma
metáfora visual construída com o próprio produto. O produto continua sendo o protagonista.
Não use mulher, modelo ou pessoa como solução padrão; pessoas são opcionais e no máximo uma variação
de um grupo pode depender delas. Não repita a mesma estrutura de cena nas variações do grupo.

GRUPOS COM @INFLUENCIADOR (exceção que manda mais que tudo acima): se a direção visual aprovada
de uma copy contém um token @Nome, essa pessoa é a IDENTIDADE daquele criativo — TODAS as
variações do grupo a mantêm em cena, com o token @Nome LITERAL no prompt. As variações mudam
cenário, enquadramento, ação e luz — NUNCA removem nem trocam a pessoa. A regra de 'não usar
pessoa como solução padrão' NÃO se aplica a esses grupos. Nos grupos SEM @, ela continua valendo.
"""

    visual_bloco = ""
    if visuais_sel:
        visual_bloco = ("\n===== DIREÇÕES VISUAIS APROVADAS =====\n"
                        "Transforme cada direção abaixo em um prompt final, mantendo o copy literal.\n"
                        "Se a direção contém um token @Nome (influenciador real), o prompt final "
                        "correspondente DEVE conter o mesmo @Nome literal — nunca o substitua por "
                        "'uma pessoa/influenciadora' nem o remova.\n"
                        + json.dumps(visuais_sel, ensure_ascii=False, indent=2) + "\n")

    if visuais_sel:
        visual_bloco += (
            "\nREGRA DE FIDELIDADE DAS DIREÇÕES APROVADAS: cada item acima representa uma direção "
            "escolhida pelo usuário e deve gerar exatamente um prompt. Não invente outra ideia, "
            "não troque o papel produto/expert/criativa e não transforme a direção do expert em "
            "uma variação criativa. Preserve a ordem e o campo variacao.\n")

    contexto = montar_contexto_produto(produto) + _bloco_data_noticia(produto, formato)
    cerebro = _cerebro_arte_de(formato)

    # Referência de ESTILO ativa: se o usuário anexou imagem(ns) marcando "estilo",
    # o diretor de arte precisa VÊ-las (via --add-dir) e, em CADA prompt, escrever
    # exatamente COMO aplicá-las. Identidade do produto continua vindo das fotos reais.
    estilo_files = _listar_ref_estilo(produto)
    estilo_bloco = ""
    add_dirs = [str(product_dir(produto) / "referencia")]
    contextos_estilo = ""
    if estilo_files:
        d = _ref_estilo_dir(produto)
        lista = "\n".join(f"- {d / n}" for n in estilo_files)
        contextos_estilo = "\n".join(
            f"- {i['arquivo']}: {i['contexto']}" for i in _referencias_com_contexto(produto, "estilo")
            if i.get("contexto"))
        add_dirs.append(str(d))
        estilo_bloco = (
            "\n===== REFERÊNCIA DE ESTILO ANEXADA PELO USUÁRIO (obrigatória) =====\n"
            "Use a ferramenta Read para VER cada imagem nestes caminhos:\n" + lista + "\n"
            "Essas imagens definem o ESTILO VISUAL do criativo: paleta de cores, composição, "
            "enquadramento, tipografia e layout do texto, clima e acabamento. Elas NÃO definem o "
            "produto (o produto vem das fotos reais e nunca muda: forma, cor, logo e rótulos são "
            "sempre os das fotos de referência). O usuário anexou de propósito, então PESA FORTE: "
            "em CADA prompt que você gerar, descreva de forma EXPLÍCITA como aplicar essa "
            "referência de estilo (o que copiar dela: paleta, luz, enquadramento, diagramação do "
            "texto, mood), deixando claro que o produto mantém sua identidade real. Não copie o "
            "produto/objeto que aparece na referência de estilo; copie só a linguagem visual.\n")
    if estilo_files and contextos_estilo:
        estilo_bloco += "Contexto específico de uso das referências:\n" + contextos_estilo + "\n"

    # Formato WikiHow: anexa referências curadas do estilo (só no passo de TEXTO,
    # que é barato) pro modelo que escreve os prompts se ancorar no traço certo.
    if formato == "wikihow":
        wdir = PROMPTS_DIR / "wikihow_ref"
        if wdir.exists():
            add_dirs.append(str(wdir))
            anchors = ["nervo_01_grayscale_puro.jpg", "inset_04_grayscale.jpg",
                       "inflamacao_01_textbook.jpg", "x_vilao_01_limpo.jpg",
                       "antes_depois_01_intestino.jpg", "inset_01.jpg"]
            lista_w = "\n".join(f"- {wdir / a}" for a in anchors if (wdir / a).exists())
            estilo_bloco += (
                "\n===== REFERÊNCIAS DE ESTILO WIKIHOW (obrigatórias neste formato) =====\n"
                "Use a ferramenta Read para VER estas ilustrações de referência do estilo wikiHow:\n"
                + lista_w + "\n"
                "Elas definem o TRAÇO e a linguagem: contorno preto grosso, cor chapada, corpo/cena "
                "em cinza dessaturado com UM acento de cor no mecanismo, insets em lupa/bolha. "
                "Reproduza ESSE estilo em TODOS os prompts (a pasta tem mais exemplos por categoria). "
                "Não copie o conteúdo específico delas, copie a linguagem visual.\n")

    # Anti-repetição: cenas dos prompts que JÁ existem e vão continuar no lote
    # (geração parcial). O modelo não pode repetir essas cenas nas entradas novas.
    nums_novos = {n for n in (_num_de_copy(i) for i in copy_ids) if n is not None}
    cenas_existentes = ""
    if existentes:
        manter = [p for p in existentes if isinstance(p, dict)
                  and _num_de_copy(p.get("copy_id")) not in nums_novos]
        if manter:
            linhas = "\n".join(
                f"- {p.get('id')}: {p.get('formato', '?')} | "
                f"{' '.join(str(p.get('prompt', '')).split()[:14])}..."
                for p in manter)
            cenas_existentes = (f"\nCENAS JÁ USADAS neste produto (prompts que permanecem no "
                                f"lote) — NÃO repita estes cenários/enquadramentos:\n{linhas}\n")

    instrucoes_bloco = ("\n===== INSTRUCOES EXTRAS DO USUARIO PARA ESTAS IMAGENS =====\n"
                        + instrucoes_usuario + "\n===== FIM DAS INSTRUCOES EXTRAS =====\n") if instrucoes_usuario else ""
    # WikiHow é ilustração de mecanismo, sem pessoa real/@influenciador: não injeta
    # o bloco de influenciadores (evita empurrar rosto real numa ilustração chapada).
    _influ_bloco = "" if formato == "wikihow" else _bloco_influenciadores()
    prompt = f"""{cerebro}

Agora gere os prompts de imagem para ESTE produto, com base nas COPIES aprovadas e no CONTEXTO
abaixo. Gere {variantes_por_copy} entrada(s) por copy. Siga rigorosamente o formato de saída (array JSON puro).
{instrucao_extra}
REGRA DE LOTE (dura): as entradas geradas agora precisam ter cenas CLARAMENTE diferentes entre
si — cenário/locação, luz/momento, ângulo/enquadramento e layout do texto não se repetem entre
entradas. No máximo 2 entradas com o mesmo "formato". Distribua as cenas do lote ANTES de
escrever o primeiro prompt.
{cenas_existentes}{estilo_bloco}{_influ_bloco}
{instrucoes_bloco}
{visual_bloco}
===== CONTEXTO DO PRODUTO =====
{contexto}
===== COPIES APROVADAS =====
{copies}"""

    texto = _bridge(modelo).pedir_texto(prompt, modelo=modelo,
                                        system_prompt=SYSTEM_PROMPTS_IMG, timeout=420,
                                        add_dirs=add_dirs)
    dados = _extrair_json(texto)
    if isinstance(dados, dict) and "criativos" in dados:
        dados = dados["criativos"]

    # Limpa travessões dos campos que viram texto renderizado na arte.
    for d in dados:
        if isinstance(d, dict):
            for k in ("angulo", "copy", "prompt"):
                if k in d:
                    d[k] = _sem_travessoes(d[k])

    # Numeração espelha a da copy de origem: copy_01 -> criativo_01 (ou _v1..vN).
    # Feita no Python (não confiamos no modelo pra numerar): casa cada entrada
    # retornada à sua copy pelo copy_id, com fallback posicional.
    contagens: dict[int, int] = {}
    normalizados: list[dict] = []
    for idx, d in enumerate(dados):
        if not isinstance(d, dict):
            continue
        num = _num_de_copy(d.get("copy_id"))
        pos_copy = idx // variantes_por_copy
        if num is None and pos_copy < len(selecionadas):
            # copy_id ausente/inválido: casa pela ordem das selecionadas.
            d["copy_id"] = selecionadas[pos_copy].get("id")
            num = _num_de_copy(selecionadas[pos_copy].get("id"))
        if num is not None:
            contagens[num] = contagens.get(num, 0) + 1
            variante = contagens[num]
            d["id"] = (f"criativo_{num:02d}" if variantes_por_copy == 1
                        else f"criativo_{num:02d}_v{variante}")
            d["formato"] = formato  # rastreia o formato de cada criativo (mix)
            if variante <= variantes_por_copy:
                normalizados.append(d)
    ordem_copies = {str(c.get("id")): i for i, c in enumerate(selecionadas)}
    normalizados.sort(key=lambda d: (
        ordem_copies.get(str(d.get("copy_id")), len(ordem_copies)),
        int(str(d.get("id")).rsplit("_v", 1)[-1])
        if "_v" in str(d.get("id")) else 1,
    ))
    dados = normalizados

    # Dedup interno: se duas entradas caírem no mesmo id, a última vence.
    por_id: dict[str, dict] = {}
    novos: list[dict] = []
    for d in dados:
        _id = str(d.get("id")) if isinstance(d, dict) else None
        if _id and _id in por_id:
            novos[novos.index(por_id[_id])] = d
        else:
            if _id:
                por_id[_id] = d
            novos.append(d)
    dados = novos

    # Merge com dedup: as copies regeradas agora substituem qualquer prompt antigo
    # dessas mesmas copies (por número); os das outras copies permanecem no lote.
    base = [p for p in existentes if isinstance(p, dict)
            and _num_de_copy(p.get("copy_id")) not in nums_novos]
    return base + dados


def _marcar_copies_usadas(produto, copy_ids):
    """Tira as copies geradas da fila de pendentes do chat (status='usada')."""
    copies_json_f = product_dir(produto) / "output" / "copies.json"
    try:
        todas = json.loads(copies_json_f.read_text(encoding="utf-8"))
        alvo = {str(i) for i in copy_ids}
        for c in todas:
            if str(c.get("id")) in alvo:
                c["status"] = "usada"
        atomic_write_json(copies_json_f, todas)
    except Exception:  # noqa: BLE001 — marcação é best-effort
        pass


def _id_base(nome: str) -> str:
    """De 'criativo_03.png', 'criativo_03_v2.png' ou 'criativo_03_refinado1.png'
    devolve o id base 'criativo_03' (pra casar com a entrada do prompts.json)."""
    m = re.match(r"(criativo_\d+)", str(nome))
    return m.group(1) if m else re.sub(r"\.png$", "", str(nome))


@app.route("/api/sugerir_ideias/<produto>", methods=["POST"])
def sugerir_ideias(produto):
    """Agente de ideias: analisa os criativos recém-gerados (copy + conceito visual)
    junto do contexto do produto e propõe novas ideias em dois caminhos (padrão
    lateralizado e disruptivo), sempre com copy E conceito de imagem."""
    body = request.get_json(silent=True) or {}
    modelo = body.get("modelo") or "sonnet"
    arqs = [str(a) for a in (body.get("arquivos") or []) if str(a).endswith(".png")]
    # Títulos de ideias já mostradas nesta sessão — para "Gerar mais" trazer
    # ideias realmente novas em vez de repetir.
    evitar = [str(t).strip() for t in (body.get("evitar") or []) if str(t).strip()][:60]
    try:
        qtd = int(body.get("quantidade") or 3)
    except (TypeError, ValueError):
        qtd = 3
    qtd = max(1, min(qtd, 8))

    prompts = _ler_prompts_existentes(produto)
    gerados = [p for p in prompts if isinstance(p, dict) and p.get("status") == "gerado"]
    # Se o front mandou os arquivos que estão na tela, foca neles.
    if arqs:
        bases = {_id_base(a) for a in arqs}
        foco = [p for p in gerados if str(p.get("id")) in bases]
        if foco:
            gerados = foco
    if not gerados:
        gerados = [p for p in prompts if isinstance(p, dict)]
    if not gerados:
        return jsonify({"ok": False, "erro": "Gere alguns criativos primeiro."}), 400

    resumo = [{"id": p.get("id"),
               "copy": p.get("copy") or p.get("angulo") or "",
               "conceito_imagem": str(p.get("prompt", ""))[:700]}
              for p in gerados[:24]]
    contexto = montar_contexto_produto(produto)
    pedido = (
        "CONTEXTO DO PRODUTO:\n" + contexto + "\n\n"
        "CRIATIVOS QUE ACABARAM DE SER GERADOS (o que já foi explorado):\n"
        + json.dumps(resumo, ensure_ascii=False, indent=2) + "\n\n"
        "TAREFA: analise o que já foi feito e proponha NOVAS ideias de criativo (copy + imagem) "
        "que ainda NÃO foram exploradas. Trabalhe nos dois caminhos:\n"
        "- 'padrao': mantém a linha atual, lateralizando (novo ângulo/oferta/prova/cena), seguro e coerente.\n"
        "- 'disruptivo': ideia realmente diferente e inexplorada, mas plausível de rodar pra este produto "
        "(sem viajar).\n\n"
        + (("IDEIAS QUE JÁ FORAM PROPOSTAS (NÃO repita nenhuma delas, traga ângulos novos):\n"
            + json.dumps(evitar, ensure_ascii=False) + "\n\n") if evitar else "")
        + f"Gere {qtd} ideias de CADA caminho. Devolva SOMENTE um array JSON, um objeto por ideia:\n"
        "{'caminho': 'padrao'|'disruptivo', 'titulo': 'curto', "
        "'copy': {'headline': '...', 'apoio': '...', 'cta': '...'}, "
        "'conceito_imagem': 'descrição do visual/cena/composição', "
        "'porque': 'por que faz sentido dado o que já foi feito'}"
        + _bloco_influenciadores()
    )
    try:
        texto = _bridge(modelo).pedir_texto(
            pedido, modelo=modelo, system_prompt=SYSTEM_IDEIAS, timeout=420)
        ideias = _extrair_json(texto)
        if not isinstance(ideias, list):
            ideias = []
        return jsonify({"ok": True, "ideias": ideias})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/diagnosticar_criativos/<produto>", methods=["POST"])
def diagnosticar_criativos(produto):
    """QA com visão: abre cada PNG e caça defeitos (prioridade a ERROS DE TEXTO,
    depois anatomia e embalagem), devolvendo por imagem os problemas e uma
    instrução de correção cirúrgica pronta pro refino. Usa sempre o Claude (o
    Codex de texto não lê imagem de forma confiável)."""
    body = request.get_json(silent=True) or {}
    # QA exige visão -> Claude. Se o dropdown estiver em GPT, cai pro sonnet.
    modelo = body.get("modelo") or "sonnet"
    if str(modelo).lower().startswith("gpt"):
        modelo = "sonnet"

    out_dir = criativos_dir(produto)
    if not out_dir.exists():
        return jsonify({"ok": False, "erro": "Nenhum criativo gerado ainda."}), 400

    def _valido(a: str) -> bool:
        return (a.endswith(".png") and "/" not in a and "\\" not in a
                and (out_dir / a).exists())

    arquivos = [a for a in (str(x) for x in (body.get("arquivos") or [])) if _valido(a)]
    if not arquivos:
        arquivos = sorted(p.name for p in out_dir.glob("criativo_*.png"))
    if not arquivos:
        return jsonify({"ok": False, "erro": "Nenhum criativo para verificar."}), 400
    arquivos = arquivos[:24]

    prompts = {str(p.get("id")): p for p in _ler_prompts_existentes(produto)
               if isinstance(p, dict)}
    ref_dir = product_dir(produto) / "referencia"
    add_dirs = [str(out_dir)]
    if ref_dir.exists():
        add_dirs.append(str(ref_dir))

    def _linha(a: str) -> str:
        p = prompts.get(_id_base(a))
        copy_prevista = ""
        if p:
            partes = [p.get("copy") or p.get("angulo") or ""]
            copy_prevista = " / ".join(x for x in partes if x)[:300]
        return f"- {a}" + (f"  (texto pretendido na copy: {copy_prevista})"
                           if copy_prevista else "")

    def _pedido(lote: list) -> str:
        return (
            "Abra e inspecione COM ATENÇÃO cada um destes arquivos de imagem (você tem acesso de "
            "leitura à pasta onde eles estão):\n" + "\n".join(_linha(a) for a in lote) + "\n\n"
            "As fotos REAIS do produto, para comparar embalagem, cor, logo e rótulo, estão na pasta "
            "de referência (também acessível).\n\n"
            "Para CADA arquivo, verifique nesta ordem de prioridade: 1) ERROS DE TEXTO na arte "
            "(ortografia, letras trocadas/faltando, texto cortado ou embolado, sem sentido, hífen/travessão "
            "proibidos, divergência com o texto pretendido); 2) anatomia (dedos, mãos, membros, rostos); "
            "3) embalagem/produto divergente da referência.\n\n"
            "Devolva SOMENTE um array JSON, um objeto por arquivo, na mesma ordem:\n"
            "{'arquivo': 'nome.exato.png', 'ok': true|false, 'severidade': 'ok'|'leve'|'grave', "
            "'problemas': ['defeito curto e específico', ...], "
            "'instrucao_correcao': 'instrução cirúrgica pro refino, deixando claro que o resto fica "
            "idêntico e que o texto correto NÃO pode ser estragado (ou string vazia se estiver ok)'}"
        )

    def _diag_lote(lote: list) -> list:
        texto = claude_bridge.pedir_texto(
            _pedido(lote), modelo=modelo, system_prompt=SYSTEM_QA, timeout=900, add_dirs=add_dirs)
        d = _extrair_json(texto)
        return d if isinstance(d, list) else []

    # Verifica em LOTES de 6, em PARALELO — bem mais rápido que uma única chamada
    # com todas as imagens (a visão do modelo lê imagem a imagem dentro do contexto).
    lotes = [arquivos[i:i + 6] for i in range(0, len(arquivos), 6)]
    try:
        with ThreadPoolExecutor(max_workers=min(len(lotes), 4)) as ex:
            partes = list(ex.map(_diag_lote, lotes))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500

    # Achata os lotes e casa cada item com um arquivo real (basename), na ordem pedida.
    diag = [d for sub in partes for d in sub]
    validos = set(arquivos)
    saida = []
    for d in diag:
        if not isinstance(d, dict):
            continue
        nome = str(d.get("arquivo") or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if nome in validos:
            d["arquivo"] = nome
            saida.append(d)
    return jsonify({"ok": True, "diagnostico": saida})


def _ler_prompts_existentes(produto):
    prompts_f = product_dir(produto) / "output" / "prompts.json"
    if not prompts_f.exists():
        return []
    try:
        dados = json.loads(prompts_f.read_text(encoding="utf-8"))
        if isinstance(dados, dict) and "criativos" in dados:
            dados = dados["criativos"]
        return dados if isinstance(dados, list) else []
    except Exception:  # noqa: BLE001
        return []


@app.route("/api/gerar_prompts/<produto>", methods=["POST"])
def gerar_prompts(produto):
    """Regenera os prompts finais das copies selecionadas (usado para 'refazer'
    um prompt já promovido). O caminho principal de criação é /promover_prompts,
    que já entrega os prompts finais prontos para gerar as imagens."""
    body = request.get_json(silent=True) or {}
    modelo = body.get("modelo") or "sonnet"
    copy_ids = body.get("copy_ids")
    if not copy_ids:
        return jsonify({"ok": False, "erro": "Selecione ao menos uma copy."}), 400
    try:
        variantes_por_copy = max(1, min(6, int(body.get("variantes_por_copy") or 1)))
    except (TypeError, ValueError):
        variantes_por_copy = 1
    visual_ids = {str(i) for i in (body.get("visual_ids") or [])}
    instrucoes_usuario = str(body.get("instrucoes") or "").strip()[:12000]
    out = product_dir(produto) / "output"

    copies_json_f = out / "copies.json"
    if not copies_json_f.exists():
        return jsonify({"ok": False,
                        "erro": "Salve as copies primeiro (botão Salvar copies)."}), 400
    todas = json.loads(copies_json_f.read_text(encoding="utf-8"))
    selecionadas = [c for c in todas if str(c.get("id")) in {str(i) for i in copy_ids}]
    if not selecionadas:
        return jsonify({"ok": False, "erro": "Nenhuma copy corresponde à seleção."}), 400

    visuais_sel = [v for v in _ler_visuais(produto)
                   if not visual_ids or str(v.get("id")) in visual_ids]

    try:
        dados = _gerar_prompts_finais(produto, modelo, selecionadas, visuais_sel,
                                      variantes_por_copy, instrucoes_usuario,
                                      _ler_prompts_existentes(produto))
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out / "prompts.json", dados)
        _marcar_copies_usadas(produto, copy_ids)
        return jsonify({"ok": True, "prompts": dados})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/prompts/<produto>", methods=["GET"])
def get_prompts(produto):
    f = product_dir(produto) / "output" / "prompts.json"
    if not f.exists():
        return jsonify([])
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


@app.route("/api/prompts/<produto>", methods=["POST"])
def salvar_prompts(produto):
    body = request.get_json(force=True)
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "prompts.json", body.get("prompts", [])[:1000])
    return jsonify({"ok": True})


def _status_erro(produto: str, e: Exception):
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "status.json", {
        "id": JOBS.new_id(), "total": 0, "feitos": 0, "atual": None, "arquivos": [],
        "erros": [{"id": "-", "erro": str(e)[:2000]}], "em_andamento": False})


@app.route("/api/gerar_imagens/<produto>", methods=["POST"])
def gerar_imagens(produto):
    body = request.get_json(silent=True) or {}
    ids = body.get("ids")
    modo = body.get("modo", "pendentes")
    if modo not in {"pendentes", "substituir"}:
        return jsonify({"ok": False, "erro": "Modo de geração inválido."}), 400
    if modo == "substituir" and body.get("confirmar") is not True:
        return jsonify({"ok": False, "erro": "Substituição exige confirmação explícita."}), 400

    if ids:
        # Valida ANTES do lock/thread para responder 400 sem prender o lock.
        prompts_f = product_dir(produto) / "output" / "prompts.json"
        if not prompts_f.exists():
            return jsonify({"ok": False, "erro": "Gere os prompts primeiro."}), 400
        entradas = json.loads(prompts_f.read_text(encoding="utf-8"))
        if isinstance(entradas, dict) and "criativos" in entradas:
            entradas = entradas["criativos"]
        validos = {str(e.get("id")) for e in entradas}
        if not any(str(i) in validos for i in ids):
            return jsonify({"ok": False, "erro": "Nenhum prompt corresponde à seleção."}), 400

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409

    cancel = _cancel_event(produto)
    cancel.clear()

    def tarefa():
        try:
            gerar.gerar_criativos(produto, ids=ids, cancel_event=cancel, modo=modo)
        except Exception as e:  # noqa: BLE001
            _status_erro(produto, e)
        finally:
            lock.release()

    threading.Thread(target=nosleep.envolver(tarefa), daemon=False).start()
    return jsonify({"ok": True})


@app.route("/api/gerar_ideias/<produto>", methods=["POST"])
def gerar_ideias(produto):
    """Recebe as ideias marcadas no agente de ideias, vira cada uma num prompt
    final (o conceito_imagem já é a direção visual; a fidelidade/estilo/verdade
    visual são aplicados na geração) e dispara a geração em LOTE (paralelizada),
    igual ao fluxo normal de gerar_imagens."""
    body = request.get_json(silent=True) or {}
    ideias = body.get("ideias") or []
    if not isinstance(ideias, list) or not ideias:
        return jsonify({"ok": False, "erro": "Nenhuma ideia selecionada."}), 400

    existentes = _ler_prompts_existentes(produto)
    ids_usados = {str(e.get("id")) for e in existentes if isinstance(e, dict)}

    novos, novos_ids = [], []
    for idx, i in enumerate(ideias):
        if not isinstance(i, dict):
            continue
        conceito = str(i.get("conceito_imagem") or "").strip()
        if not conceito:
            continue
        copy = i.get("copy") or {}
        # Prefixo criativo_ é OBRIGATÓRIO: a grade (e _pngs_existentes) só lista
        # PNGs que começam com "criativo_". Sem ele, a imagem é gerada no disco
        # mas nunca aparece na etapa de Criativos.
        cid = f"criativo_ideia_{uuid.uuid4().hex[:8]}"
        while cid in ids_usados:
            cid = f"criativo_ideia_{uuid.uuid4().hex[:8]}"
        ids_usados.add(cid)
        novos.append({
            "id": cid,
            "angulo": str(i.get("titulo") or "").strip(),
            "copy": str(copy.get("headline") or i.get("titulo") or "").strip(),
            "copy_id": "",
            "estilo": "",
            "formato": (i.get("caminho") or "ideia"),
            "prompt": conceito,
            "selo": "",
            "tamanho": "1024x1024",
            "status": "pendente",
        })
        novos_ids.append(cid)

    if not novos:
        return jsonify({"ok": False, "erro": "As ideias não têm conceito de imagem."}), 400

    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "prompts.json", (existentes + novos)[:1000])

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409

    cancel = _cancel_event(produto)
    cancel.clear()

    def tarefa():
        try:
            gerar.gerar_criativos(produto, ids=novos_ids, cancel_event=cancel, modo="pendentes")
        except Exception as e:  # noqa: BLE001
            _status_erro(produto, e)
        finally:
            lock.release()

    threading.Thread(target=nosleep.envolver(tarefa), daemon=False).start()
    return jsonify({"ok": True, "ids": novos_ids})


@app.route("/api/parar/<produto>", methods=["POST"])
def parar(produto):
    """Sinaliza o cancelamento da geração/refino em andamento deste produto."""
    _cancel_event(produto).set()
    return jsonify({"ok": True})


@app.route("/api/descartar_criativo/<produto>", methods=["POST"])
def descartar_criativo(produto):
    """Move um criativo ruim para output/criativos/descartados/ (não apaga)."""
    body = request.get_json(force=True)
    arquivo = (body.get("arquivo") or "").strip()
    if not arquivo or "/" in arquivo or "\\" in arquivo or not arquivo.endswith(".png"):
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    pasta = criativos_dir(produto)
    origem = safe_child(pasta, arquivo, suffix=".png")
    if not origem.exists():
        return jsonify({"ok": False, "erro": "Criativo não encontrado."}), 400

    destino_dir = pasta / "descartados"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / arquivo
    if destino.exists():  # já descartou um homônimo antes: não sobrescreve
        destino = destino_dir / f"{origem.stem}_{datetime.now().strftime('%H%M%S')}.png"
    origem.rename(destino)

    # Tira da lista do status.json pra grade não recriar o thumb.
    status_f = product_dir(produto) / "output" / "status.json"
    if status_f.exists():
        try:
            s = json.loads(status_f.read_text(encoding="utf-8"))
            if arquivo in s.get("arquivos", []):
                s["arquivos"].remove(arquivo)
                atomic_write_json(status_f, s)
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"ok": True})


@app.route("/api/refinar_fila/<produto>", methods=["POST"])
def refinar_fila(produto):
    """Executa todos os refinamentos recebidos em paralelo, após o usuário
    montar a fila inteira. Cada item usa um status privado; o status público
    agregado continua sendo o que o front acompanha."""
    body = request.get_json(silent=True) or {}
    itens = body.get("itens") or []
    if not isinstance(itens, list) or not itens or len(itens) > 50:
        return jsonify({"ok": False, "erro": "Fila de refinamentos vazia ou grande demais."}), 400

    limpos = []
    pasta = criativos_dir(produto)
    for item in itens:
        arquivo = str(item.get("arq") or "").strip() if isinstance(item, dict) else ""
        instrucao = str(item.get("instrucao") or "").strip() if isinstance(item, dict) else ""
        if (not instrucao or len(instrucao) > 10000 or not arquivo or "/" in arquivo
                or "\\" in arquivo or not arquivo.endswith(".png")):
            return jsonify({"ok": False, "erro": "Item de refino inválido."}), 400
        try:
            base = safe_child(pasta, arquivo, suffix=".png")
        except ValueError:
            return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
        if not base.exists():
            return jsonify({"ok": False, "erro": f"Criativo não encontrado: {arquivo}"}), 400
        limpos.append({"arq": arquivo, "instrucao": instrucao})

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409
    cancel = _cancel_event(produto)
    cancel.clear()
    status_file = product_dir(produto) / "output" / "status.json"
    status = {"id": uuid.uuid4().hex, "produto": produto, "total": len(limpos),
              "feitos": 0, "atual": None, "atuais": [], "arquivos": [],
              "erros": [], "em_andamento": True, "inicio": time.time(),
              "atualizado": time.time()}
    st_lock = threading.Lock()

    def salvar():
        status["atualizado"] = time.time()
        atomic_write_json(status_file, status)

    def tarefa():
        privates = []
        try:
            with st_lock:
                status["arquivos"] = sorted(p.name for p in pasta.glob("criativo_*.png"))
                salvar()

            def worker(item):
                private = pasta / f".refino-status-{uuid.uuid4().hex}.json"
                privates.append(private)
                try:
                    result = gerar.refinar_criativo(
                        produto, item["arq"], item["instrucao"], cancel_event=cancel,
                        status_file=private)
                    with st_lock:
                        status["feitos"] += 1
                        status["arquivos"] = sorted(p.name for p in pasta.glob("criativo_*.png"))
                        status["erros"].extend(result.get("erros", []))
                        status["atual"] = None
                        salvar()
                    threading.Thread(target=_aprender_verdade_visual,
                                     args=(produto, item["instrucao"], body.get("modelo") or "haiku"),
                                     daemon=True).start()
                except Exception as exc:  # noqa: BLE001
                    with st_lock:
                        status["feitos"] += 1
                        status["erros"].append({"id": item["arq"], "erro": str(exc)})
                        salvar()

            workers = min(len(limpos), 6)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(worker, limpos))
        finally:
            with st_lock:
                status["atuais"] = []
                status["arquivos"] = sorted(p.name for p in pasta.glob("criativo_*.png"))
                status["em_andamento"] = False
                status["cancelado"] = bool(cancel.is_set())
                status["atual"] = None
                salvar()
            for private in privates:
                private.unlink(missing_ok=True)
            lock.release()

    threading.Thread(target=nosleep.envolver(tarefa), daemon=False).start()
    return jsonify({"ok": True})


@app.route("/api/refinar_criativo/<produto>", methods=["POST"])
def refinar_criativo(produto):
    body = request.get_json(force=True)
    arquivo = (body.get("arquivo") or "").strip()
    instrucao = (body.get("instrucao") or "").strip()

    if not instrucao:
        return jsonify({"ok": False, "erro": "Descreva o ajuste desejado."}), 400
    if len(instrucao) > 10000:
        return jsonify({"ok": False, "erro": "Instrução grande demais."}), 400
    if not arquivo or "/" in arquivo or "\\" in arquivo or not arquivo.endswith(".png"):
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    try:
        base = safe_child(criativos_dir(produto), arquivo, suffix=".png")
    except ValueError:
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    if not base.exists():
        return jsonify({"ok": False, "erro": "Criativo não encontrado."}), 400

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409

    cancel = _cancel_event(produto)
    cancel.clear()

    def tarefa():
        try:
            gerar.refinar_criativo(produto, arquivo, instrucao, cancel_event=cancel)
        except Exception as e:  # noqa: BLE001
            _status_erro(produto, e)
        finally:
            lock.release()

    threading.Thread(target=nosleep.envolver(tarefa), daemon=False).start()

    # Em paralelo (best-effort): destila a instrução num fato visual durável do produto,
    # para o mesmo erro não voltar em futuros criativos. Não bloqueia nem afeta o refino.
    modelo = (body.get("modelo") or "haiku")
    threading.Thread(
        target=_aprender_verdade_visual, args=(produto, instrucao, modelo), daemon=True
    ).start()
    return jsonify({"ok": True})


@app.route("/api/refazer_criativo/<produto>", methods=["POST"])
def refazer_criativo(produto):
    """Refaz um criativo do zero a partir de referências novas anexadas + a instrução
    do usuário, mantendo a copy. Diferente do refino (img2img), aqui a versão atual é
    só ponto de partida. Recebe multipart: arquivo, instrucao, anexos[]."""
    import shutil
    arquivo = (request.form.get("arquivo") or "").strip()
    instrucao = (request.form.get("instrucao") or "").strip()
    if not instrucao:
        return jsonify({"ok": False, "erro": "Descreva o que você quer no refazer."}), 400
    if len(instrucao) > 10000:
        return jsonify({"ok": False, "erro": "Instrução grande demais."}), 400
    if not arquivo or "/" in arquivo or "\\" in arquivo or not arquivo.endswith(".png"):
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    try:
        base = safe_child(criativos_dir(produto), arquivo, suffix=".png")
    except ValueError:
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    if not base.exists():
        return jsonify({"ok": False, "erro": "Criativo não encontrado."}), 400

    # Referências anexadas: salvas num diretório TEMPORÁRIO (uso único deste refazer).
    tmp_dir = product_dir(produto) / "output" / ".refazer_tmp" / __import__("uuid").uuid4().hex
    tmp_dir.mkdir(parents=True, exist_ok=True)
    refs_extra = []
    for f in request.files.getlist("anexos"):
        nome = _salvar_upload(f, tmp_dir, IMG_EXTS, _MAX_IMG, "ref.png")
        if nome:
            refs_extra.append(str(tmp_dir / nome))

    # Copy (headline) do criativo, para manter a mensagem na arte refeita.
    copy_text = ""
    m = re.match(r"(criativo_\d+)", arquivo)
    if m:
        pf = product_dir(produto) / "output" / "prompts.json"
        try:
            dados = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else []
            for d in (dados if isinstance(dados, list) else []):
                if str(d.get("id")) == m.group(1):
                    copy_text = str(d.get("copy") or "")
                    break
        except Exception:  # noqa: BLE001
            pass

    lock = _lock(produto)
    if not lock.acquire(blocking=False):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"ok": False, "erro": "Já existe uma geração em andamento."}), 409

    cancel = _cancel_event(produto)
    cancel.clear()

    def tarefa():
        try:
            gerar.refazer_criativo(produto, arquivo, instrucao, refs_extra=refs_extra,
                                   copy_text=copy_text, cancel_event=cancel)
        except Exception as e:  # noqa: BLE001
            _status_erro(produto, e)
        finally:
            lock.release()
            shutil.rmtree(tmp_dir, ignore_errors=True)

    threading.Thread(target=nosleep.envolver(tarefa), daemon=False).start()
    return jsonify({"ok": True})


def _mtimes_criativos(pasta: Path, arquivos: list) -> dict:
    """mtime (int) de cada PNG da grade — o front usa como cache-buster para
    re-renderizar um criativo REGERADO com o mesmo nome (senão a grade mostra o antigo)."""
    mt = {}
    for nome in arquivos or []:
        p = pasta / nome
        try:
            mt[nome] = int(p.stat().st_mtime)
        except OSError:
            pass
    return mt


def _formatos_por_id(produto):
    """Mapa {id_base -> formato} lido de prompts.json, para a grade exibir o selo
    de formato em cada thumb. Formato ausente vira 'padrao'."""
    mapa = {}
    for p in _ler_prompts_existentes(produto):
        if isinstance(p, dict) and p.get("id"):
            mapa[_id_base(str(p["id"]))] = p.get("formato") or "padrao"
    return mapa


@app.route("/api/status/<produto>")
def status(produto):
    pasta = criativos_dir(produto)
    f = product_dir(produto) / "output" / "status.json"
    if f.exists():
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            # Um processo encerrado pode deixar o último estado como ativo.
            # Só declara a execução morta se, ALÉM de não haver lock neste processo,
            # o status estiver ESTAGNADO (sem heartbeat há >90s). A geração grava um
            # batimento a cada ~15s (gerar.py), então uma execução viva em OUTRO
            # processo (ex.: CLI `python gerar.py` com o app aberto) nunca é morta
            # por engano — o falso "interrompida após reinício" vinha daqui.
            import time as _t
            estagnado = (_t.time() - float(s.get("atualizado") or 0)) > 90
            if s.get("em_andamento") and estagnado:
                lock = _lock(produto)
                if lock.acquire(False):
                    try:
                        s["em_andamento"] = False
                        s.setdefault("erros", []).append({
                            "id": "-", "erro": "Execução interrompida após reinício do servidor."})
                        atomic_write_json(f, s)
                    finally:
                        lock.release()
            # Reconcilia a grade com o DISCO: se o usuário renomeou, moveu, apagou ou
            # adicionou PNGs na pasta na mão, a grade passa a refletir o que existe de
            # verdade (nada de thumbnail quebrado de arquivo sumido, e os criativos
            # colocados manualmente aparecem). Só fora de geração ativa — durante a
            # geração o próprio job de gerar.py é dono da lista.
            if not s.get("em_andamento"):
                reais = sorted(p.name for p in pasta.iterdir()
                               if p.is_file() and p.suffix.lower() == ".png"
                               and p.name.lower().startswith("criativo_"))
                if reais != sorted(s.get("arquivos", [])):
                    s["arquivos"] = reais
                    s["total"] = len(reais)
                    s["feitos"] = len(reais)
                    try:
                        atomic_write_json(f, s)
                    except Exception:  # noqa: BLE001
                        pass
            s["mtimes"] = _mtimes_criativos(pasta, s.get("arquivos", []))
            s["formatos"] = _formatos_por_id(produto)
            return jsonify(s)
        except Exception:
            pass
    # Sem status.json (ou ilegível): monta a grade direto do disco.
    reais = []
    if pasta.exists():
        reais = sorted(p.name for p in pasta.iterdir()
                       if p.is_file() and p.suffix.lower() == ".png"
                       and p.name.lower().startswith("criativo_"))
    return jsonify({"total": len(reais), "feitos": len(reais), "atual": None,
                    "arquivos": reais, "erros": [], "em_andamento": False,
                    "mtimes": _mtimes_criativos(pasta, reais),
                    "formatos": _formatos_por_id(produto)})


@app.route("/criativos/<produto>/<path:arquivo>")
def criativo(produto, arquivo):
    pasta = criativos_dir(produto)
    try:
        safe_descendant(pasta, arquivo)
    except ValueError:
        abort(404)
    return send_from_directory(pasta, arquivo)


@app.route("/referencia/<produto>/<path:arquivo>")
def referencia(produto, arquivo):
    pasta = product_dir(produto) / "referencia"
    try:
        safe_child(pasta, arquivo)
    except ValueError:
        abort(404)
    return send_from_directory(pasta, arquivo)


# ---- Referências de ESTILO (imagens anexadas na aba de copies, modo "estilo") ----

@app.route("/api/referencia_estilo/<produto>", methods=["GET"])
def get_referencia_estilo(produto):
    detalhes = _referencias_com_contexto(produto, "estilo")
    return jsonify({"referencias": [i["arquivo"] for i in detalhes], "detalhes": detalhes})


@app.route("/api/referencia_estilo/<produto>", methods=["POST"])
def upload_referencia_estilo(produto):
    product_dir(produto)
    arquivos = request.files.getlist("anexos")
    try:
        contextos = json.loads(request.form.get("contextos") or "[]")
    except Exception:
        contextos = []
    salvos = _salvar_ref_estilo(produto, arquivos)
    info = _ler_ref_info(produto, "estilo")
    por_nome = {i.get("arquivo"): i for i in info if isinstance(i, dict)}
    for i, nome in enumerate(salvos):
        ctx_novo = str(contextos[i] if i < len(contextos) else "").strip()[:4000]
        if nome in por_nome:
            # Já existe (reanexo): só atualiza a nota se veio uma nova; não apaga a atual.
            if ctx_novo:
                por_nome[nome]["contexto"] = ctx_novo
        else:
            entrada = {"arquivo": nome, "contexto": ctx_novo}
            info.append(entrada)
            por_nome[nome] = entrada
    _salvar_ref_info(produto, "estilo", info)
    detalhes = _referencias_com_contexto(produto, "estilo")
    return jsonify({"ok": True, "salvos": salvos, "referencias": [i["arquivo"] for i in detalhes], "detalhes": detalhes})


@app.route("/api/referencia_estilo/<produto>", methods=["DELETE"])
def remover_referencia_estilo(produto):
    body = request.get_json(force=True)
    arquivo = (body.get("arquivo") or "").strip()
    try:
        alvo = safe_child(_ref_estilo_dir(produto), arquivo)
    except ValueError:
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    alvo.unlink(missing_ok=True)
    _salvar_ref_info(produto, "estilo", [i for i in _ler_ref_info(produto, "estilo") if i.get("arquivo") != arquivo])
    detalhes = _referencias_com_contexto(produto, "estilo")
    return jsonify({"ok": True, "referencias": [i["arquivo"] for i in detalhes], "detalhes": detalhes})


@app.route("/api/referencia_produto/<produto>", methods=["GET"])
def get_referencia_produto(produto):
    return jsonify({"detalhes": _referencias_com_contexto(produto, "produto")})


@app.route("/api/referencia_produto/<produto>", methods=["POST"])
def upload_referencia_produto(produto):
    product_dir(produto)
    arquivos = request.files.getlist("anexos")
    try:
        contextos = json.loads(request.form.get("contextos") or "[]")
    except Exception:
        contextos = []
    salvos = []
    pasta = product_dir(produto) / "referencia"
    for arquivo in arquivos:
        nome = _salvar_upload(arquivo, pasta, IMG_EXTS, _MAX_IMG, "produto.png")
        if nome:
            salvos.append(nome)
    info = _ler_ref_info(produto, "produto")
    for i, nome in enumerate(salvos):
        info.append({"arquivo": nome, "contexto": str(contextos[i] if i < len(contextos) else "").strip()[:4000]})
    _salvar_ref_info(produto, "produto", info)
    return jsonify({"ok": True, "salvos": salvos, "detalhes": _referencias_com_contexto(produto, "produto")})


@app.route("/api/referencia_produto/<produto>", methods=["DELETE"])
def remover_referencia_produto(produto):
    """Apaga uma foto real do produto. A foto é OPCIONAL: dá para remover todas
    (produtos como cursos/infoprodutos podem não ter imagem). Com foto, a geração
    fica mais fiel; sem nenhuma, a arte é construída a partir do texto do produto."""
    body = request.get_json(force=True)
    arquivo = (body.get("arquivo") or "").strip()
    pasta = product_dir(produto) / "referencia"
    try:
        alvo = safe_child(pasta, arquivo)
    except ValueError:
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    if not alvo.exists():
        return jsonify({"ok": False, "erro": "Foto não encontrada."}), 404
    alvo.unlink(missing_ok=True)
    _salvar_ref_info(produto, "produto",
                     [i for i in _ler_ref_info(produto, "produto") if i.get("arquivo") != arquivo])
    detalhes = _referencias_com_contexto(produto, "produto")
    return jsonify({"ok": True, "referencias": [i["arquivo"] for i in detalhes], "detalhes": detalhes})


@app.route("/api/referencia_produto/<produto>/contexto", methods=["POST"])
def atualizar_contexto_referencia_produto(produto):
    body = request.get_json(silent=True) or {}
    arquivo = str(body.get("arquivo") or "").strip()
    contexto = str(body.get("contexto") or "").strip()[:4000]
    detalhes = _referencias_com_contexto(produto, "produto")
    if arquivo not in {i["arquivo"] for i in detalhes}:
        return jsonify({"ok": False, "erro": "Foto de produto não encontrada."}), 404
    for item in detalhes:
        if item["arquivo"] == arquivo:
            item["contexto"] = contexto
    _salvar_ref_info(produto, "produto", detalhes)
    return jsonify({"ok": True, "detalhes": detalhes})


@app.route("/api/referencia_estilo/<produto>/contexto", methods=["POST"])
def atualizar_contexto_referencia_estilo(produto):
    body = request.get_json(silent=True) or {}
    arquivo = str(body.get("arquivo") or "").strip()
    contexto = str(body.get("contexto") or "").strip()[:4000]
    info = _ler_ref_info(produto, "estilo")
    achou = False
    for item in info:
        if item.get("arquivo") == arquivo:
            item["contexto"] = contexto
            achou = True
    if not achou:
        info.append({"arquivo": arquivo, "contexto": contexto})
    _salvar_ref_info(produto, "estilo", info)
    return jsonify({"ok": True, "detalhes": _referencias_com_contexto(produto, "estilo")})


@app.route("/referencia_estilo/<produto>/<path:arquivo>")
def servir_referencia_estilo(produto, arquivo):
    pasta = _ref_estilo_dir(produto)
    try:
        safe_child(pasta, arquivo)
    except ValueError:
        abort(404)
    return send_from_directory(pasta, arquivo)


# ---- Influenciadores: pessoas reais que entram idênticas nos criativos ----------
# Cadastro global (influenciadores/<nome>/). A ativação é POR CRIATIVO: o prompt de
# imagem menciona @Nome (detecção em gerar.influenciador_no_texto). As fotos marcadas
# como principais (principais.json, até 3) são as que entram na geração; sem
# marcação, valem as primeiras por ordem de nome.

INFLU_PRINCIPAIS = "principais.json"
INFLU_MAX_PRINCIPAIS = 3


def _influ_dados(nome: str) -> dict:
    d = influencer_dir(nome)
    ref = d / "referencia"
    fotos = sorted(f.name for f in ref.iterdir()
                   if f.is_file() and f.suffix.lower() in IMG_EXTS) if ref.exists() else []
    principais = [p for p in (ler_json(d / INFLU_PRINCIPAIS, []) or []) if p in fotos]
    perfil_f = d / "perfil.md"
    perfil = perfil_f.read_text(encoding="utf-8", errors="replace") if perfil_f.exists() else ""
    return {"nome": d.name, "fotos": fotos, "principais": principais, "perfil": perfil}


@app.route("/api/influenciadores", methods=["GET"])
def listar_influenciadores():
    itens = []
    if INFLUENCIADORES.exists():
        for d in sorted(INFLUENCIADORES.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                itens.append(_influ_dados(d.name))
    return jsonify({"ok": True, "influenciadores": itens})


@app.route("/api/influenciadores", methods=["POST"])
def criar_influenciador():
    body = request.get_json(force=True) or {}
    nome = _ILEGAIS.sub("", str(body.get("nome") or "")).strip(" .")[:60]
    if not nome or nome.lower() in _RESERVADOS:
        return jsonify({"ok": False, "erro": "Nome de influenciador inválido."}), 400
    try:
        d = influencer_dir(nome, create=True)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    (d / "referencia").mkdir(exist_ok=True)
    perfil = str(body.get("perfil") or "").strip()[:8000]
    if perfil or not (d / "perfil.md").exists():
        atomic_write_text(d / "perfil.md", perfil)
    return jsonify({"ok": True, **_influ_dados(nome)})


@app.route("/api/influenciadores/<nome>", methods=["DELETE"])
def apagar_influenciador(nome):
    try:
        d = influencer_dir(nome)
    except ValueError:
        return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    return jsonify({"ok": True})


@app.route("/api/influenciadores/<nome>/perfil", methods=["POST"])
def salvar_perfil_influenciador(nome):
    try:
        d = influencer_dir(nome)
    except ValueError:
        return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    body = request.get_json(silent=True) or {}
    atomic_write_text(d / "perfil.md", str(body.get("perfil") or "").strip()[:8000])
    return jsonify({"ok": True})


@app.route("/api/influenciadores/<nome>/fotos", methods=["POST"])
def upload_fotos_influenciador(nome):
    try:
        d = influencer_dir(nome)
    except ValueError:
        return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    salvos = []
    for f in request.files.getlist("anexos"):
        n = _salvar_upload(f, d / "referencia", IMG_EXTS, _MAX_IMG, "foto.png")
        if n:
            salvos.append(n)
    return jsonify({"ok": True, "salvos": salvos, **_influ_dados(nome)})


@app.route("/api/influenciadores/<nome>/fotos", methods=["DELETE"])
def apagar_foto_influenciador(nome):
    try:
        d = influencer_dir(nome)
    except ValueError:
        return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    arquivo = str((request.get_json(silent=True) or {}).get("arquivo") or "").strip()
    try:
        alvo = safe_child(d / "referencia", arquivo)
    except ValueError:
        return jsonify({"ok": False, "erro": "Arquivo inválido."}), 400
    alvo.unlink(missing_ok=True)
    principais = [p for p in (ler_json(d / INFLU_PRINCIPAIS, []) or []) if p != arquivo]
    atomic_write_json(d / INFLU_PRINCIPAIS, principais)
    return jsonify({"ok": True, **_influ_dados(nome)})


@app.route("/api/influenciadores/<nome>/principais", methods=["POST"])
def marcar_principais_influenciador(nome):
    try:
        influencer_dir(nome)
    except ValueError:
        return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    body = request.get_json(silent=True) or {}
    fotos = set(_influ_dados(nome)["fotos"])
    marcadas = [str(a) for a in (body.get("arquivos") or []) if str(a) in fotos]
    atomic_write_json(influencer_dir(nome) / INFLU_PRINCIPAIS, marcadas[:INFLU_MAX_PRINCIPAIS])
    return jsonify({"ok": True, **_influ_dados(nome)})


@app.route("/influenciador_media/<nome>/<path:arquivo>")
def influenciador_media(nome, arquivo):
    try:
        pasta = influencer_dir(nome) / "referencia"
        safe_child(pasta, arquivo)
    except ValueError:
        abort(404)
    return send_from_directory(pasta, arquivo)


# Influenciador PADRÃO do produto: configuração leve que alimenta as SUGESTÕES —
# a etapa de Estilo visual garante pelo menos 1/3 das direções com essa pessoa
# (escrita como @Nome). A GERAÇÃO continua ativada por criativo, pelo @ no prompt.
INFLU_PROD_ARQ = "influenciador.json"


def _influ_do_produto(produto: str) -> str | None:
    f = product_dir(produto) / "output" / INFLU_PROD_ARQ
    nome = str((ler_json(f, {}) or {}).get("nome") or "").strip()
    if not nome:
        return None
    try:
        influencer_dir(nome)
    except ValueError:
        return None  # influenciador apagado: padrão vira "nenhum"
    return nome


@app.route("/api/influenciador_produto/<produto>", methods=["GET"])
def get_influenciador_produto(produto):
    return jsonify({"ok": True, "nome": _influ_do_produto(produto)})


@app.route("/api/influenciador_produto/<produto>", methods=["POST"])
def set_influenciador_produto(produto):
    body = request.get_json(silent=True) or {}
    nome = str(body.get("nome") or "").strip()
    if nome:
        try:
            influencer_dir(nome)
        except ValueError:
            return jsonify({"ok": False, "erro": "Influenciador não encontrado."}), 404
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / INFLU_PROD_ARQ, {"nome": nome or None})
    return jsonify({"ok": True, "nome": nome or None})


IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
REF_EXTS = IMG_EXTS | {".avif", ".heic", ".heif"}


# ------------------------------------------------------------- contexto (UI) ---

@app.route("/api/contexto/<produto>", methods=["GET"])
def get_contexto(produto):
    pdir = product_dir(produto)
    cfg = pdir / "config.md"
    arquivos = []
    ctx_dir = pdir / "contexto"
    if ctx_dir.exists():
        for f in sorted(ctx_dir.iterdir()):
            if f.name == ".gitkeep" or f.is_dir() or f.name in (APRENDIZADO_ARQ, VERDADE_ARQ):
                continue  # aprendizado.md e verdade_visual.md têm card editável próprio
            if f.suffix.lower() in {".md", ".txt"}:
                arquivos.append({"nome": f.name, "tipo": "texto",
                                 "conteudo": f.read_text(encoding="utf-8", errors="replace")})
            else:
                arquivos.append({"nome": f.name, "tipo": "outro", "conteudo": None})
    referencias = []
    ref_dir = pdir / "referencia"
    if ref_dir.exists():
        for f in sorted(ref_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in REF_EXTS:
                referencias.append(f.name)
    return jsonify({"config": cfg.read_text(encoding="utf-8", errors="replace") if cfg.exists() else "",
                    "arquivos": arquivos, "referencias": referencias,
                    "referencias_estilo": _listar_ref_estilo(produto)})


@app.route("/api/contexto/<produto>", methods=["POST"])
def salvar_contexto(produto):
    body = request.get_json(force=True)
    pdir = product_dir(produto)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(pdir / "config.md", str(body.get("config", ""))[:100000])
    return jsonify({"ok": True})


# ---------------------------------------------------- criar produto (wizard) ---

# Caracteres proibidos em nome de arquivo/pasta no Windows (+ controle).
_ILEGAIS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Nomes de dispositivo reservados no Windows (não podem ser pasta).
_RESERVADOS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
               *(f"lpt{i}" for i in range(1, 10))}
_MAX_IMG = 15 * 1024 * 1024   # 15 MB por imagem
_MAX_TXT = 2 * 1024 * 1024    # 2 MB por texto
TXT_EXTS = {".txt", ".md"}


def _nome_seguro(nome, padrao="arquivo"):
    """Sanitiza um nome de arquivo (tira caminho e caracteres ilegais)."""
    base = _ILEGAIS.sub("", Path(str(nome or "")).name).strip(" .")
    return (base or padrao)[:120]


def _destino_unico(pasta: Path, nome: str) -> Path:
    """Garante um caminho que ainda não existe (acrescenta _2, _3… se preciso)."""
    alvo = pasta / nome
    if not alvo.exists():
        return alvo
    stem, suf = Path(nome).stem, Path(nome).suffix
    i = 2
    while (pasta / f"{stem}_{i}{suf}").exists():
        i += 1
    return pasta / f"{stem}_{i}{suf}"


def _salvar_upload(file, pasta: Path, exts: set, max_bytes: int, padrao: str,
                   overwrite: bool = False) -> str | None:
    """Valida (extensão/tamanho) e grava um upload em `pasta`. Retorna o nome salvo ou None.

    overwrite=True: reanexar um arquivo de mesmo nome SOBRESCREVE (não cria cópia _2,
    _3...). Usado nas referências de estilo, que o usuário reanexa com frequência.
    """
    if file is None or not getattr(file, "filename", ""):
        return None
    nome = _nome_seguro(file.filename, padrao)
    if Path(nome).suffix.lower() not in exts:
        return None
    dados = file.read(max_bytes + 1)
    if not dados or len(dados) > max_bytes:
        return None
    pasta.mkdir(parents=True, exist_ok=True)
    destino = (pasta / nome) if overwrite else _destino_unico(pasta, nome)
    tmp = destino.with_name(f".{destino.name}.{JOBS.new_id()}.tmp")
    tmp.write_bytes(dados)
    tmp.replace(destino)
    return destino.name


def _gerar_config_inicial(nome: str, pdir: Path, modelo: str = "sonnet") -> str:
    """Gera o primeiro config.md a partir do material enviado no wizard."""
    ctx = pdir / "contexto"
    textos = []
    if ctx.exists():
        for f in sorted(ctx.iterdir()):
            if f.is_file() and f.suffix.lower() in TXT_EXTS:
                textos.append(f"\n===== {f.name} =====\n{f.read_text(encoding='utf-8', errors='replace')[:_MAX_TXT]}")
    imagens = []
    for pasta in (pdir / "referencia", ctx):
        if pasta.exists():
            imagens.extend(str(f) for f in sorted(pasta.iterdir())
                           if f.is_file() and f.suffix.lower() in REF_EXTS)
    lista_imagens = "\n".join(f"- {p}" for p in imagens) or "(nenhuma imagem enviada)"
    prompt = f"""Crie a configuração inicial do produto **{nome}**.

Use SOMENTE fatos presentes nos textos e imagens enviadas. Se algo não existir, escreva
\"Não informado\". Não use placeholders ou colchetes. Veja as imagens antes de responder.

IMAGENS PARA INSPEÇÃO:
{lista_imagens}

TEXTOS ENVIADOS:
{''.join(textos) or '(nenhum texto enviado)'}

Responda SOMENTE com Markdown seguindo estas seções:
# Configuração do produto — {nome}
## Produto
- **Nome:**
- **O que é:**
- **Diferenciais:**
- **Preço / oferta:**
## Público-alvo
- **Quem é:**
- **Nível de consciência:**
- **Objeções comuns:**
## Tom de voz / regras de copy
- **Tom:**
- **Gatilhos preferidos:**
- **Proibições de copy:**
## Regras visuais OBRIGATÓRIAS
- **Cores da marca (produto/cena):**
- **Cor de destaque / cor do botão de CTA:** Não informado
- **Estilo das imagens:**
- **Sempre incluir:**
- **Formato padrão:** 1024x1024 feed
## Proibições visuais
- Não inventar rótulo, texto, marca ou detalhe diferente do produto real.
- Não distorcer proporções, cores ou materiais do produto.
- Deixar os dois cantos superiores limpos para o logo entrar na pós-produção.
## Observações livres
"""
    resposta = _bridge(modelo).pedir_texto(
        prompt, modelo=modelo,
        system_prompt="Você é um analista de produto rigoroso. Entregue apenas o Markdown solicitado.",
        timeout=300, add_dirs=[str(pdir)])
    resposta = resposta.strip()
    resposta = re.sub(r"^```(?:markdown|md)?\s*", "", resposta, flags=re.I)
    resposta = re.sub(r"\s*```$", "", resposta).strip()
    if not resposta.startswith("# Configuração do produto"):
        raise ValueError("A IA retornou uma configuração em formato inválido.")
    return resposta + "\n"


@app.route("/api/criar_produto", methods=["POST"])
def criar_produto():
    """Cria um produto do zero (wizard guiado): estrutura + config do template +
    fotos de referência, página de vendas, estáticos validados e transcrições."""
    nome = (request.form.get("nome") or "").strip().rstrip(". ")
    modelo = request.form.get("modelo") or "sonnet"
    if not nome or len(nome) > 80 or _ILEGAIS.search(nome) or "~" in nome or nome in {".", ".."} \
            or nome.split(".")[0].lower() in _RESERVADOS:
        return jsonify({"ok": False, "erro": "Nome inválido (evite / \\ ~ : * ? \" < > | e nomes reservados)."}), 400

    # Cliente opcional: cria o produto dentro de products/<cliente>/ (id = cliente~produto).
    cliente = (request.form.get("cliente") or "").strip().rstrip(". ")
    if cliente:
        if len(cliente) > 80 or _ILEGAIS.search(cliente) or "~" in cliente or cliente in {".", ".."} \
                or cliente.split(".")[0].lower() in _RESERVADOS:
            return jsonify({"ok": False, "erro": "Cliente inválido."}), 400
        cli_dir = PRODUCTS / cliente
        if cli_dir.exists() and _is_product_dir(cli_dir):
            return jsonify({"ok": False, "erro": "Já existe um produto solto com o nome desse cliente."}), 409
        pdir = cli_dir / nome
        nome_id = f"{cliente}~{nome}"
    else:
        pdir = PRODUCTS / nome
        nome_id = nome
    if pdir.exists():
        return jsonify({"ok": False, "erro": "Já existe um produto com esse nome."}), 409

    ref_dir = pdir / "referencia"
    ctx_dir = pdir / "contexto"
    try:
        ref_dir.mkdir(parents=True)
        ctx_dir.mkdir(parents=True)
        (pdir / "output").mkdir(parents=True, exist_ok=True)

        # Config a partir do template (com o nome preenchido no cabeçalho).
        tmpl = PRODUCTS / "_TEMPLATE" / "config.md"
        cfg = tmpl.read_text(encoding="utf-8") if tmpl.exists() else "# Configuração do produto\n"
        cfg = cfg.replace("[NOME DO PRODUTO]", nome)
        atomic_write_text(pdir / "config.md", cfg)

        salvos = {"referencia": 0, "estaticos": 0, "transcricoes": 0, "pagina_vendas": False}

        # Fotos de referência (identidade do produto).
        for f in request.files.getlist("referencia"):
            if _salvar_upload(f, ref_dir, REF_EXTS, _MAX_IMG, "referencia.png"):
                salvos["referencia"] += 1

        # Página de vendas: texto colado e/ou arquivo.
        pv_txt = (request.form.get("pagina_vendas_texto") or "").strip()
        if pv_txt:
            atomic_write_text(ctx_dir / "pagina-vendas.txt", pv_txt[:_MAX_TXT])
            salvos["pagina_vendas"] = True
        pv_file = request.files.get("pagina_vendas_arquivo")
        if _salvar_upload(pv_file, ctx_dir, TXT_EXTS, _MAX_TXT, "pagina-vendas.txt"):
            salvos["pagina_vendas"] = True

        # Criativos validados — ESTÁTICOS (imagens).
        for f in request.files.getlist("estaticos"):
            if _salvar_upload(f, ctx_dir, IMG_EXTS, _MAX_IMG, "criativo-validado-estatico.png"):
                salvos["estaticos"] += 1

        # Criativos validados — TRANSCRIÇÕES de vídeo (textos colados e/ou arquivos).
        n = 0
        for t in request.form.getlist("transcricao_texto"):
            t = (t or "").strip()
            if not t:
                continue
            n += 1
            atomic_write_text(ctx_dir / f"transcricao-video-{n}.txt", t[:_MAX_TXT])
            salvos["transcricoes"] += 1
        for f in request.files.getlist("transcricao_arquivo"):
            if _salvar_upload(f, ctx_dir, TXT_EXTS, _MAX_TXT, "transcricao-video.txt"):
                salvos["transcricoes"] += 1

        config_gerada = False
        erro_config = ""
        try:
            atomic_write_text(pdir / "config.md", _gerar_config_inicial(nome, pdir, modelo))
            config_gerada = True
        except Exception as exc:  # criação continua com o template revisável
            erro_config = str(exc)

        return jsonify({"ok": True, "nome": nome_id, "label": nome, "salvos": salvos,
                        "config_gerada": config_gerada, "erro_config": erro_config})
    except Exception as e:  # noqa: BLE001 — falhou no meio: não deixa produto quebrado.
        try:
            import shutil
            if pdir.exists():
                shutil.rmtree(pdir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": False, "erro": f"Falha ao criar: {e}"}), 500


# ------------------------------------------------- histórico de criativos ------

@app.route("/api/criativos/<produto>/arquivar", methods=["POST"])
def arquivar_criativos(produto):
    """Move a rodada atual (imagens + status) para historico/<timestamp> e limpa a atual."""
    pasta = criativos_dir(produto)
    if not pasta.exists():
        return jsonify({"ok": True, "arquivados": 0})
    imgs = [f for f in pasta.iterdir() if f.is_file() and f.suffix.lower() in IMG_EXTS]
    status_f = product_dir(produto) / "output" / "status.json"
    if not imgs and not status_f.exists():
        return jsonify({"ok": True, "arquivados": 0})

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = pasta / "historico" / ts
    destino.mkdir(parents=True, exist_ok=True)
    for f in imgs:
        f.rename(destino / f.name)
    if status_f.exists():
        status_f.rename(destino / "status.json")
    return jsonify({"ok": True, "arquivados": len(imgs), "id": ts})


@app.route("/api/historico/<produto>")
def historico(produto):
    base = criativos_dir(produto) / "historico"
    rodadas = []
    if base.exists():
        for d in sorted(base.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            arqs = sorted(f.name for f in d.iterdir()
                          if f.is_file() and f.suffix.lower() in IMG_EXTS)
            rodadas.append({"id": d.name, "arquivos": arqs, "total": len(arqs)})
    return jsonify(rodadas)


# ------------------------------------------------------------------ logos -----
# Etapa final: sobrepor o logo oficial (PNG) nos criativos. A composicao acontece
# no navegador (canvas), entao o servidor so guarda o logo, a config de
# posicoes/escala e recebe os PNGs ja compostos para salvar em criativos/finais/.
LOGO_ARQ = "logo.png"
FINAIS_DIR = "finais"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _logo_path(produto: str) -> Path:
    return product_dir(produto) / LOGO_ARQ


@app.route("/logo/<produto>")
def logo_img(produto):
    f = _logo_path(produto)
    if not f.exists():
        abort(404)
    return send_from_directory(f.parent, f.name)


@app.route("/api/logo/<produto>", methods=["GET"])
def get_logo(produto):
    return jsonify({"existe": _logo_path(produto).exists()})


@app.route("/api/logo/<produto>", methods=["POST"])
def upload_logo(produto):
    product_dir(produto)
    file = request.files.get("logo")
    if file is None:
        return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400
    dados = file.read(8 * 1024 * 1024 + 1)
    if len(dados) > 8 * 1024 * 1024:
        return jsonify({"ok": False, "erro": "Logo grande demais (maximo 8MB)."}), 400
    if not dados.startswith(_PNG_MAGIC):
        return jsonify({"ok": False, "erro": "O logo precisa ser um PNG (de preferencia com fundo transparente)."}), 400
    f = _logo_path(produto)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".logo.{JOBS.new_id()}.tmp")
    tmp.write_bytes(dados)
    tmp.replace(f)
    return jsonify({"ok": True})


@app.route("/api/logo/<produto>", methods=["DELETE"])
def remover_logo(produto):
    _logo_path(produto).unlink(missing_ok=True)
    return jsonify({"ok": True})


@app.route("/api/logo_config/<produto>", methods=["GET"])
def get_logo_config(produto):
    f = product_dir(produto) / "output" / "logo_config.json"
    if f.exists():
        try:
            return jsonify(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"escala": 15, "margem": 4, "posicoes": {}, "escalas": {}, "margens": {}})


def _clamp_map(m, lo, hi) -> dict:
    """Sanitiza um mapa {arquivo: numero} vindo do front, com clamp por valor."""
    out = {}
    if isinstance(m, dict):
        for k, v in m.items():
            try:
                out[str(k)] = max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                pass
    return out


@app.route("/api/logo_config/<produto>", methods=["POST"])
def salvar_logo_config(produto):
    body = request.get_json(force=True)
    out = product_dir(produto) / "output"
    out.mkdir(parents=True, exist_ok=True)
    pos = body.get("posicoes")
    cfg = {
        "escala": max(2, min(60, int(body.get("escala", 15)))),
        "margem": max(0, min(25, int(body.get("margem", 4)))),
        "posicoes": pos if isinstance(pos, dict) else {},
        "escalas": _clamp_map(body.get("escalas"), 2, 60),   # escala por criativo
        "margens": _clamp_map(body.get("margens"), 0, 25),   # margem por criativo
    }
    atomic_write_json(out / "logo_config.json", cfg)
    return jsonify({"ok": True})


@app.route("/api/criativos_lista/<produto>")
def criativos_lista(produto):
    """Lista os criativos atuais (criativo_*.png de nivel raiz, ignora finais/)."""
    pasta = criativos_dir(produto)
    itens = []
    if pasta.exists():
        for p in sorted(pasta.iterdir()):
            if (p.is_file() and p.suffix.lower() == ".png"
                    and p.name.lower().startswith("criativo_")):
                itens.append(p.name)
    return jsonify(itens)


@app.route("/api/exportar_logos/<produto>", methods=["POST"])
def exportar_logos(produto):
    """Recebe os PNGs ja compostos (logo sobreposto no navegador) e salva em finais/."""
    product_dir(produto)
    pasta = criativos_dir(produto) / FINAIS_DIR
    pasta.mkdir(parents=True, exist_ok=True)
    salvos = []
    for nome, file in request.files.items(multi=True):
        try:
            alvo = safe_child(pasta, nome, suffix=".png")
        except ValueError:
            continue
        dados = file.read(25 * 1024 * 1024 + 1)
        if len(dados) > 25 * 1024 * 1024 or not dados.startswith(_PNG_MAGIC):
            continue
        tmp = alvo.with_name(f".{alvo.name}.{JOBS.new_id()}.tmp")
        tmp.write_bytes(dados)
        tmp.replace(alvo)
        salvos.append(nome)
    if salvos:
        mirror_saida_cliente(produto, "criativos", [pasta / nome for nome in salvos])
    return jsonify({"ok": True, "salvos": salvos})


@app.route("/api/finais/<produto>")
def finais_lista(produto):
    pasta = criativos_dir(produto) / FINAIS_DIR
    itens = []
    if pasta.exists():
        for p in sorted(pasta.iterdir()):
            if p.is_file() and p.suffix.lower() == ".png":
                itens.append(p.name)
    return jsonify(itens)


def _reparar_aspas(t: str) -> str:
    """Escapa aspas duplas 'soltas' dentro dos valores de string do JSON.

    O modelo às vezes cita texto do anúncio com aspas duplas no meio de um valor,
    o que quebra o JSON. Aqui percorremos o texto rastreando se estamos dentro de
    uma string: uma aspa dupla só fecha a string se o próximo caractere não-espaço
    for estrutural (: , ] }); caso contrário, é uma aspa interna e a escapamos.
    """
    out = []
    in_str = False
    i, n = 0, len(t)
    while i < n:
        ch = t[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == '\\':  # mantém pares de escape intactos
            out.append(ch)
            if i + 1 < n:
                out.append(t[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and t[j] in ' \t\r\n':
                j += 1
            nxt = t[j] if j < n else ''
            if nxt in ':,]}' or nxt == '':
                out.append(ch)        # aspa estrutural: fecha a string
                in_str = False
            else:
                out.append('\\"')     # aspa interna solta: escapa
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _aspas_simples_para_json(t: str) -> str:
    """Converte um pseudo-JSON que usa aspas SIMPLES como delimitador (o modelo às
    vezes devolve tudo com ') em JSON válido de aspas duplas. Espelha a heurística de
    _reparar_aspas: uma ' só fecha a string se o próximo não-espaço for estrutural
    (: , ] }); caso contrário é apóstrofo interno (ex.: d'água) e fica literal. Aspas
    duplas soltas viram \\" para não quebrar o JSON resultante."""
    out = []
    in_str = False
    i, n = 0, len(t)
    while i < n:
        ch = t[i]
        if not in_str:
            if ch == "'":
                out.append('"'); in_str = True
            elif ch == '"':
                out.append('\\"')  # aspa dupla fora de string: escapa (defensivo)
            else:
                out.append(ch)
            i += 1
            continue
        if ch == '\\':
            out.append(ch)
            if i + 1 < n:
                out.append(t[i + 1]); i += 2
            else:
                i += 1
            continue
        if ch == '"':
            out.append('\\"'); i += 1; continue   # aspa dupla dentro do valor: escapa
        if ch == "'":
            j = i + 1
            while j < n and t[j] in ' \t\r\n':
                j += 1
            nxt = t[j] if j < n else ''
            if nxt in ':,]}' or nxt == '':
                out.append('"'); in_str = False    # ' estrutural: fecha a string
            else:
                out.append("'")                     # apóstrofo interno: mantém literal
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _extrair_json(texto: str):
    """Extrai o array/obj JSON de uma resposta (removendo cercas e reparando aspas)."""
    t = texto.strip()
    t = re.sub(r"^```(json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    m = re.search(r"\[.*\]", t, re.DOTALL)
    candidatos = [t]
    if m:
        candidatos.append(m.group(0))
    erro = None
    for cand in candidatos:
        # 1) como veio; 2) reparando aspas duplas soltas; 3) tratando ' como delimitador.
        for tentativa in (cand, _reparar_aspas(cand), _aspas_simples_para_json(cand)):
            try:
                return json.loads(tentativa)
            except json.JSONDecodeError as e:
                erro = e
    raise erro
