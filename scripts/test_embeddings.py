"""Manual test for Stage 5's embedding layer. Proves: the endpoint
responds, vectors have consistent dimensionality, and semantically
similar sentences score closer than dissimilar ones - a real
correctness check, not just "did it return numbers."
"""

import math

from llm.lemonade.embeddings import embed


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def main() -> None:
    sentences = [
        "James teaches Grade 4 ICT and mathematics.",       # A
        "The teacher instructs elementary students in computing and math.",  # B - similar to A
        "The battery reported 100 percent charge during the test.",  # C - unrelated
    ]
    vectors = embed(sentences)
    print(f"Got {len(vectors)} vectors, dimension {len(vectors[0])} each.")
    for v in vectors:
        assert len(v) == len(vectors[0]), "Inconsistent embedding dimension!"
    sim_ab = cosine_similarity(vectors[0], vectors[1])
    sim_ac = cosine_similarity(vectors[0], vectors[2])
    print(f"\nSimilarity(A, B) [should be HIGH - both about teaching]: {sim_ab:.4f}")
    print(f"Similarity(A, C) [should be LOW - unrelated topics]: {sim_ac:.4f}")
    if sim_ab > sim_ac:
        print("\nPASS: semantically related sentences scored higher, as expected.")
    else:
        print("\nFAIL: unrelated sentence scored as similar or more similar - investigate before proceeding.")


if __name__ == "__main__":
    main()
