import asyncio
from memory.memory.api import MemoryAPI

async def main():
    async with MemoryAPI() as memory:
        results = await memory.search("Que es Nexe?", collection="user_knowledge", top_k=5)
        print(f"Results: {len(results)}")
        for r in results:
            print(f"- Score: {r.score:.4f}, Content: {r.text[:100]}...")

if __name__ == "__main__":
    asyncio.run(main())
