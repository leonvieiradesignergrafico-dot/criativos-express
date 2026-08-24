"""Runtime hook (PyInstaller): aponta o SSL do Python para um bundle de CAs.

POR QUE ISSO EXISTE: no macOS o `ssl` do Python NÃO lê o Keychain do sistema — ele
depende do bundle de CAs que veio junto com a instalação do Python (é o que o
"Install Certificates.command" do python.org configura). Dentro de um .app congelado
esse bundle não existe, então TODO HTTPS feito de dentro do Python falha com
    <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate>
Foi exatamente o que derrubava a geração de clipes (backends/veo_backend.py -> Vertex/Veo),
enquanto copy/keyframes passavam por serem feitos pelas CLIs Node (claude/codex), que usam
as CAs do sistema.

No Windows nada disso é necessário (o ssl usa a cert store do SO), por isso o hook só é
registrado no spec do Mac.

Roda ANTES de qualquer import do app, então basta plantar as variáveis de ambiente que o
OpenSSL/ssl/requests/httpx leem na hora de montar o contexto padrão.
"""
import os
import sys


def _bundle_ca() -> str:
    # 1) certifi empacotado (caminho normal — o hook-certifi do PyInstaller extrai o
    #    cacert.pem para dentro do bundle).
    try:
        import certifi
        caminho = certifi.where()
        if caminho and os.path.exists(caminho):
            return caminho
    except Exception:  # noqa: BLE001
        pass
    # 2) fallback: cacert.pem solto na raiz do bundle extraído.
    base = getattr(sys, "_MEIPASS", "")
    if base:
        for nome in ("cacert.pem", os.path.join("certifi", "cacert.pem")):
            caminho = os.path.join(base, nome)
            if os.path.exists(caminho):
                return caminho
    return ""


def _aplicar() -> None:
    ca = _bundle_ca()
    if not ca:
        return
    # Não sobrescreve o que o usuário/ambiente já definiu (proxy corporativo com CA própria).
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        if not os.environ.get(var):
            os.environ[var] = ca


_aplicar()
