"""Diretor de dicção pro Veo (áudio nativo).

O Veo fala PT-BR, mas tende a ler com fonética inglesa: erra número, tônica e acento.
Este passo reescreve a narração SÓ na grafia, para maximizar a pronúncia correta — sem mudar
o sentido nem as palavras. Números viram por extenso no CÓDIGO (determinístico: preço nunca sai
errado) e um mapa corrige palavras que o Veo pronuncia torto (ex.: doze → dôze).
"""
from __future__ import annotations

import re

_U = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
      "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_D = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_C = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
      "setecentos", "oitocentos", "novecentos"]

# Palavras que o Veo lê com tônica/vogal errada -> grafia fonética que corrige (a palavra é a mesma).
_PRONUNCIA = {
    "doze": "dôze",
}

# Grafia exclusiva do motor de voz. Roteiro, legendas e nome exibido não são alterados.
# SEM HÍFEN: o hífen vira separador de sílaba pro gerador e "Bêi-bi" saiu como "bebê"
# (observado no veo_lite em 2026-08-25). "Beibi" usa o ditongo "ei" do português, que já
# soa BAY-bee sem precisar de marcação.
_PRONUNCIA_MARCAS = {
    "Baba Baby": "Bába Beibi",
}

# Quando o gerador de vídeo não sustenta a pronúncia de uma marca, a solução segura é
# deixá-la visual no rótulo e falar a categoria. Evita insistir em áudio defeituoso.
_MARCAS_SOMENTE_VISUAIS = {
    "Baba Baby": "o creme redutor que eu comecei a usar",
}

# RESTAURAÇÃO DE ACENTOS (determinística): o LLM às vezes derruba acento em palavras
# frequentes ("voce" em vez de "você"), e aí o Veo lê a grafia literal e sai errado.
# Só entram aqui palavras cuja forma SEM acento NÃO é uma palavra válida do PT-BR (ou é
# esmagadoramente a forma acentuada na fala) — assim a troca é SEGURA, sem quebrar sentido.
# NÃO inclua ambíguas como "e"(→é) e "esta"(→está): mudariam o sentido.
_ACENTOS = {
    # função / alta frequência
    "voce": "você", "voces": "vocês", "vc": "você", "vcs": "vocês",
    "nao": "não", "ja": "já", "so": "só", "ne": "né", "ate": "até", "la": "lá", "ai": "aí",
    "tambem": "também", "porem": "porém", "alem": "além", "entao": "então", "sao": "são",
    "ninguem": "ninguém", "alguem": "alguém", "porque": "porque", "voce": "você",
    "ta": "tá", "to": "tô", "mae": "mãe", "irmao": "irmão", "coracao": "coração",
    "sera": "será", "esta": "esta",  # "esta" fica igual (ambígua) — placeholder neutro
    # conteúdo comum (proparoxítonas/paroxítonas cuja forma sem acento não é palavra)
    "otimo": "ótimo", "otima": "ótima", "unico": "único", "unica": "única",
    "ultimo": "último", "ultima": "última", "proximo": "próximo", "proxima": "próxima",
    "numero": "número", "codigo": "código", "pagina": "página", "video": "vídeo",
    "audio": "áudio", "facil": "fácil", "dificil": "difícil", "rapido": "rápido",
    "rapida": "rápida", "pratico": "prático", "pratica": "prática", "basico": "básico",
    "basica": "básica", "logica": "lógica", "magica": "mágica", "tecnica": "técnica",
    "tecnico": "técnico", "publico": "público", "servico": "serviço", "preco": "preço",
    "comeco": "começo", "negocio": "negócio", "estrategia": "estratégia", "duvida": "dúvida",
    "conteudo": "conteúdo", "voce": "você",
}
# remove o placeholder neutro (não queremos trocar "esta")
_ACENTOS.pop("esta", None)


def _preserva_caixa(orig: str, repl: str) -> str:
    if orig.isupper():
        return repl.upper()
    if orig[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def _restaurar_acentos(texto: str) -> str:
    """Recoloca o acento em palavras frequentes que o LLM derrubou (você, não, tá...).
    Word-boundary + preserva a caixa. Só o dicionário SEGURO acima."""
    if not _ACENTOS:
        return texto
    padrao = re.compile(r"(?<![\wÀ-ÿ])(" + "|".join(sorted(map(re.escape, _ACENTOS), key=len, reverse=True))
                        + r")(?![\wÀ-ÿ])", re.IGNORECASE)
    return padrao.sub(lambda m: _preserva_caixa(m.group(0), _ACENTOS[m.group(0).lower()]), texto)


def _ext(n: int) -> str:
    if n < 20:
        return _U[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _D[d] + (" e " + _U[u] if u else "")
    if n == 100:
        return "cem"
    if n < 1000:
        c, r = divmod(n, 100)
        return _C[c] + (" e " + _ext(r) if r else "")
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        mil = "mil" if m == 1 else _ext(m) + " mil"
        if not r:
            return mil
        lig = " e " if (r < 100 or r % 100 == 0) else " "
        return mil + lig + _ext(r)
    return str(n)  # números enormes não aparecem em copy; deixa como está


def _num(txt: str) -> int:
    """'1.997' -> 1997 ; '17' -> 17."""
    return int(txt.replace(".", ""))


def _reais(m: re.Match) -> str:
    inteiro = _ext(_num(m.group(1)))
    centavos = m.group(2)
    unidade = "real" if _num(m.group(1)) == 1 else "reais"
    if centavos and int(centavos) > 0:
        c = _ext(int(centavos))
        return f"{inteiro} {unidade} e {c} {'centavo' if int(centavos) == 1 else 'centavos'}"
    return f"{inteiro} {unidade}"


def _numeros_por_extenso(texto: str) -> str:
    # R$ 1.997,50  |  R$17
    texto = re.sub(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?", _reais, texto)
    # 50%
    texto = re.sub(r"(\d{1,3}(?:\.\d{3})*|\d+)\s?%", lambda m: f"{_ext(_num(m.group(1)))} por cento", texto)
    # inteiros soltos restantes
    texto = re.sub(r"\b(\d{1,3}(?:\.\d{3})*|\d+)\b", lambda m: _ext(_num(m.group(1))), texto)
    return texto


def _corrige_pronuncia(texto: str) -> str:
    for marca, substituto in _MARCAS_SOMENTE_VISUAIS.items():
        texto = re.sub(rf"\b(?:esse|este)\s+[ée]\s+(?:o\s+)?{re.escape(marca)}\b[.!]?",
                       substituto.capitalize() + ".", texto, flags=re.IGNORECASE)
    for marca, fonetica in _PRONUNCIA_MARCAS.items():
        texto = re.sub(re.escape(marca), fonetica, texto, flags=re.IGNORECASE)

    def troca(m: re.Match) -> str:
        p = m.group(0)
        repl = _PRONUNCIA[p.lower()]
        return repl.capitalize() if p[0].isupper() else repl
    if not _PRONUNCIA:
        return texto
    padrao = re.compile(r"\b(" + "|".join(map(re.escape, _PRONUNCIA)) + r")\b", re.IGNORECASE)
    return padrao.sub(troca, texto)


def adaptar(texto: str) -> str:
    """Narração -> versão pra dicção do Veo (números por extenso + pronúncia corrigida).
    Determinístico: mesmas palavras, preço sempre certo. Nunca derruba a geração."""
    texto = (texto or "").strip()
    if not texto:
        return texto
    try:
        return _corrige_pronuncia(_restaurar_acentos(_numeros_por_extenso(texto)))
    except Exception:  # noqa: BLE001 — dicção é best-effort
        return texto
