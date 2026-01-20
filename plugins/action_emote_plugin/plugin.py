import re
from typing import List, Tuple, Type, Optional

from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    EventType,
    ComponentInfo,
    ConfigField,
    MaiMessages,
    CustomEventHandlerResult,
)
from src.common.logger import get_logger

logger = get_logger("action_emote_plugin")


class ActionEmoteHandler(BaseEventHandler):
    """动作文本处理器 - 将括号动作转为可发送内容"""

    event_type = EventType.AFTER_LLM
    handler_name = "action_emote_handler"
    handler_description = "解析括号动作并发送"
    weight = 80

    async def execute(
        self, message: MaiMessages | None
    ) -> Tuple[bool, bool, str | None, CustomEventHandlerResult | None, MaiMessages | None]:
        if not message:
            return True, True, None, None, None

        if not self.get_config("action_emote.enabled", True):
            return True, True, None, None, None

        content = getattr(message, "llm_response_content", None) or ""
        if not content:
            return True, True, None, None, None

        # 匹配中文括号动作（尽量保留括号内文本）
        pattern = re.compile(r"[（(]([^）)]*)[）)]")
        actions = pattern.findall(content)
        if not actions:
            return True, True, None, None, None

        # 只保留动作内容，避免整段清空导致默认回复
        action_texts = [f"（{action.strip()}）" for action in actions if action.strip()]
        if not action_texts:
            return True, True, None, None, None

        # 是否保留原回复的非动作内容
        keep_original = self.get_config("action_emote.keep_original", True)
        cleaned_content = pattern.sub("", content).strip()

        # 动作触发概率
        trigger_prob_value = self.get_config("action_emote.trigger_probability", 1.0)
        if isinstance(trigger_prob_value, (int, float)):
            trigger_prob = float(trigger_prob_value)
        else:
            try:
                trigger_prob = float(str(trigger_prob_value).strip())
            except (TypeError, ValueError):
                trigger_prob = 1.0
        trigger_prob = max(0.0, min(1.0, trigger_prob))

        # 构建新回复内容
        if trigger_prob < 1.0:
            import random

            if random.random() > trigger_prob:
                if cleaned_content:
                    message.modify_llm_response_content(cleaned_content, suppress_warning=True)
                return True, True, "动作概率未触发", None, message

        if keep_original and cleaned_content:
            new_content = "\n".join(action_texts + [cleaned_content])
        else:
            new_content = "\n".join(action_texts)

        message.modify_llm_response_content(new_content, suppress_warning=True)
        return True, True, "动作内容已替换", None, message


@register_plugin
class ActionEmotePlugin(BasePlugin):
    """动作表情插件 - 控制括号动作输出"""

    plugin_name: str = "action_emote_plugin"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    config_section_descriptions = {"plugin": "插件基本信息", "action_emote": "动作输出配置"}

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        "action_emote": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用动作输出"),
            "keep_original": ConfigField(type=bool, default=False, description="是否保留原文本"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [(ActionEmoteHandler.get_handler_info(), ActionEmoteHandler)]
