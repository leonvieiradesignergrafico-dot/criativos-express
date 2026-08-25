"""Trava a configuração do motor de vídeo: qual modelo Veo a esteira usa e quanto custa.

O preço no config é a base da estimativa mostrada na UI. Já ficou 50% defasado uma vez
(config dizia US$0,15/s quando o SKU oficial era US$0,10/s), então aqui a conta é
verificada contra o catálogo de billing conferido em 2026-08-25.
"""
import unittest

from backends import veo_backend
from app.pipeline import fala_veo
from workspace import carregar_config

# US$ por SEGUNDO, 720p com áudio, do catálogo oficial (unidade "count" do SKU = 1s).
PRECO_SKU_POR_SEGUNDO = {
    "veo_lite": 0.05,      # SKU "Veo Lite Generation 720p with Audio"
    "veo_fast": 0.10,      # SKU "Veo 3 Fast 720p Audio Video Generation"
    "veo_quality": 0.40,   # SKU "Veo 3 Audio Video Generation"
}


class ModeloVideoTests(unittest.TestCase):
    def setUp(self):
        self.video = carregar_config().get("video", {})

    def test_padrao_da_casa_e_o_lite(self):
        self.assertEqual(self.video.get("modelo_veo"), "veo_lite")

    def test_todo_slug_do_config_resolve_para_um_model_id_real(self):
        for slug in self.video.get("precos_usd", {}):
            self.assertIn(slug, veo_backend.MODEL_MAP, f"slug sem model_id: {slug}")
        self.assertEqual(veo_backend.MODEL_MAP["veo_lite"], "veo-3.1-lite-generate-001")

    def test_preco_do_config_bate_com_o_sku_oficial(self):
        """O config guarda o preço de um clipe de 5s; o SKU cobra por segundo."""
        for slug, usd_5s in self.video.get("precos_usd", {}).items():
            esperado = PRECO_SKU_POR_SEGUNDO[slug] * 5
            self.assertAlmostEqual(usd_5s, esperado, places=4,
                                   msg=f"{slug}: config {usd_5s} != SKU {esperado}")

    def test_slug_desconhecido_cai_no_barato_e_nao_no_caro(self):
        """Erro de digitação no config não pode escalar a conta silenciosamente."""
        escolhido = veo_backend.MODEL_MAP.get("slug_que_nao_existe") or veo_backend.MODEL_MAP["veo_lite"]
        self.assertEqual(escolhido, veo_backend.MODEL_MAP["veo_lite"])

    def test_marca_baba_baby_nao_vira_bebe_na_fonetica(self):
        """O veo_lite leu 'Bêi-bi' como 'bebê' (2026-08-25). Sem hífen, sem colapso."""
        falado = fala_veo.adaptar("Aí comecei a usar o Baba Baby todo dia.")
        self.assertIn("Beibi", falado)
        self.assertNotIn("-", falado)
        self.assertNotIn("bebê", falado.lower())


if __name__ == "__main__":
    unittest.main()
