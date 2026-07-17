import unittest

from side_translate.baidu import BaiduClient
from side_translate.config import AppConfig, protect, unprotect
from side_translate.windows import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    HotkeyError,
    is_selection_drag,
    parse_hotkey,
)


class BaiduSigningTests(unittest.TestCase):
    def test_sign_matches_baidu_example_algorithm(self):
        value = BaiduClient.make_sign("2015063000000001", "apple", "1435660288", "12345678")
        self.assertEqual(value, "f89f9594663708c1605f3d736d01d2d4")


class HotkeyParsingTests(unittest.TestCase):
    def test_common_shortcut(self):
        modifiers, key = parse_hotkey("Ctrl+Alt+T")
        self.assertEqual(modifiers, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
        self.assertEqual(key, ord("T"))

    def test_function_key(self):
        _, key = parse_hotkey("Ctrl+F12")
        self.assertEqual(key, 0x7B)

    def test_modifier_is_required(self):
        with self.assertRaises(HotkeyError):
            parse_hotkey("T")


class ConfigurationProtectionTests(unittest.TestCase):
    def test_dpapi_round_trip(self):
        encrypted = protect("test-secret")
        self.assertTrue(encrypted.startswith("dpapi:"))
        self.assertEqual(unprotect(encrypted), "test-secret")

    def test_auto_selection_toggle_hotkey_default(self):
        self.assertEqual(AppConfig().auto_selection_hotkey, "Ctrl+Alt+A")


class MouseSelectionTests(unittest.TestCase):
    def test_drag_over_threshold_is_selection(self):
        self.assertTrue(is_selection_drag((10, 10), (30, 10), 0.2))

    def test_click_jitter_is_not_selection(self):
        self.assertFalse(is_selection_drag((10, 10), (13, 12), 0.2))

    def test_fast_gesture_is_not_selection(self):
        self.assertFalse(is_selection_drag((10, 10), (30, 10), 0.03))


if __name__ == "__main__":
    unittest.main()
