## Input paper for grounding
"""
{{$PAPER}}
"""

## Instructions

Compress the paper to 1 page, omitting all experiments, and retaining only the synthesis from existing literature. Start with background and related work, gradually build logical reasoning, and mention the actual innovation only in the last paragraph without naming it, just describe it. Keep all inline references. It should look like a report, not a paper summary.

I study how scientists synthesize information from sources. I want it to be a coherent report that demonstrates how the authors of this paper address broad problems supported by many sources, gradually incorporate more existing literature, and make statements based on those findings, then statements based on previous statements, and finally come up with a scientific hypothesis.

The report must not mention any experiments or field studies conducted by the authors. I need only the synthesis from existing literature. The report must exclude any new terms or innovations proposed by the authors. I need only direct synthesis from literature, some reasoning on findings, and one or more most plausible hypotheses at the end, that's it!

The hypothesis must be borrowed directly from the paper, do not make it up yourself!

## Response format:

- 1-page reflection on the given paper, what it is about, what it is trying to do, and how (high-level) you are going to write a perfect report that would satisfy the requirements of the task I gave you by grounding on the paper. Also analyze if authors introduced any new terms or innovations that must be excluded from the report. Make a high-level report structure, what you are going to cover in the report.

- The report itself, 2-3 pages, make it nice and readable. Don't borrow the heading from the paper, write your own, topic-specific to make it more readable. After each sentence of the report, you must add one or more inline references to the specific snippets of the paper that you used to support your given sentence. Use exactly the IDs of the snippets as they are in the input in square brackets (e.g. [s1][s2]). Future reviewers must be able to understand the report without the original paper and verify the correctness of the report by following these inline references.