import asyncio
from openai import AsyncOpenAI
import os
from agent.prompts import CLASSIFIER_PROMPT
from core.config import settings

client = AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
model = settings.GROQ_LIGHT_MODEL

async def main():
    try:
        response = await client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT.format(current_date="2026-07-03")},
                {"role": "user", "content": "I want to cook rajma, make a grocery list for it and remind me at 6pm to buy them"},
            ],
        )
        print("Response:", response.choices[0].message.content)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
