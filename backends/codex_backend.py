"""Backend de geração via Codex CLI (consome o plano ChatGPT — custo de API = zero).

Como funciona:
- Dispara `codex exec` de forma não-interativa, passando o prompt e as fotos de
  referência com `-i`. IMPORTANTE: o prompt vem ANTES dos `-i` porque a flag `-i`
  é variádica e engoliria o texto do prompt.
- O Codex salva o PNG em ~/.codex/generated_images/<sessao>/exec-<uuid>.png e o
  sandbox impede que ele copie pro destino final — então nós pegamos o PNG mais
  recente dessa pasta e copiamos para `output_path`.

Pré-requisito: `codex login` feito (verifique com `codex login status`).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# No Windows, subprocessos de console abrem uma janela CMD quando o pai roda sem
# console (pythonw). Esta flag suprime a janela. Vira 0 em outros SOs.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

GENERATED_DIR = Path.home() / ".codex" / "generated_images"
# O CLI não oferece um diretório de saída por chamada; todos os `codex exec`
# escrevem em GENERATED_DIR. Para permitir gerações CONCORRENTES (workers > 1),
# o subprocess roda FORA de lock e a atribuição do PNG à chamada certa é feita em
# 3 níveis (ver generate()): caminho impresso no stdout > pasta da sessão > claim-set.
# O lock protege apenas as seções curtas de snapshot/escolha/claim.
_CLAIM_LOCK = threading.Lock()
_CLAIMED: set[str] = set()  # PNGs já entregues a alguma chamada deste processo

# Rede de segurança do paralelismo: rate-limit do plano NÃO pode matar a imagem.
# Quando bate, a chamada espera (backoff) e tenta de novo. Assim dá pra subir os
# workers sem perder criativo — o pior caso vira "essa demorou mais", não "sumiu".
# São as esperas ENTRE tentativas (nº de retries = len(...)); a 1ª tentativa é imediata.
_RETRY_ESPERAS = [5, 15, 40]


class _RateLimit(RuntimeError):
    """Rate-limit transitório do plano ChatGPT: vale a pena esperar e tentar de novo.
    Diferente de 'usage limit' (cota do dia/plano esgotada), que não adianta repetir."""


def _dormir_cancelavel(segundos: float, cancel_event=None) -> None:
    """Espera acordando cedo se o usuário cancelar (não prende o backoff inteiro)."""
    fim = time.time() + segundos
    while time.time() < fim:
        if cancel_event is not None and cancel_event.is_set():
            return
        time.sleep(0.5)

# Caminho de PNG dentro de generated_images impresso no stdout do codex (correlação exata).
_RE_PNG_STDOUT = re.compile(
    r"(?:[A-Za-z]:)?[\\/][^\s'\"<>|]*generated_images[^\s'\"<>|]*?\.png", re.IGNORECASE)
# Session id no cabeçalho do codex exec (ex.: "session id: 0198..." ou "session_id: ...").
_RE_SESSION = re.compile(r"session[\s_-]*id\s*:?\s*([0-9a-f][0-9a-f-]{7,})", re.IGNORECASE)


def _run_codex(cmd: list[str], timeout: int, cwd: str | None, cancel_event=None):
    """Roda o Codex de forma robusta no Windows.

    - stdin fechado (o Codex nunca fica esperando input).
    - stdout/stderr vão para arquivos temporários (evita o deadlock clássico de
      pipe quando o processo-neto codex.exe herda os handles e não os fecha).
    - no timeout OU no cancelamento, mata a ÁRVORE de processos (node.exe + codex.exe).
    Retorna (stdout, stderr, timed_out, cancelled).
    """
    out_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".out", encoding="utf-8", errors="replace")
    err_f = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".err", encoding="utf-8", errors="replace")
    out_path, err_path = out_f.name, err_f.name
    timed_out = False
    cancelled = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
            cwd=cwd,
            text=True,
            creationflags=_NO_WINDOW,
        )
        # Poll curto pra poder reagir ao cancelamento sem esperar o timeout inteiro.
        deadline = time.time() + timeout
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    _kill_tree(proc.pid)
                    break
                if time.time() >= deadline:
                    timed_out = True
                    _kill_tree(proc.pid)
                    break
    finally:
        out_f.close()
        err_f.close()
    stdout = Path(out_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(err_path).read_text(encoding="utf-8", errors="replace")
    for p in (out_path, err_path):
        try:
            os.unlink(p)
        except OSError:
            pass
    return stdout, stderr, timed_out, cancelled


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, creationflags=_NO_WINDOW,
        )
    else:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _codex_cmd_base() -> list[str]:
    """Comando base para invocar o Codex.

    No Windows, `codex` é um shim `codex.CMD` que passa pelo cmd.exe e quebra
    caminhos com espaço. Por isso, quando possível, chamamos `node codex.js`
    diretamente (node.exe é um executável real e o Python faz o quoting certo).
    """
    node = shutil.which("node")
    candidatos = []
    exe = shutil.which("codex")
    if exe:
        # .../npm/codex.CMD -> .../npm/node_modules/@openai/codex/bin/codex.js
        candidatos.append(Path(exe).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidatos.append(Path(appdata) / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")

    if node:
        for js in candidatos:
            if js.exists():
                return [node, str(js)]

    # Fallbacks: binário nativo, ou o próprio shim (pode ter problema com espaços).
    if exe:
        return [exe]
    return ["codex"]


def _diagnostico(stderr: str) -> str | None:
    """Traduz erros conhecidos do Codex numa 1ª linha clara (a UI mostra só ela)."""
    s = (stderr or "").lower()
    if "usage limit" in s or "hit your usage" in s:
        quando = ""
        m = re.search(r"try again at ([^\n(]+)", stderr, re.IGNORECASE)
        if m:
            quando = f" Volta a funcionar em {m.group(1).strip().rstrip('.')}."
        return ("Limite de uso do Codex (plano ChatGPT) atingido." + quando +
                " Aguarde o reset, faça upgrade do plano, ou troque para o backend de API.")
    if "not logged in" in s or "please run" in s and "login" in s or "unauthorized" in s:
        return "Codex não está autenticado. Rode 'codex login' no terminal e tente de novo."
    if "rate limit" in s:
        return "Codex retornou limite de requisições (rate limit). Aguarde um pouco e tente de novo."
    return None


def _snapshot_pngs() -> dict[Path, float]:
    if not GENERATED_DIR.exists():
        return {}
    return {p: p.stat().st_mtime for p in GENERATED_DIR.rglob("*.png")}


def generate(
    prompt: str,
    reference_paths: list,
    output_path,
    size: str = "1024x1024",
    timeout: int = 300,
    workdir: str | None = None,
    cancel_event=None,
    reasoning: str | None = None,
    model: str | None = None,
    n_estilo: int = 0,
    anexos_desc: str | None = None,
    **_ignored,
) -> str:
    """Gera 1 imagem e a salva em output_path. Levanta exceção em caso de falha.

    n_estilo: quantas das imagens anexadas (as ÚLTIMAS da lista) são REFERÊNCIA DE
    ESTILO — não o produto. Quando > 0, o wrapper instrui o agente a aplicar
    FORTEMENTE a linguagem visual dessas fotos no resultado.
    anexos_desc: quando fornecido, SUBSTITUI a moldura padrão que descreve o papel
    das imagens anexadas (usado pelo Refazer, que tem ordem própria de anexos).
    """
    output_path = Path(output_path)

    n_estilo = int(n_estilo or 0)
    if anexos_desc:
        anexos_txt = anexos_desc
    elif not reference_paths:
        # Produto sem foto real (ex.: curso/infoproduto): não há imagem de identidade.
        # Construa a arte só a partir do briefing, sem prometer fidelidade a um produto
        # físico que não foi fornecido.
        anexos_txt = (
            "Nenhuma imagem de referência foi anexada: este produto não tem foto real. "
            "Crie a arte inteiramente a partir do briefing abaixo, sem inventar uma "
            "embalagem/rótulo específico como se fosse o produto real."
        )
    elif n_estilo > 0:
        n_produto = max(0, len(reference_paths) - n_estilo)
        anexos_txt = (
            f"São {len(reference_paths)} imagens anexadas: as PRIMEIRAS {n_produto} são as fotos "
            f"REAIS do PRODUTO (a identidade — forma, cor, logo, rótulo, textos — a manter igual) "
            f"e as ÚLTIMAS {n_estilo} são REFERÊNCIAS DE ESTILO escolhidas pelo usuário. "
            "As referências de estilo são OBRIGATÓRIAS e mandam mais que o texto: passe TODAS elas "
            "ao $imagegen e faça a imagem final no MESMO ESTILO VISUAL delas — paleta de cores, "
            "composição, enquadramento, tipografia/layout do texto, luz e clima. Não precisa ficar "
            "idêntico, pode adaptar, mas o resultado TEM que pertencer claramente à mesma linguagem "
            "visual das referências de estilo (nunca um estilo completamente diferente). O briefing "
            "de texto é só direção extra; onde ele conflitar com o estilo das referências, o ESTILO "
            "das referências vence. NÃO desenhe os produtos/objetos/pessoas que aparecem nas fotos "
            "de estilo — delas você tira só a linguagem visual, não o conteúdo."
        )
    else:
        anexos_txt = (
            "As imagens anexadas são a referência do PRODUTO (a identidade dele), NÃO a cena a ser "
            "copiada: use-as para manter o produto igual, mas monte a cena nova do briefing."
        )

    instruction = (
        "Gere UMA imagem usando $imagegen a partir do briefing abaixo. " + anexos_txt + "\n"
        "Ao chamar o $imagegen, transporte o briefing INTEIRO e FIELMENTE para o prompt da "
        "ferramenta (não resuma nem descarte a direção de arte, a tipografia, a cor de "
        "destaque, o alinhamento nem os textos exatos) e ANEXE ao $imagegen todas as imagens de "
        "referência recebidas. No prompt do $imagegen, deixe explícito "
        "que o produto deve ser REDESENHADO/re-renderizado integrado à cena (mesma identidade "
        "da referência, mas re-iluminado no novo ângulo), e que é PROIBIDO colar ou recortar "
        "a foto de referência com o fundo original. Não explique nem descreva para mim: só gere.\n\n"
        f"{prompt}"
    )

    cmd = _codex_cmd_base() + [
        "exec",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
    ]
    # Modelo e esforço de raciocínio (opcionais): menos raciocínio = mais rápido,
    # já que gerar imagem não exige raciocínio profundo. Vêm ANTES do prompt.
    if model:
        cmd += ["-m", str(model)]
    if reasoning:
        cmd += ["-c", f"model_reasoning_effort={reasoning}"]
    cmd += [instruction]
    for ref in reference_paths:
        cmd += ["-i", str(ref)]

    def _tentativa() -> str:
        """Uma tentativa completa de gerar+reivindicar o PNG. Levanta _RateLimit
        (retentável) ou RuntimeError (falha dura) quando não sai imagem."""
        with _CLAIM_LOCK:
            before = _snapshot_pngs()
        start = time.time()
        # O subprocess roda SEM lock: é aqui que gerações concorrentes acontecem de fato.
        stdout, stderr, timed_out, cancelled = _run_codex(
            cmd, timeout=timeout, cwd=workdir, cancel_event=cancel_event)
        if cancelled:
            raise RuntimeError("Geração interrompida pelo usuário.")

        # O cabeçalho do codex (com o session id) sai no STDERR; o caminho do PNG, quando
        # impresso, pode aparecer em qualquer um dos dois. Procura nos dois.
        saida_cli = f"{stdout or ''}\n{stderr or ''}"

        with _CLAIM_LOCK:
            after = _snapshot_pngs()
            # Só conta como resultado um PNG REALMENTE novo (não existia antes, ou foi
            # (re)escrito depois do início desta geração) e ainda NÃO reivindicado por
            # outra chamada concorrente. NÃO existe fallback por "mtime perto do início".
            candidatos = [p for p, m in after.items()
                          if (p not in before or m > start) and str(p) not in _CLAIMED]

            escolhido = None
            # 1) Correlação exata: o codex imprimiu o caminho do PNG.
            m = _RE_PNG_STDOUT.search(saida_cli)
            if m:
                p = Path(m.group(0))
                if p.exists() and str(p) not in _CLAIMED:
                    escolhido = p
            # 2) Session id (do cabeçalho no stderr) -> o PNG desta chamada vive em
            #    generated_images/<session_id>/. Correlação exata (validada: as pastas
            #    têm exatamente o nome do session id).
            if escolhido is None:
                ms = _RE_SESSION.search(saida_cli)
                if ms:
                    da_sessao = [p for p in candidatos if ms.group(1).lower() in str(p).lower()]
                    if da_sessao:
                        candidatos = da_sessao
            if escolhido is None:
                if not candidatos:
                    if timed_out:
                        raise RuntimeError(
                            "Timeout: o Codex demorou demais e foi encerrado.\n"
                            f"stdout (fim):\n{(stdout or '')[-1500:]}\n"
                            f"stderr (fim):\n{(stderr or '')[-800:]}")
                    # Rate-limit transitório: sinaliza como retentável (a rede de segurança
                    # cuida do backoff). 'usage limit' (cota esgotada) NÃO cai aqui.
                    if "rate limit" in (stderr or "").lower():
                        raise _RateLimit(_diagnostico(stderr) or "Rate limit do Codex.")
                    motivo = _diagnostico(stderr) or (
                        "Codex não gerou nenhuma imagem (possível limite de uso do plano, "
                        "erro, ou resposta sem imagem). Nenhuma imagem foi salva para este "
                        "criativo.")
                    raise RuntimeError(
                        f"{motivo}\n"
                        f"stdout (fim):\n{(stdout or '')[-1500:]}\n"
                        f"stderr (fim):\n{(stderr or '')[-800:]}"
                    )
                # 3) Claim-set: entre os novos não reivindicados, o mais recente.
                escolhido = max(candidatos, key=lambda p: p.stat().st_mtime)
            _CLAIMED.add(str(escolhido))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(escolhido, output_path)
        return str(output_path)

    # Laço de retry: só o rate-limit é retentável. Timeout, cota esgotada e recusa
    # falham na hora (repetir não ajudaria). A 1ª tentativa é imediata.
    ultima: _RateLimit | None = None
    for i in range(len(_RETRY_ESPERAS) + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Geração interrompida pelo usuário.")
        try:
            return _tentativa()
        except _RateLimit as e:
            ultima = e
            if i < len(_RETRY_ESPERAS):
                _dormir_cancelavel(_RETRY_ESPERAS[i], cancel_event)
                continue
            raise RuntimeError(
                f"Rate limit do Codex persistiu após {len(_RETRY_ESPERAS) + 1} tentativas. "
                f"Baixe o 'workers' no config.toml ou aguarde. Detalhe: {ultima}")
    # Inalcançável (o for sempre retorna ou levanta), mas mantém o type-checker feliz.
    raise RuntimeError(str(ultima) if ultima else "Falha desconhecida na geração.")
