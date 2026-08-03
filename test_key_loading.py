"""Quick test to verify key loading"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.guest_assistant_chatbot import OPENAI_API_KEY, OPENAI_MODEL

print(f"Loaded API Key length: {len(OPENAI_API_KEY)}")
print(f"Model: {OPENAI_MODEL}")
if OPENAI_API_KEY:
    print(f"First 20 chars: {OPENAI_API_KEY[:20]}...")
    print(f"Last 20 chars: ...{OPENAI_API_KEY[-20:]}")
    
    # Test if it works
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=5
        )
        print(f"✅ API call successful! Response: {resp.choices[0].message.content}")
    except Exception as e:
        print(f"❌ API call failed: {e}")

