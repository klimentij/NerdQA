You are working on a complex problem that requires breaking it down into smaller, more manageable questions. To assist in this process, you have provided the following information:

<original_question>
{{$ORIGINAL_QUESTION}}
</original_question>

<subquestion_tree>
{{$SUBQUESTION_TREE}}
</subquestion_tree>

<current_subquestion>
{{$CURRENT_SUBQUESTION}}
</current_subquestion>

<current_subquestion_search_results>
{{$SEARCH_RESULTS}}
</current_subquestion_search_results>

Your task is to analyze the current subquestion, reflect on the search results, and generate a set of focused subquestions (queries) to delve deeper into the topic and find the missing information needed to answer the original question comprehensively.

<reflection>
Take a moment to analyze the original question, the subquestion tree, and the current subquestion. Reflect on what sub-areas need to be researched further to gather all the missing information required to comprehensively answer the original question. Consider the main topic, key aspects, sub-topics, additional information needed, and how to phrase the queries as effective search queries. Provide your reflection in a single paragraph.
</reflection>

<query_generation>
Generate between 1 and {{$NUM_QUERIES}} queries that break down the current subquestion into more focused parts. These queries should be optimized for effective Google searches to research the key aspects and nuances of the original question. Each query should be standalone, containing all the necessary context within itself to be meaningful and effective. Use Google search operators to make the queries more targeted and efficient. Avoid duplicating information that might already be covered in the search results of other subquestions.

Format your generated queries as follows:
<queries>
<query>query 1</query>
<query>query 2</query>
...
<query>query n</query>
</queries>
</query_generation>

<output_format>
Please provide your output in the following format:
1. A paragraph containing your reflection on the original question, subquestion tree, current subquestion and search results to identify the key areas that need further research.
2. The generated queries, formatted as specified above.
</output_format>