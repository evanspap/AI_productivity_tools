import unittest
import export_codex_chat as exporter

SID = "01a0cacf-96b5-7d51-b23e-d5b32997ad28"


class Tests(unittest.TestCase):
    def test_id_and_deeplink(self):
        self.assertEqual(exporter.parse_session_id(SID), SID)
        self.assertEqual(exporter.parse_session_id("codex://threads/" + SID), SID)

    def test_invalid_deeplink(self):
        with self.assertRaises(ValueError):
            exporter.parse_session_id("codex://other/" + SID)

    def test_safe_filename(self):
        self.assertEqual(
            exporter.safe_filename('Analysis: A/B? "final"'),
            "Analysis- A-B- -final-",
        )
        self.assertEqual(exporter.safe_filename("CON"), "_CON")

    def test_math_delimiters(self):
        source = r"Inline \(x^2\) and display \[x=1\]"
        self.assertEqual(
            exporter.normalize_math_for_markdown(source),
            "Inline $x^2$ and display $$x=1$$",
        )

    def test_display_math_has_no_html_line_breaks(self):
        source = "\\[\n\\left[\nx\n\\right]\n\\]"
        rendered = exporter.markdown_to_html(source)
        self.assertIn('class="math-block"', rendered)
        self.assertNotIn("<br>", rendered)
        self.assertIn("\\left[\nx\n\\right]", rendered)

    def test_prompt_heading(self):
        item = {
            "role": "user",
            "phase": None,
            "timestamp": "",
            "parts": [("text", "Can you check this?\nMore detail")],
        }
        self.assertEqual(
            exporter.prompt_heading(item, 1),
            "Can you check this? More detail",
        )

    def test_right_aligned_user_style(self):
        item = {
            "role": "user",
            "phase": None,
            "timestamp": "",
            "parts": [("text", "Hello")],
        }
        result = exporter.render_html([item], {"session_id": SID})
        self.assertIn("margin-left:auto", result)
        self.assertIn('class="message user"', result)
        self.assertIn("mathjax@3.2.2", result)


if __name__ == "__main__":
    unittest.main()
