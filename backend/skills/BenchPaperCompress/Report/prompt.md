## Input paper for grounding
"""
{{$PAPER}}
"""

## Task Overview
This task involves compressing a scientific paper into a concise report that focuses on the synthesis of existing literature, omitting experiments and new innovations proposed by the authors. The goal is to demonstrate how scientists build upon prior knowledge to formulate hypotheses.

## Instructions

### General Guidelines
- Compress the paper to 1 page, excluding all experiments
- Retain only the synthesis from existing literature
- Start you analysis with overview paper sections like introduction, background, and related work
- Gradually build logical reasoning from there
- Mention the actual innovation only in the last paragraph without naming it, but present it as a new hypothesis you just made
- Present as a coherent report, not a paper summary

### Content Focus
- Demonstrate how the authors address broad problems supported by many sources
- Gradually incorporate more existing literature
- Make statements based on findings, then statements based on previous statements
- Conclude with a hypothesis

### Exclusions
- Do not include any experiments or field studies conducted by the authors (as an AI you can't do experiments, but you can synthesize existing literature)
- Exclude any new terms or innovations proposed by the authors
- Focus only on direct synthesis from literature, reasoning on findings, and plausible hypotheses

### Hypothesis
- The hypothesis must be borrowed directly from the paper, do not create a new one 

## Response Format

### Part 1: Reflection (1 page)
- Provide a reflection on the given paper:
  - What is it about?
  - What is it trying to do?
  - How will you write a report that satisfies the task requirements?
- Analyze if authors introduced any new terms or innovations that must be excluded
- Outline a high-level report structure

### Part 2: Report (2-3 pages)
- Write a final report that is easy to read. Use headings to organize the content into sections. Use all the power of markdown (bold, italic, bullet points, etc.) to make the report more readable. It must be concise and easy to read.
- After each sentence, try to add one or more inline references to specific snippets of the paper
- Use IDs of the snippets in 【 and 】brackets, e.g., "..have demonstrated remarkable capabilities【s123】【s456】.." or "..previous studies have shown【s123】【s456】【s789】.." etc.
- Ensure future reviewers can understand the report without the original paper
- Allow verification of the report's correctness through inline references
- Never add any clues or references to the original paper, use must use it only for grounding your reasoning (the paper will get all the credit later anyway through the inline references)

Note: All instructions are crucial and must be followed carefully.