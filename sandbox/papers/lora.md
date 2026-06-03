# LoRA: Low-Rank Adaptation of Large Language Models

**Authors:** Edward J. Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu, Yuanzhi Li, Shean Wang, Lu Wang, Weizhu Chen  
**Published:** ICLR 2022  
**arXiv:** 2106.09685

## Abstract

We propose Low-Rank Adaptation (LoRA), which freezes the pre-trained model weights and injects trainable rank decomposition matrices into each layer of the Transformer architecture, greatly reducing the number of trainable parameters for downstream tasks. Compared to full fine-tuning GPT-3 175B with Adam, LoRA can reduce the number of trainable parameters by 10,000x and GPU memory requirements by 3x.

## Key Contributions

1. **Low-rank weight updates:** LoRA freezes all pre-trained weights and adds trainable low-rank matrices A and B alongside existing weight matrices. The update ΔW = BA where B ∈ R^(d×r), A ∈ R^(r×k), and rank r << min(d,k). Only A and B are trained.

2. **No inference latency:** At deployment, the low-rank matrices are merged into the original weights (W' = W + BA), so there is zero additional latency compared to the base model. Unlike adapter layers, LoRA adds no sequential computation.

3. **Parameter efficiency at scale:** For GPT-3 175B, LoRA reduces trainable parameters from 175B to ~4.7M (a 10,000x reduction) while matching or exceeding fine-tuning quality on tasks like GLUE, E2E NLG, and WikiSQL.

## Method

For a pre-trained weight matrix W₀ ∈ R^(d×k), the forward pass becomes:

```
h = W₀x + ΔWx = W₀x + BAx
```

A is initialized with random Gaussian, B with zeros (so ΔW = 0 at the start of training). The rank r is typically 1–8; results are not sensitive to exact value. LoRA is applied to attention weight matrices Q, V (and optionally K, O).

## Results

| Model | Method | Trainable Params | WikiSQL | MultiNLI |
|---|---|---|---|---|
| GPT-3 | Full FT | 175B | 73.8% | 89.5% |
| GPT-3 | LoRA r=4 | 4.7M | 73.4% | 91.7% |
| RoBERTa | Full FT | 125M | — | 90.2% |
| RoBERTa | LoRA r=8 | 0.3M | — | 90.6% |

## Why It Matters

LoRA became the standard technique for fine-tuning LLMs on consumer hardware. By reducing trainable parameters by 10,000x, it made task-specific adaptation of 7B–70B models feasible on a single GPU. It is integrated into HuggingFace PEFT and is the basis for QLoRA, LoRA+, and most production fine-tuning pipelines.
