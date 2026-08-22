"""Controle de qualidade visual/audiovisual dos keyframes e clipes UGC.

O avaliador usa o Codex CLI já autenticado pela ferramenta.  Toda reprovação é
preservada em ``descartados/cena_NN/tentativa_NN`` para inspeção temporária.
"""
from __future__ import annotations

import json
import difflib
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import wave
from pathlib import Path

from backends.codex_backend import _NO_WINDOW, _codex_cmd_base
from workspace import atomic_write_json, carregar_config


PROMPT_BASE = """Você é o controle de qualidade de uma esteira de vídeos UGC.
Analise TODAS as imagens anexadas como frames ordenados do mesmo take. Seja rigoroso,
mas reprove apenas defeitos visíveis. Responda SOMENTE JSON válido:
{"aprovado":true|false,"motivos":[{"codigo":"snake_case","detalhe":"curto"}],
 "correcao_prompt":"instrução objetiva para a próxima geração"}

Critérios duros:
- anatomia humana plausível: exatamente dois braços no corpo, mãos/dedos plausíveis,
  nenhum membro duplicado, desconectado, fundido ou surgindo sem origem;
- respeitar a geometria esperada descrita abaixo;
- celular pode aparecer se for OBJETO demonstrado à câmera, filmado por uma segunda
  câmera, apoiado, ou refletido num espelho. Se o frame representa a perspectiva da
  própria câmera frontal/selfie, esse mesmo celular e o braço que o segura NÃO aparecem;
- corpo e objetos não podem estar fundidos, esmagados nem apoiados de forma impossível;
- mesma pessoa, roupa, ambiente e produto; produto sem deformação grosseira;
- em clipe: uma única tomada contínua. Reprovar morph, wipe, dissolução, split screen,
  duplicação, troca de cena ou transição interna;
- reprovar sequência visual congelada enquanto o take ainda deveria estar acontecendo;
- conte também braços parcialmente cortados pelas bordas. Se uma mão segura produto, outra
  aponta e um terceiro braço se estende para a lente, são TRÊS braços: reprove;
- coerência fala-imagem: demonstrativos como "este/esses/aqui/olha" e gestos de apontar
  exigem que a coisa alegada esteja realmente visível. Reprovar quando a fala trata um
  problema como presente/visível, mas a imagem mostra pele lisa ou nenhuma evidência;
- coerência temporal: se o roteiro apresenta resultado depois do uso, não mostrar nem apontar
  o mesmo problema como se ainda estivesse presente, salvo comparação antes/depois explícita.
Não reprove pequenas imperfeições naturais de UGC, microtremor ou mudança normal de pose.
"""

PROMPT_CONTINUIDADE = """Você é o controle de continuidade de um vídeo UGC. A imagem anexada
é uma grade temporal: cada célula, da esquerda para a direita e de cima para baixo, representa
uma cena diferente do MESMO vídeo. Responda SOMENTE JSON válido no mesmo formato pedido abaixo.
Reprove se a pessoa recorrente trocar rosto, cabelo, cor ou peça de roupa, parte de baixo,
calçado ou acessórios entre cenas. Analise também closes de torso, mãos e produto: qualquer
trecho de tecido visível deve pertencer ao figurino canônico. Não confunda mudança de ângulo,
distância, pose ou iluminação com troca de roupa. O cenário pode variar só quando o roteiro
planejar isso explicitamente. Não avalie transições nesta grade, pois cada célula é outro take.
Este portão decide SOMENTE identidade e figurino. Não reprove diferenças de ação, pose,
composição, enquadramento, presença do produto ou fidelidade ao plano de cada cena; esses itens
são avaliados em outra etapa. Se rosto/cabelo/roupa forem consistentes, marque aprovado=true.
"""


