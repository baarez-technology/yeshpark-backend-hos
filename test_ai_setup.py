"""Test script to verify AI assistant setup"""
import sys

print("Testing AI Assistant Setup...")
print("=" * 50)

# Test 1: Check LangGraph
try:
    from langgraph.graph import StateGraph, END
    print("✓ LangGraph: OK")
except ImportError as e:
    print(f"✗ LangGraph: NOT INSTALLED - {e}")
    sys.exit(1)

# Test 2: Check langchain-openai
try:
    from langchain_openai import ChatOpenAI
    print("✓ langchain-openai: OK")
except ImportError as e:
    print(f"✗ langchain-openai: NOT INSTALLED - {e}")
    sys.exit(1)

# Test 3: Check config
try:
    from app.core.config import settings
    print(f"✓ Config loaded")
    print(f"  - API Key present: {bool(settings.openai_api_key)}")
    print(f"  - API Key length: {len(settings.openai_api_key) if settings.openai_api_key else 0}")
    print(f"  - Model: {settings.openai_model}")
except Exception as e:
    print(f"✗ Config error: {e}")
    sys.exit(1)

# Test 4: Try to initialize LLM
try:
    from langchain_openai import ChatOpenAI
    import os
    
    api_key = settings.openai_api_key.strip() if settings.openai_api_key else None
    if not api_key or api_key == "":
        print("✗ API Key is empty")
        sys.exit(1)
    
    # Set environment variable
    os.environ["OPENAI_API_KEY"] = api_key
    
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0.7
    )
    print("✓ LLM initialized successfully")
    
    # Test a simple call
    print("  Testing LLM call...")
    response = llm.invoke("Say 'Hello' in one word")
    print(f"  ✓ LLM response: {response.content}")
    
except Exception as e:
    print(f"✗ LLM initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("=" * 50)
print("All tests passed! AI Assistant is ready.")

