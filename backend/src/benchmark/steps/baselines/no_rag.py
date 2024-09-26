import asyncio
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import BenchmarkConfig
from typing import Dict, Any

async def generate_no_rag_answer(question: str, metadata: Dict[str, str]) -> str:
    skill = Completion(('BenchPaperCompress', 'Baseline', 'NoRAGAnswer'))
    
    result = await asyncio.to_thread(skill.complete,
        prompt_inputs={"MAIN_QUESTION": question},
        completion_kwargs={
            "metadata": metadata,
        }
    )
    
    return result.content


async def main():
    question = "What is the capital of France?"
    metadata = {}
    
    answer = await generate_no_rag_answer(question, metadata)
    print(f"Answer: {answer}")

if __name__ == "__main__":
    asyncio.run(main())