from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.input_parser import albums_from_chat_text


class InputParserTests(unittest.TestCase):
    def test_parse_pasted_album_lines(self):
        albums = albums_from_chat_text("Miles Davis - Kind of Blue\nThe Beatles - Help!")
        self.assertEqual(albums[0].artist, "Miles Davis")
        self.assertEqual(albums[0].album, "Kind of Blue")
        self.assertEqual(albums[1].artist, "The Beatles")
        self.assertEqual(albums[1].album, "Help!")

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


if __name__ == "__main__":
    unittest.main()
