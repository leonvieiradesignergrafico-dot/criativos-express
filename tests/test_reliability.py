import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import gerar
import workspace


class ReliabilityTests(unittest.TestCase):
    def test_paths_reject_traversal(self):
        with self.assertRaises(ValueError):
            workspace.product_dir("../segredo")
        with self.assertRaises(ValueError):
            workspace.safe_child(Path(tempfile.gettempdir()), "../segredo.txt")

    def test_atomic_json_is_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "status.json"
            workspace.atomic_write_json(path, {"ok": True, "n": 1})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["n"], 1)

    def test_same_product_job_lock_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            products = Path(d) / "products"
            (products / "x").mkdir(parents=True)
            with patch.object(workspace, "PRODUCTS", products):
                lock = workspace.JobManager().lock("x")
                self.assertTrue(lock.acquire(False))
                try:
                    self.assertFalse(lock.acquire(False))
                finally:
                    lock.release()

    def test_generation_uses_pending_policy_and_isolated_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            products = root / "products"
            gerados = root / "gerados"
            for name in ("a", "b"):
                p = products / name
                (p / "referencia").mkdir(parents=True)
                (p / "output").mkdir(parents=True)
                (p / "referencia" / "produto.png").write_bytes(b"png")
                (p / "output" / "prompts.json").write_text(
                    json.dumps([{"id": "criativo_01", "prompt": name}]), encoding="utf-8")

            def fake_builder(*args, **kwargs):
                def fake(prompt, output, **_):
                    Path(output).write_bytes(prompt.encode())
                return fake

            # Novo layout: imagens vão para gerados/<cliente|_sem-cliente>/<produto>/<dia>/,
            # e o estado de trabalho (status.json) fica em <produto>/output/.
            with patch.object(workspace, "PRODUCTS", products), \
                 patch.object(workspace, "GERADOS_DIR", gerados), \
                 patch.object(gerar, "_montar_gerar_um", fake_builder):
                results = {}
                threads = [threading.Thread(target=lambda n=n: results.setdefault(
                    n, gerar.gerar_criativos(n, backend="api")), args=()) for n in ("a", "b")]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.assertEqual(results["a"]["arquivos"], ["criativo_01.png"])
                self.assertEqual(results["b"]["arquivos"], ["criativo_01.png"])
                self.assertNotEqual(
                    (workspace.criativos_dir("a") / "criativo_01.png").read_bytes(),
                    (workspace.criativos_dir("b") / "criativo_01.png").read_bytes())
                # As imagens caíram no bucket _sem-cliente do novo layout.
                self.assertTrue(
                    (gerados / "_sem-cliente" / "a").exists())

                # A segunda rodada padrão não sobrescreve o original.
                again = gerar.gerar_criativos("a", backend="api")
                self.assertEqual(again["total"], 0)


if __name__ == "__main__":
    unittest.main()
