# Direct Preference Optimization: Your Language Model is Secretly a Reward Model

**Authors:** Rafael Rafailov, Archit Sharma, Eric Mitchell, Stefano Ermon, Christopher D. Manning, Chelsea Finn  
**Published:** NeurIPS 2023  
**arXiv:** 2305.18290

## Abstract

We introduce Direct Preference Optimization (DPO), a simple and stable algorithm for training language models from human preferences without reinforcement learning. DPO shows that the RLHF objective can be optimized directly using a simple binary cross-entropy loss on preference data, without needing to fit a separate reward model or use PPO.

## Key Contributions

1. **Eliminates the reward model:** DPO reparameterizes the reward function in terms of the language model itself, showing that the optimal policy can be extracted directly from preference data using a closed-form solution. No separate reward model training is needed.

2. **No reinforcement learning required:** Instead of PPO-style RL training, DPO optimizes a simple binary cross-entropy objective on (chosen, rejected) response pairs. This makes training more stable, memory-efficient, and easier to implement.

3. **Matches or exceeds RLHF performance:** On sentiment control, summarization, and dialogue tasks, DPO matches or outperforms PPO-based RLHF while requiring significantly less compute and no hyperparameter tuning of an RL loop.

## Method

Given a dataset of preference pairs (x, y_w, y_l) where y_w is preferred over y_l for prompt x, DPO optimizes:

```
L_DPO(π_θ; π_ref) = -E[(x,y_w,y_l)] [ log σ( β log π_θ(y_w|x)/π_ref(y_w|x) - β log π_θ(y_l|x)/π_ref(y_l|x) ) ]
```

Where π_ref is a frozen reference model (e.g., SFT model), β controls deviation from reference, and σ is sigmoid.

## Results

| Task | PPO (RLHF) | DPO |
|---|---|---|
| Summarization (win rate) | 56% | 61% |
| Sentiment (reward) | 2.5 | 2.5 |
| Dialogue (GPT-4 eval) | comparable | comparable |

## Why It Matters

DPO became the dominant method for aligning LLMs after its publication. Its simplicity — a single training loop with a standard loss function — made RLHF-quality alignment accessible without the infrastructure complexity of PPO. Most open-source aligned models (Llama 2, Mistral variants, etc.) now use DPO or DPO-derived methods.
