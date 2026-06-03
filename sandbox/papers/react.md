# ReAct: Synergizing Reasoning and Acting in Language Models

**Authors:** Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao  
**Published:** ICLR 2023  
**arXiv:** 2210.03629

## Abstract

We explore the use of LLMs to generate both reasoning traces and task-specific actions in an interleaved manner. ReAct prompts LLMs to generate verbal reasoning steps (Thought) and environment actions (Act) together, allowing the model to dynamically create and update plans while interacting with external tools. ReAct overcomes hallucination and error propagation issues in chain-of-thought by grounding reasoning in real observations.

## Key Contributions

1. **Interleaved reasoning and acting:** ReAct interleaves language model reasoning traces with action calls to external tools (search, lookup, calculator). Each step alternates between Thought (reasoning), Action (tool call), and Observation (tool result), creating a tight loop between planning and execution.

2. **Grounded reasoning reduces hallucination:** By allowing the model to retrieve real information mid-reasoning, ReAct reduces factual hallucination compared to pure chain-of-thought. The model can correct wrong assumptions when observations contradict its beliefs.

3. **Human interpretability:** The explicit Thought steps make the agent's reasoning transparent and diagnosable. Humans can identify where the agent went wrong and intervene, unlike opaque action-only agents.

## Method

ReAct prompting format for a question-answering task:

```
Thought: I need to find out when the Eiffel Tower was built.
Action: Search[Eiffel Tower construction date]
Observation: The Eiffel Tower was built between 1887 and 1889.
Thought: The construction was completed in 1889.
Action: Finish[1889]
```

Few-shot examples with this format are provided in the prompt. No fine-tuning is required for the basic version.

## Results

| Benchmark | CoT | Act-only | ReAct |
|---|---|---|---|
| HotpotQA | 29.4% | 25.7% | 35.1% |
| FEVER | 56.3% | 58.9% | 60.9% |
| ALFWorld | — | 45% | 71% |
| WebShop | — | 45.7% | 49.4% |

## Why It Matters

ReAct is the conceptual foundation for modern tool-using agents and agentic frameworks. It showed that interleaving reasoning with tool use is more reliable than either alone. It directly inspired LangChain's agent loop, OpenAI function calling patterns, and virtually every production LLM agent that uses search, code execution, or API calls as tools.
