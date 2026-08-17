"""Criativos Express â€” geraÃ§Ã£o de imagens em lote.

LÃª products/<produto>/output/prompts.json e gera 1 imagem por entrada, sempre
anexando as fotos de products/<produto>/referencia/ para manter o produto IDÃŠNTICO.

Backend padrÃ£o: Codex (plano ChatGPT, grÃ¡tis). Alternativa: API paga (gpt-image-2).

Uso:
    python gerar.py <produto> [--backend codex|api]
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from workspace import atomic_write_json, atomic_write_text, influencer_dir, product_dir

ROOT = Path(__file__).resolve().parent
PRODUCTS = ROOT / "products"

# No Windows, subprocessos de console (ex.: ffmpeg) abrem uma janela CMD quando o
# pai roda sem console (pythonw). Esta flag suprime a janela. Vira 0 em outros SOs.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Formatos aceitos diretamente como referÃªncia pelo gpt-image-2 / Codex.
FORMATOS_OK = {".png", ".jpg", ".jpeg", ".webp"}
# Formatos que precisam ser convertidos antes (via ffmpeg).
FORMATOS_CONVERTER = {".avif", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}


# Regra de fidelidade injetada em TODO prompt.
# IMPORTANTE: fidelidade Ã© do PRODUTO, nÃ£o da CENA. Martelar "idÃªntico Ã  referÃªncia" fazia o
# modelo COLAR o produto com o fundo preto e o Ã¢ngulo da prÃ³pria foto de referÃªncia. Aqui a
# identidade do produto Ã© dita UMA vez, e a instruÃ§Ã£o de re-iluminar/re-angular/integrar na
# cena nova vem em destaque (Ã© o que o modelo precisa ouvir perto da imagem anexada).
PREFIXO_FIDELIDADE = (
    "IDENTIDADE DO PRODUTO: mantenha o produto com o MESMO formato, cor, material, tampa, "
    "logotipo, símbolo e textos/rótulos reais das fotos do produto anexadas. Não invente "
    "rótulos, números, marcas nem símbolos que não existam no produto real. "
    "Das FOTOS DO PRODUTO (as de identidade) NÃO copie o fundo de estúdio nem o ângulo delas — "
    "servem só para acertar forma, cor, símbolo e rótulo. REDESENHE o produto do zero dentro da "
    "cena, reiluminado no novo ângulo; NÃO cole nem recorte a foto do produto com o fundo dela "
    "por cima da cena. A COMPOSIÇÃO, o fundo, o enquadramento e o clima seguem o briefing e as "
    "referências de estilo anexadas. "
    "Componha um ANÚNCIO ao redor do produto com a camada gráfica de texto (headline, apoio, "
    "selo, botão de CTA) diagramada como um designer sênior, ortografia perfeita em português. "
    "ACENTOS OBRIGATÓRIOS: desenhe o texto com os acentos e a cedilha EXATAMENTE como escritos "
    "(á â ã à ç é ê í ó ô õ ú); NUNCA remova, troque ou 'americanize' o texto (é 'Não', 'você', "
    "'aliança', 'explicação' — jamais 'Nao', 'voce', 'alianca'). Texto sem acento = arte reprovada. "
    "PROIBIDO hífen ou travessão em qualquer texto da arte. PROIBIDO criar logos, escudos, "
    "emblemas, marcas ou estampas que não estejam no produto real; pessoas usam roupas neutras. "
    "ANATOMIA (regra dura de segurança): se aparecer alguma pessoa, a anatomia tem que ser "
    "PERFEITA — mãos com exatamente cinco dedos, proporções e articulações corretas, sem membros "
    "extras nem faltando, sem dedos fundidos ou tortos. EVITE composições de risco que o gerador "
    "erra: várias mãos juntas, dedos entrelaçados, brinde/aperto em grupo, multidão em primeiro "
    "plano ou poses complexas. Prefira o produto como herói e, quando houver pessoa, UMA única "
    "mão/pessoa num gesto simples e nítido, em plano limpo. "
    "PROIBIDO desenhar objetos citados no texto que não existam nas fotos (certificado, medalha, "
    "brinde, cartela, embalagem): a menção existe só como texto na arte. "
    "Os DOIS cantos superiores da arte ficam LIMPOS (reservados para o logo oficial em pós-produção)."
)

# Variante usada quando o produto NÃO tem foto real de referência (ex.: curso,
# infoproduto, serviço). Sem imagem de identidade, o produto é construído a partir
# do briefing e do contexto textual — sem prometer fidelidade a uma embalagem que
# não existe e sem instruir o modelo a "não copiar a foto" (não há foto).
PREFIXO_SEM_REF_PRODUTO = (
    "SEM FOTO DE REFERÊNCIA DO PRODUTO: este produto não tem imagem real anexada "
    "(pode ser um curso, infoproduto, serviço ou algo intangível). NÃO invente uma "
    "embalagem, caixa, frasco ou rótulo específico como se fosse o produto real; "
    "represente-o de forma coerente com o que o briefing e o contexto descrevem "
    "(ex.: mockup de tela/dispositivo, elemento gráfico, símbolo do tema, cena de uso), "
    "sem alegar uma identidade visual que não foi fornecida. "
    "Componha um ANÚNCIO com a camada gráfica de texto (headline, apoio, selo, botão de "
    "CTA) diagramada como um designer sênior, ortografia perfeita em português. "
    "ACENTOS OBRIGATÓRIOS: desenhe o texto com os acentos e a cedilha EXATAMENTE como escritos "
    "(á â ã à ç é ê í ó ô õ ú); NUNCA remova, troque ou 'americanize' o texto (é 'Não', 'você', "
    "'aliança', 'explicação' — jamais 'Nao', 'voce', 'alianca'). Texto sem acento = arte reprovada. "
    "PROIBIDO hífen ou travessão em qualquer texto da arte. PROIBIDO criar logos, escudos, "
    "emblemas ou marcas que não estejam descritos; pessoas usam roupas neutras. "
    "ANATOMIA (regra dura de segurança): se aparecer alguma pessoa, a anatomia tem que ser "
    "PERFEITA — mãos com exatamente cinco dedos, proporções e articulações corretas, sem "
    "membros extras nem faltando, sem dedos fundidos ou tortos. EVITE composições de risco "
    "que o gerador erra: várias mãos juntas, dedos entrelaçados, brinde/aperto em grupo, "
    "multidão em primeiro plano ou poses complexas. "
    "Os DOIS cantos superiores da arte ficam LIMPOS (reservados para o logo oficial em pós-produção)."
)

# Verdade visual durável do produto: correções que o usuário fez refinando criativos
# (ex.: "vem sempre numa caixinha preta, nunca embalagem transparente"). Fica em
# contexto/verdade_visual.md e entra em TODO prompt de imagem — geração inicial e refino —
# para o modelo não repetir o mesmo erro visual em criativo nenhum.
VERDADE_VISUAL_ARQ = "verdade_visual.md"


def carregar_verdade_visual(product_path: Path) -> str:
    """Lê os fatos visuais duráveis de contexto/verdade_visual.md e devolve um bloco
    pronto para injetar no prompt, ou '' se não houver nenhum."""
    f = product_path / "contexto" / VERDADE_VISUAL_ARQ
    if not f.exists():
        return ""
    itens = []
    for linha in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = linha.strip()
        if s.startswith("- "):
            item = s[2:].strip()
            if item:
                itens.append(item)
    if not itens:
        return ""
    corpo = "\n".join(f"- {i}" for i in itens)
    return (
        "FATOS VISUAIS OBRIGATORIOS DESTE PRODUTO (correcoes ja aprendidas em refinos "
        "anteriores; valem SEMPRE e tem prioridade sobre o briefing da cena):\n" + corpo
    )


def carregar_config() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def coletar_referencias(product_dir: Path) -> list[Path]:
    """Retorna atÃ© 16 fotos de referÃªncia utilizÃ¡veis (convertendo formatos quando preciso)."""
    ref_dir = product_dir / "referencia"
    if not ref_dir.exists():
        return []
    cache = product_dir / "output" / ".refs"
    refs: list[Path] = []
    # Prioriza formatos jÃ¡ aceitos; evita duplicar o mesmo produto (mesmo nome-base).
    arquivos = [p for p in sorted(ref_dir.iterdir())
                if p.is_file() and p.name != ".gitkeep"]
    stems_ok = {p.stem.lower() for p in arquivos if p.suffix.lower() in FORMATOS_OK}
    for p in arquivos:
        ext = p.suffix.lower()
        if ext in FORMATOS_OK:
            refs.append(p)
        elif ext in FORMATOS_CONVERTER and p.stem.lower() not in stems_ok:
            cache.mkdir(parents=True, exist_ok=True)
            destino = cache / (p.stem + ".png")
            if not destino.exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(p), str(destino)],
                    capture_output=True, creationflags=_NO_WINDOW,
                )
            if destino.exists():
                refs.append(destino)
    return refs[:16]


def coletar_referencias_estilo(product_dir: Path) -> list[Path]:
    """Fotos de ESTILO/CENÁRIO anexadas pelo usuário (fundos, estádios, estilos de
    imagem). Direção visual, NÃO identidade do produto. Ficam em referencia_estilo/.
    Entram em TODA geração de imagem deste produto."""
    ref_dir = product_dir / "referencia_estilo"
    if not ref_dir.exists():
        return []
    refs: list[Path] = []
    for p in sorted(ref_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in FORMATOS_OK:
            refs.append(p)
    return refs[:12]


# ---- Influenciador (opcional): pessoa real que aparece IDÊNTICA nos criativos ----
# A ativação é POR CRIATIVO, via menção explícita "@Nome" no prompt de imagem
# (ex.: "@Julia segurando o produto"). Sem a menção, "uma pessoa/influenciadora"
# genérica continua gerando gente aleatória — de propósito, para o mesmo lote poder
# misturar criativos com o influenciador, sem pessoa e com cliente genérico.
# As fotos vivem em influenciadores/<nome>/referencia/ e as marcadas como principais
# (principais.json) entram na geração, dentro do teto de 5 anexos.
INFLU_MAX_FOTOS = 2


def influenciadores_registrados() -> list[str]:
    from workspace import INFLUENCIADORES
    if not INFLUENCIADORES.exists():
        return []
    return [d.name for d in sorted(INFLUENCIADORES.iterdir())
            if d.is_dir() and not d.name.startswith(".")]


def influenciador_no_texto(texto: str) -> str | None:
    """Detecta a menção @Nome de um influenciador cadastrado no texto do prompt."""
    if not texto or "@" not in texto:
        return None
    # Nomes mais longos primeiro: "@Ana Clara" ganha de "@Ana".
    for nome in sorted(influenciadores_registrados(), key=len, reverse=True):
        if re.search("@" + re.escape(nome) + r"(?!\w)", texto, re.IGNORECASE):
            return nome
    return None


def _texto_sem_mencao(texto: str, nome: str) -> str:
    """Troca '@Nome' por 'Nome' antes de mandar pro gerador (o '@' literal poderia
    virar texto desenhado na arte)."""
    return re.sub("@" + re.escape(nome), nome, texto, flags=re.IGNORECASE)


def influenciador_do_criativo(product_path: Path, arquivo: str) -> str | None:
    """Influenciador de um criativo JÁ GERADO (para Refinar/Refazer manterem o mesmo
    rosto): acha a entrada do prompts.json pelo id-base do arquivo e detecta o @Nome."""
    m = _RE_VERSAO.match(arquivo)
    base = m.group(1) if (m and m.group(1)) else Path(arquivo).stem
    f = product_path / "output" / "prompts.json"
    if not f.exists():
        return None
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        lista = dados["criativos"] if isinstance(dados, dict) and "criativos" in dados else dados
        for e in lista:
            if str(e.get("id")) == base:
                return influenciador_no_texto(str(e.get("prompt") or ""))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def coletar_referencias_influenciador(nome: str, limite: int = INFLU_MAX_FOTOS) -> list[Path]:
    """Fotos do influenciador que entram na geração: as marcadas como PRINCIPAIS
    (principais.json, na ordem marcada) ou, sem marcação, as primeiras por nome."""
    try:
        d = influencer_dir(nome)
    except ValueError:
        return []
    ref_dir = d / "referencia"
    if not ref_dir.exists():
        return []
    fotos = [p for p in sorted(ref_dir.iterdir())
             if p.is_file() and p.suffix.lower() in FORMATOS_OK]
    principais: list[Path] = []
    pj = d / "principais.json"
    if pj.exists():
        try:
            marcadas = [str(x) for x in json.loads(pj.read_text(encoding="utf-8"))]
            por_nome = {p.name: p for p in fotos}
            principais = [por_nome[m] for m in marcadas if m in por_nome]
        except (OSError, json.JSONDecodeError):
            principais = []
    return (principais or fotos)[:max(0, limite)]


def _perfil_influenciador(nome: str) -> str:
    """Descrição canônica da pessoa (perfil.md), pronta para injetar no prompt."""
    try:
        perfil = influencer_dir(nome) / "perfil.md"
    except ValueError:
        return ""
    if not perfil.exists():
        return ""
    txt = perfil.read_text(encoding="utf-8", errors="replace").strip()
    if not txt:
        return ""
    return "PERFIL CANONICO DO INFLUENCIADOR (fatos que valem em toda cena com pessoa):\n" + txt


def _influ_look_fixo(nome: str) -> bool:
    """True se o perfil do influenciador declara um LOOK FIXO (uniforme/roupa/boné/
    emblemas travados que fazem parte da identidade da pessoa e devem ser reproduzidos
    IDÊNTICOS em toda cena). Marcado com 'LOOK FIXO' no perfil.md."""
    try:
        perfil = influencer_dir(nome) / "perfil.md"
    except ValueError:
        return False
    if not perfil.exists():
        return False
    txt = perfil.read_text(encoding="utf-8", errors="replace").lower()
    return "look fixo" in txt or "look_fixo" in txt


def _bloco_influenciador(nome: str, n_influ: int, look_fixo: bool = False) -> str:
    """Instrução de identidade da pessoa: as ÚLTIMAS n_influ imagens anexadas são o
    influenciador, e a pessoa do criativo tem que ser EXATAMENTE essa.

    look_fixo=True: a ROUPA/uniforme/boné/emblemas fazem parte da identidade e devem ser
    reproduzidos IDÊNTICOS às fotos (não trocar por roupa neutra). Caso contrário, mantém
    o comportamento padrão (copiar só a identidade física, roupa neutra na cena)."""
    if n_influ <= 0:
        return ""
    base = (
        f"INFLUENCIADOR NA CENA: das imagens anexadas, as ÚLTIMAS {n_influ} são fotos REAIS "
        f"de '{nome}', a pessoa que o briefing pede na cena. A pessoa do criativo é "
        "EXATAMENTE essa: mesmo rosto, mesmos traços, mesmo tom de pele, "
        "mesmo cabelo e mesmo corpo das fotos — a semelhança facial é OBRIGATÓRIA e tem "
        "prioridade máxima sobre qualquer outra direção. REDESENHE a pessoa integrada à cena "
        "nova (nova luz, novo ângulo, nova pose); NÃO recorte nem cole as fotos dela, NÃO "
        "'embeleze', rejuvenesça ou altere o rosto, NÃO troque por outra pessoa parecida. "
    )
    if look_fixo:
        return base + (
            "LOOK FIXO OBRIGATÓRIO: a ROUPA, o BONÉ e todos os EMBLEMAS/PATCHES/TEXTOS da "
            "pessoa fazem parte da identidade dela e têm que ser IDÊNTICOS aos das fotos "
            "anexadas — mesmo boné, mesma camisa/uniforme, mesmas insígnias e os mesmos "
            "textos, sem trocar por outra roupa e sem versão de terno ou de luxo. Das fotos "
            "copie a identidade física E o figurino; mude apenas o fundo, a luz, o ângulo e a pose."
        )
    return base + (
        "Dessas fotos NÃO copie o fundo, a roupa nem a pose — só a identidade física da pessoa."
    )


def _contextos_ref(product_dir: Path, tipo: str) -> dict:
    """Mapa {arquivo: contexto} das referências, do json que o app grava quando o
    usuário comenta cada imagem (ex.: 'fundo de estádio à noite'). tipo: estilo|produto."""
    nome = "referencias_estilo.json" if tipo == "estilo" else "referencias_produto.json"
    f = product_dir / "output" / nome
    if not f.exists():
        return {}
    try:
        dados = json.loads(f.read_text(encoding="utf-8"))
        return {str(i.get("arquivo")): str(i.get("contexto") or "").strip()
                for i in dados if isinstance(i, dict) and i.get("arquivo")}
    except Exception:  # noqa: BLE001
        return {}


def _bloco_estilo(n_produto: int, estilo_infos: list) -> str:
    """Instrução que separa, no prompt, as fotos do PRODUTO das de ESTILO (por ordem),
    e dá o CONTEXTO de cada referência de estilo (o comentário do usuário).

    estilo_infos: lista de (nome_arquivo, contexto) na MESMA ordem das imagens anexadas.
    """
    n_estilo = len(estilo_infos)
    if n_estilo <= 0:
        return ""
    linhas = []
    for idx, (_nome, ctx) in enumerate(estilo_infos, start=1):
        desc = ctx if ctx else "referência de estilo/cenário (aplique a linguagem visual)"
        linhas.append(f"  - imagem anexada {n_produto + idx} (referência de estilo {idx}): {desc}")
    # Sem foto do produto (n_produto == 0), TODAS as imagens anexadas são de estilo.
    if n_produto <= 0:
        abertura = (
            f"REFERENCIA DE ESTILO/CENARIO ANEXADA: este produto nao tem foto real; as "
            f"{n_estilo} imagens em anexo sao TODAS REFERENCIAS DE ESTILO/CENARIO escolhidas pelo "
        )
    else:
        abertura = (
            f"REFERENCIA DE ESTILO/CENARIO ANEXADA: das imagens em anexo, as PRIMEIRAS {n_produto} sao "
            f"as fotos REAIS do produto (identidade: forma, cor, logo, rotulo, textos, que voce mantem "
            f"exatamente). As {n_estilo} SEGUINTES sao REFERENCIAS DE ESTILO/CENARIO escolhidas pelo "
        )
    return (
        abertura +
        "usuario — sao OBRIGATORIAS e mandam mais que o texto: copie DELAS o fundo/cenario, a paleta "
        "de cores, a composicao, o enquadramento, o layout/tipografia, a luz e o clima. O que cada "
        "uma representa:\n" + "\n".join(linhas) + "\n"
        "NAO trate a referencia de estilo como o produto, NAO desenhe os objetos/produtos/pessoas "
        "que aparecem nela; dela voce tira so a linguagem visual. O resultado tem que pertencer "
        "claramente ao mesmo estilo dessas referencias (adaptado, nunca um estilo diferente). O "
        "produto continua sendo EXATAMENTE o das fotos reais."
    )


def _pngs_existentes(out_dir: Path) -> list[str]:
    """PNGs jÃ¡ gerados na rodada atual (ignora historico/).

    So arquivos criativo_*.png: protege a grade de arquivos avulsos que o Codex
    eventualmente salva por conta propria no diretorio de trabalho.
    """
    if not out_dir.exists():
        return []
    return sorted(p.name for p in out_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".png"
                  and p.name.lower().startswith("criativo_"))


def _montar_gerar_um(backend, referencias, size, quality, timeout, out_dir,
                     cancel_event=None, reasoning=None, img_model=None, n_estilo=0,
                     anexos_desc=None):
    """Devolve a funÃ§Ã£o gerar_um(prompt, out_file) do backend escolhido.

    n_estilo: quantas das `referencias` (as ÚLTIMAS) são de ESTILO, não do produto
    — repassado ao backend para ele aplicar fortemente a linguagem visual delas.
    anexos_desc: descrição própria do papel dos anexos (usada pelo Refazer).
    A gerar_um devolvida aceita os mesmos três como kwargs POR CHAMADA (a geração em
    lote varia os anexos por criativo quando o prompt menciona um @influenciador).
    """
    if backend == "api":
        from backends import api_backend as be

        def gerar_um(prompt, out_file, referencias=referencias, n_estilo=n_estilo,
                     anexos_desc=anexos_desc):
            return be.generate(prompt, referencias, out_file, size=size,
                               quality=quality, timeout=timeout, n_estilo=n_estilo,
                               anexos_desc=anexos_desc)
    else:
        from backends import codex_backend as be

        # Workdir ISOLADO: o Codex (sandbox workspace-write) as vezes salva uma
        # copia do PNG por conta propria no diretorio de trabalho. Se o workdir
        # fosse a pasta da grade, esse arquivo avulso apareceria como criativo.
        # IMPORTANTE (paralelismo): cada geração ganha um SUBDIRETÓRIO próprio dentro
        # do scratch. Vários codex concorrentes compartilhando o MESMO cwd disputavam
        # os arquivos avulsos do sandbox e podiam se atrapalhar (efeito "1 de cada
        # vez"); com um workdir por job eles rodam de fato em paralelo, sem contenção.
        scratch_base = out_dir / ".codex_scratch"
        scratch_base.mkdir(parents=True, exist_ok=True)

        def gerar_um(prompt, out_file, referencias=referencias, n_estilo=n_estilo,
                     anexos_desc=anexos_desc):
            scratch = scratch_base / __import__('uuid').uuid4().hex
            scratch.mkdir(parents=True, exist_ok=True)
            try:
                return be.generate(prompt, referencias, out_file, size=size,
                                   timeout=timeout, workdir=str(scratch),
                                   cancel_event=cancel_event,
                                   reasoning=reasoning, model=img_model, n_estilo=n_estilo,
                                   anexos_desc=anexos_desc)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
    return gerar_um


def _opcoes_velocidade(cfg: dict):
    """Lê da config o esforço de raciocínio e o modelo de imagem (aceleradores)."""
    reasoning = (cfg.get("reasoning") or "").strip() or None
    img_model = (cfg.get("img_model") or "").strip() or None
    return reasoning, img_model


def _cancelado(cancel_event) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _marcar_prompt_gerado(prompts_file: Path, cid: str) -> None:
    """Grava status='gerado' na entrada do prompts.json (ciclo de vida da UI)."""
    try:
        dados = json.loads(prompts_file.read_text(encoding="utf-8"))
        lista = dados["criativos"] if isinstance(dados, dict) and "criativos" in dados else dados
        for e in lista:
            if str(e.get("id")) == cid:
                e["status"] = "gerado"
        atomic_write_json(prompts_file, dados)
    except Exception:  # noqa: BLE001 â€” marcaÃ§Ã£o Ã© best-effort
        pass


def gerar_criativos(produto: str, backend: str | None = None, on_progress=None,
                    ids: list[str] | None = None, cancel_event=None,
                    modo: str = "pendentes") -> dict:
    """Gera os criativos de um produto (todos, ou sÃ³ os de `ids`). Retorna o status final.

    on_progress(status_dict) Ã© chamado a cada atualizaÃ§Ã£o (usado pelo painel).
    """
    cfg = carregar_config()["geracao"]
    backend = backend or cfg.get("backend", "codex")
    size = cfg.get("size", "1024x1024")
    quality = cfg.get("quality", "high")
    timeout = int(cfg.get("timeout", 300))
    # Paralelismo so no backend codex (a correlacao concorrente vive la);
    # backend api continua sequencial por prudencia com rate limit.
    workers = max(1, int(cfg.get("workers", 1))) if backend == "codex" else 1

    product_path = product_dir(produto)
    verdade_visual = carregar_verdade_visual(product_path)
    prompts_file = product_path / "output" / "prompts.json"
    if not prompts_file.exists():
        raise FileNotFoundError(
            f"NÃ£o achei {prompts_file}. Rode a skill /gerar-prompts-imagem antes."
        )

    entradas = json.loads(prompts_file.read_text(encoding="utf-8"))
    if isinstance(entradas, dict) and "criativos" in entradas:
        entradas = entradas["criativos"]

    # prompts.json vazio/quebrado ([], {}, {"criativos": []} ou formato invÃ¡lido) =
    # NENHUM criativo pra renderizar. Falha ALTO na origem (nÃ£o segue pra 0 imagens/exit 0):
    # isso Ã© a skill /gerar-prompts-imagem nÃ£o ter produzido prompt algum. O filtro de
    # "pendentes" (jÃ¡ renderizados) acontece DEPOIS e continua podendo zerar sem erro.
    if not isinstance(entradas, list) or not entradas:
        raise ValueError(
            f"{prompts_file} nÃ£o descreve nenhum criativo (lista vazia ou formato "
            f"invÃ¡lido). Rode a skill /gerar-prompts-imagem para gerar os prompts antes."
        )

    if modo not in {"pendentes", "substituir"}:
        raise ValueError("Modo de geraÃ§Ã£o invÃ¡lido.")
    if ids:
        alvo = {str(i) for i in ids}
        entradas = [e for e in entradas if str(e.get("id")) in alvo]
        if not entradas:
            raise ValueError("Nenhum prompt corresponde aos ids selecionados.")

    # PolÃ­tica segura: por padrÃ£o sÃ³ gera o que ainda nÃ£o existe. SubstituiÃ§Ã£o
    # explÃ­cita continua disponÃ­vel para chamadas internas/confirmadas pela UI.
    if modo == "pendentes":
        entradas = [e for e in entradas
                    if not (product_path / "output" / "criativos" /
                            f"{str(e.get('id') or '')}.png").exists()]

    # Paralelismo: roda SEMPRE até o teto (config `workers`, hoje 6) por vez. Fila
    # rolante — assim que um job termina, o próximo entra. Ex.: 8 imagens com teto 6 =>
    # 6 de uma vez e as 2 seguintes assim que abrir vaga (não 4+4). Antes usávamos
    # rodadas parelhas (_workers_balanceados), que REDUZIA a concorrência abaixo do teto;
    # trocado por min(n, teto) para nunca rodar menos que o teto quando há trabalho.
    # (api é sempre 1 por prudência com rate limit.)
    if backend == "codex" and entradas:
        workers = min(len(entradas), workers)

    referencias_produto = coletar_referencias(product_path)
    # Foto do produto é OPCIONAL: produtos sem imagem real (ex.: cursos, infoprodutos
    # como "n8n master") geram normalmente. Sem foto, a identidade do produto vem do
    # texto (config/contexto) e o prefixo de fidelidade troca para o modo "sem foto".
    tem_ref_produto = bool(referencias_produto)
    # Referências de ESTILO (opcionais) entram DEPOIS das do produto: a ordem é o que
    # o _bloco_estilo usa pra explicar ao modelo qual imagem é produto e qual é estilo.
    referencias_estilo_full = coletar_referencias_estilo(product_path)
    # LIMITE DO $imagegen (Codex): NO MÁXIMO 5 imagens por geração. Passar mais faz o
    # agente descartar imagens sozinho e improvisar quais usar — resultado "viajado" e
    # não-determinístico. Escolha fixa: até 2 fotos do produto (identidade) + até 2 do
    # influenciador (só nos criativos cujo prompt menciona @Nome) + estilo até fechar 5.
    # Ordem: produto -> estilo -> influenciador (os blocos explicam o papel por posição).
    MAX_IMGS = 5
    referencias_produto = referencias_produto[:2]
    # Contexto por imagem (comentário do usuário: "fundo de estádio", "estilo X"...):
    # entra no prompt de TODA geração, junto das próprias imagens anexadas.
    _ctx_estilo = _contextos_ref(product_path, "estilo")

    def _pacote(influ_nome: str | None) -> dict:
        """Anexos e blocos de prompt de um criativo, com ou sem influenciador."""
        refs_influ = coletar_referencias_influenciador(influ_nome) if influ_nome else []
        refs_estilo = referencias_estilo_full[
            :max(0, MAX_IMGS - len(referencias_produto) - len(refs_influ))]
        refs = referencias_produto + refs_estilo + refs_influ
        infos = [(p.name, _ctx_estilo.get(p.name, "")) for p in refs_estilo]
        anexos_desc = None
        if refs_influ:
            # Com influenciador, a moldura padrão do backend (produto + estilo por
            # posição) não descreve os anexos direito — descreve os 3 grupos.
            partes = [
                f"São {len(refs)} imagens anexadas, nesta ordem: as PRIMEIRAS "
                f"{len(referencias_produto)} são fotos REAIS do PRODUTO (identidade — forma, "
                "cor, logo, rótulo, textos — a manter igual)."]
            if refs_estilo:
                partes.append(
                    f"As {len(refs_estilo)} seguintes são REFERÊNCIAS DE ESTILO/CENÁRIO "
                    "escolhidas pelo usuário: copie delas a linguagem visual (fundo, paleta, "
                    "composição, luz e clima), nunca os objetos/pessoas que aparecem nelas.")
            partes.append(
                f"As ÚLTIMAS {len(refs_influ)} são fotos REAIS do INFLUENCIADOR — a pessoa "
                "da cena é EXATAMENTE essa (mesmo rosto, cabelo, pele e corpo). Passe TODAS "
                "as imagens ao $imagegen.")
            anexos_desc = " ".join(partes)
        return {
            "referencias": refs, "n_estilo": len(refs_estilo), "anexos_desc": anexos_desc,
            "estilo_bloco": _bloco_estilo(len(referencias_produto), infos),
            "influ_perfil": _perfil_influenciador(influ_nome) if refs_influ else "",
            "influ_bloco": _bloco_influenciador(
                influ_nome or "", len(refs_influ),
                look_fixo=_influ_look_fixo(influ_nome) if influ_nome else False),
        }

    # Pacote base (sem influenciador) é o default do gerar_um; os com influenciador
    # são criados sob demanda quando algum prompt menciona @Nome.
    pacotes: dict = {None: _pacote(None)}
    referencias = pacotes[None]["referencias"]
    n_estilo_base = pacotes[None]["n_estilo"]

    out_dir = product_path / "output" / "criativos"
    out_dir.mkdir(parents=True, exist_ok=True)
    status_file = out_dir / "status.json"

    # Trava ENTRE PROCESSOS via heartbeat: se ja existe um status vivo (batimento
    # ha menos de 60s) de outra execucao, recusa iniciar. Evita dois processos
    # (ex.: app aberto + CLI) gerando e clobberando o status.json um do outro.
    if status_file.exists():
        try:
            _s = json.loads(status_file.read_text(encoding="utf-8"))
            if _s.get("em_andamento") and (time.time() - float(_s.get("atualizado") or 0)) < 60:
                raise RuntimeError(
                    "Ja existe uma geracao em andamento para este produto "
                    "(outro processo). Aguarde terminar ou pare-a antes de iniciar outra.")
        except (json.JSONDecodeError, OSError):
            pass  # status ilegivel = nao bloqueia

    status = {
        "id": __import__('uuid').uuid4().hex,
        "produto": produto,
        "backend": backend,
        "total": len(entradas),
        "feitos": 0,
        "atual": None,
        "atuais": [],
        # Em geraÃ§Ã£o parcial, semeia com o que jÃ¡ existe pra grade nÃ£o regredir.
        "arquivos": _pngs_existentes(out_dir) if ids else [],
        "erros": [],
        "em_andamento": True,
        "inicio": time.time(),
        "atualizado": time.time(),
    }

    # Com workers > 1 varios jobs mexem no status ao mesmo tempo: todo acesso de
    # escrita (e o salvar) acontece sob este lock.
    st_lock = threading.Lock()

    def salvar():
        # SEMPRE chamado com st_lock preso.
        # "atual" segue string (compat com o front); "atuais" e a lista em voo.
        status["atual"] = ", ".join(status["atuais"]) or None
        # Reconcilia a lista de arquivos com o DISCO a cada escrita. Assim um descarte
        # feito DURANTE a geração (o PNG é MOVIDO para descartados/, nunca apagado) não
        # volta a aparecer na grade: nenhuma escrita nossa "ressuscita" o thumb descartado.
        status["arquivos"] = _pngs_existentes(out_dir)
        status["atualizado"] = time.time()
        atomic_write_json(status_file, status)
        if on_progress:
            on_progress(dict(status))

    with st_lock:
        salvar()

    # Heartbeat: regrava o status a cada ~15s enquanto gera. Uma imagem leva minutos
    # sem nenhum evento de progresso; sem batimento, o /api/status do app aberto
    # interpretaria o status parado como "execucao morta" e marcaria interrompida
    # (falso positivo quando a geracao roda em outro processo, ex. CLI).
    hb_stop = threading.Event()

    def _heartbeat():
        while not hb_stop.wait(15):
            with st_lock:
                if not status.get("em_andamento"):
                    break
                salvar()

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()

    reasoning, img_model = _opcoes_velocidade(cfg)
    gerar_um = _montar_gerar_um(backend, referencias, size, quality, timeout, out_dir,
                                cancel_event=cancel_event, reasoning=reasoning, img_model=img_model,
                                n_estilo=n_estilo_base)

    def _job(i: int, entrada: dict) -> None:
        if _cancelado(cancel_event):
            return  # nao iniciado: nao conta em feitos (espelha o break sequencial)
        cid = str(entrada.get("id") or f"criativo_{i + 1:02d}")
        with st_lock:
            status["atuais"].append(cid)
            salvar()

        tamanho = entrada.get("tamanho", size)
        texto = entrada.get("prompt", "")
        # Influenciador POR CRIATIVO: só quando o prompt menciona @Nome.
        influ_nome = influenciador_no_texto(texto)
        with st_lock:
            if influ_nome not in pacotes:
                pacotes[influ_nome] = _pacote(influ_nome)
            pac = pacotes[influ_nome]
        if influ_nome:
            texto = _texto_sem_mencao(texto, influ_nome)
        blocos = [PREFIXO_FIDELIDADE if tem_ref_produto else PREFIXO_SEM_REF_PRODUTO]
        if verdade_visual:
            blocos.append(verdade_visual)
        if pac["estilo_bloco"]:
            blocos.append(pac["estilo_bloco"])
        if pac["influ_perfil"]:
            blocos.append(pac["influ_perfil"])
        if pac["influ_bloco"]:
            blocos.append(pac["influ_bloco"])
        blocos.append(texto)
        blocos.append(f"Formato/tamanho: {tamanho}, fotorrealista.")
        prompt = "\n\n".join(blocos)
        out_file = out_dir / f"{cid}.png"
        # Nunca deixa um backend escrever diretamente na imagem final.
        tmp_file = out_dir / f".{cid}.{__import__('uuid').uuid4().hex}.tmp.png"
        ok = False
        try:
            gerar_um(prompt, tmp_file, referencias=pac["referencias"],
                     n_estilo=pac["n_estilo"], anexos_desc=pac["anexos_desc"])
            tmp_file.replace(out_file)
            ok = True
        except Exception as e:  # noqa: BLE001
            if not _cancelado(cancel_event):  # cancelamento nao e erro real
                with st_lock:
                    status["erros"].append({"id": cid, "erro": str(e)})
        finally:
            tmp_file.unlink(missing_ok=True)
            with st_lock:
                if ok and out_file.name not in status["arquivos"]:
                    status["arquivos"].append(out_file.name)
                if cid in status["atuais"]:
                    status["atuais"].remove(cid)
                status["feitos"] += 1
                salvar()
        if ok:
            # read-modify-write do prompts.json: serializado pelo lock.
            with st_lock:
                _marcar_prompt_gerado(prompts_file, cid)

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_job, i, e) for i, e in enumerate(entradas)]
            for f in futs:
                f.result()  # _job engole as proprias excecoes; result() so propaga bug real
    finally:
        hb_stop.set()

    with st_lock:
        status["atuais"] = []
        status["em_andamento"] = False
        status["cancelado"] = _cancelado(cancel_event)
        salvar()
    return status


# Aceita tanto o esquema antigo (_v2) quanto o novo (_refinado1) ao extrair a base,
# para nao quebrar criativos ja versionados antes da mudanca de nomenclatura.
_RE_VERSAO = re.compile(r"^(.*?)(?:_(?:refinado|v)(\d+))?\.png$", re.IGNORECASE)


def _proxima_versao(out_dir: Path, arquivo: str) -> str:
    """Proxima versao de refino, SEM apagar a anterior:
    criativo_08.png -> criativo_08_refinado1.png; _refinado1 -> _refinado2 ...

    Incrementa a partir da MAIOR versao ja existente no disco, entao refinar de novo
    sempre cria um arquivo novo e preserva todos os anteriores (o dono compara e escolhe).
    """
    m = _RE_VERSAO.match(arquivo)
    base = m.group(1) if (m and m.group(1)) else Path(arquivo).stem
    maior = 0
    for p in out_dir.glob(f"{base}_refinado*.png"):
        mm = _RE_VERSAO.match(p.name)
        if mm and mm.group(1) == base and mm.group(2):
            maior = max(maior, int(mm.group(2)))
    return f"{base}_refinado{maior + 1}.png"


def refinar_criativo(produto: str, arquivo: str, instrucao: str,
                     backend: str | None = None, on_progress=None,
                     cancel_event=None, status_file: Path | None = None) -> dict:
    """Regenera um criativo jÃ¡ gerado aplicando um ajuste pontual (img2img).

    O criativo base entra como PRIMEIRA referÃªncia; as fotos reais do produto vÃªm
    depois. O resultado Ã© salvo como nova versÃ£o (_v2, _v3...), preservando a original.
    """
    cfg = carregar_config()["geracao"]
    backend = backend or cfg.get("backend", "codex")
    size = cfg.get("size", "1024x1024")
    quality = cfg.get("quality", "high")
    timeout = int(cfg.get("timeout", 300))

    product_path = product_dir(produto)
    out_dir = product_path / "output" / "criativos"
    base_file = out_dir / arquivo
    if base_file.name != arquivo or base_file.parent != out_dir.resolve() or base_file.suffix.lower() != ".png":
        raise ValueError("Arquivo invÃ¡lido.")
    if not base_file.exists():
        raise FileNotFoundError(f"Criativo nÃ£o encontrado: {arquivo}")

    # Se o criativo original foi gerado com @influenciador (ou o ajuste menciona um
    # @Nome), o refino anexa as fotos dele para o rosto não mudar entre versões.
    influenciador = influenciador_no_texto(instrucao) or influenciador_do_criativo(product_path, arquivo)
    if influenciador:
        instrucao = _texto_sem_mencao(instrucao, influenciador)
    referencias_influ = coletar_referencias_influenciador(influenciador) if influenciador else []
    # Teto de 5 anexos do $imagegen (mais que isso o agente descarta sozinho e viaja):
    # 1 base + até 2 produto + até 2 influenciador = nunca passa de 5.
    referencias = [base_file] + coletar_referencias(product_path)[:2] + referencias_influ
    verdade_visual = carregar_verdade_visual(product_path)
    novo_nome = _proxima_versao(out_dir, arquivo)
    status_file = status_file or (out_dir / "status.json")

    status = {
        "id": __import__('uuid').uuid4().hex,
        "produto": produto,
        "backend": backend,
        "total": 1,
        "feitos": 0,
        "atual": novo_nome,
        "arquivos": _pngs_existentes(out_dir),
        "erros": [],
        "em_andamento": True,
        "inicio": time.time(),
        "atualizado": time.time(),
    }

    def salvar():
        status["atualizado"] = time.time()
        atomic_write_json(status_file, status)
        if on_progress:
            on_progress(dict(status))

    salvar()

    reasoning, img_model = _opcoes_velocidade(cfg)
    gerar_um = _montar_gerar_um(backend, referencias, size, quality, timeout, out_dir,
                                cancel_event=cancel_event, reasoning=reasoning, img_model=img_model)

    prompt = (
        "TAREFA DE EDIÇÃO DE IMAGEM: a PRIMEIRA imagem anexada é o criativo base já "
        "aprovado. Recrie essa MESMA imagem aplicando APENAS este ajuste: "
        f"{instrucao.strip()}\n"
        f"{(chr(10) + chr(10) + verdade_visual) if verdade_visual else ''}"
        "Todo o resto (composição, enquadramento, luz, cenário, cores, produto e textos "
        "não mencionados no ajuste) deve permanecer IDÊNTICO à imagem base.\n\n"
        "As demais imagens anexadas são as fotos reais do produto: mantenha o produto com o "
        "mesmo formato, cor, símbolo e rótulos reais delas. Não invente logos, escudos nem "
        "marcas que não existam no produto. PROIBIDO hífen ou travessão em qualquer texto.\n\n"
        + ((f"As ÚLTIMAS {len(referencias_influ)} imagens anexadas são fotos REAIS do "
            f"influenciador '{influenciador}': se houver pessoa na imagem, o rosto e os traços "
            "dela ficam EXATAMENTE iguais aos dessas fotos.\n\n") if referencias_influ else "")
        + f"Formato/tamanho: {size}, fotorrealista."
    )

    out_file = out_dir / novo_nome
    tmp_file = out_dir / f".{novo_nome}.{__import__('uuid').uuid4().hex}.tmp.png"
    if not _cancelado(cancel_event):
        try:
            gerar_um(prompt, tmp_file)
            tmp_file.replace(out_file)
            if out_file.name not in status["arquivos"]:
                status["arquivos"].append(out_file.name)
        except Exception as e:  # noqa: BLE001
            if not _cancelado(cancel_event):
                status["erros"].append({"id": novo_nome, "erro": str(e)})
        finally:
            tmp_file.unlink(missing_ok=True)

    status["feitos"] = 1
    status["atual"] = None
    status["em_andamento"] = False
    status["cancelado"] = _cancelado(cancel_event)
    salvar()
    return status


def refazer_criativo(produto: str, arquivo: str, instrucao: str,
                     refs_extra=None, copy_text: str = "",
                     backend: str | None = None, on_progress=None,
                     cancel_event=None) -> dict:
    """Refaz um criativo do ZERO (não é img2img como o refino): a versão atual entra
    só como ponto de partida da ideia/copy, e o resultado é gerado a partir das
    NOVAS referências anexadas pelo usuário + a instrução dele, mantendo a copy.
    Salva como nova versão, preservando a original."""
    cfg = carregar_config()["geracao"]
    backend = backend or cfg.get("backend", "codex")
    size = cfg.get("size", "1024x1024")
    quality = cfg.get("quality", "high")
    timeout = int(cfg.get("timeout", 300))

    product_path = product_dir(produto)
    out_dir = product_path / "output" / "criativos"
    base_file = out_dir / arquivo
    if base_file.name != arquivo or base_file.parent != out_dir.resolve() or base_file.suffix.lower() != ".png":
        raise ValueError("Arquivo invalido.")
    if not base_file.exists():
        raise FileNotFoundError(f"Criativo nao encontrado: {arquivo}")

    # Mesmo critério do refino: @Nome na instrução do usuário, ou o do prompt original.
    influenciador = influenciador_no_texto(instrucao) or influenciador_do_criativo(product_path, arquivo)
    if influenciador:
        instrucao = _texto_sem_mencao(instrucao, influenciador)
    referencias_influ = coletar_referencias_influenciador(influenciador) if influenciador else []
    # Ordem dos anexos: [versão atual, *refs novas, *fotos do produto, *fotos do influenciador],
    # SEMPRE dentro do teto de 5 do $imagegen (mais que isso o agente descarta e viaja).
    # Prioridade: base > refs do usuário (até 3) > influenciador (o rosto) > produto (mín. 1).
    MAX_IMGS = 5
    extras = [Path(r) for r in (refs_extra or []) if Path(r).exists()][:3]
    produto_refs = coletar_referencias(product_path)
    referencias_influ = referencias_influ[:max(0, MAX_IMGS - 1 - len(extras) - 1)]
    produto_refs = produto_refs[
        :max(1, min(2, MAX_IMGS - 1 - len(extras) - len(referencias_influ)))]
    referencias = [base_file] + extras + produto_refs + referencias_influ
    verdade_visual = carregar_verdade_visual(product_path)
    novo_nome = _proxima_versao(out_dir, arquivo)
    status_file = out_dir / "status.json"

    status = {
        "id": __import__('uuid').uuid4().hex,
        "produto": produto,
        "backend": backend,
        "total": 1,
        "feitos": 0,
        "atual": novo_nome,
        "arquivos": _pngs_existentes(out_dir),
        "erros": [],
        "em_andamento": True,
        "inicio": time.time(),
        "atualizado": time.time(),
    }

    def salvar():
        status["atualizado"] = time.time()
        atomic_write_json(status_file, status)
        if on_progress:
            on_progress(dict(status))

    salvar()

    n_extra = len(extras)
    n_prod = len(produto_refs)
    anexos_desc = (
        f"São {len(referencias)} imagens anexadas, nesta ordem: a 1ª é a VERSÃO ATUAL deste "
        "criativo (ficou ruim) — use SÓ como ponto de partida da ideia e para preservar a copy; "
        "NÃO copie o fundo nem a composição fraca dela. "
    )
    if n_extra:
        anexos_desc += (
            f"As {n_extra} imagens seguintes são as REFERÊNCIAS que o usuário anexou agora "
            "(fundos, cenários, estilo): o resultado TEM que ficar no MESMO estilo visual delas "
            "— fundo, paleta, composição, luz e clima — adaptado, nunca um estilo diferente. "
            "NÃO desenhe os objetos/pessoas que aparecem nelas; delas você tira só a linguagem "
            "visual. "
        )
    if referencias_influ:
        anexos_desc += (
            f"As {n_prod} imagens seguintes são as fotos REAIS do produto (identidade a manter "
            f"igual). As ÚLTIMAS {len(referencias_influ)} são fotos REAIS do influenciador "
            f"'{influenciador}': quando houver pessoa na cena, é EXATAMENTE essa pessoa — mesmo "
            "rosto, cabelo, pele e corpo das fotos."
        )
    else:
        anexos_desc += f"As últimas {n_prod} são as fotos REAIS do produto (identidade a manter igual)."

    reasoning, img_model = _opcoes_velocidade(cfg)
    gerar_um = _montar_gerar_um(backend, referencias, size, quality, timeout, out_dir,
                                cancel_event=cancel_event, reasoning=reasoning,
                                img_model=img_model, anexos_desc=anexos_desc)

    blocos = [PREFIXO_FIDELIDADE]
    if verdade_visual:
        blocos.append(verdade_visual)
    refaz = ["REFAÇA este criativo do zero seguindo a instrução do usuário e as referências "
             "anexadas (elas mandam mais que o texto na direção visual)."]
    if copy_text:
        refaz.append(f"MANTENHA esta mensagem/copy na arte (mesmo texto e sentido): {copy_text}")
    refaz.append(f"INSTRUÇÃO DO USUÁRIO: {instrucao.strip()}")
    blocos.append("\n".join(refaz))
    blocos.append(f"Formato/tamanho: {size}, fotorrealista.")
    prompt = "\n\n".join(blocos)

    out_file = out_dir / novo_nome
    tmp_file = out_dir / f".{novo_nome}.{__import__('uuid').uuid4().hex}.tmp.png"
    if not _cancelado(cancel_event):
        try:
            gerar_um(prompt, tmp_file)
            tmp_file.replace(out_file)
            if out_file.name not in status["arquivos"]:
                status["arquivos"].append(out_file.name)
        except Exception as e:  # noqa: BLE001
            if not _cancelado(cancel_event):
                status["erros"].append({"id": novo_nome, "erro": str(e)})
        finally:
            tmp_file.unlink(missing_ok=True)

    status["feitos"] = 1
    status["atual"] = None
    status["em_andamento"] = False
    status["cancelado"] = _cancelado(cancel_event)
    salvar()
    return status


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Gera criativos em lote.")
    ap.add_argument("produto", help="nome da pasta do produto em products/")
    ap.add_argument("--backend", choices=["codex", "api"], default=None)
    args = ap.parse_args(argv)

    def progresso(s):
        atual = s["atual"] or "-"
        print(f"[{s['feitos']}/{s['total']}] gerando: {atual}")

    res = gerar_criativos(args.produto, backend=args.backend, on_progress=progresso)
    arquivos = res.get("arquivos") or []
    erros = res.get("erros") or []
    print(f"\nConcluído: {len(arquivos)} criativos, {len(erros)} erros.")
    if erros:
        for e in erros:
            print(f"  ERRO {e['id']}: {e['erro'][:200]}")
    # Saída NÃO-ZERO só quando NADA foi renderizado E houve erro (ex.: Codex não
    # logado / rate-limit / timeout fez TODA imagem falhar). O caller precisa saber
    # que a etapa não produziu criativo. Casos legítimos mantêm exit 0: tudo já
    # existia (nada a fazer) ou zero entradas pedidas — nesses não há erro.
    if not arquivos and erros:
        # Cauda do primeiro diagnóstico para o caller expor o PORQUÊ.
        primeiro = str(erros[0].get("erro") or "")[:300]
        print(f"\nFALHA: nenhuma imagem foi renderizada ({len(erros)} erro(s)). "
              f"Diagnóstico: {primeiro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
