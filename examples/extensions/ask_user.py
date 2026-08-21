"""Shipped-style extension — ask_user: structured multi-choice questions.

按需启用:
  * 复制/软链本文件到 preset 扩展目录:
    ~/.mangocli/presets/<name>/extensions/  (需设 MANGO_PRESET=<name>)
    ~/.mangocli/extensions/  (未设置 MANGO_PRESET 时)

行为:
  * 1-4 个问题, 每个 2-4 个选项, 同步阻塞等用户回答.
  * MANGO_YOLO 跳过 UI, 自动选每题第一个选项.
  * 选项用 m.console.output 渲染, 用 m.console.prompt 收集数字.

契约: 顶层仅 import; 其余符号一律函数体内延迟导入.
"""


from mangopi_cli import ToolBase


class AskUserTool(ToolBase):
    name = "ask_user"
    description = (
        "Ask the user 1-4 multi-choice questions to clarify requirements. "
        "Each question has 2-4 options. The user picks one per question. "
        "Use when truly ambiguous: multiple valid paths, user preference "
        "matters, or the cost of guessing wrong is high. Do NOT use for "
        "trivial decisions you can decide yourself."
    )
    params = {
        "questions": {
            "type": "array",
            "description": (
                "1-4 questions. Each is an object with: "
                "question (string, the actual question, ending in '?'), "
                "header (string, 1-5 words, shown as section label), "
                "options (array of 2-4 objects with label + description), "
                "multiSelect (boolean, default false)."
            ),
        },
    }
    guidance = (
        "Use ask_user when the decision is genuinely ambiguous and the "
        "user's preference matters. Don't ask trivial questions; just decide. "
        "If MANGO_YOLO is set, the tool auto-picks the first option per question."
    )

    MAX_QUESTIONS = 4
    MAX_OPTIONS = 4

    def run(self, args):
        questions = args.get("questions") or []
        if not isinstance(questions, list) or not questions:
            return self.fail("questions array is required (at least 1 question)")

        if len(questions) > self.MAX_QUESTIONS:
            return self.fail(
                f"Too many questions: {len(questions)} > {self.MAX_QUESTIONS}. "
                f"Group them or ask the most important first.")

        for qi, q in enumerate(questions):
            if not isinstance(q, dict):
                return self.fail(f"Question #{qi} is not an object: {q!r}")
            for required in ("question", "header", "options"):
                if required not in q:
                    return self.fail(
                        f"Question #{qi} missing {required!r}; got keys {list(q.keys())}")
            opts = q["options"]
            if not isinstance(opts, list) or not (2 <= len(opts) <= self.MAX_OPTIONS):
                return self.fail(
                    f"Question #{qi} needs 2-{self.MAX_OPTIONS} options, got {len(opts) if isinstance(opts, list) else opts!r}")
            for oi, opt in enumerate(opts):
                if not isinstance(opt, dict) or "label" not in opt or "description" not in opt:
                    return self.fail(
                        f"Question #{qi} option #{oi} missing label/description")

        import mangopi_cli as m

        # YOLO: auto-pick first option per question.
        if m.MANGO_YOLO:
            answers = {
                q["question"]: {"label": q["options"][0]["label"], "auto_picked": True}
                for q in questions
            }
            return self.ok(
                "MANGO_YOLO: auto-picked first option per question.\n"
                + _format_pairs(answers))

        answers: dict = {}
        for qi, q in enumerate(questions):
            chosen = self._ask_one(m, qi, q)
            if chosen is None:
                return self.fail("ask_user aborted (could not parse user input)")
            answers[q["question"]] = chosen
        return self.ok(_format_pairs(answers))

    @staticmethod
    def _ask_one(m, qi: int, q: dict):
        m.console.output("")
        m.console.output(f"[Q{qi + 1}] {q['header']}")
        m.console.output(f"  {q['question']}")
        for i, opt in enumerate(q["options"], 1):
            m.console.output(f"  {i}. {opt['label']}: {opt.get('description', '')}")

        n = len(q["options"])
        multi = bool(q.get("multiSelect"))
        suffix = " (comma-separated)" if multi else ""
        raw = _ask_input(m, f"Choose 1-{n}{suffix}:")
        if raw is None:
            return None
        raw = raw.strip()

        if multi:
            try:
                picks = [int(x) for x in raw.replace(" ", "").split(",") if x]
                picks = [p for p in picks if 1 <= p <= n]
                if not picks:
                    return None
                return {
                    "label": ", ".join(q["options"][p - 1]["label"] for p in picks),
                    "selections": picks,
                }
            except ValueError:
                return None
        if not raw.isdigit():
            return None
        pick = int(raw)
        if not (1 <= pick <= n):
            return None
        return {"label": q["options"][pick - 1]["label"], "selection": pick}


def _ask_input(m, message: str):
    """通用文本输入. console 模式走终端 input(); acp 模式无文本交互通道, 返回 None (调用方 abort)."""
    if m.console.mode == "acp":
        return None
    try:
        return input(f"{m.YELLOW}{message} {m.RESET}")
    except (EOFError, KeyboardInterrupt):
        return None


def _format_pairs(answers: dict) -> str:
    out = []
    for q, a in answers.items():
        out.append(f"  Q: {q}\n  A: {a.get('label')}{' [auto]' if a.get('auto_picked') else ''}")
    return "\n".join(out) if out else "(no answers)"


tools = [AskUserTool()]
