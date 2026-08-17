---
name: subir-anuncios-meta
description: Sobe criativos da pasta "finais" de um produto para a Meta e monta a campanha de teste (ABO, 1 conjunto por anúncio), com copies geradas por arte. Ativa quando o usuário disser algo como "sobe esses testes na BM/conta X", "sobe a Invasão para anunciar", "joga esses criativos na Meta".
---

# Subir anúncios na Meta (Corinthians / Criativos Express)

Você monta uma estrutura de teste na Meta a partir das artes finais de um produto: sobe as artes,
escreve a copy de cada uma (baseada na própria arte) e cria **1 campanha em ABO → 1 conjunto por
anúncio → 1 anúncio por conjunto**, tudo **PAUSADO** para o usuário revisar e ligar.

> Tudo é feito via **Graph API** com o token do usuário (não usa o MCP da Meta — o MCP não faz upload de imagem).
> Token em `C:/Users/Leon/.claude/.secrets/meta_ads.json` (fora do Git). Se expirar, ver "Token" no fim.

## Execução enxuta (leia uma vez, siga direto)
- **Não releia este SKILL** no meio; siga os passos 1→7 em ordem.
- **Leia SÓ:** `accounts.json` (mapa do produto) + o `config.md`/cérebro do produto + as artes da pasta
  `finais/`. Não varra o repositório.
- As seções **Identidade/PARCERIA** e **Tokens** (fim do arquivo) são de referência: **leia só se for
  Corinthians** ou se `check`/`create` acusar problema de token. Não as leia por padrão.
- Uma checagem de token no passo 1 basta; não fique repetindo `check`. Pare após o passo 7 (reporte) —
  tudo nasce PAUSADO, não ligue nada.

## Ferramentas desta skill
- `lib/meta.py` — helper Graph API (stdlib, sem deps). Comandos: `check`, `upload`, `create`.
- `accounts.json` — mapa produto → conta / **pixel** / páginas. O **pixel é automático pelo produto**.

---

## Passo a passo (siga na ordem)

### 1. Identifique o produto e a conta
- Descubra de qual **produto** são os testes (a fala do usuário + a pasta `products/<produto>/output/criativos/finais`).
- Leia `accounts.json`. Ache o produto (ex: `invasao`). Dele saem: `account_id`, `pixel_id`,
  `pagina_padrao`, `slug_arquivo`, `min_daily_budget_cents`.
- Se o produto não estiver no mapa (ou `account_id: null`), **pergunte** a conta e rode
  `python lib/meta.py check <account_id>` pra confirmar. Se for Corinthians, o pixel já está no mapa.
- Rode `python lib/meta.py check <account_id>` pra confirmar que o token está vivo antes de tudo.

### 2. Renomeie as artes (padrão de nome)
Padrão: **`<slug>-<dd-mm-aa>-ad<NN>`** (número com 2 dígitos). Ex: `invasao-19-07-26-ad01.png`.
- Data = hoje (`date +%d-%m-%y`).
- Renomeie os arquivos da pasta `finais/` em ordem (ad01, ad02, …). Mantenha o mapeamento
  arquivo → número, porque ele vira o nome do anúncio.

### 3. Suba as artes e pegue os hashes
```
python lib/meta.py upload <account_id> "<finais>/<slug>-<data>-ad01.png" "...ad02.png" ...
```
Retorna `{ "arquivo.png": "image_hash" }`. Guarde cada hash casado com seu número de anúncio.
(Subir pra biblioteca **não** cria anúncio nem gasta nada.)

### 4. Gere a copy de CADA arte (1 copy por arte)
Use o cérebro de copy do projeto — **leia `app/prompts/copywriter.md`** (mente do copywriter) e o
`products/<produto>/config.md` (oferta, tom, proibições). Depois **olhe cada arte** (leia o PNG) e
escreva, para aquele criativo específico:
- **message** — texto principal do feed (pode vender à vontade; primeira linha forte).
- **headline** — título curto (vai em `link_data.name`).
- **description** — descrição curta (abaixo da imagem).
Cada anúncio vende UMA ideia. Respeite o `config.md`. Não invente oferta/preço.

> ⚠️ **ACENTOS OBRIGATÓRIOS:** escreva as copies com a acentuação correta do português
> (é, não, história, coleção, edição, São Paulo…). **NUNCA remova/achate acentos.** O pipeline é
> UTF-8 seguro (`meta.py` usa `ensure_ascii=False`). Ver [[copy-sempre-com-acento]].

