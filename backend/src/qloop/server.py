# @src/qloop/server.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your Vercel URL when you deploy
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    content: str

class ExampleMessage(BaseModel):
    heading: str
    subheading: str
    message: str

@app.post("/api/message")
async def process_message(message: Message):
    # This is where you'd normally call your Pipeline or other processing logic
    response = f"Server received: '{message.content}'. This is a dummy response."
    return {"response": response}

@app.get("/api/example-messages")
async def get_example_messages():
    example_messages = [
        {
            "heading": "What are the uvicorns?",
            "subheading": "trending memecoins today?",
            "message": "What are the trending memecoins today?"
        },
        {
            "heading": "What is the price of",
            "subheading": "$DOGE right now?",
            "message": "What is the price of $DOGE right now?"
        },
        {
            "heading": "I would like to buy",
            "subheading": "42 $DOGE",
            "message": "I would like to buy 42 $DOGE"
        },
        {
            "heading": "What are some",
            "subheading": "recent events about $DOGE?",
            "message": "What are some recent events about $DOGE?"
        }
    ]
    return {"example_messages": example_messages}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)