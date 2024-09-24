import asyncio
import websockets
import json

async def connect_and_send():
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        # Sample input data
        sample_input = {
            "question": "What are the latest research trends in AI?",
            "iterations": 1,
            "num_queries": 1,
            "start_date": "2024-01-01",
            "end_date": "2025-01-01",
            "search_client": "openalex"
        }

        # Send the sample input data
        await websocket.send(json.dumps(sample_input))
        print(f"Sent: {sample_input}")

        # Receive and print the results
        while True:
            response = await websocket.recv()
            print(f"Received: {response}")

# Run the client
asyncio.get_event_loop().run_until_complete(connect_and_send())