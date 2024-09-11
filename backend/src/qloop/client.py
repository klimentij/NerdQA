import asyncio
import websockets
import json
import os
import sys

# Set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

# Configuration
WEBSOCKET_URI = "ws://localhost:8000/ws"
MAIN_QUESTION = "What are the main causes of climate change???"
ITERATIONS = 1
NUM_QUERIES = 5

async def connect_websocket():
    try:
        async with websockets.connect(WEBSOCKET_URI) as websocket:
            # Send initial configuration to server
            await websocket.send(json.dumps({
                "question": MAIN_QUESTION,
                "iterations": ITERATIONS,
                "num_queries": NUM_QUERIES
            }))

            logger.info(f"Sent question: {MAIN_QUESTION}")
            logger.info(f"Iterations: {ITERATIONS}")
            logger.info(f"Queries per iteration: {NUM_QUERIES}")
            logger.info("Waiting for server responses...")

            while True:
                message = await websocket.recv()
                data = json.loads(message)
                
                if 'error' in data:
                    logger.error(f"Error: {data['error']}")
                    break
                
                if data['type'] == 'queries':
                    logger.info("Generated queries:")
                    for i, query in enumerate(data['data'], 1):
                        logger.info(f"  {i}. {query}")
                
                elif data['type'] == 'statements':
                    logger.info("Generated statements:")
                    for i, statement in enumerate(data['data'], 1):
                        logger.info(f"  {i}. [ID: {statement['id']}] {statement['text']}")
                
                elif data['type'] == 'answer':
                    logger.info("Intermediate answer:")
                    logger.info(data['data'])
                
                elif data['type'] == 'final_answer':
                    logger.info("Final answer:")
                    logger.info(data['data'])
                    logger.info("Pipeline completed successfully.")
                    break
                
                else:
                    logger.warning(f"Unknown message type: {data['type']}")
                    logger.info(data['data'])

    except websockets.exceptions.ConnectionClosedOK:
        logger.info("WebSocket connection closed normally.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(connect_websocket())
    logger.info("Client finished.")