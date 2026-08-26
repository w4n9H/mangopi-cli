"""Shipped-style extension — skill: skill discovery + use_skill tool + skills guidance.

按需启用:
  * 复制/软链本文件到扩展目录:
      ~/.mangocli/extensions/                  (无 MANGO_PRESET)
      ~/.mangocli/presets/<name>/extensions/   (需设 MANGO_PRESET=<name>)

行为:
  * use_skill         — 加载已安装技能 (SKILL.md + scripts/ + references/) 注入上下文;
                        静默规则经 ToolBase.guidance 进入 tool_guidance 段
                        (随 TOOLS 注册自动注入/卸载自动消失, 无需核心改动).
  * prompt_sections() — "skills_guidance" 段 (callable 动态形式): 每次 SystemPrompt
                        构建时输出运行时技能清单. 核心未改时同名覆盖默认段,
                        核心移除默认段后变为追加段, 两种状态均兼容.

设计说明:
  * SkillManager 扫描 ~/.mangocli/skills 与 <cwd>/.mangocli/skills 下的 */SKILL.md
    (YAML frontmatter 解析, load_level="resources" 时附带 scripts/references).
  * 清单与规则分工: 静态规则归工具 guidance (单一数据源: 工具自身声明);
    动态清单归 prompt_sections (唯一能运行时求值的通道).
  * 提示词段用进程级懒加载单例 get_manager(), 会话内技能列表稳定;
    use_skill 每次调用新建 SkillManager 重扫磁盘 (与核心内置时代语义一致).
  * 无技能时 prompt_sections() 返回空列表, 该段整体消失 (比 "No skills available."
    占位更合理; 工具仍在, 模型调用会得到 fail 反馈).

契约: 顶层仅 import; core 符号 (base_persist_dir/console) 在函数体内延迟导入.
"""
import ast
import glob
import os
import re

from mangopi_cli import ToolBase


class SkillManager:
    """按目录发现并加载 SKILL.md; load_level="resources" 时附带 scripts/references."""

    def __init__(self, base_paths=None, load_level: str = "resources"):
        self.base_paths = base_paths or self.default_base_paths()
        self.level = load_level
        try:
            self.skills = self._load_skills()
        except Exception as err:
            self.skills = {}
            import mangopi_cli as m
            m.console.error(f"load skills err: {err}")

    @staticmethod
    def default_base_paths():
        import mangopi_cli as m
        return [os.path.expanduser("~/.mangocli/skills"),
                os.path.join(m.base_persist_dir, "skills")]

    def _load_skills(self) -> dict:
        def _load_directory(_skill_path: str, _dirname: str):
            dir_path = os.path.join(_skill_path, _dirname)
            if not os.path.exists(dir_path):
                return {}
            files = {}
            for root, _, filenames in os.walk(dir_path):
                for file in filenames:
                    path = os.path.join(root, file)
                    with open(path, 'r', encoding='utf-8') as f:
                        files[path] = f.read()
            return files

        skills = {}
        for base in self.base_paths:
            for skill_md in glob.glob(os.path.join(base, "*/SKILL.md")):
                skill_dir = os.path.dirname(skill_md)
                skill_name = os.path.basename(skill_dir)
                with open(skill_md, 'r', encoding='utf-8') as f:
                    content = f.read()

                yaml_end = content.find('---', 3)
                if yaml_end == -1:
                    raise ValueError(f"Invalid SKILL.md: missing YAML frontmatter in {skill_md}")
                yaml_text, body = content[3:yaml_end].strip(), content[yaml_end + 3:].strip()

                meta = {}
                for line in yaml_text.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    key, val = re.split(r':\s*', line, 1)
                    val = val.strip()
                    if val.lower() == 'true':
                        val = True
                    elif val.lower() == 'false':
                        val = False
                    elif val.lower() in ('null', '~'):
                        val = None
                    else:
                        try:
                            val = ast.literal_eval(val)
                        except Exception:
                            pass
                    meta[key.strip()] = val
                meta["body"] = body
                skills[skill_name] = {"meta": meta}
                if self.level == "resources":
                    skills[skill_name].update({
                        "scripts": _load_directory(skill_dir, "scripts"),
                        "references": _load_directory(skill_dir, "references")})
        return skills

    def reload(self):
        try:
            self.skills = self._load_skills()
        except Exception as err:
            self.skills = {}
            import mangopi_cli as m
            m.console.error(f"reload skills err: {err}")

    def all(self) -> dict: return self.skills

    def descriptions(self) -> str:
        return "\n".join(f"- {name}: {data['meta'].get('description', '')}" for name, data in self.skills.items())

    def find(self, keyword: str) -> list:
        matched = []
        for name, data in self.skills.items():
            meta = data.get("meta", {})
            if keyword.lower() in name.lower() or any(keyword.lower() in t.lower() for t in meta.get("tags", [])):
                matched.append({"name": name, "meta": meta})
        return matched


class UseSkillTool(ToolBase):
    name = "use_skill"
    description = "Load an installed skill with guidance, scripts and references"
    params = {"name": {"type": "string", "description": "Skill name"}}
    # 静态使用规则: 经 _build_tool_guidance 自动拼入 tool_guidance 段 (随注册启停)
    guidance = "If an installed skill is relevant, call **use_skill** first before proceeding."

    def run(self, args):
        name = args["name"]
        skills = SkillManager().all()  # 每次调用重扫磁盘, 与原内置时代语义一致
        if name not in skills:
            return self.fail(f"skill '{name}' not found")
        skill = skills[name]
        result = []
        meta = skill.get("meta", {})
        result.append(f"# Skill: {name}")
        result.append(meta.get("body", ""))
        scripts = skill.get("scripts", {})
        if scripts:
            result.append("\n## Scripts\n")
            for path in scripts:
                result.append(path)
        refs = skill.get("references", {})
        if refs:
            result.append("\n## References\n")
            for path in refs:
                result.append(path)
        return self.ok("\n".join(result))


# 进程级懒加载单例: 提示词段构建时首次实例化; 避免扩展导入期触碰 core 符号
_manager = None


def get_manager() -> SkillManager:
    global _manager
    if _manager is None:
        _manager = SkillManager()
    return _manager


def prompt_sections():
    """skills_guidance 段 (动态): 仅运行时技能清单, 静态规则已归工具 guidance."""
    desc = get_manager().descriptions()
    if not desc:
        return []  # 无技能 → 该段整体消失 (核心未改时保留默认占位段)
    return [("skills_guidance", f"## Skills Selection Guidelines\n\n{desc}\n\n")]


tools = [UseSkillTool()]
