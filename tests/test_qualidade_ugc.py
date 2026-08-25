import unittest
from pathlib import Path

from app.pipeline import fala_veo, qualidade


class QualidadeUGCTests(unittest.TestCase):
    def test_selfie_proibe_o_mesmo_celular_no_quadro(self):
        g = qualidade.contrato_cena({"tipo": "avatar_fala", "prompt_keyframe": "selfie falando"})
        self.assertEqual(g["perspectiva"], "camera_frontal")
        self.assertEqual(g["celular_visivel"], "proibido")

    def test_celular_pode_aparecer_quando_a_tela_e_demonstrada(self):
        g = qualidade.contrato_cena({
            "tipo": "avatar_aponta_tela", "prompt_keyframe": "mostra a tela do celular para a câmera"})
        self.assertEqual(g["celular_visivel"], "obrigatorio")

    def test_comparacao_de_voz_e_conservadora(self):
        ref = {"pitch_hz": 180.0, "centroide_hz": 1500.0}
        self.assertIsNone(qualidade.comparar_voz(
            {"pitch_hz": 205.0, "centroide_hz": 1700.0}, ref))
        self.assertEqual(qualidade.comparar_voz(
            {"pitch_hz": 90.0, "centroide_hz": 800.0}, ref)["codigo"], "voz_inconsistente")

    def test_pronuncia_da_marca_baba_baby_nao_e_portugues_literal(self):
        self.assertEqual(fala_veo.adaptar("Esse é o Baba Baby."),
                         "O creme redutor que eu comecei a usar.")

    def test_fala_embolada_ou_cortada_e_reprovada(self):
        self.assertIsNotNone(qualidade.comparar_fala(
            "mais um creme sentir barriga", "Eu achei que fosse só mais um creme até sentir na barriga"))
        self.assertIsNone(qualidade.comparar_fala(
            "Eu achei que fosse só mais um creme até sentir na barriga",
            "Eu achei que fosse só mais um creme até sentir na barriga"))

    def test_corte_sugerido_remove_palavras_fantasmas(self):
        detalhe = {"words": [
            {"word": "e", "start": 0.0, "end": 0.14, "probability": .9},
            {"word": "a", "start": .14, "end": .30, "probability": .9},
            {"word": "gente", "start": .30, "end": .44, "probability": .8},
            {"word": "esse", "start": .44, "end": 1.32, "probability": .95},
            {"word": "é", "start": 1.32, "end": 1.92, "probability": .99},
            {"word": "o", "start": 1.92, "end": 2.08, "probability": .99},
            {"word": "creme", "start": 2.08, "end": 2.60, "probability": .99},
        ]}
        s = qualidade.sugerir_corte_por_fala(detalhe, "Esse é o creme", 3.0)
        self.assertGreaterEqual(s["inicio_s"], .35)
        self.assertEqual(s["extras_inicio"], ["e", "a", "gente"])

    def test_fim_manual_nunca_corta_palavra_ao_meio(self):
        detalhe = {"words": [{"word": "barriga", "start": 5.06, "end": 5.66}]}
        fim, palavra = qualidade.proteger_fim_de_palavra(5.41, detalhe)
        self.assertEqual(fim, 5.76)
        self.assertEqual(palavra, "barriga")

    def test_numero_falado_por_extenso_nao_reprova_clipe_pago(self):
        """O whisper transcreve DÍGITO ("7"), o roteiro falado vai por extenso ("sete").
        Antes isso reprovava a 96% de similaridade e queimava 3 clipes pagos por cena."""
        roteiro = "Existem 7 orações para restaurar o casamento, uma por dia."
        self.assertIsNone(qualidade.comparar_fala(roteiro, fala_veo.adaptar(roteiro)))
        pct = "70% viram a celulite menos marcada."
        self.assertIsNone(qualidade.comparar_fala(pct, fala_veo.adaptar(pct)))

    def test_audio_realmente_embolado_continua_reprovando(self):
        self.assertIsNotNone(qualidade.comparar_fala(
            "Os kits estão aqui embaixo, ou? E sem essa peima contra a salentinha, eu vou achar os 3.",
            fala_veo.adaptar("Os kits estão aqui embaixo, corre que a promoção acaba hoje.")))

    def test_regeneracao_identica_e_detectada_para_nao_pagar_de_novo(self):
        fala = "Existem sete orações para restaurar o casamento."
        self.assertTrue(qualidade.fala_equivalente(fala, fala))
        self.assertFalse(qualidade.fala_equivalente(fala, "A pele ficou mais firme em trinta dias."))

    def test_clipe_para_de_regenerar_quando_a_fala_repete(self):
        fonte = (Path(__file__).parents[1] / "app" / "pipeline" / "clipes.py").read_text(encoding="utf-8")
        self.assertIn("fala_equivalente", fonte)
        self.assertIn("regeneracao_sem_efeito", fonte)

    def test_montagem_nao_congela_ultimo_frame_e_preserva_bruto(self):
        fonte = (Path(__file__).parents[1] / "app" / "pipeline" / "montagem.py").read_text(encoding="utf-8")
        self.assertNotIn("stop_mode=clone", fonte)
        self.assertIn("video-bruto.mp4", fonte)
        self.assertIn("video-ajustado.mp4", fonte)


if __name__ == "__main__":
    unittest.main()
