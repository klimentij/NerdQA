# Quote Synthesis Identification Guide

## Role
You are an expert research analyst specializing in identifying novel syntheses and insights in academic literature. Your task is to find quotes from a given paper that demonstrate the authors' ability to draw new conclusions by synthesizing multiple existing sources.

## Inputs

### Paper
"""
{{$PAPER}}
"""


## Instructions

1. **Thoroughly read and analyze the paper:**
   - Focus on the introduction, literature review, and discussion sections, especially before any experimental results are presented.
   - Pay special attention to paragraphs that cite multiple sources.

2. **Identify potential synthesis candidates:**
   - Look for paragraphs that discuss multiple related works or concepts.
   - Focus on sections where authors are comparing or contrasting different approaches.

3. **Evaluate the novelty of the synthesis:**
   - Determine if the authors are presenting a new perspective or insight.
   - Check if the conclusion drawn could not be found in any single cited source.

4. **Assess the quality of reasoning:**
   - Ensure the synthesis logically follows from the cited sources.
   - Look for clear connections between different ideas or approaches.

5. **Verify the standalone nature of the quote:**
   - The quote should be understandable without additional context.
   - It should present a complete thought or conclusion.

6. **Check for absence of experimental results:**
   - The quote should not include the paper's own experimental findings.
   - Focus on theoretical insights or conceptual syntheses.

7. **Ensure proper citation:**
   - The quote should include multiple in-text citations.
   - More citations generally indicate a stronger synthesis.

8. **Extract the quote:**
   - Copy the quote exactly, maintaining its original structure and content.
   - Preserve the original citations exactly as they appear in the paper, including numeric citation formats like [1], [2], etc.
   - It is crucial to copy the quote character-for-character, including any broken words, mistakes, or unusual formatting. Even a single character difference will cause the entire job to fail.

9. **Create a references list:**
   - For each citation in the quote, create a shortened reference.
   - If the paper uses numeric citations (e.g., [1], [2]), start each reference with the corresponding number.
   - Format the reference as: "Number. FirstAuthor (Year) Title". If the paper cites a different kind of work, use the appropriate citation style, but keep it short.

10. **Output as JSON:**
    - Include the exactly copied quotes and shortened references.
    - Ensure that when read in sequence, the output forms a coherent synthesis of the paper's novel insights.

11. **If no good candidates are found:**
    - It's better to output an empty quote list than to include weak or inappropriate candidates.
    - Provide a brief explanation in the reflection about why no suitable quotes were found.

## Output

1. A brief reflection on the paper and potential synthesis candidates.
2. The exact quote(s) demonstrating novel synthesis, with original citation formatting preserved, presented as a JSON array. If no suitable quotes are found, output an empty array. Remember, quotes must be copied character-for-character exactly as they appear in the paper.
3. A references array with shortened citations corresponding to the citations in the quotes. If no quotes are found, this should also be an empty array.

## Example 1 (With Quotes)

### Input Paper:
"Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (trimmed for brevity)

### Reflection:
The paper synthesizes insights from existing literature to propose a novel framework for evaluating large language models (LLMs) using LLMs themselves as judges. The authors identify a gap in traditional evaluation methods, which often fail to align with human preferences, and suggest that leveraging LLMs as evaluators can provide a scalable and explainable alternative. This synthesis draws on previous work in LLM capabilities, human alignment, and evaluation benchmarks to offer a new perspective on assessing LLM performance.

### Quotes demonstrating novel synthesis:

[
    "There has been a proliferation of LLM-based chat assistants (chatbots) that leverage supervised instruction fine-tuning and reinforcement learning with human feedback (RLHF) to unlock new instruction following and conversational abilities (Wei et al., 2022; Ouyang et al., 2022; Touvron et al., 2023; Anthropic, 2022; Google, 2022; OpenAI, 2022; DeepMind, 2023). Once aligned with humans, these chat models are strongly preferred by human users over the original, unaligned models on which they are built. However, the heightened user preference does not always correspond to improved scores on traditional LLM benchmarks – benchmarks like MMLU (Hendrycks et al., 2021) and HELM (Liang et al., 2022) cannot effectively tell the difference between these aligned models and the base models. This phenomenon suggests that there is a fundamental discrepancy between user perceptions of the usefulness of chatbots and the criteria adopted by conventional benchmarks.",
    "With the recent advances of LLMs, LLM-based assistants start to exhibit artificial general intelligence across diverse tasks, from writing and chatting to coding (Brown et al., 2020; Ouyang et al., 2022; OpenAI, 2023; Chen et al., 2021). However, evaluating their broad capabilities also becomes more challenging. Despite the availability of numerous benchmarks for language models, they primarily focus on evaluating models on closed-ended questions with short responses. Given that these chat assistants can now precisely follow user instructions in multi-turn dialogues and answer open-ended questions in a zero-shot manner, current benchmarks are inadequate for assessing such capabilities."
]


### References:

[
    "Wei (2022) Chain-of-thought prompting elicits reasoning in large language models",
    "Ouyang (2022) Training language models to follow instructions with human feedback",
    "Touvron (2023) LLaMA: Open and Efficient Foundation Language Models",
    "Anthropic (2022) Constitutional AI: Harmlessness from AI Feedback",
    "Google (2022) LaMDA: Language Models for Dialog Applications",
    "OpenAI (2022) ChatGPT: Optimizing Language Models for Dialogue",
    "DeepMind (2023) Sparrow: An AI agent to make language models safer and more ethical",
    "Hendrycks (2021) Measuring massive multitask language understanding",
    "Liang (2022) Holistic Evaluation of Language Models",
    "Brown (2020) Language models are few-shot learners",
    "Ouyang (2022) Training language models to follow instructions with human feedback",
    "OpenAI (2023) GPT-4 Technical Report",
    "Chen (2021) Evaluating large language models trained on code"
]


