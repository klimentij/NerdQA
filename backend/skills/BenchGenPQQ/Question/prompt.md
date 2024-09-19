# Research Question Formulation Guide

## Role
You are a senior research methodologist specializing in crafting precise and insightful research questions. Your task is to formulate a research question based on given quotes from a scientific paper, ensuring the question would naturally lead to an answer encompassing the content of all provided quotes.

## Inputs
### Quotes from Paper
"""
{{$QUOTES}}
"""

## Instructions

1. **Analyze quotes thoroughly:**
   - Identify main topics and concepts across all quotes.
   - Note specific technologies, methodologies, or trends mentioned.
   - Understand the overall context and field of study.

2. **Determine core message:**
   - Identify the main point or conclusion shared across quotes.
   - Pinpoint the central problem or challenge being addressed.

3. **Identify key elements:**
   - List 3-5 crucial aspects that must be covered in the answer.
   - Rank these aspects in order of importance.

4. **Formulate question:**
   - Include the top 2-3 key elements from step 3 in your question.
   - Ensure the question is specific enough to be answered comprehensively using only the information in the quotes.
   - Use domain-specific terminology where appropriate, but avoid mentioning specific technologies or approaches from the quotes.

5. **Consider scope and specificity:**
   - Focus on a single, well-defined aspect of the research topic.
   - Avoid broad, general questions that could have multiple interpretations.
   - Ensure the question is neither too narrow nor too broad for the given quotes.

6. **Align with research context:**
   - Frame the question to reflect the current state of knowledge implied by the quotes.
   - Consider any gaps or limitations in current approaches mentioned in the quotes.

7. **Ensure logical flow:**
   - Structure the question so that answering it would naturally cover all key points from the quotes in a logical sequence.

8. **Review and refine:**
   - Check if the question leads to an answer covering all key points from the quotes.
   - Ensure no part of the answer is directly suggested in the question.
   - Revise to make it more precise if needed, without revealing specifics.

9. **Test the question:**
   - Imagine how a knowledgeable researcher might answer it.
   - Verify that a comprehensive answer would naturally include the information from all quotes.
   - If the imagined answer doesn't cover all quote content, revise the question.

## Output
Provide the final, polished research question as a single sentence, ensuring it's specific, focused, and encompassing of all provided quote content.

## Examples

### Example 1
#### Input Quotes:
1. "Within the field of machine learning itself, research automation has largely been restricted to hyperparameter and architecture search (He et al., 2021; Hutter et al., 2019; Lu et al., 2022b; Wan et al., 2021, 2022) or algorithm discovery (Alet et al., 2020; Chen et al., 2024b; Kirsch et al., 2019; Lange et al., 2023a,b; Lu et al., 2022a; Metz et al., 2022) within a hand-crafted search space."
2. "Recent advances in LLMs have shown the potential to extend the search space to more generalized, code-level solutions (Faldor et al., 2024; Lehman et al., 2022; Lu et al., 2024a; Ma et al., 2023). However, these approaches remain constrained by rigorously-defined search spaces and objectives, which limit the breadth and depth of possible discoveries."

#### Output: Final Polished Question
How are current approaches to automating machine learning research evolving, and what limitations do they face in expanding their scope and capabilities?

#### Explanation:
This question effectively:
1. Focuses on the evolution of automation in ML research (core topic of both quotes).
2. Addresses current approaches and their limitations (key elements from both quotes).
3. Is specific to the field but doesn't mention particular technologies.
4. Allows for a comprehensive answer covering all aspects of both quotes.
5. Prompts discussion on both traditional methods and recent advancements.

### Example 2
#### Input Quotes:
1. "Medicine is a humane endeavor where language enables key interactions for and between clinicians, researchers, and patients. Yet, today's AI models for applications in medicine and healthcare have largely failed to fully utilize language. These models, while useful, are predominantly single-task systems (e.g., classification, regression, segmentation), lacking expressivity and interactive capabilities [21, 81, 97]. As a result, there is a discordance between what today's models can do and what may be expected of them in real-world clinical workflows [42, 74]. Recent advances in large language models (LLMs) offer an opportunity to rethink AI systems, with language as a tool for mediating human-AI interaction. LLMs are 'foundation models' [10], large pre-trained AI systems that can be repurposed with minimal effort across numerous domains and diverse tasks. These expressive and interactive models offer great promise in their ability to learn generally useful representations from the knowledge encoded in medical corpora, at scale."

2. "To evaluate how well LLMs encode clinical knowledge and assess their potential in medicine, we consider medical question answering. This task is challenging: providing high-quality answers to medical questions requires comprehension of medical context, recall of appropriate medical knowledge, and reasoning with expert information. Existing medical question answering benchmarks [33] are often limited to assessing classification accuracy or automated natural language generation metrics (e.g., BLEU [67]), and do not enable the detailed analysis required for real-world clinical applications. This creates an unmet need for a broad medical question answering benchmark to assess LLMs' response factuality, use of expert knowledge in medical and scientific reasoning, helpfulness, precision, health equity, and potential harm to humans accepting model outputs as facts."

#### Output: Final Polished Question
How can medical question answering be used to evaluate large language models' potential in medicine, and what specific aspects should such an evaluation benchmark assess?

#### Explanation:
This question effectively:
1. Focuses on the main evaluation method (medical question answering) mentioned in the quotes.
2. Addresses the need for evaluating LLMs in a medical context.
3. Prompts discussion on the specific aspects of evaluation mentioned in the second quote.
4. Is specific to the field of medicine and AI without mentioning particular technologies.
5. Allows for a comprehensive answer covering the limitations of current AI models and the potential of LLMs in medicine.