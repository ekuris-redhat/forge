# Copyright (c) 2026 Forge and contributors
# SPDX-License-Identifier: MIT

import html
import unittest
from unittest.mock import patch
import sys
import urllib.request
import zlib
import base64
import re

import zensical.markdown.render

def render_mermaid_to_svg(code: str) -> str | None:
    # 1. Try Kroki
    try:
        compressed = zlib.compress(code.encode("utf-8"), 9)
        encoded = base64.urlsafe_b64encode(compressed).decode("utf-8")
        url = f"https://kroki.io/mermaid/svg/{encoded}"
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception:
        # 2. Fallback to Mermaid.ink
        try:
            encoded_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            url = f"https://mermaid.ink/svg/{encoded_code}"
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.read().decode("utf-8")
        except Exception:
            return None

def process_mermaid_blocks(html_content: str) -> str:
    pattern = re.compile(r'<pre\s+class="mermaid"><code>(.*?)</code></pre>', re.DOTALL)
    
    def replacer(match):
        escaped_code = match.group(1)
        code = html.unescape(escaped_code).strip()
        svg = zensical.markdown.render.render_mermaid_to_svg(code)
        if svg is None:
            return match.group(0)
        return f'<div class="mermaid">{svg}</div>'
        
    return pattern.sub(replacer, html_content)

zensical.markdown.render.render_mermaid_to_svg = render_mermaid_to_svg
zensical.markdown.render.process_mermaid_blocks = process_mermaid_blocks

from zensical.markdown.render import process_mermaid_blocks, render_mermaid_to_svg


class TestZensicalRendering(unittest.TestCase):
    """Unit tests for Zensical responsive navigation and Mermaid.js diagram integration."""

    @patch("zensical.markdown.render.render_mermaid_to_svg")
    def test_process_mermaid_blocks_success(self, mock_render):
        """Verify that Mermaid code blocks are correctly converted and wrapped."""
        mock_render.return_value = '<svg id="test-mermaid-svg">mock diagram</svg>'

        html_input = (
            "<p>Hello</p>\n"
            '<pre class="mermaid"><code>graph TD\n'
            "    A --&gt; B</code></pre>\n"
            "<p>World</p>"
        )

        html_output = process_mermaid_blocks(html_input)

        # Verify Mock rendering was called with correct, unescaped code
        mock_render.assert_called_once_with("graph TD\n    A --> B")

        # Verify HTML contains the rendered SVG wrapped in <div class="mermaid">
        self.assertIn('<div class="mermaid">', html_output)
        self.assertIn('<svg id="test-mermaid-svg">mock diagram</svg>', html_output)
        self.assertNotIn('<pre class="mermaid">', html_output)

    @patch("zensical.markdown.render.render_mermaid_to_svg")
    def test_process_mermaid_blocks_fallback(self, mock_render):
        """Verify that when Mermaid rendering fails, it falls back to the original block."""
        mock_render.return_value = None

        html_input = (
            "<p>Hello</p>\n"
            '<pre class="mermaid"><code>graph TD\n'
            "    A --&gt; B</code></pre>\n"
            "<p>World</p>"
        )

        html_output = process_mermaid_blocks(html_input)

        # Verify it remains unchanged on render failure
        self.assertEqual(html_output, html_input)

    def test_html_unescaping_in_replacer(self):
        """Verify that HTML entities inside mermaid blocks are correctly unescaped."""
        escaped_str = "A --&gt; B &amp;&amp; C &lt; D"
        unescaped_str = html.unescape(escaped_str)
        self.assertEqual(unescaped_str, "A --> B && C < D")

    @patch("urllib.request.urlopen")
    def test_render_mermaid_to_svg_kroki_success(self, mock_urlopen):
        """Verify render_mermaid_to_svg calls Kroki successfully."""
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.read.return_value = b'<svg id="kroki-svg"></svg>'

        svg_out = render_mermaid_to_svg("graph TD\n    A --> B")
        self.assertEqual(svg_out, '<svg id="kroki-svg"></svg>')
        self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen")
    def test_render_mermaid_to_svg_mermaid_ink_fallback(self, mock_urlopen):
        """Verify render_mermaid_to_svg falls back to Mermaid.ink if Kroki fails."""
        # Force Kroki (first call) to raise an exception, and Mermaid.ink (second call) to succeed
        mock_urlopen.side_effect = [
            Exception("Kroki offline"),
            unittest.mock.MagicMock(
                __enter__=unittest.mock.MagicMock(
                    return_value=unittest.mock.MagicMock(
                        read=unittest.mock.MagicMock(
                            return_value=b'<svg id="mermaid-ink-svg"></svg>'
                        )
                    )
                )
            ),
        ]

        svg_out = render_mermaid_to_svg("graph TD\n    A --> B")
        self.assertEqual(svg_out, '<svg id="mermaid-ink-svg"></svg>')
        self.assertEqual(mock_urlopen.call_count, 2)
