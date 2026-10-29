import argparse, json, torch
from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments
from peft import LoraConfig, get_peft_model
from shared import INTERRUPT, WAIT

BASE = "Qwen/Qwen3-4B"
MAX_LEN = 768

class DS(torch.utils.data.Dataset):
    def __init__(self, path, tok):
        self.items, skipped = [], 0
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            p = tok(r["prompt"], add_special_tokens=False)["input_ids"]
            c = tok(r["completion"], add_special_tokens=False)["input_ids"]
            if len(p) + len(c) > MAX_LEN:
                skipped += 1
                continue
            self.items.append({"input_ids": p + c, "labels": [-100] * len(p) + c})  # loss only on the completion
        print(f"{path}: {len(self.items)} samples, {skipped} skipped (too long)")
    def __len__(self): return len(self.items)
    def __getitem__(self, i): return self.items[i]

def make_collator(pad_id):
    def collate(batch):
        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), pad_id)
        lab = torch.full((len(batch), n), -100)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            k = len(b["input_ids"])
            ids[i, :k] = torch.tensor(b["input_ids"])
            lab[i, :k] = torch.tensor(b["labels"])
            att[i, :k] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}
    return collate

@torch.no_grad()
def eval_decision(model, tok, path, ids):
    """How well does the model separate interrupt from wait on held-out samples?"""
    model.eval()
    res = {"interrupt": [], "wait": []}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["type"] not in res:
            continue
        x = tok(r["prompt"], return_tensors="pt", add_special_tokens=False).to(model.device)
        logits = model(**x).logits[0, -1].float()
        res[r["type"]].append(torch.softmax(logits[ids], 0)[0].item())
    for k, v in res.items():
        if v:
            print(f"{k}: n={len(v)}, mean p(interrupt)={sum(v)/len(v):.2f}")
    if res["interrupt"] and res["wait"]:
        ok = sum(p > 0.5 for p in res["interrupt"]) + sum(p <= 0.5 for p in res["wait"])
        print(f"accuracy at 0.5: {ok / (len(res['interrupt']) + len(res['wait'])):.2f}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("persona")
    ap.add_argument("--base", default=BASE, help=f"HF model id (default: {BASE})")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=1e-4)
    a = ap.parse_args()

    if a.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = a.device
    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested, but this torch build has no CUDA support.")

    base = a.base
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    print(f"device={device} base={base} dtype={dtype}")
    if device == "cpu":
        print("CPU training is slow; use --base Qwen/Qwen3-0.6B if 4B does not fit in RAM.")

    tok = AutoTokenizer.from_pretrained(base)
    tok.add_special_tokens({"additional_special_tokens": [INTERRUPT, WAIT]})
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(base, dtype=dtype,
                                                 attn_implementation="sdpa").to(device)
    if len(tok) > model.get_input_embeddings().num_embeddings:
        model.resize_token_embeddings(len(tok))
    ids = tok.convert_tokens_to_ids([INTERRUPT, WAIT])
    with torch.no_grad():
        w = model.get_input_embeddings().weight
        mean = w[: len(tok) - 2].mean(0)
        for i in ids:
            w[i] = mean

    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules="all-linear",
        trainable_token_indices={"embed_tokens": ids}))
    model.print_trainable_parameters()

    train = DS(f"data/train_{a.persona}.jsonl", tok)
    out = f"out/{a.persona}"
    Trainer(model=model, train_dataset=train, data_collator=make_collator(tok.pad_token_id),
            args=TrainingArguments(
                output_dir=out, per_device_train_batch_size=4 if device == "cuda" else 1,
                gradient_accumulation_steps=4 if device == "cuda" else 16,
                num_train_epochs=a.epochs, learning_rate=a.lr, lr_scheduler_type="cosine",
                warmup_steps=10, bf16=device == "cuda", fp16=False, use_cpu=device == "cpu",
                logging_steps=5, save_strategy="no",
                report_to="none", remove_unused_columns=False)).train()

    eval_decision(model, tok, f"data/test_{a.persona}.jsonl", ids)

    merged = model.merge_and_unload()
    merged.save_pretrained(f"{out}/merged")
    tok.save_pretrained(f"{out}/merged")

if __name__ == "__main__":
    main()
