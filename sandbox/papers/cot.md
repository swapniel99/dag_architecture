# Chain-of-Thought Prompting Elicits Reasoning in Large Language Models

**Authors:** Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Brian Ichter, Fei Xia, Ed Chi, Quoc Le, Denny Zhou  
**Published:** NeurIPS 2022  
**arXiv:** 2201.11903

## Abstract

We explore how generating a chain of thought — a series of intermediate reasoning steps — significantly improves the ability of large language models to perform complex reasoning. A simple method called chain-of-thought prompting, where a few chain-of-thought demonstrations are provided as exemplars in prompting, substantially outperforms standard prompting on a range of arithmetic, commonsense, and symbolic reasoning tasks.

## Key Contributions

1. **Chain-of-thought prompting:** Instead of mapping input directly to output, the model is prompted to produce a sequence of intermediate reasoning steps before the final answer. This is achieved by including a few worked examples in the prompt that show the reasoning chain.

2. **Emergent capability at scale:** Chain-of-thought reasoning is an emergent property that only appears in sufficiently large models (≥100B parameters). Smaller models produce incoherent reasoning chains and do not benefit.

3. **Strong gains on hard benchmarks:** Chain-of-thought prompting achieves state-of-the-art on GSM8K (math word problems), SVAMP, AQuA, StrategyQA, and other benchmarks where standard prompting plateaus. On GSM8K, a 540B PaLM model with CoT reached 57% accuracy vs 17% with standard prompting.

## Method

Standard prompting: `(input, output)` exemplars.  
Chain-of-thought prompting: `(input, chain of thought, output)` exemplars.

The chain of thought is a natural language rationale that connects the question to the answer step by step. No training or fine-tuning is required — it is purely a prompting technique.

## Results

| Benchmark | Standard | Chain-of-Thought |
|---|---|---|
| GSM8K (PaLM 540B) | 17.9% | 56.9% |
| SVAMP | 69.9% | 79.0% |
| AQuA | 35.8% | 47.0% |
| StrategyQA | 65.3% | 75.6% |

## Why It Matters

Chain-of-thought prompting is the conceptual foundation for modern reasoning techniques in LLMs. It showed that prompting LLMs to "show their work" dramatically improves accuracy on multi-step problems. It directly inspired zero-shot CoT ("Let's think step by step"), self-consistency, and tree-of-thought approaches.
