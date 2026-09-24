import queue
import unittest
from unittest.mock import patch

import select_translate


class SelectionCaptureTests(unittest.TestCase):
    def setUp(self):
        self.app = select_translate.App.__new__(select_translate.App)
        self.app.events = queue.Queue()

    @patch.object(select_translate, "get_window_class", return_value="Chrome_WidgetWin_1")
    @patch.object(select_translate, "capture_selection_uia")
    @patch.object(select_translate, "capture_selection")
    def test_browser_prefers_current_clipboard_selection(self, clipboard, uia, _window_class):
        clipboard.return_value = "For most organisms on Earth, rocks are objects, not food."
        self.app._capture_worker(123)
        self.assertEqual(self.app.events.get_nowait(), ("selection", clipboard.return_value))
        uia.assert_not_called()

    @patch.object(select_translate, "get_window_class", return_value="Chrome_WidgetWin_1")
    @patch.object(select_translate, "capture_selection_uia", return_value="Selected text")
    @patch.object(select_translate, "capture_selection", return_value="")
    def test_browser_uses_uia_only_when_copy_fails(self, clipboard, uia, _window_class):
        self.app._capture_worker(123)
        self.assertEqual(self.app.events.get_nowait(), ("selection", "Selected text"))
        clipboard.assert_called_once()
        uia.assert_called_once()


if __name__ == "__main__":
    unittest.main()
