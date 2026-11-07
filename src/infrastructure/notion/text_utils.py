"""Small text helpers shared by Notion writers."""
import re


def clean_html(text: str) -> str:
    """Strip tags, collapse whitespace, unescape the few entities Kobo uses."""
    clean = re.sub(r'<[^>]+>', '', text or '')
    clean = re.sub(r'\s+', ' ', clean).strip()
    return (clean
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'"))
