"""Gera os três vídeos aprovados de Doce Sem Culpa no workspace do app instalado."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("ADSEXPRESS_DATA_ROOT", str(Path.home() / "AppData/Local/Ads Express"))

from workspace import atomic_write_json, ler_json, video_dir  # noqa: E402
from app.pipeline import roteiro as roteiro_mod  # noqa: E402
from app.pipeline import keyframes, clipes, montagem  # noqa: E402

PRODUTO = "iohanna~Doce Sem Culpa"
AVATAR = "Camila"

VIDEOS = [
    {
        "titulo": "UGC principal — Acredita que esse bolo não tem açúcar?",
        "formato": "ugc_depoimento",
        "fala": (
            "Acredita que esse bolo não tem açúcar? Eu sempre achei que bolo sem açúcar "
            "ficava seco, sem graça ou com aquele gosto forte de adoçante. Até que encontrei "
            "o Doce Sem Culpa, testei as receitas e me surpreendi. A massa continua molhadinha, "
            "a cobertura fica cremosa e fica delicioso. Todo mundo que prova me pede a receita. "
            "Tem chocolate, cenoura, banana com canela, brigadeiro de colher e vários outros. "
            "E é feito apenas com um liquidificador, com coisas que eu encontro no mercado. "
            "Eu vou deixar o link no botão aqui embaixo pra você clicar e baixar suas receitas também."
        ),
        "duracao": "40 a 45 segundos",
        "direcao": (
            "Abra no PRIMEIRO FRAME com macro irresistível de colher retirando uma porção de bolo de chocolate "
            "molhadinho numa marmita retangular de alumínio. Em seguida revele uma mulher brasileira comum, 28–38, "
            "UGC caseiro na cozinha, falando como consumidora; ela NÃO é Iohanna e não pode se parecer com Iohanna. "
            "Use a mesma personagem e uma fala contínua como áudio-base. Avatar visível no gancho verbal, na virada "
            "'Até que encontrei' e no CTA; cubra o restante com inserts frequentes, sem interromper a voz: bolo de "
            "chocolate na marmita sendo aberto, massa úmida, cobertura cremosa, bolo de cenoura na marmita, bolo de "
            "banana com canela sem rodelas de banana decorativas, brigadeiro de colher, ingredientes comuns, massa no "
            "liquidificador, tela real do entregável e tela das 3 Trocas. Bolo deve ocupar 70–80% do tempo. Novo plano "
            "a cada 1,5–3s; três planos de bolo nos primeiros 10s. Sem frutas ou decorações inventadas."
        ),
    },
    {
        "titulo": "UGC curto — As 3 trocas que mantêm o bolo gostoso",
        "formato": "ugc_depoimento",
        "fala": (
            "Eu queria diminuir o açúcar, mas toda receita que eu tentava ficava seca ou com gosto forte de adoçante. "
            "Foi aí que eu descobri o Doce Sem Culpa. Trocando só três ingredientes, eu consigo fazer bolos sem açúcar "
            "que continuam molhadinhos, cremosos e deliciosos. E é tudo feito apenas com um liquidificador. "
            "Vou deixar o link no botão aqui embaixo pra você clicar e baixar as receitas também."
        ),
        "duracao": "22 a 25 segundos",
        "direcao": (
            "Primeiro frame: cobertura cremosa e colher abrindo bolo de chocolate numa marmita de alumínio. Mesma "
            "mulher UGC brasileira comum do começo ao fim, nunca Iohanna, com fala contínua. Avatar aparece rapidamente "
            "na confissão inicial, em 'Foi aí que eu descobri' e no CTA. Nos demais trechos, voz continua em off sobre "
            "inserts: três ingredientes dispostos na bancada, tela real das 3 Trocas, liquidificador, massa indo para "
            "marmita, close de miolo molhadinho, cobertura cremosa e 3 sabores coerentes na marmita. Bolo em 70–80% "
            "do vídeo, cortes de 1,5–2,5s. Nenhuma fruta decorativa aleatória."
        ),
    },
    {
        "titulo": "Nativo orgânico — Receita de bolo sem açúcar molhadinho",
        "formato": "receita",
        "fala": (
            "Receita de bolo sem açúcar que continua molhadinho e delicioso. A massa é feita apenas com um liquidificador "
            "e o segredo é trocar só três ingredientes pra manter a textura e o sabor. Essa é uma das receitas do Doce "
            "Sem Culpa, que ensina a fazer bolos gostosos sem açúcar, sem deixar tudo seco e sem graça. Vou deixar o link "
            "aqui embaixo pra você clicar e baixar as outras receitas."
        ),
        "duracao": "12 a 16 segundos",
        "direcao": (
            "Pareça conteúdo orgânico de receita, não anúncio. Primeiro frame já mostra colher rompendo cobertura de "
            "bolo de chocolate numa marmita de alumínio, com texto visual curto 'Bolo sem açúcar molhadinho'. Use uma "
            "única voz feminina UGC contínua; rosto da personagem apenas num flash natural perto da descoberta do produto "
            "e no CTA, sem Iohanna. Montagem acelerada: liquidificador, massa caindo na marmita, três ingredientes/trocas, "
            "bolo assado, cobertura, miolo úmido, dois outros sabores na marmita, tela real do Doce Sem Culpa por no máximo "
            "1s e melhor macro no CTA. Bolo em 80–90%, corte a cada 1–2s. Sem banana ou frutas usadas como decoração."
        ),
    },
]


def criar(item: dict) -> str:
    prompt = f"""OBJETIVO: criar exatamente UM vídeo vertical {item['formato']} com {item['duracao']}.

