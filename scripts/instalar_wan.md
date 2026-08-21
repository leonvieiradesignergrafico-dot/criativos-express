# Motor local grátis (Wan 2.2 TI2V 5B) — instalação (Fase 4)

O motor "local" anima keyframes na sua RTX 3060 Ti (8GB), de graça e sem internet,
porém LENTO (~10–20 min por cena de 5s) e sem fala. Bom pra rodar lotes de noite
e comparar com o motor API.

## Passos

1. Criar o venv separado (o torch pesado NÃO entra no venv do app):
   ```
   cd "D:\Desktop\Projetos de IA\UGC Express"
   py -3.11 -m venv venv_wan
   venv_wan\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
   venv_wan\Scripts\pip install diffusers transformers accelerate safetensors imageio[ffmpeg] ftfy
   ```
2. Apontar no `config.toml`:
   ```
   [local]
   python = "D:/Desktop/Projetos de IA/UGC Express/venv_wan/Scripts/python.exe"
   ```
3. O download do modelo (Wan2.2-TI2V-5B-Diffusers, ~12GB) acontece na primeira geração
   e fica em cache no huggingface hub.

O script chamado pelo backend é `scripts/wan_i2v.py` (image-to-video 720p com offload
de CPU pra caber nos 8GB de VRAM).

## F5-TTS PT-BR local (voz grátis com timbre melhor que o edge-tts)

```
venv_wan\Scripts\pip install f5-tts
```
Checkpoint PT-BR da comunidade: https://huggingface.co/firstpixel/F5-TTS-pt-br
No voz.json do avatar: {"engine": "f5", "ref_audio": "caminho/amostra.wav", "ref_text": "..."}
