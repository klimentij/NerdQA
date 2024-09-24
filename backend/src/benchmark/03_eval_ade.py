# import asyncio
# import websockets
# import json

# async def connect_and_send():
#     uri = "ws://localhost:8000/ws"
#     async with websockets.connect(uri) as websocket:
#         # Sample input data
#         sample_input = {
#             "question": "What are the latest research trends in AI?",
#             "iterations": 1,
#             "num_queries": 1,
#             "start_date": "2024-01-01",
#             "end_date": "2024-01-01",
#             "search_client": "openalex"
#         }

#         # Send the sample input data
#         await websocket.send(json.dumps(sample_input))
#         print(f"Sent: {sample_input}")

#         # Receive and print the results
#         while True:
#             response = await websocket.recv()
#             print(f"Received: {response}")

# # Run the client
# asyncio.get_event_loop().run_until_complete(connect_and_send())


import asyncio
import json
import os
import sys
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import re

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.qloop.pipeline import StatementGenerator, QueryGenerator, AnswerGenerator
from src.tools.search_client import SearchClient
from src.tools.brave_search_client import BraveSearchClient
from src.tools.exa_search_client import ExaSearchClient
from src.tools.openalex_search_client import OpenAlexSearchClient
from src.util.setup_logging import setup_logging


search = ExaSearchClient()
print(search.search())