TÍTULO INTERNO: {item['titulo']}

FALA FECHADA — preserve literalmente, sem reescrever, retirar ou acrescentar alegações:
“{item['fala']}”

DIREÇÃO VISUAL OBRIGATÓRIA:
{item['direcao']}

REGRAS DURAS:
- Não use imagem, rosto, nome ou personagem de Iohanna.
- A pessoa é avatar UGC/consumidora contando a própria experiência em primeira pessoa.
- Linguagem falada é 'sem açúcar', nunca 'sem adição de açúcar'.
- Todo bolo é realista e servido/feito em marmita retangular de alumínio.
- Não invente frutas, rodelas, confeitos ou decorações não solicitadas.
- A narração deve formar uma fala contínua da mesma mulher; inserts funcionam como B-roll por cima dessa fala.
- Avatar visível nos trechos indicados; inserts de bolo dominam o vídeo.
- Preserve cenas e takes individualizados para edição fina na etapa Final.
"""
    rot = roteiro_mod.criar_roteiro(PRODUTO, prompt, AVATAR, modelo="sonnet", pessoa_tipo="avatar", formato_video=item["formato"])
    d = video_dir(PRODUTO, rot["id"])
    saved = ler_json(d / "roteiro.json")
    saved["titulo"] = item["titulo"]
    saved["copy_final_aprovada"] = item["fala"]
    atomic_write_json(d / "roteiro.json", saved)
    return rot["id"]


def executar(vid: str) -> None:
    keyframes.gerar_keyframes(PRODUTO, vid)
    clipes.gerar_clipes(PRODUTO, vid)
    montagem.montar(PRODUTO, vid, legendas=True)


def _cena(n: int, tipo: str, duracao: int, narracao: str, quadro: str, movimento: str) -> dict:
    return {
        "n": n, "tipo": tipo, "elenco": "A", "duracao_s": duracao,
        "narracao": narracao, "prompt_keyframe": quadro, "prompt_movimento": movimento,
        "geometria": {},
        "keyframe": {"arquivo": None, "aprovado": False, "tentativas": 0},
        "audio": {"arquivo": None, "duracao_s": None},
        "clipe": {"arquivo": None, "gerado": False, "fal_request_id": None,
                  "erro": None, "lipsync_aplicado": False},
        "qualidade": {"estado": "pendente", "etapa": None, "tentativa": 0,
                      "motivos": [], "descartes": 0},
    }


def corrigir(vid: str, indice: int) -> None:
    d = video_dir(PRODUTO, vid)
    rot = ler_json(d / "roteiro.json")
    comum_bolo = ("Foto vertical 9:16 caseira e realista, bolo obrigatoriamente dentro de marmita "
                  "retangular de alumínio, cozinha brasileira comum, luz natural, sem texto, sem "
                  "frutas ou decoração inventada. ")
    comum_avatar = ("Camila das fotos de referência, mulher brasileira comum gravando UGC na mesma "
                    "cozinha, mesma roupa casual em todas as cenas, luz de janela, celular vertical, "
                    "sem qualquer semelhança, foto ou menção a Iohanna. ")
    if indice == 0:
        cenas = [
            _cena(1, "close_produto", 3, "Acredita que esse bolo não tem açúcar?",
                   comum_bolo + "Macro irresistível: colher acaba de abrir bolo de chocolate muito molhadinho; miolo úmido e cobertura cremosa ocupam o quadro.",
                   "Colher levanta lentamente uma porção; câmera handheld faz leve aproximação, tomada única."),
            _cena(2, "avatar_fala", 6, "Eu sempre achei que bolo sem açúcar ficava seco, sem graça ou com aquele gosto forte de adoçante.",
                   comum_avatar + "Plano médio natural, ela olha para a câmera com expressão de quem confessa uma crença antiga; nenhum produto ou tela na mão.",
                   "Ela fala direto para a câmera com gestos pequenos, lipsync natural e tomada contínua."),
            _cena(3, "avatar_fala", 6, "Até que encontrei o Doce Sem Culpa, testei as receitas e me surpreendi.",
                   comum_avatar + "Ângulo lateral 3/4 diferente, sorriso surpreso e sincero, um bolo de chocolate na marmita repousa na bancada ao lado sem ser segurado.",
                   "Ela fala e olha rapidamente para o bolo na bancada, depois volta à câmera; lipsync natural."),
            _cena(4, "close_produto", 7, "A massa continua molhadinha, a cobertura fica cremosa e fica delicioso. Todo mundo que prova me pede a receita.",
                   comum_bolo + "Close de bolo de chocolate; colher pressiona o miolo úmido e atravessa cobertura cremosa, textura artesanal imperfeita e apetitosa.",
                   "Sequência contínua curta de colher pressionando e retirando uma porção, sem morph nem troca de doce."),
            _cena(5, "close_produto", 6, "Tem chocolate, cenoura, banana com canela, brigadeiro de colher e vários outros.",
                   comum_bolo + "Bancada com quatro marmitas coerentes: chocolate com cobertura de chocolate; cenoura com cobertura fina de chocolate; banana com canela sem rodelas de fruta; brigadeiro cremoso de colher. Sem enfeites.",
                   "Câmera passeia lateralmente pelas quatro marmitas; nenhum doce muda de forma ou sabor."),
            _cena(6, "close_produto", 6, "E é feito apenas com um liquidificador, com coisas que eu encontro no mercado.",
                   "Foto vertical caseira da mesma cozinha: liquidificador comum com massa de bolo lisa, ovos, aveia, cacau e leite organizados naturalmente; marmitas vazias ao lado. Sem frutas decorativas, sem tela.",
                   "Liquidificador em funcionamento por poucos segundos e mão desliga o botão; câmera fixa, anatomia correta."),
            _cena(7, "avatar_fala", 6, "Eu vou deixar o link no botão aqui embaixo pra você clicar e baixar suas receitas também.",
                   comum_avatar + "Plano médio frontal, ela sorri e aponta uma única vez para a parte inferior do quadro; bolo na marmita visível na bancada ao fundo.",
                   "Ela fala olhando para a câmera e aponta para baixo no fim; lipsync natural, dois braços apenas."),
        ]
    elif indice == 1:
        cenas = [
            _cena(1, "close_produto", 3, "Eu queria diminuir o açúcar, mas toda receita que eu tentava ficava seca ou com gosto forte de adoçante.",
                   comum_bolo + "Macro de colher abrindo bolo de chocolate molhadinho e cobertura cremosa; aparência contradiz visualmente bolo seco.",
                   "Colher entra e levanta uma porção; câmera acompanha com micro movimento."),
            _cena(2, "avatar_fala", 4, "Foi aí que eu descobri o Doce Sem Culpa.",
                   comum_avatar + "Plano médio 3/4, reação natural de descoberta, olha direto para a câmera; bolo na marmita sobre a bancada.",
                   "Fala curta com sorriso leve e lipsync natural, tomada contínua."),
            _cena(3, "tela_dispositivo", 6, "Trocando só três ingredientes, eu consigo fazer bolos sem açúcar que continuam molhadinhos, cremosos e deliciosos.",
                   "Celular comum em retrato apoiado na bancada da cozinha mostrando fielmente a tela real das 3 Trocas do Doce Sem Culpa; ao lado, três ingredientes comuns e uma marmita de bolo real, tudo em escala natural.",
                   "Pequeno push-in no celular; tela estável e legível; objetos não mudam."),
            _cena(4, "close_produto", 4, "E é tudo feito apenas com um liquidificador.",
                   "Foto vertical caseira: massa lisa rodando dentro de liquidificador comum na cozinha; em primeiro plano, marmita de alumínio vazia pronta para receber a massa. Sem frutas, sem tela.",
                   "Massa gira e mão desliga o liquidificador; tomada única, sem cortes internos."),
            _cena(5, "avatar_fala", 6, "Vou deixar o link no botão aqui embaixo pra você clicar e baixar as receitas também.",
                   comum_avatar + "Plano médio frontal, ela aponta para baixo e há três bolos na marmita coerentes na bancada: chocolate, cenoura e banana com canela sem rodelas.",
                   "Ela fala, sorri e aponta para baixo no final; lipsync natural, dois braços apenas."),
        ]
    else:
        cenas = [
            _cena(1, "close_produto", 2, "Receita de bolo sem açúcar que continua molhadinho e delicioso.",
                   comum_bolo + "Primeiríssimo frame macro: colher rompe cobertura cremosa de bolo de chocolate e revela miolo úmido. Espaço limpo no alto para legenda automática.",
                   "A colher rompe e levanta a porção imediatamente, movimento rápido de conteúdo orgânico."),
            _cena(2, "close_produto", 3, "A massa é feita apenas com um liquidificador e o segredo é trocar só três ingredientes pra manter a textura e o sabor.",
                   "Foto vertical caseira da cozinha: liquidificador com massa de chocolate lisa, exatamente três ingredientes organizados ao lado e marmita de alumínio vazia; sem frutas nem telas.",
                   "Liquidificador gira, câmera faz pequeno whip pan até os três ingredientes; sem morph."),
            _cena(3, "close_produto", 3, "Essa é uma das receitas do Doce Sem Culpa,",
                   comum_bolo + "Mão finaliza cobertura cremosa sobre bolo de chocolate assado na marmita; textura artesanal real e apetitosa.",
                   "Espátula faz um único movimento de cobertura; tomada contínua."),
            _cena(4, "avatar_fala", 3, "que ensina a fazer bolos gostosos sem açúcar, sem deixar tudo seco e sem graça.",
                   comum_avatar + "Plano fechado natural; ela segura apenas a colher com uma porção do bolo próxima ao peito, marmita apoiada na bancada, expressão satisfeita.",
                   "Ela fala brevemente e mostra a colher sem aproximá-la da lente; lipsync natural."),
            _cena(5, "close_produto", 2, "",
                   comum_bolo + "Três marmitas em sequência na bancada: chocolate, cenoura com cobertura fina de chocolate e banana com canela sem rodelas de fruta.",
                   "Passeio lateral muito rápido pelos três sabores, sem transformação."),
            _cena(6, "avatar_fala", 4, "Vou deixar o link aqui embaixo pra você clicar e baixar as outras receitas.",
                   comum_avatar + "Plano médio frontal; ela aponta para baixo, melhor marmita de chocolate aberta visível na bancada.",
                   "Ela fala e aponta para baixo no final; lipsync natural, tomada única."),
        ]
    rot["cenas"] = cenas
    rot["estado"] = "roteiro_aprovado"
    atomic_write_json(d / "roteiro.json", rot)


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else "criar"
    if modo == "criar":
        for item in VIDEOS:
            print(f"VID={criar(item)}", flush=True)
    elif modo == "corrigir":
        for i, vid in enumerate(sys.argv[2:]):
            corrigir(vid, i)
            print(f"CORRIGIDO {vid}", flush=True)
    elif modo == "executar":
        for vid in sys.argv[2:]:
            print(f"EXECUTANDO {vid}", flush=True)
            executar(vid)
    elif modo == "reparar_nativo":
        vid = sys.argv[2]
        d = video_dir(PRODUTO, vid)
        rot = ler_json(d / "roteiro.json")
        c = next(x for x in rot["cenas"] if x["n"] == 4)
        c["prompt_keyframe"] = (
            "Camila exatamente como na foto de referência: mesmo rosto, cabelo preto longo, blusa branca lisa, "
            "diante dos mesmos armários brancos e do mesmo fogão com coifa visíveis ao fundo. Close vertical "
            "caseiro do rosto e busto, olhando para a câmera e falando. Mãos fora do quadro. Não mostrar bolo, "
            "marmita, prato, tigela, colher, celular, tela nem produto. Luz natural e textura real de celular."
        )
        c["prompt_movimento"] = "Ela fala direto para a câmera, pisca e inclina levemente a cabeça; lipsync natural, mãos fora do quadro."
        c["keyframe"] = {"arquivo": None, "aprovado": False, "tentativas": 0}
        c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                      "erro": None, "lipsync_aplicado": False}
        c["qualidade"] = {"estado": "pendente", "etapa": None, "tentativa": 0,
                          "motivos": [], "descartes": 0}
        rot["estado"] = "roteiro_aprovado"
        atomic_write_json(d / "roteiro.json", rot)
        keyframes.gerar_keyframes(PRODUTO, vid, ns=[4])
        clipes.gerar_clipes(PRODUTO, vid)
        montagem.montar(PRODUTO, vid, legendas=True)
        print(f"REPARADO {vid}", flush=True)
    elif modo == "reparar_clipe_nativo":
        vid = sys.argv[2]
        d = video_dir(PRODUTO, vid)
        rot = ler_json(d / "roteiro.json")
        c = next(x for x in rot["cenas"] if x["n"] == 4)
        c["prompt_keyframe"] = c["prompt_keyframe"].replace("Mãos fora do quadro. ", "")
        c["prompt_movimento"] = (
            "Ela fala direto para a câmera, pisca e inclina levemente a cabeça; lipsync natural. "
            "Pode fazer um único gesto discreto com uma mão na altura do peito, com anatomia correta."
        )
        c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                      "erro": None, "lipsync_aplicado": False}
        c["qualidade"] = {"estado": "pendente", "etapa": None, "tentativa": 0,
                          "motivos": [], "descartes": 0}
        rot["estado"] = "clips_gerados"
        atomic_write_json(d / "roteiro.json", rot)
        clipes.gerar_clipes(PRODUTO, vid)
        montagem.montar(PRODUTO, vid, legendas=True)
        print(f"CLIPE REPARADO {vid}", flush=True)
    elif modo == "reparar_falas":
        # Recebe pares VID:CENA. Mantém IDs/pastas e regenera somente os takes cuja
        # transcrição alterou palavra-chave, claim ou introduziu fala espúria.
        for alvo in sys.argv[2:]:
            vid, n_txt = alvo.rsplit(":", 1)
            n = int(n_txt)
            d = video_dir(PRODUTO, vid)
            rot = ler_json(d / "roteiro.json")
            c = next(x for x in rot["cenas"] if x["n"] == n)
            fala = c["narracao"]
            c["instrucao_clipe"] = (
                "Fale EXATAMENTE a narração escrita, começando na primeira palavra, sem ruído, "
                "fala anterior, palavra extra ou improviso. Pronuncie claramente cada sílaba. "
                "Quando aparecer, diga o nome da marca exatamente como 'Doce Sem Culpa' "
                "(DO-ce SEM CUL-pa). Quando aparecer, diga claramente 'molhadinhos', com M inicial."
            )
            c["clipe"] = {"arquivo": None, "gerado": False, "fal_request_id": None,
                          "erro": None, "lipsync_aplicado": False}
            c["qualidade"] = {"estado": "pendente", "etapa": None, "tentativa": 0,
                              "motivos": [], "descartes": 0,
                              "fala_alvo_auditoria": fala}
            rot["estado"] = "clips_gerados"
            atomic_write_json(d / "roteiro.json", rot)
            clipes.gerar_clipes(PRODUTO, vid)
            montagem.montar(PRODUTO, vid, legendas=True)
            print(f"FALA REPARADA {vid}:{n}", flush=True)
