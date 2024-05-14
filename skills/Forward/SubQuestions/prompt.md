You will be generating subquestions to help research and answer a complex original question.

Here is the original question:
<original_question>
{{$ORIGINAL_QUESTION}}
</original_question>

And here are the search results returned so far for that question:
<search_results>
{{$SEARCH_RESULTS}}
</search_results>

First, carefully analyze the original question and the provided search results. Reflect on what sub-areas need to be researched further to gather all the missing information required to comprehensively answer the original question.

Provide your reflection in one paragraph, considering the following:
1. The main topic of the original question
2. Key aspects and sub-topics related to the main topic
3. Additional information needed to thoroughly address the question
4. Gaps in knowledge not covered by the provided search results
5. How to phrase the subquestions as effective search queries

Write your reflection inside <reflection> tags. It should be a single paragraph of very compressed and concise text.

Next, generate {{$NUM_SUBQUESTIONS}} subquestions that break down the original question into more focused queries. These subquestions should be used to research the key aspects and nuances of the original question using a search engine like Google.

Format the subquestions like this:
<subquestions>
<subquestion>Subquestion 1</subquestion>
<subquestion>Subquestion 2</subquestion>
...
<subquestion>Subquestion {{$NUM_SUBQUESTIONS}}</subquestion>
</subquestions>

The subquestions you generate will be used as Google search queries by a small language model to collect the missing information needed to thoroughly address the original question.