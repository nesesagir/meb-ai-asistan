import json
import os

import pandas as pd
from fastembed import SparseTextEmbedding, TextEmbedding

CHUNKS_DIR = "chunks/v1"
VECTORS_DIR = "vectors/v2"

dense_model = TextEmbedding(model_name="intfloat/multilingual-e5-large")
sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

os.makedirs(VECTORS_DIR, exist_ok=True)

for root, _dirs, files in os.walk(CHUNKS_DIR):
    for file in files:
        if not file.endswith(".json"):
            continue

        json_path = os.path.join(root, file)
        relative_path = os.path.relpath(root, CHUNKS_DIR)
        target_dir = os.path.join(VECTORS_DIR, relative_path)
        os.makedirs(target_dir, exist_ok=True)

        parquet_filename = file.replace(".json", ".parquet")
        parquet_path = os.path.join(target_dir, parquet_filename)
        if os.path.exists(parquet_path):
            print(f"skip {parquet_filename}")
            continue

        print(f"embed {file}")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            items = []
            for val in data.values():
                if isinstance(val, list):
                    items.extend(val)
            if not items:
                items = [data]
        else:
            items = data

        texts = []
        metadatas = []
        for item in items:
            if isinstance(item, dict):
                text = item.get("page_content") or item.get("text") or item.get("content") or ""
                meta = item.get("metadata") or {}
            elif isinstance(item, str):
                text = item
                meta = {}
            else:
                continue
            if str(text).strip():
                texts.append(str(text))
                metadatas.append(meta)

        if not texts:
            print(f"empty {file}")
            continue

        dense_embeddings = list(dense_model.embed(texts, batch_size=8))
        sparse_embeddings = list(sparse_model.embed(texts, batch_size=8))

        df = pd.DataFrame(
            {
                "text": texts,
                "metadata": metadatas,
                "dense_vector": [list(d) for d in dense_embeddings],
                "sparse_indices": [list(s.indices) for s in sparse_embeddings],
                "sparse_values": [list(s.values) for s in sparse_embeddings],
            }
        )
        df.to_parquet(parquet_path, engine="pyarrow")
        print(f"saved {parquet_filename}")

print("done")
