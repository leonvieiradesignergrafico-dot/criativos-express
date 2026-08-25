"""Testa (1) refino do usuário nunca ser descartado pelo QA e (2) o resgate quando o
filtro de conteúdo da OpenAI recusa uma cena de produto de corpo/pele.

Sem gastar geração: o gerador de imagem e o QA são substituídos por dublês.

Roda com: python tests/test_refino_e_modo_clinico.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import keyframes as kf  # noqa: E402
from app.pipeline import qualidade as qa  # noqa: E402
from backends.codex_backend import ConteudoBloqueado  # noqa: E402

FALHAS = []

# Os produtos aqui sao ficticios (o teste nao pode depender do que existe em disco),
# entao a leitura da 'verdade visual' do produto real vira no-op.
kf._verdade_visual = lambda _produto: ""
# Config em memoria: o teste nao pode depender do config.toml da maquina.
kf.carregar_config = lambda: {"qualidade": {"max_tentativas_keyframe": 4},
                              "keyframes": {"workers": 6}}


def checar(cond, msg):
    print(("  ok   " if cond else "  FALHA") + f" {msg}")
    if not cond:
        FALHAS.append(msg)


ROTEIRO_CORPO = {"produto": "collab-store~Baba Baby", "tipo_produto": "fisico",
                 "cenas": [{"n": 1, "tipo": "fala", "prompt_keyframe":
                            "mulher aplicando o creme na coxa, mostrando a celulite"}]}
ROTEIRO_NEUTRO = {"produto": "paiva~N8N Master", "tipo_produto": "digital",
                  "cenas": [{"n": 1, "tipo": "fala", "prompt_keyframe":
                             "homem falando com o notebook na mesa"}]}


def test_deteccao_produto_de_corpo():
    checar(kf._precisa_modo_clinico(ROTEIRO_CORPO, ROTEIRO_CORPO["cenas"][0]),
           "produto de celulite entra em modo clinico")
    checar(not kf._precisa_modo_clinico(ROTEIRO_NEUTRO, ROTEIRO_NEUTRO["cenas"][0]),
           "produto neutro NAO entra em modo clinico (nada muda pro resto)")


def test_prompt_clinico_nao_contradiz_a_cena():
    p = kf.montar_prompt(ROTEIRO_CORPO, ROTEIRO_CORPO["cenas"][0])
    checar("MEIO DA COXA pra cima" not in p,
           "some a regra generica que PROIBIA mostrar a coxa (contradizia a cena)")
    checar("roupa de treino" in p, "entra o registro clinico (roupa de treino)")
    checar("pose sensual" in p, "mantem a protecao contra pose sensual")
    p2 = kf.montar_prompt(ROTEIRO_CORPO, ROTEIRO_CORPO["cenas"][0], modo_clinico_reforcado=True)
    checar("plano aberto" in p2, "o reforco pede plano aberto")
    p3 = kf.montar_prompt(ROTEIRO_NEUTRO, ROTEIRO_NEUTRO["cenas"][0])
    checar("MEIO DA COXA pra cima" in p3, "produto neutro segue com a regra de sempre")


def _instalar_dubles(monkey):
    """Troca gerador e QA por dublês controlados pelo dict `monkey`."""
    def falso_gerar(roteiro, cena, out_dir, cancel_event=None, extra=None,
                    modo_clinico_reforcado=False):
        monkey["chamadas"].append({"reforcado": modo_clinico_reforcado, "extra": extra})
        if monkey.get("bloquear_ate", 0) >= len(monkey["chamadas"]):
            raise ConteudoBloqueado("A OpenAI bloqueou esta cena pelo filtro de conteudo DELA")
        nome = f"cena_{cena['n']:02d}.png"
        (out_dir / nome).write_bytes(b"png-falso")
        return nome

    def falso_qa(path, cena, referencias=None):
        return {"aprovado": monkey.get("qa_aprova", True),
                "motivos": [] if monkey.get("qa_aprova", True)
                else [{"codigo": "enquadramento", "detalhe": "cortou a mao"}]}

    kf.gerar_um_keyframe = falso_gerar
    qa.avaliar_keyframe = falso_qa
    qa.arquivar_descarte = lambda *a, **k: monkey.setdefault("descartes", []).append(a)


def test_refino_do_usuario_nao_e_descartado(tmp: Path):
    monkey = {"chamadas": [], "qa_aprova": False}   # QA REPROVA de propósito
    _instalar_dubles(monkey)
    out = tmp / "kf_refino"; out.mkdir(parents=True, exist_ok=True)
    nome, analise, tent = kf.gerar_keyframe_validado(
        ROTEIRO_NEUTRO, ROTEIRO_NEUTRO["cenas"][0], out,
        extra="deixa o fundo mais escuro", manter_sempre=True)
    checar(nome == "cena_01.png", "o refino foi ENTREGUE mesmo com o QA reprovando")
    checar((out / nome).exists(), "o arquivo do refino continua em disco (nao apagou)")
    checar(not monkey.get("descartes"), "nao arquivou como descarte")
    checar(len(monkey["chamadas"]) == 1, f"gerou UMA vez so (gerou {len(monkey['chamadas'])})")
    checar(analise.get("aprovado") is False, "o parecer do QA volta junto (vira ressalva na UI)")


def test_geracao_normal_continua_descartando(tmp: Path):
    """Garantia de nao-regressao: fora do refino, o QA segue mandando (4 tentativas)."""
    monkey = {"chamadas": [], "qa_aprova": False}
    _instalar_dubles(monkey)
    out = tmp / "kf_normal"; out.mkdir(parents=True, exist_ok=True)
    try:
        kf.gerar_keyframe_validado(ROTEIRO_NEUTRO, ROTEIRO_NEUTRO["cenas"][0], out)
        checar(False, "deveria ter falhado apos as tentativas")
    except RuntimeError as e:
        checar("reprovado" in str(e).lower(), "geracao normal segue reprovando e tentando de novo")
    checar(len(monkey["chamadas"]) > 1,
           f"tentou varias vezes como antes ({len(monkey['chamadas'])}x)")
    checar(bool(monkey.get("descartes")), "e arquivou os descartes como antes")


def test_recusa_de_conteudo_reenquadra_e_tenta_de_novo(tmp: Path):
    monkey = {"chamadas": [], "qa_aprova": True, "bloquear_ate": 1}  # 1ª chamada recusada
    _instalar_dubles(monkey)
    out = tmp / "kf_bloqueio"; out.mkdir(parents=True, exist_ok=True)
    nome, _analise, _t = kf.gerar_keyframe_validado(
        ROTEIRO_CORPO, ROTEIRO_CORPO["cenas"][0], out)
    checar(nome == "cena_01.png", "a cena foi salva apos o reenquadramento")
    checar(len(monkey["chamadas"]) == 2, "tentou de novo UMA vez (nao queimou as 4 tentativas)")
    checar(monkey["chamadas"][0]["reforcado"] is False
           and monkey["chamadas"][1]["reforcado"] is True,
           "a 2a tentativa foi com o reenquadramento reforcado")


def test_recusa_persistente_nao_vira_loop(tmp: Path):
    monkey = {"chamadas": [], "qa_aprova": True, "bloquear_ate": 99}
    _instalar_dubles(monkey)
    out = tmp / "kf_bloqueio2"; out.mkdir(parents=True, exist_ok=True)
    try:
        kf.gerar_keyframe_validado(ROTEIRO_CORPO, ROTEIRO_CORPO["cenas"][0], out)
        checar(False, "deveria propagar a recusa")
    except ConteudoBloqueado:
        checar(True, "recusa persistente sobe com a mensagem clara da OpenAI")
    checar(len(monkey["chamadas"]) == 2,
           f"parou em 2 tentativas (gastou {len(monkey['chamadas'])})")


if __name__ == "__main__":
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="kf_test_"))
    print("== refino preservado + modo clinico ==")
    for t in (test_deteccao_produto_de_corpo, test_prompt_clinico_nao_contradiz_a_cena):
        print(f"\n{t.__name__}:"); t()
    for t in (test_refino_do_usuario_nao_e_descartado, test_geracao_normal_continua_descartando,
              test_recusa_de_conteudo_reenquadra_e_tenta_de_novo,
              test_recusa_persistente_nao_vira_loop):
        print(f"\n{t.__name__}:"); t(tmp)
    print("\n" + ("FALHAS: " + "; ".join(FALHAS) if FALHAS else "tudo passou"))
    sys.exit(1 if FALHAS else 0)
