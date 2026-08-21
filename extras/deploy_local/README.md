# Deploy local — app de duplo-clique

Roda a Impressora de Criativos como um app de janela nativa, **sem terminal**,
usando o Python que você já tem instalado. Seus dados (`products/`, `config.toml`)
continuam na pasta do projeto, do jeito que estão.

## Como gerar o atalho

```
python deploy_local/criar_atalho.py
```

Isso cria:
- `deploy_local/icone.ico` — ícone do app
- **"Criativos Express"** na sua Área de Trabalho (e uma cópia na raiz do projeto)

Depois é só **dar duplo-clique**. Para deixar na barra de tarefas: botão direito no
atalho → *Fixar na barra de tarefas*.

## Quando rodar de novo

Rode `criar_atalho.py` outra vez se você:
- mover a pasta do projeto para outro lugar;
- reinstalar/trocar a versão do Python.

(O atalho aponta para o `pythonw.exe` atual e para o `desktop.py` na pasta atual;
se algum desses caminhos mudar, é só regenerar.)

## Como funciona (custo zero)

O atalho executa `pythonw.exe desktop.py`, que sobe o servidor local (Flask) numa
thread e abre a janela nativa (pywebview) apontando para `http://127.0.0.1:5000`.
Toda a inteligência continua usando os CLIs logados na sua máquina:
- copies/prompts → `claude -p` (seu plano Claude)
- imagens → `codex exec` (seu plano ChatGPT)

Nenhuma chamada de API paga. **Pré-requisito:** `claude` e `codex` instalados e
logados (`claude` já logado; `codex login` feito).

## Observações

- **Uma instância por vez:** o app usa a porta 5000. Se já houver uma janela aberta,
  abrir de novo pode não subir uma segunda — feche a primeira antes.
- **Precisa do Python instalado.** Se um dia quiser um `.exe` autônomo (sem Python,
  para levar a outra máquina), dá para empacotar com PyInstaller — é a "opção B",
  mais pesada; peça quando precisar.
