import os
from dotenv import load_dotenv
from anthropic import Anthropic

# load .env file
load_dotenv()

# get api key from .env
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# simple test
message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Say 'Mithrandir lives' and nothing else."}
    ]
)

print(message.content[0].text)