def _eh_selfie(fmt: str, prompt: str, espelho: bool) -> bool:
    """SELFIE = a pessoa filma a SI MESMA com a câmera frontal (o celular É a câmera). É o
    ÚNICO caso em que o celular/braço que o segura NÃO podem aparecer no quadro. Filmado
    por OUTRA pessoa/suporte (experimento social, entrevista/abordagem de rua, two-shot,
    multi-pessoa) NÃO é selfie — nesses o celular pode aparecer normalmente."""
    if espelho:
        return False
    if any(x in prompt for x in ("experimento", "abordagem", "entrevista", "outra pessoa",
            "filmado por", "dupla", "two-shot", "two shot", "câmera de mão de", "camera de mao de",
            "segurada por", "suporte", "tripé", "tripe", "de rua")):
        return False
    try:
        from app.pipeline import formatos_video as fv
        if fmt and (fv.multi_pessoa(fmt) or fv.two_shot(fmt)):
            return False
    except Exception:  # noqa: BLE001
        pass
    if any(x in prompt for x in ("selfie", "braço estendido", "braco estendido", "câmera frontal",
            "camera frontal", "autorretrato", "self-tape", "filma a si", "se filmando")):
        return True
    # Formato solo conhecido (não caiu nos não-selfie acima) = padrão UGC depoimento = selfie.
    return bool(fmt)


def contrato_cena(cena: dict) -> dict:
    """Normaliza a geometria explícita da cena, inclusive roteiros antigos."""
    tipo = cena.get("tipo") or ""
    prompt = (cena.get("prompt_keyframe") or "").lower()
    fmt = (cena.get("formato_video") or "").lower()
    geo = dict(cena.get("geometria") or {})
    espelho = any(x in prompt for x in ("espelho", "reflexo", "mirror"))
    mostra_tela = tipo in ("tela_dispositivo", "avatar_aponta_tela") or any(
        x in prompt for x in ("mostrar a tela", "mostra a tela", "tela do celular"))
    selfie = _eh_selfie(fmt, prompt, espelho)
    if not geo.get("perspectiva"):
        geo["perspectiva"] = "espelho" if espelho else "camera_frontal"
    if not geo.get("camera_operador"):
        geo["camera_operador"] = "personagem" if geo["perspectiva"] == "camera_frontal" else "outra_pessoa_ou_suporte"
    if not geo.get("celular_visivel"):
        # Celular proibido SÓ em selfie (é a própria câmera). Fora disso, permitido — corrige
        # o falso positivo do QA em experimento social / cena filmada por outra pessoa.
        if mostra_tela:
            geo["celular_visivel"] = "obrigatorio"
        elif selfie:
            geo["celular_visivel"] = "proibido"
        else:
            geo["celular_visivel"] = "permitido"
    geo.setdefault("maos_visiveis", "no_maximo_duas; preferir_uma")
    geo.setdefault("acao_maos", "uma acao simples por mao; nenhuma mao ou braco sem origem corporal visivel")
    geo.setdefault("contatos_fisicos", "sem corpo fundido, esmagado ou colado em mesa, lente ou objetos")
    return geo


def reforco_prompt(cena: dict) -> str:
    g = contrato_cena(cena)
    return (
        "\nCONTRATO FISICO E DE CAMERA (regra dura): "
        f"operador={g['camera_operador']}; perspectiva={g['perspectiva']}; "
        f"celular_visivel={g['celular_visivel']}; maos={g['maos_visiveis']}; "
        f"acao_maos={g['acao_maos']}; contatos={g['contatos_fisicos']}. "
        "Cada pessoa tem exatamente dois bracos ligados naturalmente aos proprios ombros. Mostre somente os membros "
        "necessarios para a acao, sem membro extra, duplicado ou entrando pela borda. Uma unica tomada: "
        "sem transicao, morph, wipe, dissolucao, sobreposicao, split screen ou mudanca de cena."
    )


def _extrair_json(txt: str) -> dict:
    txt = txt.strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise RuntimeError("A análise de qualidade não devolveu JSON válido.")
        return json.loads(m.group(0))


