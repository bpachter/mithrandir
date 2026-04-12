import os
from dotenv import load_dotenv
from anthropic import Anthropic

# load .env file
load_dotenv()

# get api key from .env
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# simple test
message = client.messages.create(
    model="claude-opus-4-1-20250805",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Say 'Enkidu lives' and nothing else."}
    ]
)

print(message.content[0].text)