from pathlib import Path
import sys
import unittest
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discogs_vinyl_optimizer.emailer import (
    EmailError,
    EmailSettings,
    build_results_message,
    load_email_settings,
    write_results_email_draft,
)


class EmailerTests(unittest.TestCase):
    def test_load_email_settings_requires_host_and_sender(self):
        with self.assertRaises(EmailError) as context:
            load_email_settings({})

        message = str(context.exception)
        self.assertIn("SMTP_HOST", message)
        self.assertIn("SMTP_FROM", message)

    def test_build_results_message_attaches_files(self):
        root = Path(__file__).resolve().parent / f"tmp_emailer_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            purchase_options = root / "purchase_options.json"
            offers = root / "offers_scraped.csv"
            purchase_options.write_text("[]", encoding="utf-8")
            offers.write_text("artist,album\n", encoding="utf-8")

            message = build_results_message(
                recipient="buyer@example.com",
                attachments=[purchase_options, offers],
                run_name="shortcut_test",
                settings=EmailSettings(
                    host="smtp.example.com",
                    port=587,
                    sender="sender@example.com",
                ),
            )

            filenames = [part.get_filename() for part in message.iter_attachments()]
            self.assertEqual(filenames, ["purchase_options.json", "offers_scraped.csv"])
            self.assertEqual(message["To"], "buyer@example.com")
            self.assertIn("shortcut_test", message["Subject"])
        finally:
            for path in root.glob("*"):
                try:
                    path.unlink()
                except PermissionError:
                    pass
            try:
                root.rmdir()
            except OSError:
                pass

    def test_write_results_email_draft(self):
        root = Path(__file__).resolve().parent / f"tmp_emailer_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            purchase_options = root / "purchase_options.json"
            offers = root / "offers_scraped.csv"
            purchase_options.write_text("[]", encoding="utf-8")
            offers.write_text("artist,album\n", encoding="utf-8")

            draft = write_results_email_draft(
                recipient="buyer@example.com",
                attachments=[purchase_options, offers],
                run_dir=root,
            )

            self.assertEqual(draft.name, "discogs_results_email.eml")
            content = draft.read_text(encoding="utf-8")
            self.assertIn("buyer@example.com", content)
            self.assertIn("purchase_options.json", content)
            self.assertIn("offers_scraped.csv", content)
        finally:
            for path in root.glob("*"):
                try:
                    path.unlink()
                except PermissionError:
                    pass
            try:
                root.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
