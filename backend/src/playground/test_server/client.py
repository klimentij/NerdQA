import asyncio
import websockets
import json

# Configuration
NUM_TASKS = 100  # Number of parallel tasks in step 2
NUM_SUBTASKS = 300  # Number of subtasks per task in step 2

async def connect_websocket():
    uri = "ws://localhost:8000/ws"
    try:
        async with websockets.connect(uri) as websocket:
            # Send configuration to server
            await websocket.send(json.dumps({
                "num_tasks": NUM_TASKS,
                "num_subtasks": NUM_SUBTASKS
            }))

            while True:
                message = await websocket.recv()
                data = json.loads(message)
                print(data)
                if 'status' in data:
                    if data['status'] == 'started':
                        print(f"Step {data['step']} started")
                    elif data['status'] == 'completed':
                        print(f"Step {data['step']} completed in {data['duration_ms']} ms")
                        if 'result' in data:
                            print(f"Step {data['step']} result: {data['result']}")
                    elif data['status'] == 'pipeline_completed':
                        print("Pipeline completed successfully.")
                        break
    except websockets.exceptions.ConnectionClosedOK:
        print("WebSocket connection closed normally.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(connect_websocket())
    print("Client finished.")