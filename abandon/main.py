import asyncio
import os
import sys

from dotenv import load_dotenv


from langchain_core.messages import HumanMessage, AIMessage

from agent import CustomAgent

async def main():
    load_dotenv()  # 改动：读取项目目录下的 .env

    async with CustomAgent() as custom_agent:
        agent = custom_agent.agent
        config = {"configurable": {"thread_id": "thread_0"}}

        while True:
            user_input = input("你：").strip()
            if user_input.lower() == "exit":
                print("已退出。")
                break
            if not user_input:
                continue
            try:
                response = await agent.ainvoke(
                    {"messages": [HumanMessage(content=user_input)]},config)
                print("助手：", response["messages"][-1].content)
            except Exception as exc:
                print("调用失败：", repr(exc))

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )
    asyncio.run(main())
