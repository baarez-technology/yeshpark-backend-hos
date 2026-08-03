"""
Test script to verify guest assistant chatbot API key and client initialization
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

print("Testing Guest Assistant Chatbot API Key...")
print("=" * 60)

# Test 1: Check environment variable
print("\n1. Checking environment variables:")
env_key = os.getenv("OPENAI_API_KEY", "")
print(f"   OPENAI_API_KEY from env: {'Set' if env_key else 'Not set'} (length: {len(env_key)})")
if env_key:
    print(f"   First 20 chars: {env_key[:20]}...")
    print(f"   Last 20 chars: ...{env_key[-20:]}")

# Test 2: Check settings
print("\n2. Checking settings:")
try:
    from app.core.config import settings
    print(f"   Settings loaded successfully")
    print(f"   settings.openai_api_key: {'Set' if settings.openai_api_key else 'Not set'} (length: {len(settings.openai_api_key) if settings.openai_api_key else 0})")
    if settings.openai_api_key:
        print(f"   First 20 chars: {settings.openai_api_key[:20]}...")
        print(f"   Last 20 chars: ...{settings.openai_api_key[-20:]}")
    print(f"   settings.openai_model: {settings.openai_model}")
except Exception as e:
    print(f"   ✗ Error loading settings: {e}")
    sys.exit(1)

# Test 3: Test OpenAI client initialization (same as user's working code)
test_key = os.getenv("OPENAI_API_KEY", "") or (settings.openai_api_key if hasattr(settings, 'openai_api_key') else "")

try:
    from openai import OpenAI
    
    if test_key:
        print("   Testing with configured API key...")
        client = OpenAI(api_key=test_key)
    
    # Test a simple call
    print("   Making test API call...")
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'Hello' in one word"}
        ]
    )
    print(f"   ✅ API call successful! Response: {completion.choices[0].message.content}")
    
    # Now test with settings key
    if settings.openai_api_key and settings.openai_api_key.strip():
        print("\n   Testing with settings.openai_api_key...")
        client2 = OpenAI(api_key=settings.openai_api_key.strip())
        completion2 = client2.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Test' in one word"}
            ]
        )
        print(f"   ✅ Settings key works! Response: {completion2.choices[0].message.content}")
    else:
        print("   ⚠️  settings.openai_api_key is empty, cannot test")
        
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Test how guest_assistant_chatbot loads the key
print("\n4. Testing guest_assistant_chatbot key loading:")
try:
    # Simulate what the service does
    from app.core.config import settings
    from dotenv import load_dotenv
    load_dotenv()
    
    loaded_key = settings.openai_api_key if settings.openai_api_key else os.getenv("OPENAI_API_KEY", "")
    loaded_model = settings.openai_model if settings.openai_model else os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    
    print(f"   Loaded key: {'Set' if loaded_key else 'Not set'} (length: {len(loaded_key)})")
    print(f"   Loaded model: {loaded_model}")
    
    if loaded_key:
        print(f"   First 20 chars: {loaded_key[:20]}...")
        print(f"   Last 20 chars: ...{loaded_key[-20:]}")
        
        # Test if keys match
        if loaded_key.strip() == test_key.strip():
            print("   ✅ Loaded key matches user's test key!")
        else:
            print("   ⚠️  Loaded key does NOT match user's test key")
            print(f"   User key length: {len(test_key)}")
            print(f"   Loaded key length: {len(loaded_key)}")
            
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test complete!")

