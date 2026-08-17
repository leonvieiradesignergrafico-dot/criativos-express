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
        return _corrige_pronuncia(_numeros_por_extenso(texto))
    except Exception:  # noqa: BLE001 — dicção é best-effort
        return texto
