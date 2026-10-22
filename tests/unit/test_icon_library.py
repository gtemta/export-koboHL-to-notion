"""圖示白名單與 SVG 檔必須一一對得上，否則渲染時才會發現缺圖。"""
import unittest

from src.domain.services.infographic_rules import ICON_NAMES
from src.infrastructure.infographic.icon_library import icon_inner_svg


class TestIconLibrary(unittest.TestCase):
    def test_every_whitelisted_icon_has_an_svg_with_shapes(self):
        shapes = ("<path", "<circle", "<rect", "<line", "<polyline", "<polygon", "<ellipse")
        for name in ICON_NAMES:
            inner = icon_inner_svg(name)
            self.assertTrue(any(s in inner for s in shapes), name)

    def test_inner_markup_has_no_svg_wrapper_or_license_comment(self):
        inner = icon_inner_svg("target")
        self.assertNotIn("<svg", inner)
        self.assertNotIn("</svg>", inner)
        self.assertNotIn("license", inner)

    def test_names_outside_the_whitelist_are_refused(self):
        for name in ("no-such-icon", "../icon_library", "..\\x", ""):
            with self.assertRaises(KeyError):
                icon_inner_svg(name)

    def test_icons_carry_no_executable_markup(self):
        for name in ICON_NAMES:
            inner = icon_inner_svg(name).lower()
            for bad in ("<script", "onload", "onclick", "href", "<style", "<foreignobject"):
                self.assertNotIn(bad, inner, f"{name}: {bad}")


if __name__ == "__main__":
    unittest.main()
