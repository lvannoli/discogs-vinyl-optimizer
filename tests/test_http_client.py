from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.http_client import DiscogsClient, DiscogsMethodError


class DiscogsClientTests(unittest.TestCase):
    def test_discogs_client_rejects_non_get_methods(self):
        client = DiscogsClient()
        with self.assertRaises(DiscogsMethodError):
            client.request("POST", "/marketplace/listings")


if __name__ == "__main__":
    unittest.main()
