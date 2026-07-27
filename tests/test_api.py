import sys
import os
import unittest
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from app.main import app

class TestPQRSDAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_catalogos(self):
        response = self.client.get("/api/v1/pqrsd/catalogos")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("tipos_correspondencia", data)
        self.assertIn("dependencias_areas", data)

    def test_consultar_pqrsd_invalid(self):
        payload = {
            "radicado": "0000000000",
            "codigo_autenticacion": "0000"
        }
        response = self.client.post("/api/v1/pqrsd/consultar", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["found"])
        self.assertIn("No se encontró", data["message"])

if __name__ == "__main__":
    unittest.main()
