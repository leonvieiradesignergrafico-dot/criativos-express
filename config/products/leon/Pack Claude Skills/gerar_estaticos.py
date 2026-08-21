# -*- coding: utf-8 -*-
"""
Gerador de estáticos — Pack Claude Skills.
3 ângulos validados (curiosidade / value-stack / FOMO), 1080x1350, dark premium,
destaque terracota do Claude. Texto renderizado por código (nítido em PT-BR).
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = r"D:\Desktop\Gestao de Trafego\Leon\criativos"
os.makedirs(OUT, exist_ok=True)
W, H = 1080, 1350

# paleta
BG0 = (24, 19, 16)       # topo (marrom-quase-preto quente)
BG1 = (12, 10, 9)        # base
INK = (245, 240, 234)    # texto claro
MUT = (170, 160, 150)    # texto secundário
ACC = (204, 120, 92)     # terracota Claude
ACC2 = (222, 160, 120)   # terracota claro
GOLD = (210, 170, 120)

F = r"C:\Windows\Fonts"
def font(name, size): return ImageFont.truetype(os.path.join(F, name), size)
BLACK = "arialbd.ttf"    # headline bold
REG   = "arial.ttf"
NARROW= "ARIALNB.TTF"    # condensada bold p/ números grandes

def vgrad(w, h, c0, c1):
    base = Image.new("RGB", (w, h), c0)
    top = Image.new("RGB", (w, h), c1)
    mask = Image.new("L", (w, h))
    md = mask.load()
    for y in range(h):
        v = int(255 * (y / h) ** 1.15)
        for x in range(w):
            md[x, y] = v
    base.paste(top, (0, 0), mask)
    return base

def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w_
    if cur: lines.append(cur)
    return lines

def draw_lines(draw, lines, fnt, x, y, fill, lh, spacing=0):
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += lh + spacing
    return y

def canvas():
    img = vgrad(W, H, BG0, BG1)
    d = ImageDraw.Draw(img)
    # brilho quente sutil no canto sup. esquerdo
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-300, -400, 700, 500], fill=(90, 45, 25))
    img = Image.blend(img, Image.composite(glow, img, Image.new("L", (W, H), 40)), 0.5)
    return img, ImageDraw.Draw(img)

def kicker(d, y=90):
    txt = "P A C K   C L A U D E   S K I L L S"
    f = font(BLACK, 26)
    d.text((90, y), txt, font=f, fill=ACC2)
    return y

def cta(d, y, label):
    f = font(BLACK, 38)
    tw = d.textlength(label, font=f)
    pad_x, h = 46, 92
    w = tw + pad_x * 2
    x0 = 90
    d.rounded_rectangle([x0, y, x0 + w, y + h], radius=h // 2, fill=ACC)
    d.text((x0 + pad_x, y + (h - 46) // 2), label, font=f, fill=(20, 14, 11))
    return y + h

def price_badge(d, x, y):
    fsmall = font(REG, 30); fbig = font(NARROW, 96); fcents = font(NARROW, 44)
    d.text((x, y), "de R$197 por apenas", font=fsmall, fill=MUT)
    # strike em 197
    sw = d.textlength("de R$197", font=fsmall)
    d.line([x + d.textlength("de ", font=fsmall), y + 18,
            x + sw, y + 18], fill=MUT, width=2)
    yy = y + 40
    d.text((x, yy), "R$", font=font(NARROW, 46), fill=ACC2)
    d.text((x + 66, yy - 24), "17", font=fbig, fill=INK)
    return yy

# ---------- Criativo 1 — Curiosidade (gancho campeão) ----------
def c1():
    img, d = canvas(); kicker(d)
    fh = font(BLACK, 88); y = 185
    d.text((88, y), "Eu fechei um", font=fh, fill=INK); y += 94
    d.text((88, y), "serviço de ", font=fh, fill=INK)
    xw = d.textlength("serviço de ", font=fh)
    d.text((88 + xw, y), "R$600", font=fh, fill=ACC2); y += 94
    d.text((88, y), "que eu nem", font=fh, fill=INK); y += 94
    d.text((88, y), "sei fazer.", font=fh, fill=INK); y += 94
    y += 18
    fb = font(REG, 40)
    sub = "Uma skill do Claude fez o trabalho todo por mim — sem eu saber do assunto."
    y = draw_lines(d, wrap(d, sub, fb, W - 180), fb, 90, y, MUT, 50)
    y += 24
    card = [90, y, W - 90, y + 150]
    d.rounded_rectangle(card, radius=24, fill=(34, 27, 22))
    d.ellipse([116, y + 58, 150, y + 92], fill=ACC)
    d.text((170, y + 40), "serviço: página de vendas", font=font(REG, 34), fill=INK)
    cx, cy = 176, y + 106
    d.line([(cx - 9, cy), (cx - 2, cy + 8), (cx + 13, cy - 11)], fill=ACC2, width=5, joint="curve")
    d.text((205, y + 88), "entregue — cobrei R$600", font=font(REG, 30), fill=ACC2)
    y += 190
    price_badge(d, 90, y)
    cta(d, H - 220, "Quero faturar com IA  →")
    img.save(os.path.join(OUT, "static_01_prova.png"), quality=95)

# ---------- Criativo 2 — Value stack (12 skills x preço de mercado) ----------
def c2():
    img, d = canvas(); kicker(d)
    fh = font(BLACK, 82); y = 175
    for ln, col in [("12 Skills do Claude", INK), ("que o mercado cobra", INK), ("R$500 a R$5.000", ACC2)]:
        d.text((88, y), ln, font=fh, fill=col); y += 88
    y += 20
    skills = [("App / ferramenta completa", "R$5.000"),
              ("Página de vendas publicada", "R$2.000"),
              ("Identidade de marca", "R$2.000"),
              ("Anúncios de alta conversão", "R$800"),
              ("Dashboard profissional", "R$1.000")]
    fn = font(REG, 36); fp = font(BLACK, 36)
    for name, price in skills:
        d.rounded_rectangle([90, y, W - 90, y + 84], radius=18, fill=(32, 25, 21))
        d.text((120, y + 24), name, font=fn, fill=INK)
        pw = d.textlength(price, font=fp)
        d.text((W - 120 - pw, y + 22), price, font=fp, fill=ACC2)
        y += 98
    d.text((120, y + 4), "+ 7 outras skills e 8 bônus", font=font(REG, 32), fill=MUT)
    y += 70
    fbig = font(NARROW, 60)
    d.text((90, y), "Tudo isso por ", font=font(REG, 44), fill=INK)
    tw = d.textlength("Tudo isso por ", font=font(REG, 44))
    d.text((90 + tw, y - 14), "R$17", font=fbig, fill=ACC2)
    cta(d, H - 210, "Quero as 12 skills  →")
    img.save(os.path.join(OUT, "static_02_valuestack.png"), quality=95)

# ---------- Criativo 3 — FOMO / dor ----------
def c3():
    img, d = canvas(); kicker(d)
    fh = font(BLACK, 84); y = 195
    for ln, col in [("Se você sabe", INK), ("arrastar um", INK), ("arquivo, você", INK), ("sabe faturar", INK), ("com IA", ACC2)]:
        d.text((88, y), ln, font=fh, fill=col); y += 90
    y += 18
    fb = font(REG, 40)
    sub = "Baixa a skill, arrasta no Claude e ela faz o serviço inteiro. Sem programar."
    y = draw_lines(d, wrap(d, sub, fb, W - 180), fb, 90, y, MUT, 52)
    y += 34
    py = price_badge(d, 90, y)
    cta(d, py + 165, "Começar por R$17  →")
    img.save(os.path.join(OUT, "static_03_facilidade.png"), quality=95)

def c4():
    img, d = canvas(); kicker(d)
    fh = font(BLACK, 76); y = 180
    d.text((88, y), "As 3 formas de", font=fh, fill=INK); y += 82
    d.text((88, y), "lucrar com IA", font=fh, fill=INK); y += 108
    rows = [("3º", "GPT", "generalista, pra amador", MUT, (30, 24, 20)),
            ("2º", "Claude", "forte, mas pra quem é dev", INK, (34, 27, 22)),
            ("1º", "Skills do Claude", "faz o serviço inteiro por você", ACC2, (48, 33, 25))]
    fn = font(BLACK, 42); fpos = font(BLACK, 40); fsub = font(REG, 30)
    for pos, name, desc, col, bg in rows:
        h = 132
        d.rounded_rectangle([90, y, W - 90, y + h], radius=20, fill=bg)
        d.text((116, y + 44), pos, font=fpos, fill=col)
        d.text((210, y + 30), name, font=fn, fill=col)
        d.text((210, y + 86), desc, font=fsub, fill=MUT)
        y += h + 18
    y += 16
    d.text((90, y), "As 12 skills por ", font=font(REG, 40), fill=INK)
    tw = d.textlength("As 12 skills por ", font=font(REG, 40))
    d.text((90 + tw, y - 14), "R$17", font=font(NARROW, 58), fill=ACC2)
    cta(d, H - 200, "Quero as skills  →")
    img.save(os.path.join(OUT, "static_04_ranking.png"), quality=95)

# limpa versões antigas e regenera
for _f in os.listdir(OUT):
    if _f.startswith("static_") and _f.endswith(".png"):
        os.remove(os.path.join(OUT, _f))
c1(); c2(); c3(); c4()
print("OK ->", OUT)
for f_ in sorted(os.listdir(OUT)):
    print(" -", f_)
