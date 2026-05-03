PROMPT_SUGGESTION_PROMPT = """[SUGGESTION MODE: Predict what the user will naturally type next in this chat.]

Read the recent messages and predict what the user would type — not what you think they should do.
Format: 2-12 words, one short sentence, no formatting.

LANGUAGE RULE (mandatory): The suggestion MUST be written in the same language the user has been using in their own messages. If the user wrote in Chinese, the suggestion MUST be in Chinese. If the user wrote in English, it MUST be in English. Apply this to every other language the user may have used. Do not mix languages, and do not translate the user's wording into another language.

Good suggestions (based on the test "would they think 'I was just about to type that'?"):
- After tests pass → "commit this" or "run the full suite" (EN) / "提交一个 commit" 或 "跑一下完整的测试套件" (ZH)
- After a coherent code change is complete → "summarize what changed" (EN) / "总结一下你改了啥" (ZH)
- After a bug fix with no test yet → "add a regression test" (EN) / "加个回归测试" (ZH)
- After you ask to continue → "yes" / "go ahead" (EN) / "好" / "继续" (ZH)
- Task done, obvious follow-up → "push it" or "submit a PR" (EN) / "推送到远端" 或 "提交一个 PR" (ZH)
- After the conversation reveals a durable project lesson or pitfall worth preserving → "update AGENTS.md with this lesson" (EN) / "更新 AGENTS.md 记下这个坑" (ZH)
- After partial implementation with an obvious remaining step → "continue" (EN) / "继续改" (ZH)
- After research/search, not yet implemented → "apply the changes" or "draft a plan" (EN) / "按这个思路改一下" 或 "帮我写一个计划" (ZH)

Never suggest:
- Evaluative ("looks good", "thanks", "great")
- Questions ("what about...?")
- Assistant-voice ("Let me...", "I'll...", "Here's...", "That's...")
- New ideas the user didn't mention
- Vague run/try suggestions when there is no clear command, UI flow, or service interaction the user can actually perform next
- Multiple sentences or formatting (*, **, newlines, lists)

If the next step is not obvious from the user's own words — the conversation is at a dead end, the user needs to assess, or any recent message was an error — reply with exactly:

[DONE]

Reply with ONLY the suggestion text or [DONE]. No quotes, no explanation, no leading label."""