### 5. Pergunte a configuração (UMA rodada só)
Use AskUserQuestion. Traga os **defaults abaixo já preenchidos** — o usuário só muda o que quiser.

**Campanha**
- Nome da campanha (sugira: `INVASAO | Teste | dd-mm-aa`).
- Objetivo — default **Vendas (OUTCOME_SALES)**.

**Conjunto (vale pra todos — ABO, 1 conjunto por anúncio)**
- Orçamento por conjunto/dia (R$) — lembre o mínimo da conta (`min_daily_budget_cents`).
- Meta de otimização — default **Compras (OFFSITE_CONVERSIONS)** + evento **PURCHASE**.
- **Janela de atribuição** — default do usuário: **clique 1 dia + visualização 1 dia + engajamento
  de vídeo 1 dia** → `[{CLICK_THROUGH,1},{VIEW_THROUGH,1},{ENGAGED_VIDEO_VIEW,1}]`.
- Público — default **Brasil, 18–65, amplo (Advantage+)**. Pergunte se quer detalhar.
- Estratégia de lance — default **menor custo (LOWEST_COST_WITHOUT_CAP)**.

**Anúncio / criativo**
- Página — default `pagina_padrao` do mapa (Corinthians Essencial). Conta do Instagram (opcional; peça o ID se quiser placement no IG).
- **CTA** — default **Saiba mais (LEARN_MORE)**; opção comum: **Comprar (SHOP_NOW)**.
- **URL de destino** (link da página de vendas).
- **Parâmetros de URL / UTM** — SEMPRE. Default sugerido (macros dinâmicas da Meta):
  `utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}&utm_term={{adset.name}}&utm_placement={{placement}}`
  (vai no campo `url_tags` do criativo; confirme/edite com o usuário).

### 6. Monte o plan.json e crie tudo
Escreva um `plan.json` (formato abaixo) no scratchpad e rode:
```
python lib/meta.py create <caminho>/plan.json
```
Cria campanha (ABO) + N conjuntos + N anúncios, **todos PAUSADOS**, e imprime os IDs.

### 7. Reporte
Mostre: nome/ID da campanha, quantos conjuntos/anúncios, orçamento total/dia, pixel usado,
e o link do Gerenciador: `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=<account_id>`.
Lembre que está **tudo pausado** — o usuário revisa e liga.

---

## Formato do plan.json
```json
{
  "account_id": "1542878477392736",
  "page_id": "604611286073591",
  "instagram_user_id": null,
  "pixel_id": "28033781292872432",
  "campaign": { "name": "INVASAO | Teste | 19-07-26", "objective": "OUTCOME_SALES", "special_ad_categories": [] },
  "defaults": {
    "daily_budget_cents": 2000,
    "optimization_goal": "OFFSITE_CONVERSIONS",
    "billing_event": "IMPRESSIONS",
    "custom_event_type": "PURCHASE",
    "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
    "attribution_spec": [
      {"event_type": "CLICK_THROUGH", "window_days": 1},
      {"event_type": "VIEW_THROUGH", "window_days": 1},
      {"event_type": "ENGAGED_VIDEO_VIEW", "window_days": 1}
    ],
    "targeting": { "geo_locations": { "countries": ["BR"] }, "age_min": 18, "age_max": 65 },
    "link": "https://SUA-PAGINA-DE-VENDAS",
    "url_tags": "utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}",
    "cta": "LEARN_MORE"
  },
  "ads": [
    { "name": "invasao-19-07-26-ad01", "image_hash": "62256d2d23d753afccec96b4b287653d",
      "message": "texto principal...", "headline": "titulo...", "description": "descricao..." }
  ]
}
```

## Regras duras
- **Público/identidade Corinthians**: use `accounts.json` → `identidade_corinthians.targeting_padrao`
  (São Paulo 80km, 18–65, brand_safety, individual_setting) — NÃO use "Brasil amplo". É o público
  idêntico ao da campanha que já roda.
- **`start_time` = sempre 04:01 (America/Sao_Paulo)** do dia do lançamento (começa a gastar de manhã).
  ⚠️ `start_time` NÃO pode ser editado depois de criado — se errar a data, recria o conjunto.