def _avaliar_imagens(imagens: list[Path], cena: dict, etapa: str,
                     qtd_referencias: int = 0) -> dict:
    cfg = carregar_config().get("qualidade", {})
    if cfg.get("habilitada", True) is False:
        return {"aprovado": True, "motivos": [], "correcao_prompt": "", "ignorada": True}
    with tempfile.TemporaryDirectory(prefix="ce_qa_") as td:
        out = Path(td) / "resposta.txt"
        base = PROMPT_CONTINUIDADE if etapa == "continuidade_video" else PROMPT_BASE
        prompt = (base + f"\nETAPA: {etapa}.\nCONTRATO DA CENA: "
                  + json.dumps(contrato_cena(cena), ensure_ascii=False)
                  + "\nDESCRIÇÃO PLANEJADA: " + (cena.get("prompt_keyframe") or ""))
        if qtd_referencias:
            prompt += (f"\nORDEM DAS IMAGENS: as primeiras {qtd_referencias} imagens são REFERÊNCIAS "
                       "aprovadas da mesma personagem/vídeo; as imagens seguintes são o CANDIDATO atual. "
                       "Use as referências para reprovar troca de identidade, rosto, cabelo, figurino completo, "
                       "ambiente ou produto. Mudança legítima de ângulo/ação não é erro.")
        cmd = _codex_cmd_base() + ["exec", "--sandbox", "read-only",
                                   "--skip-git-repo-check", "--ephemeral", "-o", str(out)]
        modelo = str(cfg.get("modelo") or "").strip()
        if modelo:
            cmd += ["--model", modelo]
        # O prompt precisa vir antes de -i: no CLI a flag de imagem é variádica.
        cmd += [prompt]
        for img in imagens:
            cmd += ["-i", str(img)]
        r = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW,
                           timeout=int(cfg.get("timeout", 180)))
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("Falha na análise visual: " + r.stderr.decode(errors="replace")[-500:])
        dado = _extrair_json(out.read_text(encoding="utf-8", errors="replace"))
        dado["aprovado"] = bool(dado.get("aprovado"))
        dado.setdefault("motivos", [])
        dado.setdefault("correcao_prompt", "")
        dado["etapa"] = etapa
        dado["analisado_em"] = time.time()
        return dado


def avaliar_keyframe(path: Path, cena: dict, referencias: list[Path] | None = None) -> dict:
    refs = [p for p in (referencias or []) if p.exists()]
    return _avaliar_imagens(refs + [path], cena, "keyframe", len(refs))


