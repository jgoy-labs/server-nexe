"""MC-045: _chunk_by_paragraphs derived char offsets by accumulating
len(stripped_paragraph) + 2, assuming exact '\\n\\n' separators and
whitespace-free paragraphs. With leading/trailing whitespace or multi-newline
separators the offsets drift, so content[char_start:char_end] no longer
returns the paragraph text (SmartChunker is position-based: a chunk's text IS
content[char_start:char_end]).
"""
from memory.embeddings.core.chunker import SmartChunker

# Long, sentence-final paragraphs so the title heuristic never fires.
P1 = "This is the first paragraph with several words to avoid the title heuristic."
P2 = "And here is the second paragraph, also reasonably long so it dodges titles."


def test_offsets_point_at_real_text_with_irregular_whitespace():
    chunker = SmartChunker(max_chunk_size=1500, min_chunk_size=1)
    # Leading newlines, padded paragraphs, a 3-newline separator and trailing space.
    content = f"\n\n   {P1}   \n\n\n  {P2}  \n\n"

    chunks = chunker._chunk_by_paragraphs(content, "doc1")

    assert len(chunks) == 2, f"expected 2 paragraph chunks, got {len(chunks)}"
    for chunk, expected in zip(chunks, [P1, P2]):
        extracted = content[chunk.char_start:chunk.char_end]
        assert extracted == expected, (
            f"offset drift: content[{chunk.char_start}:{chunk.char_end}]="
            f"{extracted!r} != {expected!r}"
        )


def test_offsets_unaffected_when_already_clean():
    """No-regression: clean '\\n\\n'-separated content keeps exact offsets."""
    chunker = SmartChunker(max_chunk_size=1500, min_chunk_size=1)
    content = f"{P1}\n\n{P2}"

    chunks = chunker._chunk_by_paragraphs(content, "doc2")

    assert len(chunks) == 2
    assert content[chunks[0].char_start:chunks[0].char_end] == P1
    assert content[chunks[1].char_start:chunks[1].char_end] == P2
