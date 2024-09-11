import asyncio
from fastapi import FastAPI, WebSocket
import uvicorn
import time
import logging
import uuid

import os
import sys

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.web_search import BraveSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)


app = FastAPI()

async def sub_action(action_id):
    logger.info(f"Starting sub-action {action_id}")
    await asyncio.sleep(1)
    logger.info(f"Sub-action {action_id} completed")
    return 1.0

async def parallel_action(task_id, num_subtasks):
    logger.info(f"Starting parallel action {task_id} with {num_subtasks} subtasks")
    subtasks = [asyncio.create_task(sub_action(f"{task_id}-{i+1}")) for i in range(num_subtasks)]
    results = await asyncio.gather(*subtasks)
    total = sum(results)
    logger.info(f"Parallel action {task_id} completed. Total result: {total}")
    return total

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # Receive configuration from client
        config = await websocket.receive_json()
        num_tasks = config['num_tasks']
        num_subtasks = config['num_subtasks']
        logger.info(f"Received configuration: {num_tasks} tasks, {num_subtasks} subtasks per task")

        # Step 1: Wait 1 second
        step1_id = str(uuid.uuid4())[:8]
        logger.info(f"Starting Step 1 (ID: {step1_id})")
        start_time = time.time()
        await websocket.send_json({"step": 1, "status": "started"})
        result = await sub_action(step1_id)
        end_time = time.time()
        duration = int((end_time - start_time) * 1000)
        logger.info(f"Step 1 (ID: {step1_id}) completed in {duration}ms with result {result}")
        await websocket.send_json({"step": 1, "status": "completed", "result": result, "duration_ms": duration})

        # Step 2: N parallel actions, each with M parallel sub-actions
        step2_id = str(uuid.uuid4())[:8]
        logger.info(f"Starting Step 2 (ID: {step2_id}) with {num_tasks} tasks, each having {num_subtasks} subtasks")
        start_time = time.time()
        await websocket.send_json({"step": 2, "status": "started"})
        tasks = [asyncio.create_task(parallel_action(f"{step2_id}-{i+1}", num_subtasks)) for i in range(num_tasks)]
        results = await asyncio.gather(*tasks)
        total_result = sum(results)
        end_time = time.time()
        duration = int((end_time - start_time) * 1000)
        logger.info(f"Step 2 (ID: {step2_id}) completed in {duration}ms with total result {total_result}")
        await websocket.send_json({"step": 2, "status": "completed", "result": total_result, "duration_ms": duration})

        # Step 3: Wait 1 second
        step3_id = str(uuid.uuid4())[:8]
        logger.info(f"Starting Step 3 (ID: {step3_id})")
        start_time = time.time()
        await websocket.send_json({"step": 3, "status": "started"})
        result = await sub_action(step3_id)
        end_time = time.time()
        duration = int((end_time - start_time) * 1000)
        logger.info(f"Step 3 (ID: {step3_id}) completed in {duration}ms with result {result}")
        await websocket.send_json({"step": 3, "status": "completed", "result": result, "duration_ms": duration})

        # Pipeline completed
        logger.info("Pipeline completed")
        await websocket.send_json({"status": "pipeline_completed"})
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)