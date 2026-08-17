"""Qwen3-Reranker prompt construction."""


INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"


def build_prompt(query: str, document: str) -> str:
    return (
        "<|im_start|>system\n"
        'Judge whether the Document meets the requirements based on the Query and the '
        'Instruct provided. Note that the answer can only be "yes" or "no".'
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"<Instruct>: {INSTRUCTION}\n\n"
        f"<Query>: {query}\n\n"
        f"<Document>: {document}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )
