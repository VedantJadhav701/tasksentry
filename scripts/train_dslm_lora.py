"""
Zero-Local-Compute Fine-Tuning Pipeline for TaskSentry DSLM
=============================================================
This script trains a high-accuracy Domain-Specific Language Model (DSLM)
on TaskSentry canonical trajectories exported via:
    tasksentry domain export --format sft --out datasets/sft.jsonl

Runs seamlessly on:
  - Free Google Colab (T4 GPU, 16GB VRAM)
  - RunPod / Lambda Labs (1x RTX 3090, A10G, ~1 hour, ~$0.20)
  - Local GPU workstation

Key Features (Backed by 2024-2026 ArXiv Research):
  1. Unsloth FastLoRA (2x faster, 70% less VRAM)
  2. 4-bit QLoRA Quantization (train 3B/7B models in under 6GB VRAM)
  3. Direct export to Ollama GGUF format for instant zero-compute serving
"""

import os
import sys

# 1. Unsloth Optimization & Model Selection
try:
    import torch
    from datasets import load_dataset
    from transformers import TrainingArguments
    from trl import SFTTrainer
    from unsloth import FastLanguageModel
except ImportError:
    print("Please install training dependencies:")
    print("pip install unsloth torch transformers trl datasets accelerate")
    sys.exit(1)

# Default base model: Qwen2.5-3B-Instruct or Llama-3.2-3B-Instruct
MAX_SEQ_LENGTH = 2048
DTYPE = None  # None for auto-detection
LOAD_IN_4BIT = True  # QLoRA 4-bit quantization for minimal VRAM


def train_dslm(
    sft_data_path: str = "datasets/sft.jsonl",
    base_model: str = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    output_dir: str = "output/tasksentry_dslm",
    export_gguf: bool = True,
):
    print(f"[*] Loading base model: {base_model}...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=DTYPE,
        load_in_4bit=LOAD_IN_4BIT,
    )

    # 2. Add LoRA Adapters (targeting attention & MLP projection layers)
    print("[*] Configuring LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,  # 0 is optimized for Unsloth
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    # 3. Format TaskSentry SFT ChatML Data
    print(f"[*] Loading TaskSentry SFT dataset from {sft_data_path}...")
    dataset = load_dataset("json", data_files=sft_data_path, split="train")

    def format_chatml(examples):
        texts = []
        for msgs in examples["messages"]:
            text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            texts.append(text)
        return {"text": texts}

    dataset = dataset.map(format_chatml, batched=True)

    # 4. Training Arguments
    training_args = TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=100,  # Quick run for fine-tuning action catalog and diagnosis
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        output_dir=output_dir,
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=42,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_num_proc=2,
        packing=False,
        args=training_args,
    )

    print("[*] Starting LoRA Fine-Tuning...")
    trainer.train()

    # 5. Export to GGUF for Ollama Serving
    if export_gguf:
        print("[*] Exporting model to GGUF for Ollama zero-compute serving...")
        gguf_dir = os.path.join(output_dir, "gguf")
        model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method="q4_k_m")
        modelfile_path = os.path.join(gguf_dir, "Modelfile")
        with open(modelfile_path, "w", encoding="utf-8") as f:
            f.write("FROM ./unsloth.Q4_K_M.gguf\n")
            f.write("PARAMETER temperature 0.1\n")
            f.write("PARAMETER top_p 0.9\n")
        msg = (
            f"[+] Complete! To load into Ollama, run:\n"
            f"    cd {gguf_dir}\n"
            f"    ollama create tasksentry-dslm -f Modelfile"
        )
        print(msg)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train TaskSentry DSLM on free/cheap GPU")
    parser.add_argument(
        "--sft-data",
        default="reports/domain-demo/dataset/sft.jsonl",
        help="Path to exported sft.jsonl",
    )
    parser.add_argument(
        "--base", default="unsloth/Qwen2.5-3B-Instruct-bnb-4bit", help="HuggingFace base model"
    )
    parser.add_argument("--out", default="output/tasksentry_dslm", help="Output directory")
    args = parser.parse_args()
    train_dslm(args.sft_data, args.base, args.out)
