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
MAIN_QUESTION = "What are the main causes of climate change?"
ITERATIONS = 1
NUM_QUERIES = 2
TIMEOUT = 60  # Timeout in seconds

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

            try:
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)
                        parsed_message = json.loads(message)
                        message_type = parsed_message.get("type")
                        
                        logger.info(f"Received message type: {message_type}")
                        logger.info(f"Message content: {parsed_message}")

                        if message_type == "final_answer":
                            logger.info("Received final answer. Closing connection.")
                            break

                    except asyncio.TimeoutError:
                        logger.warning(f"No message received for {TIMEOUT} seconds. Closing connection.")
                        break

            except websockets.exceptions.ConnectionClosed:
                logger.info("WebSocket connection closed by the server.")

    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(connect_websocket())
    logger.info("Client finished.")