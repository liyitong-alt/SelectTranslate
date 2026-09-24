import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import select_translate


class DisplayPreferenceTests(unittest.TestCase):
    def test_high_frequency_chart_excludes_function_words_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = select_translate.WordStore(Path(directory) / "words.db")
            store.record_selection("the of and a in for i to as chocolate chocolate rocks")
            words = [row["word"] for row in store.top_words()]
            self.assertEqual(words, ["chocolate", "rocks"])
            self.assertEqual(store.stats(), (11, 12, 0))
            self.assertIn("the", [row["word"] for row in store.history()])

    def test_popup_font_buttons_save_selected_size(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            with patch.object(select_translate, "DATA_DIR", data_dir), patch.object(
                select_translate, "SETTINGS_FILE", data_dir / "settings.json"
            ):
                app = select_translate.App.__new__(select_translate.App)
                app.user_settings = select_translate.load_user_settings()
                app.popup_font_scale = 1.0
                app.font_decrease_button = MagicMock()
                app.font_increase_button = MagicMock()
                app._resize_at_anchor = MagicMock()
                app._change_popup_font_size(0.1)
                self.assertEqual(app.popup_font_scale, 1.1)
                self.assertEqual(select_translate.load_user_settings()["popup_font_scale"], "1.1")
                app._resize_at_anchor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
