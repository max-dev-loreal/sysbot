from config import MAX_TOKENS, MODEL, SYSTEM, client
from actions import REGISTRY, TOOLS, call_action

# ---  LLM TOOL-USE LOOP  ---

async def ask_llm(user_text: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_text},
    ]

    resp = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        max_tokens=MAX_TOKENS,
    )
    msg = resp.choices[0].message

    while msg.tool_calls:
        messages.append(msg)
        for tc in msg.tool_calls:
            entry = REGISTRY.get(tc.function.name)
            output, _ = await call_action(tc.function.name, use_cache=True)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                }
            )

        resp = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            max_tokens=MAX_TOKENS,
        )
        msg = resp.choices[0].message

    return msg.content or "(empty)"
