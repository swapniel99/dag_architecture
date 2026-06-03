# Attention Is All You Need

**Authors:** Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin  
**Published:** 2017 (NeurIPS)  
**arXiv:** 1706.03762

## Abstract

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks in an encoder-decoder configuration. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train.

## Key Contributions

1. **Attention-only architecture:** The Transformer is the first sequence transduction model relying entirely on self-attention to compute representations of input and output, replacing recurrent (RNN/LSTM) and convolutional layers entirely.

2. **Parallelizability and training efficiency:** Because the Transformer does not use recurrence, it can be trained with far greater parallelism. The authors trained a large model to state-of-the-art quality on WMT 2014 English-to-German in 3.5 days on 8 GPUs — a fraction of the cost of prior best models.

3. **Generalization across tasks:** The Transformer achieves state-of-the-art BLEU scores on machine translation (28.4 on EN-DE, 41.8 on EN-FR) and generalizes to English constituency parsing with both large and limited training data, demonstrating the architecture is not task-specific.

## Architecture

The Transformer uses an encoder-decoder structure. Both encoder and decoder are composed of stacks of identical layers.

- **Encoder:** 6 layers, each with (a) multi-head self-attention and (b) position-wise feed-forward network. Residual connections and layer normalization applied after each sub-layer.
- **Decoder:** 6 layers with an additional third sub-layer performing multi-head attention over encoder output. Masking in self-attention prevents positions from attending to subsequent positions.

### Multi-Head Attention

Rather than a single attention function, the model linearly projects queries, keys, and values h times with different learned projections, runs attention in parallel, and concatenates results.

```
MultiHead(Q, K, V) = Concat(head_1, ..., head_h) W^O
head_i = Attention(Q W_i^Q, K W_i^K, V W_i^V)
```

Scaled dot-product attention: `Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V`

### Positional Encoding

Since the model contains no recurrence or convolution, positional encodings are added to input embeddings to inject sequence order information. Sine and cosine functions of different frequencies are used.

## Results

| Task | BLEU | Prior best |
|---|---|---|
| WMT 2014 EN-DE | 28.4 | 26.4 |
| WMT 2014 EN-FR | 41.8 | 41.1 |

Training cost was significantly lower than competing models, measured in FLOPs.

## Why It Matters

The Transformer became the foundation for BERT, GPT, T5, and virtually all large language models. Its attention mechanism enables each token to directly attend to every other token in the sequence, capturing long-range dependencies more effectively than RNNs.
