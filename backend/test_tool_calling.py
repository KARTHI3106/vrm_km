from langchain_ollama import ChatOllama
from langchain_core.tools import tool

@tool
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

llm = ChatOllama(model='llama3.1:8b', base_url='http://localhost:11434', temperature=0, num_predict=256)
bound = llm.bind_tools([add])
resp = bound.invoke('What is 2 + 3? Use the add tool.')
print("Type:", type(resp))
print("Tool calls:", resp.tool_calls if hasattr(resp, 'tool_calls') else 'NO TOOL CALLS')
print("Content:", resp.content[:200] if resp.content else 'empty')
print("SUCCESS - llama3.1:8b supports tool calling!")
