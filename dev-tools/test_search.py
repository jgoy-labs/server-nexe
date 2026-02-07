import asyncio
from memory.memory.api import MemoryAPI
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"dev_tools.search.{key}", fallback, **kwargs)

async def main():
    async with MemoryAPI() as memory:
        results = await memory.search("Que es Nexe?", collection="user_knowledge", top_k=5)
        print(_t("results", "Results: {count}", count=len(results)))
        for r in results:
            print(_t(
                "item",
                "- Score: {score:.4f}, Content: {content}...",
                score=r.score,
                content=r.text[:100],
            ))

if __name__ == "__main__":
    asyncio.run(main())
