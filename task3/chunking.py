# -*- coding: utf-8 -*-
CHUNK_SIZE: int = 800
CHUNK_OVERLAP: int = 150

def split_into_chunks(
    text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP
) -> list[str]:
    paragraphs: list[str] = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: list[str] = []
    current_chunk: str = ""

    for paragraph in paragraphs:
        if len(current_chunk) + len(paragraph) + 1 <= chunk_size:
            current_chunk = f"{current_chunk}\n{paragraph}".strip()
            continue

        if current_chunk:
            chunks.append(current_chunk)

        if len(paragraph) <= chunk_size:
            current_chunk = paragraph
        else:
            start: int = 0
            while start < len(paragraph):
                end: int = start + chunk_size
                chunks.append(paragraph[start:end])
                start = end - chunk_overlap
            current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks