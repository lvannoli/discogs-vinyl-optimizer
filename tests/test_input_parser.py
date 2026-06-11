from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.input_parser import albums_from_chat_text, known_album_correction
from discogs_vinyl_optimizer.models import AlbumRequest


class InputParserTests(unittest.TestCase):
    def test_parse_pasted_album_lines(self):
        albums = albums_from_chat_text("Miles Davis - Kind of Blue\nThe Beatles - Help!")
        self.assertEqual(albums[0].artist, "Miles Davis")
        self.assertEqual(albums[0].album, "Kind of Blue")
        self.assertEqual(albums[1].artist, "The Beatles")
        self.assertEqual(albums[1].album, "Help!")

    def test_parse_pasted_album_lines_with_heading(self):
        albums = albums_from_chat_text("Records\nMiles Davis - Kind of Blue\nThe Beatles - Help!")
        self.assertEqual([album.display for album in albums], ["Miles Davis - Kind of Blue", "The Beatles - Help!"])

    def test_parse_chat_csv(self):
        albums = albums_from_chat_text("artist,album\nGenesis,Nursery Cryme")
        self.assertEqual(albums[0].artist, "Genesis")
        self.assertEqual(albums[0].album, "Nursery Cryme")

    def test_apply_known_discogs_title_corrections(self):
        albums = albums_from_chat_text("Dave Brubeck - Time Out\nThe Beatles - sgt. peppers")
        self.assertEqual(albums[0].artist, "The Dave Brubeck Quartet")
        self.assertEqual(albums[0].album, "Time Out")
        self.assertEqual(albums[1].artist, "The Beatles")
        self.assertEqual(albums[1].album, "Sgt. Pepper's Lonely Hearts Club Band")

    def test_can_parse_without_applying_known_corrections(self):
        albums = albums_from_chat_text("The Beatles - sgt. peppers", apply_corrections=False)
        self.assertEqual(albums[0].artist, "The Beatles")
        self.assertEqual(albums[0].album, "sgt. peppers")

    def test_known_album_correction_returns_suggestion(self):
        correction = known_album_correction(AlbumRequest("Genesis", "Nursery Crime"))
        self.assertIsNotNone(correction)
        self.assertEqual(correction.artist, "Genesis")
        self.assertEqual(correction.album, "Nursery Cryme")

    def test_known_album_correction_adds_the_to_artist(self):
        correction = known_album_correction(AlbumRequest("Beatles", "revolver"))
        self.assertIsNotNone(correction)
        self.assertEqual(correction.artist, "The Beatles")
        self.assertEqual(correction.album, "Revolver")

    def test_known_album_correction_strips_trailing_year_annotation(self):
        correction = known_album_correction(AlbumRequest("Fabrizio De André", "Volume 1 (1967)"))
        self.assertIsNotNone(correction)
        self.assertEqual(correction.artist, "Fabrizio De André")
        self.assertEqual(correction.album, "Volume 1")


if __name__ == "__main__":
    unittest.main()
