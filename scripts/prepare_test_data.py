"""
Download HC3 reddit_eli5 from HuggingFace and save 500 AI + 500 human samples.

Usage:
    pip install datasets
    python scripts/prepare_test_data.py
"""

import json
import sys
from pathlib import Path

try:
    from datasets import load_dataset
except ImportError:
    print("Install datasets: pip install datasets")
    sys.exit(1)

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AI_OUT = OUTPUT_DIR / "ai_samples.jsonl"
HUMAN_OUT = OUTPUT_DIR / "human_samples.jsonl"

LIMIT = 500

print("Loading HC3 reddit_eli5...")
ds = load_dataset("json", data_files="hf://datasets/Hello-SimpleAI/HC3/reddit_eli5.jsonl")
train = ds["train"]

ai_samples = []
human_samples = []

for row in train:
    for answer in row.get("chatgpt_answers", []):
        if answer and len(answer.split()) > 20:
            ai_samples.append({"text": answer, "label": "ai", "source": "hc3_reddit_eli5"})
        if len(ai_samples) >= LIMIT:
            break
    for answer in row.get("human_answers", []):
        if answer and len(answer.split()) > 10:
            human_samples.append({"text": answer, "label": "human", "source": "hc3_reddit_eli5"})
        if len(human_samples) >= LIMIT:
            break
    if len(ai_samples) >= LIMIT and len(human_samples) >= LIMIT:
        break

with open(AI_OUT, "w") as f:
    for s in ai_samples[:LIMIT]:
        f.write(json.dumps(s) + "\n")

with open(HUMAN_OUT, "w") as f:
    for s in human_samples[:LIMIT]:
        f.write(json.dumps(s) + "\n")

print(f"Saved {min(len(ai_samples), LIMIT)} AI samples to {AI_OUT}")
print(f"Saved {min(len(human_samples), LIMIT)} human samples to {HUMAN_OUT}")
