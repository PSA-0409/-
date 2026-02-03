from screener.utils import chunk_markdown


def test_chunk_markdown_respects_fences():
    message = """Header

```\ncode line 1\ncode line 2\n```

Paragraph one.

Paragraph two.
"""
    chunks = chunk_markdown(message, limit=60)
    assert chunks
    for chunk in chunks:
        assert len(chunk) <= 70
    joined = "\n\n".join(chunks)
    assert "```" in joined
