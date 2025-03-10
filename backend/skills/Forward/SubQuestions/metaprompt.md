1. Prompt should start with explaining that the client is working on a complex problem and solving it requires breaking it down into smaller, more manageable questions. The client has provided the original question, the tree of subquestions generated so far, and the current subquestion they are working on. The task is to analyze the current subquestion, reflect on the search results, and generate a set of focused subquestions to delve deeper into the topic and find the missing information needed to answer the original question comprehensively.
2. The prompt should ask the user to provide an original complex question, the tree of subquestions generated so far and the current subquestion we work on with  search results returned from the Bravo Search API for that question we work on. 
3. This current subquestion can be anywhere in the DAG of subquestions.

4. The prompt should instruct the language model to generate a specific number of subquestions (determined by a variable) that break down the given  current subquestion into more focused queries. These queries should be used to research the key aspects and nuances of the original question using a search engine like Google.

5. Before generating the queries, the language model should be instructed to analyze the original question , other subquestions and the search results of the current subquestion. It should reflect on what sub-areas need to be researched further to gather all the missing information required to comprehensively answer the original question.

6. The language model should be asked to provide its reflection in 1 paragraph, considering the main topic, key aspects, sub-topics, additional information needed, and how to phrase the queries as effective search queries.

7. The generated queries should be wrapped in <query> tags, with each individual subquestion enclosed in its own <queries> tags.

8. All variables in the prompt should be enclosed in double curly braces, i.e., {{$variable}}.

9. The queries generated by the language model will be used as Google search queries by a small language model to collect the missing information needed to thoroughly address the original question. They must be optimized to be clear, concise, and efficient search queries. They don't have to be full sentences, but rather fragments that guide the search process effectively.
10. The queries must be standalone, containing all the necessary context within themselves to be meaningful and effective. Because researchers will use these queries to find information independently, they should be self-sufficient and clear in their intent. They won't have access to the original prompt or subquestions, so the queries should encapsulate all the information needed to guide the search process.
11. You can use google search operators to make the queries more effective. For example, using "site:.gov" to restrict results to government websites, or using quotes to search for an exact phrase etc
12. Queries should be designed such they don't duplicate information that might already be covered in the search results to other subquestions. Each query should aim to gather new and unique information to fill the knowledge gaps identified in the reflection part of the prompt.
13. The input variables are
    1.  ORIGINAL_QUESTION
    2.  SUBQUESTION_TREE
    3.  CURRENT_SUBQUESTION
    4.  NUM_QUERIES (max num queries to generate, it should generate from 1 to this number depending on the need)
14. It should output the following:
    1. A paragraph with reflection 
    2. <queries> tags with generated multiple <query> inside.
 15. There's no such input as SEARCH_QUALITY_REFLECTION. AI should generate the reflection based on all the inputs and it should be a part of response