def extrair_frames(clipe: Path, destino: Path, quantidade: int = 7) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    ffmpeg = (carregar_config().get("app", {}).get("ffmpeg") or "ffmpeg").strip()
    padrao = destino / "frame_%02d.jpg"
    ffprobe = (ffmpeg[:-6] + "ffprobe" + ffmpeg[-4:] if ffmpeg.lower().endswith("ffmpeg.exe")
               else (ffmpeg[:-6] + "ffprobe" if ffmpeg.lower().endswith("ffmpeg") else "ffprobe"))
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(clipe)],
                           capture_output=True, creationflags=_NO_WINDOW, timeout=30)
    try:
        dur = max(0.1, float(probe.stdout.decode().strip()))
    except ValueError:
        dur = 5.0
    # Amostragem uniforme do take inteiro, inclusive perto do final onde surgem travamentos.
    filtro = f"fps={quantidade / dur:.6f},scale=360:-2"
    r = subprocess.run([ffmpeg, "-y", "-i", str(clipe), "-vf", filtro,
                        "-frames:v", str(quantidade), str(padrao)],
                       capture_output=True, creationflags=_NO_WINDOW, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("Falha ao extrair frames para QA: " + r.stderr.decode(errors="replace")[-500:])
    return sorted(destino.glob("frame_*.jpg"))


def criar_folha_contato(frames: list[Path], destino: Path) -> Path:
    """Condensa a sequência numa imagem para que o avaliador enxergue o gesto inteiro."""
    if not frames:
        raise RuntimeError("Nenhum frame para montar a folha de contato.")
    from PIL import Image, ImageOps
    colunas = 4
    linhas = (len(frames) + colunas - 1) // colunas
    folha = destino / "folha_contato.jpg"
    largura, altura = 270, 480
    grade = Image.new("RGB", (colunas * largura, linhas * altura), "black")
    for i, path in enumerate(frames):
        with Image.open(path) as original:
            celula = ImageOps.fit(original.convert("RGB"), (largura, altura),
                                  method=Image.Resampling.LANCZOS)
            grade.paste(celula, ((i % colunas) * largura, (i // colunas) * altura))
    grade.save(folha, quality=88)
    return folha


def avaliar_clipe(clipe: Path, cena: dict, trabalho: Path,
                  referencia_keyframe: Path | None = None) -> dict:
    quantidade = int(carregar_config().get("qualidade", {}).get("frames_por_clipe", 16))
    frames = extrair_frames(clipe, trabalho, max(3, quantidade))
    folha = criar_folha_contato(frames, trabalho)
    refs = [referencia_keyframe] if referencia_keyframe and referencia_keyframe.exists() else []
    resultado = _avaliar_imagens(refs + [folha], cena, "clipe", len(refs))
    congelado = detectar_congelamento(clipe)
    if congelado:
        resultado["aprovado"] = False
        resultado.setdefault("motivos", []).append({
            "codigo": "frame_congelado",
            "detalhe": f"imagem congelada por {congelado:.2f}s durante o take"})
        resultado["correcao_prompt"] = (
            "Mantenha movimento orgânico contínuo de câmera, respiração e gesto durante todo o take; "
            "nenhum frame pode ficar congelado.")
    return resultado


def avaliar_continuidade_video(keyframes: list[Path], trabalho: Path,
                               roteiro: dict | None = None) -> dict:
    """Auditoria cruzada obrigatória antes de gastar com animação."""
    existentes = [p for p in keyframes if p.exists()]
    if len(existentes) < 2:
        return {"aprovado": True, "motivos": [], "correcao_prompt": ""}
    folha = criar_folha_contato(existentes, trabalho)
    planos = []
    if roteiro:
        for c in roteiro.get("cenas", []):
            if (c.get("keyframe") or {}).get("arquivo"):
                planos.append(f"célula {len(planos)+1}: {c.get('prompt_keyframe', '')}")
    cena = {"tipo": "continuidade_video", "prompt_keyframe":
            "Todas as células são cenas do mesmo vídeo e devem manter identidade e figurino completos. "
            "Não infira calça ou outra peça quando a roupa estiver cortada, coberta pela perna ou ambígua; "
            "reprove somente troca visível. Planos declarados:\n" + "\n".join(planos)}
    resultado = _avaliar_imagens([folha], cena, "continuidade_video")
    # Alguns modelos ainda apontam desvios de composição apesar da instrução. Só esse portão
    # pode bloquear roupa/identidade; nunca converta outro tipo de observação em falso negativo.
    termos = " ".join(json.dumps(x, ensure_ascii=False).lower()
                      for x in resultado.get("motivos", []))
    bloqueadores = ("troca de roupa", "figurino", "camiseta", "calça", "short", "saia",
                    "vestido", "rosto diferente", "troca de pessoa", "cabelo diferente")
    if not any(t in termos for t in bloqueadores):
        resultado["aprovado"] = True
    return resultado


def detectar_congelamento(clipe: Path, minimo_s: float = 1.20) -> float:
    """Retorna a maior pausa visual detectada; zero significa fluxo normal."""
    ffmpeg = (carregar_config().get("app", {}).get("ffmpeg") or "ffmpeg").strip()
    r = subprocess.run([ffmpeg, "-i", str(clipe), "-vf",
                        f"freezedetect=n=-50dB:d={minimo_s}", "-f", "null", "-"],
                       capture_output=True, creationflags=_NO_WINDOW, timeout=120)
    txt = r.stderr.decode(errors="replace")
    vals = [float(x) for x in re.findall(r"freeze_duration:\s*([0-9.]+)", txt)]
    return max(vals, default=0.0)


def _duracao_midia(path: Path) -> float:
    ffmpeg = (carregar_config().get("app", {}).get("ffmpeg") or "ffmpeg").strip()
    ffprobe = (ffmpeg[:-6] + "ffprobe" + ffmpeg[-4:] if ffmpeg.lower().endswith("ffmpeg.exe")
               else (ffmpeg[:-6] + "ffprobe" if ffmpeg.lower().endswith("ffmpeg") else "ffprobe"))
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, creationflags=_NO_WINDOW, timeout=30)
    try:
        return float(r.stdout.decode().strip())
    except ValueError:
        return 0.0


def assinatura_audio(clipe: Path) -> dict | None:
    """Assinatura vocal conservadora (pitch + brilho) sem dependência externa além de numpy."""
    try:
        import numpy as np
    except ImportError:
        return None
    with tempfile.TemporaryDirectory(prefix="ce_voice_") as td:
        wav_path = Path(td) / "audio.wav"
        ffmpeg = (carregar_config().get("app", {}).get("ffmpeg") or "ffmpeg").strip()
        r = subprocess.run([ffmpeg, "-y", "-i", str(clipe), "-vn", "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le", str(wav_path)], capture_output=True,
                           creationflags=_NO_WINDOW, timeout=120)
        if r.returncode != 0 or not wav_path.exists():
            return None
        with wave.open(str(wav_path), "rb") as w:
            y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if len(y) < 8000:
        return None
    pitches, centroids = [], []
    size, hop, sr = 1600, 800, 16000
    for pos in range(0, len(y) - size, hop):
        frame = y[pos:pos + size]
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 0.015:
            continue
        frame = (frame - frame.mean()) * np.hanning(size)
        corr = np.correlate(frame, frame, mode="full")[size - 1:]
        lo, hi = int(sr / 320), int(sr / 75)
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] > corr[0] * 0.20:
            pitches.append(sr / lag)
        mag = np.abs(np.fft.rfft(frame))
        freqs = np.fft.rfftfreq(size, 1 / sr)
        if mag.sum() > 0:
            centroids.append(float((mag * freqs).sum() / mag.sum()))
    if len(pitches) < 3:
        return None
    return {"pitch_hz": round(float(np.median(pitches)), 2),
            "centroide_hz": round(float(np.median(centroids)), 2)}


def comparar_voz(atual: dict | None, referencia: dict | None) -> dict | None:
    """Só reprova mudança muito grande; variação natural não dispara regeneração."""
    if not atual or not referencia:
        return None
    rp = abs(atual["pitch_hz"] - referencia["pitch_hz"]) / max(referencia["pitch_hz"], 1)
    rc = abs(atual["centroide_hz"] - referencia["centroide_hz"]) / max(referencia["centroide_hz"], 1)
    if rp > 0.45 and rc > 0.35:
        return {"codigo": "voz_inconsistente",
                "detalhe": "assinatura vocal mudou fortemente em relação aos outros takes"}
    return None


def _normalizar_fala(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", texto.lower()))


def transcrever_audio_detalhado(clipe: Path) -> dict | None:
    """Transcreve com timestamps/confiança por palavra para QA e corte automático."""
    exe = shutil.which("whisper")
    if not exe:
        return None
    with tempfile.TemporaryDirectory(prefix="ce_stt_") as td:
        r = subprocess.run([exe, str(clipe), "--model", "base", "--language", "Portuguese",
                            "--task", "transcribe", "--output_format", "json",
                            "--output_dir", td, "--word_timestamps", "True", "--fp16", "False"],
                           capture_output=True, creationflags=_NO_WINDOW, timeout=300)
        arquivos = list(Path(td).glob("*.json"))
        if r.returncode != 0 or not arquivos:
            return None
        try:
            bruto = json.loads(arquivos[0].read_text(encoding="utf-8"))
            palavras = []
            for seg in bruto.get("segments") or []:
                for w in seg.get("words") or []:
                    palavras.append({"word": str(w.get("word") or "").strip(),
                                     "start": round(float(w.get("start") or 0), 3),
                                     "end": round(float(w.get("end") or 0), 3),
                                     "probability": round(float(w.get("probability") or 0), 4)})
            return {"text": str(bruto.get("text") or "").strip(), "words": palavras}
        except (OSError, ValueError, TypeError):
            return None


def transcrever_audio(clipe: Path) -> str | None:
    detalhe = transcrever_audio_detalhado(clipe)
    return detalhe.get("text") if detalhe else None


def sugerir_corte_por_fala(detalhe: dict | None, esperado: str, duracao: float,
                           pad_ini: float = 0.06, pad_fim: float = 0.12) -> dict | None:
    """Alinha palavras ao roteiro e separa silêncio/extras de articulação defeituosa."""
    if not detalhe or not detalhe.get("words"):
        return None
    palavras = detalhe["words"]
    obtidas = [_normalizar_fala(w.get("word", "")) for w in palavras]
    alvo = _normalizar_fala(esperado).split()
    obtidas = [x for x in obtidas if x]
    if not alvo or not obtidas or len(obtidas) != len(palavras):
        return None
    matcher = difflib.SequenceMatcher(None, obtidas, alvo)
    pares = []
    for bloco in matcher.get_matching_blocks():
        for k in range(bloco.size):
            pares.append((bloco.a + k, bloco.b + k))
    if not pares or len({b for _, b in pares}) / len(alvo) < 0.55:
        return None
    primeiro_i, primeiro_alvo = min(pares, key=lambda x: x[1])
    ultimo_i, ultimo_alvo = max(pares, key=lambda x: x[1])
    inicio = max(0.0, float(palavras[primeiro_i]["start"]) - pad_ini)
    fim = min(duracao, float(palavras[ultimo_i]["end"]) + pad_fim)
    extras_ini = [palavras[i]["word"] for i in range(primeiro_i)]
    extras_fim = [palavras[i]["word"] for i in range(ultimo_i + 1, len(palavras))]
    # Baixa confiança isolada em fala que começa no frame zero é comum no Whisper e não
    # significa defeito (o usuário manteve esses casos). O padrão problemático aprendido
    # foi: entrada tardia + primeira palavra incerta/embolada.
    baixa_inicio = (primeiro_alvo == 0
                    and float(palavras[primeiro_i].get("start") or 0) >= 0.25
                    and float(palavras[primeiro_i].get("probability") or 0) < 0.55)
    return {"inicio_s": round(inicio, 2), "fim_s": round(fim, 2),
            "extras_inicio": extras_ini, "extras_fim": extras_fim,
            "confianca_primeira": float(palavras[primeiro_i].get("probability") or 0),
            "fala_inicial_embolada": baixa_inicio,
            "cobertura_roteiro": round(len({b for _, b in pares}) / len(alvo), 3)}


def proteger_fim_de_palavra(fim: float, detalhe: dict | None,
                            margem: float = 0.10) -> tuple[float, str | None]:
    """Nunca permite que uma alça manual termine dentro de uma palavra reconhecida."""
    if fim <= 0 or not detalhe:
        return fim, None
    for w in detalhe.get("words") or []:
        ini_w, fim_w = float(w.get("start") or 0), float(w.get("end") or 0)
        if ini_w < fim < fim_w:
            return round(fim_w + margem, 2), str(w.get("word") or "").strip() or None
    return fim, None


def comparar_fala(transcricao: str | None, esperado: str) -> dict | None:
    """Reprova fala embolada, ausente ou materialmente diferente do roteiro falado."""
    if transcricao is None:
        return None
    obtido, alvo = _normalizar_fala(transcricao), _normalizar_fala(esperado)
    if not obtido:
        return {"codigo": "fala_ininteligivel", "detalhe": "o áudio não pôde ser compreendido"}
    similaridade = difflib.SequenceMatcher(None, obtido, alvo).ratio()
    inicio_alvo = alvo.split()[:3]
    inicio_ok = all(p in obtido.split()[:7] for p in inicio_alvo[:2])
    if similaridade < 0.62 or not inicio_ok:
        return {"codigo": "fala_divergente_ou_embolada",
                "detalhe": f"transcrição '{transcricao}' não corresponde claramente ao roteiro ({similaridade:.0%})"}
    return None


def arquivar_descarte(video_dir: Path, cena: dict, etapa: str, arquivo: Path,
                      analise: dict, prompt: str) -> Path:
    base = video_dir / "descartados" / f"cena_{int(cena['n']):02d}"
    existentes = list(base.glob("tentativa_*")) if base.exists() else []
    pasta = base / f"tentativa_{len(existentes) + 1:02d}_{etapa}"
    pasta.mkdir(parents=True, exist_ok=False)
    if arquivo.exists():
        shutil.copy2(arquivo, pasta / arquivo.name)
    atomic_write_json(pasta / "analise.json", analise)
    (pasta / "prompt.txt").write_text(prompt, encoding="utf-8")
    return pasta
