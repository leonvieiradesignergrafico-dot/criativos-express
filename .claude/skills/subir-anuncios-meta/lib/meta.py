#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper Graph API para a skill subir-anuncios-meta.
Sem dependencias externas (so stdlib). Le o token de C:/Users/Leon/.claude/.secrets/meta_ads.json.

Uso:
  python meta.py upload <account_id> <arquivo1> [arquivo2 ...]
      -> sobe imagens para a biblioteca e imprime JSON { "nome_arquivo": "image_hash", ... }

  python meta.py create <plan.json>
      -> cria 1 campanha (ABO) + 1 conjunto por anuncio + 1 anuncio por conjunto (TUDO PAUSADO)
         e imprime o resumo com os IDs criados.

  python meta.py check <account_id>
      -> testa o token e mostra dados basicos da conta (sanity check).

Formato do plan.json: ver SKILL.md (secao "Formato do plan.json").
"""
import json
import sys
import os
import mimetypes
import urllib.request
import urllib.parse
import uuid

TOKEN_PATH = os.environ.get("META_TOKEN_PATH", "C:/Users/Leon/.claude/.secrets/meta_ads.json")
GRAPH = "https://graph.facebook.com"


def load_token():
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    tok = data.get("access_token")
    if not tok:
        raise SystemExit("Token nao encontrado em " + TOKEN_PATH)
    return tok, data.get("graph_version", "v21.0")


def act(account_id):
    account_id = str(account_id)
    return account_id if account_id.startswith("act_") else "act_" + account_id


def api_post(path, params, token, version):
    url = "{}/{}/{}".format(GRAPH, version, path)
    params = dict(params)
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit("ERRO Graph API em POST {}:\n{}".format(path, body))


def api_get(path, token, version, fields=None):
    url = "{}/{}/{}".format(GRAPH, version, path)
    q = {"access_token": token}
    if fields:
        q["fields"] = fields
    url = url + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit("ERRO Graph API em GET {}:\n{}".format(path, body))


def upload_image(account_id, filepath, token, version):
    """Upload multipart de uma imagem para /adimages. Retorna o hash."""
    url = "{}/{}/{}/adimages".format(GRAPH, version, act(account_id))
    boundary = "----metaupload" + uuid.uuid4().hex
    fname = os.path.basename(filepath)
    ctype = mimetypes.guess_type(fname)[0] or "image/png"
    with open(filepath, "rb") as f:
        filedata = f.read()
    parts = []
    # campo access_token
    parts.append(("--" + boundary).encode())
    parts.append(b'Content-Disposition: form-data; name="access_token"')
    parts.append(b"")
    parts.append(token.encode())
    # campo arquivo (a Meta usa o nome do campo como key/nome da imagem)
    parts.append(("--" + boundary).encode())
    parts.append('Content-Disposition: form-data; name="{}"; filename="{}"'.format(fname, fname).encode())
    parts.append("Content-Type: {}".format(ctype).encode())
    parts.append(b"")
    body = b"\r\n".join(parts) + b"\r\n" + filedata + b"\r\n" + ("--" + boundary + "--\r\n").encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        with urllib.request.urlopen(req) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        raise SystemExit("ERRO upload {}:\n{}".format(fname, b))
    imgs = out.get("images", {})
    # a chave pode vir com ou sem extensao
    for k, v in imgs.items():
        return v["hash"]
    raise SystemExit("Upload sem hash para " + fname + ": " + json.dumps(out))


def cmd_upload(args):
    token, version = load_token()
    account_id = args[0]
    files = args[1:]
    result = {}
    for fp in files:
        h = upload_image(account_id, fp, token, version)
        result[os.path.basename(fp)] = h
        sys.stderr.write("  ok  {} -> {}\n".format(os.path.basename(fp), h))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_check(args):
    token, version = load_token()
    account_id = args[0]
    info = api_get(act(account_id), token, version,
                   fields="name,currency,min_daily_budget,timezone_name,account_status")
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_create(args):
    token, version = load_token()
    with open(args[0], "r", encoding="utf-8") as f:
        plan = json.load(f)

    account_id = plan["account_id"]
    page_id = plan["page_id"]
    ig_id = plan.get("instagram_user_id")
    pixel_id = plan["pixel_id"]
    d = plan["defaults"]
    camp = plan["campaign"]

    results = {"campaign": None, "adsets": [], "creatives": [], "ads": [], "errors": []}

    # Formato AGRUPADO (varios anuncios por conjunto): plan["adsets"] = [{name, ads:[...]}]
    # Cada conjunto ganha 1 orcamento (ABO) e leva N anuncios dentro. Se "adsets" nao existir,
    # cai no formato classico (1 conjunto por anuncio via plan["ads"]).
    if plan.get("adsets"):
        # campaign.id preenchido = ANEXAR os conjuntos a uma campanha que JA existe
        # (lateralizacao entrando numa campanha que ja roda). Sem id, cria campanha nova.
        if camp.get("id"):
            campaign_id = str(camp["id"])
            existente = api_get(campaign_id, token, version, fields="id,name,objective")
            results["campaign"] = {"id": campaign_id, "name": existente.get("name"), "reusada": True}
            sys.stderr.write("Campanha REUSADA: {} ({})\n".format(campaign_id, existente.get("name")))
        else:
            camp_params = {
                "name": camp["name"],
                "objective": camp.get("objective", "OUTCOME_SALES"),
                "buying_type": "AUCTION",
                "special_ad_categories": json.dumps(camp.get("special_ad_categories", [])),
                "is_adset_budget_sharing_enabled": "false",
                "status": "PAUSED",
            }
            camp_res = api_post(act(account_id) + "/campaigns", camp_params, token, version)
            campaign_id = camp_res["id"]
            results["campaign"] = {"id": campaign_id, "name": camp["name"]}
            sys.stderr.write("Campanha criada: {} ({})\n".format(campaign_id, camp["name"]))

        promoted_object = json.dumps({"pixel_id": pixel_id, "custom_event_type": d.get("custom_event_type", "PURCHASE")})
        targeting = json.dumps(d["targeting"])
        attribution = json.dumps(d.get("attribution_spec", []))

        for gi, grp in enumerate(plan["adsets"], start=1):
            adset_params = {
                "name": grp["name"],
                "campaign_id": campaign_id,
                "daily_budget": str(d["daily_budget_cents"]),
                "billing_event": d.get("billing_event", "IMPRESSIONS"),
                "optimization_goal": d.get("optimization_goal", "OFFSITE_CONVERSIONS"),
                "bid_strategy": d.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
                "promoted_object": promoted_object,
                "targeting": targeting,
                "status": "PAUSED",
            }
            if attribution and attribution != "[]":
                adset_params["attribution_spec"] = attribution
            if d.get("start_time"):
                adset_params["start_time"] = d["start_time"]
            if d.get("marketing_goal"):
                adset_params["marketing_goal"] = d["marketing_goal"]
            adset_res = api_post(act(account_id) + "/adsets", adset_params, token, version)
            adset_id = adset_res["id"]
            results["adsets"].append({"id": adset_id, "name": grp["name"]})
            sys.stderr.write("Conjunto {:>2}: {} ({} anuncios)\n".format(gi, adset_id, len(grp["ads"])))

            for adx in grp["ads"]:
                name = adx["name"]
                link_data = {
                    "link": d["link"],
                    "image_hash": adx["image_hash"],
                    "message": adx.get("message", ""),
                    "name": adx.get("headline", ""),
                    "description": adx.get("description", ""),
                    "call_to_action": {"type": d.get("cta", "LEARN_MORE"), "value": {"link": d["link"]}},
                }
                story_spec = {"page_id": page_id, "link_data": link_data}
                if ig_id:
                    story_spec["instagram_user_id"] = ig_id
                creative_params = {
                    "name": "creative-" + name,
                    "object_story_spec": json.dumps(story_spec, ensure_ascii=False),
                }
                if d.get("url_tags"):
                    creative_params["url_tags"] = d["url_tags"]
                if d.get("branded_content"):
                    creative_params["branded_content"] = json.dumps(d["branded_content"])
                if d.get("contextual_multi_ads"):
                    creative_params["contextual_multi_ads"] = json.dumps(d["contextual_multi_ads"])
                cre_res = api_post(act(account_id) + "/adcreatives", creative_params, token, version)
                creative_id = cre_res["id"]
                results["creatives"].append({"id": creative_id})

                ad_params = {
                    "name": name,
                    "adset_id": adset_id,
                    "creative": json.dumps({"creative_id": creative_id}),
                    "status": "PAUSED",
                }
                ad_res = api_post(act(account_id) + "/ads", ad_params, token, version)
                results["ads"].append({"id": ad_res["id"], "name": name, "adset_id": adset_id})
                sys.stderr.write("    ad {} ({})\n".format(ad_res["id"], name))

        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    # 1) Campanha (ABO = SEM orcamento na campanha)
    camp_params = {
        "name": camp["name"],
        "objective": camp.get("objective", "OUTCOME_SALES"),
        "buying_type": "AUCTION",
        "special_ad_categories": json.dumps(camp.get("special_ad_categories", [])),
        # ABO puro: sem orçamento na campanha e sem compartilhamento entre conjuntos.
        "is_adset_budget_sharing_enabled": "false",
        "status": "PAUSED",
    }
    camp_res = api_post(act(account_id) + "/campaigns", camp_params, token, version)
    campaign_id = camp_res["id"]
    results["campaign"] = {"id": campaign_id, "name": camp["name"]}
    sys.stderr.write("Campanha criada: {} ({})\n".format(campaign_id, camp["name"]))

    promoted_object = json.dumps({"pixel_id": pixel_id, "custom_event_type": d.get("custom_event_type", "PURCHASE")})
    targeting = json.dumps(d["targeting"])
    attribution = json.dumps(d.get("attribution_spec", []))

    for i, adx in enumerate(plan["ads"], start=1):
        name = adx["name"]
        # 2) Conjunto (ABO: orcamento no conjunto)
        adset_params = {
            "name": adx.get("adset_name", name),
            "campaign_id": campaign_id,
            "daily_budget": str(d["daily_budget_cents"]),
            "billing_event": d.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": d.get("optimization_goal", "OFFSITE_CONVERSIONS"),
            "bid_strategy": d.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
            "promoted_object": promoted_object,
            "targeting": targeting,
            "status": "PAUSED",
        }
        if attribution and attribution != "[]":
            adset_params["attribution_spec"] = attribution
        if d.get("start_time"):
            adset_params["start_time"] = d["start_time"]
        if d.get("marketing_goal"):
            adset_params["marketing_goal"] = d["marketing_goal"]
        adset_res = api_post(act(account_id) + "/adsets", adset_params, token, version)
        adset_id = adset_res["id"]
        results["adsets"].append({"id": adset_id, "name": adset_params["name"]})

        # 3) Criativo
        link_data = {
            "link": d["link"],
            "image_hash": adx["image_hash"],
            "message": adx.get("message", ""),
            "name": adx.get("headline", ""),
            "description": adx.get("description", ""),
            "call_to_action": {"type": d.get("cta", "LEARN_MORE"), "value": {"link": d["link"]}},
        }
        story_spec = {"page_id": page_id, "link_data": link_data}
        if ig_id:
            story_spec["instagram_user_id"] = ig_id
        creative_params = {
            "name": "creative-" + name,
            "object_story_spec": json.dumps(story_spec, ensure_ascii=False),
        }
        if d.get("url_tags"):
            creative_params["url_tags"] = d["url_tags"]
        if d.get("branded_content"):
            creative_params["branded_content"] = json.dumps(d["branded_content"])
        if d.get("contextual_multi_ads"):
            creative_params["contextual_multi_ads"] = json.dumps(d["contextual_multi_ads"])
        cre_res = api_post(act(account_id) + "/adcreatives", creative_params, token, version)
        creative_id = cre_res["id"]
        results["creatives"].append({"id": creative_id})

        # 4) Anuncio
        ad_params = {
            "name": name,
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": "PAUSED",
        }
        ad_res = api_post(act(account_id) + "/ads", ad_params, token, version)
        results["ads"].append({"id": ad_res["id"], "name": name, "adset_id": adset_id})
        sys.stderr.write("  ad {:>2}: conjunto {} + anuncio {} ({})\n".format(i, adset_id, ad_res["id"], name))

    print(json.dumps(results, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "upload":
        cmd_upload(args)
    elif cmd == "create":
        cmd_create(args)
    elif cmd == "check":
        cmd_check(args)
    else:
        raise SystemExit("Comando desconhecido: " + cmd + "\n" + __doc__)


if __name__ == "__main__":
    main()