## Example 2 (With Quotes)

### Input Paper:
"Chain-of-Thought Prompting Elicits Reasoning in Large Language Models" (trimmed for brevity)

### Reflection:
In the initial sections of the paper, the authors lay the groundwork for their approach by synthesizing insights from existing literature on language models, reasoning, and prompting techniques. They draw upon previous findings to argue that while large language models have shown promise in various tasks, their reasoning capabilities remain limited without specific interventions. A key synthesis from the literature is the idea that combining the strengths of rationale-augmented training and few-shot prompting can unlock reasoning abilities in language models. This synthesis is crucial as it forms the basis for the authors' proposal of chain-of-thought prompting, which they argue can bridge the gap between model scale and reasoning performance.

### Quotes demonstrating novel synthesis:

[
    "This work explores how the reasoning ability of large language models can be unlocked by a simple method motivated by two ideas. First, techniques for arithmetic reasoning can benefit from generating natural language rationales that lead to the final answer. Prior work has given models the ability to generate natural language intermediate steps by training from scratch (Ling et al., 2017) or finetuning a pretrained model (Cobbe et al., 2021), in addition to neuro-symbolic methods that use formal languages instead of natural language (Roy et al., 2015; Chiang et al., 2019; Amini et al., 2019; Chen et al., 2020). Second, large language models offer the exciting prospect of in-context few-shot learning via prompting. That is, instead of finetuning a separate language model checkpoint for each new task, one can simply 'prompt' the model with a few input–output exemplars demonstrating the task. Remarkably, this has been successful for a range of simple question-answering tasks (Brown et al., 2020).",
    "Both of the above ideas, however, have key limitations. For rationale-augmented training and finetuning methods, it is costly to create a large set of high quality rationales, which is much more complicated than simple input–output pairs used in normal machine learning. For the traditional few-shot prompting method used in (Brown et al., 2020), it works poorly on tasks that require reasoning abilities, and often does not improve substantially with increasing language model scale (Rae et al., 2021). In this paper, we combine the strengths of these two ideas in a way that avoids their limitations."
]


### References:

[
    "Ling (2017) Program induction by rationale generation: Learning to solve and explain algebraic word problems",
    "Cobbe (2021) Training verifiers to solve math word problems",
    "Roy (2015) Solving general arithmetic word problems",
    "Chiang (2019) Semantically-aligned equation generation for solving and reasoning math word problems",
    "Amini (2019) MathQA: Towards interpretable math word problem solving with operation-based formalisms",
    "Chen (2020) Neural symbolic reader: Scalable integration of distributed and symbolic representations for reading comprehension",
    "Brown (2020) Language models are few-shot learners",
    "Rae (2021) Scaling language models: Methods, analysis & insights from training Gopher"
]


## Example 3 (No Suitable Quotes)

### Input Paper:
"Experimental Analysis of Quantum Circuit Optimization Techniques" (trimmed for brevity)

### Reflection:
After thoroughly analyzing the paper, I couldn't identify any quotes that demonstrate novel synthesis of multiple sources. The paper primarily focuses on presenting original experimental results and comparing them to existing techniques. While the authors do cite previous work, they don't combine insights from multiple sources to draw new conclusions in a way that meets our criteria. The literature review section mainly summarizes individual prior works without significant synthesis, and the discussion section is heavily focused on interpreting the paper's own experimental findings.

### Quotes demonstrating novel synthesis:
[]

### References:
[]

## Example 4 (With One Quote)

### Input Paper:
"LEAST-TO-MOST PROMPTING ENABLES COMPLEX REASONING IN LARGE LANGUAGE MODELS" (trimmed for brevity)

### Reflection:
The paper synthesizes insights from various existing techniques to propose a novel prompting strategy called least-to-most prompting. This strategy aims to improve the generalization capabilities of large language models on complex reasoning tasks. The authors draw on previous work in chain-of-thought prompting, few-shot prompting, and educational psychology to argue that breaking down complex problems into simpler subproblems and solving them sequentially can help models generalize better to harder tasks. This synthesis is particularly evident in the introduction and literature review sections, where the authors compare and contrast different prompting methods and their limitations.

### Quotes demonstrating novel synthesis:

[
    "The recently proposed chain-of-thought prompting approach [1, 2] has taken a significant step for narrowing the gap between human intelligence and machine intelligence. It combines the idea of natural language rationales [3, 4] with few-shot prompting [5]. When further integrated with self-consistency decoding [6] rather than using the typical greedy decoding, few-shot chain-of-thought prompting largely outperforms the state-of-the-art results in the literature on many challenging natural language processing tasks obtained from specially designed neural models trained with hundreds of times more annotated examples, while being fully interpretable. However, chain-of-thought prompting has a key limitation—it often performs poorly on tasks that require generalization of solving problems harder than the demonstration examples, such as compositional generalization [7, 8]."
]

### References:

[
    "1. Wei (2022) Chain-of-thought prompting elicits reasoning in large language models",
    "2. Chowdhery (2022) PaLM: Scaling language modeling with pathways",
    "3. Ling (2017) Program induction by rationale generation: Learning to solve and explain algebraic word problems",
    "4. Cobbe (2021) Training verifiers to solve math word problems",
    "5. Brown (2020) Language models are few-shot learners",
    "6. Wang (2022) Self-consistency improves chain of thought reasoning in language models",
    "7. Lake (2018) Generalization without systematicity: On the compositional skills of sequence-to-sequence recurrent networks",
    "8. Keysers (2020) Measuring compositional generalization: A comprehensive method on realistic data"
]