- **Ciclo de vida do cliente** ("Obter conversões de todos os públicos"): NÃO é setável via API
  (erro #3 capability); é o default. Se o Gerenciador pedir, o usuário seleciona em massa (1 clique).
- **Sempre ABO**: nunca ponha orçamento na campanha; o orçamento vai em cada conjunto.
- **1 conjunto por anúncio** (12 artes = 12 conjuntos com 1 anúncio cada).
- **Tudo nasce PAUSADO.** Nunca ligue anúncio sem o usuário mandar.
- **Pixel automático por produto** (accounts.json). Nunca use o pixel reserva "Corinthians" (id 27166631173027998).
- **UTM sempre** no criativo.
- Confirme os números com o usuário **antes** de rodar `create` (é dinheiro dele).

## Identidade / PARCERIA (IMPORTANTE — ler antes de prometer)
Os anúncios Corinthians são **"Anúncios em parceria" (partnership ads)** com DUAS identidades:
(1) SC Corinthians Paulista `132769576762243` / IG @corinthians `17841401449488648` +
(2) Corinthians Essencial `604611286073591` / IG @corinthiansessencial `17841473380708751`, com "identidade dinâmica".

> ⛔ **A parceria de duas identidades NÃO é criável via API com este app.** Confirmado (docs Meta +
> testes): criar anúncio em nome de conta IG que não é do anunciante (o @corinthians é do clube) exige
> **Acesso Avançado + `instagram_branded_content_ads_brand` + `instagram_basic` + `create_ads`**, que só
> saem via **App Review + verificação de negócio**. O campo é `branded_content:{partners:[{fb_page_id,ig_user_id}]}`
> e dá erro `#3 "does not have the capability"`. O "código de parceria"/allowlisting resolve só o
> consentimento do parceiro, NÃO a capacidade do app. `branded_content:{ad_format:3}` sozinho deixa a
> parceria DESLIGADA. Não perca tempo tentando ligar via API — a Meta bloqueia por design.

**Fluxo HÍBRIDO (é o que usamos):** a skill faz tudo (upload + copies + campanha/conjuntos/anúncios com
público/04:01/pixel/UTM/página do clube), e a **parceria é ligada na UI** duplicando um anúncio que já
roda (a parceria + 2 identidades vêm junto) e trocando a imagem/copy. Ou, se o usuário mandar, a skill
cria só com a identidade **Corinthians Essencial** (sem parceria), que funciona 100% via API.

Config/estrutura (page/IG/url_tags/targeting/start_time 04:01) está em `accounts.json` → `identidade_corinthians`.
Token: **pessoal do Leon** (`meta_ads_personal.json`, expira ~60d) posta como a página do clube; o
System User permanente (`meta_ads.json`) só posta como Corinthians Essencial.

Fatos que a API exige (já tratados no `meta.py`): campanha ABO precisa de `is_adset_budget_sharing_enabled=false`;
conjunto precisa de `bid_strategy` (usar `LOWEST_COST_WITHOUT_CAP`).

## Tokens
Dois tokens, ambos em `C:/Users/Leon/.claude/.secrets/` (fora do Git):

1. **`meta_ads.json`** — System User, **PERMANENTE** (não expira). App "Uploader Anuncios Collab" (publicado),
   BM Loja Collab. Só posta como Corinthians Essencial. Use pra tudo que não precisa da colaboração do clube.
2. **`meta_ads_personal.json`** — token PESSOAL do Leon, **EXPIRA**. Necessário pra criar com a colaboração do clube.

> ⚠️ **LEMBRETE DE VALIDADE (o usuário pediu pra eu avisar):** o token pessoal expira e vai parar de
> funcionar sem aviso. **SEMPRE que for usar a colaboração, rode primeiro `debug_token` e avise o usuário
> se faltar pouco:**
> ```
> curl -s "https://graph.facebook.com/v21.0/debug_token?input_token=$TP&access_token=$TP"
> ```
> (`$TP` = token pessoal). Se `expires_at` estiver perto/passado, PARE e peça pra regenerar antes de criar.
> Regenerar: Graph API Explorer → app **"Uploader Anuncios Collab"** (publicado, NUNCA "Expor Dados
> Gerenciador" que está em dev e dá erro 1885183) → **User Token** → permissões
> `ads_management pages_read_engagement pages_manage_ads business_management` → colar em `access_token`.
> Para durar ~60 dias: trocar por long-lived via `/oauth/access_token?grant_type=fb_exchange_token&client_id=<APP_ID>&client_secret=<SECRET>&fb_exchange_token=<TOKEN_CURTO>` (precisa do app secret).
>
> **Solução definitiva (sem token que expira):** o clube compartilhar a página SC Corinthians Paulista
> com a BM Loja Collab e atribuí-la ao System User `uploader-anuncios`. Aí o token permanente cria a colab.
