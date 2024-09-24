# src/util/chunking_util.py
from typing import List, Dict
from tokenizers import Tokenizer

class Chunker:
    def __init__(self, tokenizer: Tokenizer = None, chunk_size: int = 2048, chunk_overlap: int = 512):
        self.tokenizer = tokenizer or Tokenizer.from_pretrained("Cohere/rerank-english-v3.0")
        self.tokenizer.enable_truncation(max_length=int(1e6))
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str, meta: Dict) -> List[Dict]:
        tokens = self.tokenizer.encode(text).ids
        chunks = []
        start = 0
        total_chunks = -(-len(tokens) // (self.chunk_size - self.chunk_overlap))  # Ceiling division

        while start < len(tokens):
            end = start + self.chunk_size
            chunk_tokens = tokens[start:end]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            
            if start > 0:
                chunk_text = ".." + chunk_text
            if end < len(tokens):
                chunk_text = chunk_text + ".."
            
            chunk_meta = meta.copy()
            chunk_meta["chunk"] = f"{len(chunks) + 1} of {total_chunks}"
            chunks.append({"text": chunk_text, "meta": chunk_meta, "num_tokens": len(chunk_tokens)})
            start += self.chunk_size - self.chunk_overlap

        return chunks