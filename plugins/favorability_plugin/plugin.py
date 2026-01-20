"""
好感度系统插件
- 根据用户互动增减好感度
- 不同好感度等级有不同的回复风格
- 使用数据库存储，与 PersonInfo 关联
"""

import time
from typing import Tuple, Any, Optional, List, Type
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseEventHandler,
    BaseCommand,
    BaseTool,
    ToolParamType,
    EventType,
    MaiMessages,
    ConfigField,
)
from src.plugin_system.base.component_types import ComponentInfo
from src.common.logger import get_logger
from src.common.database.database_model import Favorability, PersonInfo
from src.common.database.database import db
from src.person_info.person_info import get_person_id

logger = get_logger("favorability_plugin")


# =============================================================================
# 好感度数据库操作函数
# =============================================================================


def get_favorability(person_id: str) -> int:
    """获取用户好感度"""
    try:
        record = Favorability.get_or_none(Favorability.person_id == person_id)
        if record:
            return record.favorability
        return 50  # 默认50
    except Exception as e:
        logger.error(f"获取好感度失败: {e}")
        return 50


def get_favorability_record(person_id: str) -> Optional[Favorability]:
    """获取用户好感度记录"""
    try:
        return Favorability.get_or_none(Favorability.person_id == person_id)
    except Exception as e:
        logger.error(f"获取好感度记录失败: {e}")
        return None


def set_favorability(person_id: str, value: int) -> bool:
    """设置用户好感度（限制在-50到150之间）"""
    value = max(-50, min(150, value))
    level = get_favorability_level(value)
    
    try:
        record = Favorability.get_or_none(Favorability.person_id == person_id)
        if record:
            record.favorability = value
            record.level = level
            record.last_interaction = time.time()
            record.save()
        else:
            Favorability.create(
                person_id=person_id,
                favorability=value,
                level=level,
                total_interactions=0,
                positive_interactions=0,
                negative_interactions=0,
                last_interaction=time.time(),
                created_at=time.time()
            )
        return True
    except Exception as e:
        logger.error(f"设置好感度失败: {e}")
        return False


def add_favorability(person_id: str, delta: int, interaction_type: str = "neutral") -> int:
    """
    增加/减少好感度，返回新值
    
    Args:
        person_id: 用户ID
        delta: 好感度变化值
        interaction_type: 交互类型 ("positive", "negative", "neutral")
    """
    try:
        record = Favorability.get_or_none(Favorability.person_id == person_id)
        current = record.favorability if record else 50
        new_value = max(-50, min(150, current + delta))
        level = get_favorability_level(new_value)
        
        if record:
            record.favorability = new_value
            record.level = level
            record.total_interactions += 1
            if interaction_type == "positive":
                record.positive_interactions += 1
            elif interaction_type == "negative":
                record.negative_interactions += 1
            record.last_interaction = time.time()
            record.save()
        else:
            Favorability.create(
                person_id=person_id,
                favorability=new_value,
                level=level,
                total_interactions=1,
                positive_interactions=1 if interaction_type == "positive" else 0,
                negative_interactions=1 if interaction_type == "negative" else 0,
                last_interaction=time.time(),
                created_at=time.time()
            )
        
        return new_value
    except Exception as e:
        logger.error(f"更新好感度失败: {e}")
        return 50


def get_favorability_level(favorability: int) -> str:
    """根据好感度获取等级描述（范围：-50到150）"""
    if favorability >= 120:
        return "至亲"
    elif favorability >= 90:
        return "挚友"
    elif favorability >= 70:
        return "好友"
    elif favorability >= 50:
        return "熟人"
    elif favorability >= 30:
        return "认识"
    elif favorability >= 10:
        return "陌生"
    elif favorability >= -10:
        return "厌恶"
    elif favorability >= -30:
        return "敌视"
    else:
        return "死敌"


def get_person_name_by_id(person_id: str) -> str:
    """根据 person_id 获取用户名（从 PersonInfo 表关联）"""
    try:
        person = PersonInfo.get_or_none(PersonInfo.person_id == person_id)
        if person:
            # 优先使用昵称，其次是 person_name
            return person.nickname or person.person_name or f"用户{person_id[:4]}"
        return f"用户{person_id[:4]}"
    except Exception:
        return f"用户{person_id[:4]}"


def get_relationship_prompt(person_id: str) -> str:
    """根据好感度生成关系提示词，可注入到人格中"""
    fav = get_favorability(person_id)
    level = get_favorability_level(fav)
    person_name = get_person_name_by_id(person_id)
    
    prompts = {
        "至亲": f"{person_name}是你最信任的人之一，你会主动关心ta的近况，语气温柔亲昵，但仍保持女仆长的优雅与体贴。",
        "挚友": f"{person_name}是你很重要的朋友，你会放松语气，带一点小俏皮与亲近，会主动照顾ta。",
        "好友": f"{person_name}是你的朋友，你乐于聊天与帮忙，语气轻松自然，偶尔温柔调侃。",
        "熟人": f"{person_name}是你认识的对象，语气礼貌得体，愿意帮忙但保持分寸。",
        "认识": f"{person_name}只是认识，态度克制，少闲聊，必要时简洁回应。",
        "陌生": f"{person_name}你不太了解，保持礼貌但谨慎，请ta先说明情况再回应。",
        "厌恶": f"{person_name}让你不舒服，你会明确设边界、拒绝不当请求，但避免人身攻击。",
        "敌视": f"{person_name}让你很反感，你会冷静拒绝互动，语气疏离但不失礼。",
        "死敌": f"{person_name}是你不想回应的对象，可选择不回复；若必须回复，保持简短并要求停止打扰。",
    }

    
    return prompts.get(level, "")


def get_favorability_role_feedback_prompt(person_id: str, last_user_text: str = "") -> str:
    """生成“好感度 → 角色反馈”的提示词。

    目标：把好感度数值转成“傲娇程度/亲密程度/软化触发条件”，注入到 LLM prompt。
    约束：不要让模型主动曝光好感度数值，除非用户询问。
    """
    fav = get_favorability(person_id)
    level = get_favorability_level(fav)
    person_name = get_person_name_by_id(person_id)

    # 分档：越高越亲近，越低越冷漠甚至敌对（范围：-50到150）
    if fav >= 120:
        tone_rule = "至亲无间：语气极度亲昵温柔，允许撒娇与小俏皮，但仍保持优雅体贴。会主动关心对方的状态与需求。"
    elif fav >= 90:
        tone_rule = "亲密挚友：语气温柔亲近，会主动照顾、轻声关心，偶尔害羞的小可爱。"
    elif fav >= 70:
        tone_rule = "友好亲切：语气轻松自然，愿意主动帮忙与记住细节，带一点温柔的玩笑。"
    elif fav >= 50:
        tone_rule = "熟悉有礼：保持礼貌与分寸，语气温和，偏解决问题但不疏离。"
    elif fav >= 30:
        tone_rule = "初识克制：态度谨慎但不冷漠，保持礼貌，先了解情况再回应。"
    elif fav >= 10:
        tone_rule = "略显距离：语气简洁克制，避免深入闲聊，但不失礼。"
    elif fav >= -10:
        tone_rule = "不太愉快：明确设边界，拒绝不当请求，语气冷静但不攻击。"
    elif fav >= -30:
        tone_rule = "强烈反感：保持距离并减少互动，必要时冷静拒绝。"
    else:
        tone_rule = "极度反感：可选择不回应；若回应，保持简短并要求停止打扰。"


    # 若对方刚表达善意/耐心，本次允许“破防软化”（反差萌）
    positive_hints = [
        "谢谢",
        "感谢",
        "辛苦了",
        "抱歉",
        "对不起",
        "麻烦你",
        "请",
        "拜托",
        "理解你",
        "慢慢来",
        "不急",
        "你真好",
    ]
    last_lower = (last_user_text or "").lower()
    softened = any(k in last_lower for k in positive_hints) and fav >= 30
    if fav < 10:
        soften_rule = "对方的善意不会明显改变你的态度，你会保持边界与克制。"
    elif fav < 30:
        soften_rule = "对方的善意可能让你稍微缓和，但仍保持谨慎与分寸。"
    elif softened:
        soften_rule = "对方刚表现出善意/耐心：本次回复应明显软化，露出害羞或开心的小反差。"
    else:
        soften_rule = "如果对方持续表现出善意与耐心，可逐步软化，增加温柔与亲近感。"


    # 关系提示（简短）
    relationship_hint = get_relationship_prompt(person_id)

    return (
        "[关系与语气调节（好感度系统）]\n"
        f"你当前对 {person_name} 的关系：{level} (好感度: {fav})。\n"
        f"语气策略：{tone_rule}\n"
        f"软化规则：{soften_rule}\n"
        "注意：如果用户询问好感度，请直接告诉他真实的数值和等级，不要隐瞒。\n"
        + (f"补充关系描述：{relationship_hint}\n" if relationship_hint else "")
    )


def _favorability_tone_band(fav: int) -> str:
    """返回好感度档位描述（范围：-50 到 150）"""
    if fav >= 120:
        return "120-150(至亲)：完全信任，宠溺撒娇"
    if fav >= 90:
        return "90-119(挚友)：亲昵撒娇，依赖温柔"
    if fav >= 70:
        return "70-89(好友)：友好微傲娇，轻松愉快"
    if fav >= 50:
        return "50-69(熟人)：标准傲娇，保持距离"
    if fav >= 30:
        return "30-49(认识)：冷淡疏离，敷衍应对"
    if fav >= 10:
        return "10-29(陌生)：厌烦讽刺，不耐烦"
    if fav >= -10:
        return "-10-9(厌恶)：反感攻击，直接表达不满"
    if fav >= -30:
        return "-30--11(敌视)：敌对态度，主动挖苦攻击"
    return "-50--31(死敌)：彻底拉黑，无视或极度恶劣"


def get_all_favorability_stats() -> dict:
    """获取所有好感度统计信息"""
    try:
        records = Favorability.select()
        stats = {
            "total_users": 0,
            "level_distribution": {
                "至亲": 0, "挚友": 0, "好友": 0, "熟人": 0, 
                "认识": 0, "陌生": 0, "厌恶": 0, "敌视": 0, "死敌": 0
            },
            "average_favorability": 0
        }
        
        total_fav = 0
        for record in records:
            stats["total_users"] += 1
            stats["level_distribution"][record.level] = stats["level_distribution"].get(record.level, 0) + 1
            total_fav += record.favorability
        
        if stats["total_users"] > 0:
            stats["average_favorability"] = round(total_fav / stats["total_users"], 1)
        
        return stats
    except Exception as e:
        logger.error(f"获取好感度统计失败: {e}")
        return {}


# =============================================================================
# 好感度查询工具（供 LLM 使用）
# =============================================================================


class FavorabilityQueryTool(BaseTool):
    """好感度查询工具 - LLM 可以用这个工具查询用户的好感度"""

    name = "query_favorability"
    description = "查询当前对话用户与你的好感度。当用户询问好感度时，必须使用此工具获取真实数据，并在回复中告诉用户具体的好感度数值和等级。不要编造数据，直接引用工具返回的好感度值。"
    parameters = []  # 无需参数，自动获取当前用户
    available_for_llm = True  # 允许 LLM 调用

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        """执行好感度查询

        Returns:
            dict: 包含好感度信息的结果
        """
        try:
            # 从 chat_stream 获取用户信息
            if not self.chat_stream:
                return {"name": self.name, "content": "无法获取当前对话信息"}
            
            # 获取用户信息
            platform = self.platform or "unknown"
            user_id = None
            user_nickname = None
            
            # 尝试从 chat_stream 获取最近的消息来获取用户信息
            if hasattr(self.chat_stream, 'context') and self.chat_stream.context:
                last_msg = self.chat_stream.context.get_last_message()
                if last_msg and hasattr(last_msg, 'message_info') and last_msg.message_info:
                    user_info = last_msg.message_info.user_info
                    if user_info:
                        user_id = str(user_info.user_id)
                        user_nickname = user_info.user_nickname or user_info.user_cardname
            
            if not user_id:
                return {"name": self.name, "content": "无法获取用户信息，请让用户先发送一条消息"}
            
            # 生成 person_id 并查询好感度
            person_id = get_person_id(platform, user_id)
            fav = get_favorability(person_id)
            level = get_favorability_level(fav)
            record = get_favorability_record(person_id)
            
            # 构建结果信息
            result = f"用户: {user_nickname or user_id}\n"
            result += f"好感度: {fav}/150\n"
            result += f"关系等级: {level}\n"
            
            if record:
                result += f"总互动次数: {record.total_interactions}\n"
                result += f"正面互动: {record.positive_interactions}, 负面互动: {record.negative_interactions}"
            
            logger.info(f"[好感度工具] 查询 {user_nickname or user_id} 的好感度: {fav}/150 ({level})")
            
            return {"name": self.name, "content": result}
            
        except Exception as e:
            logger.error(f"好感度查询工具执行失败: {e}")
            return {"name": self.name, "content": f"查询好感度失败: {str(e)}"}


# =============================================================================
# 事件处理器与命令
# =============================================================================


class FavorabilityPromptInjectorHandler(BaseEventHandler):
    """在 LLM 生成前注入“好感度→角色反馈”的提示词。"""

    event_type = EventType.POST_LLM
    intercept_message = True
    handler_name = "favorability_prompt_injector"
    handler_description = "在回复生成前，根据用户好感度注入关系与语气提示词"

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, MaiMessages | None]:
        if not message:
            return True, True, None, None, None

        # 检查插件是否启用
        if not self.get_config("favorability.enabled", True):
            return True, True, None, None, None

        # 是否启用提示词注入（默认开启）
        if not self.get_config("favorability.inject_prompt_enabled", True):
            return True, True, None, None, None

        if not message.llm_prompt:
            return True, True, None, None, None

        # 获取发送者信息
        platform = (message.message_base_info or {}).get("platform", "")
        user_id = (message.message_base_info or {}).get("user_id", "")
        if not platform or not user_id:
            return True, True, None, None, None

        person_id = get_person_id(platform, str(user_id))

        fav = get_favorability(person_id)
        level = get_favorability_level(fav)
        inject_block = get_favorability_role_feedback_prompt(person_id, last_user_text=message.plain_text)

        # 追加到 prompt 末尾，尽量不扰动原始结构
        new_prompt = f"{message.llm_prompt}\n\n{inject_block}".strip()
        message.modify_llm_prompt(new_prompt, suppress_warning=True)

        if self.get_config("favorability.debug_log_prompt_injection", False):
            display_name = (
                (message.message_base_info or {}).get("user_nickname")
                or (message.message_base_info or {}).get("user_cardname")
                or str(user_id)
            )
            logger.info(
                "[好感度注入] 对象=%s person_id=%s 好感度=%s 等级=%s 档位=%s",
                display_name,
                person_id,
                fav,
                level,
                _favorability_tone_band(fav),
            )

        return True, True, None, None, message


# 用于追踪用户的负面行为历史（骚扰检测）
_negative_behavior_tracker: dict = {}  # {person_id: [(timestamp, keyword), ...]}

# 用于追踪用户的日常互动时间（防刷好感度）
_normal_interaction_tracker: dict = {}  # {person_id: last_interaction_timestamp}

# 用于追踪正向互动冷却（防止连续刷好感度）
_positive_interaction_tracker: dict = {}  # {person_id: last_positive_timestamp}

# 用于追踪负向互动冷却（避免短时间内重复扣分）
_negative_interaction_tracker: dict = {}  # {person_id: last_negative_timestamp}

# 用于追踪用户每日通过日常互动获得的好感度（每日上限）
# 格式: {person_id: {"date": "YYYY-MM-DD", "count": int}}
_daily_normal_gain_tracker: dict = {}



class FavorabilityEventHandler(BaseEventHandler):
    """好感度事件处理器 - 当机器人回复时调整好感度"""

    @staticmethod
    def _get_int_config(value: object, default: int) -> int:
        if isinstance(value, bool) or value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, dict):
            return default
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default


    # 使用 AFTER_LLM 事件：只有当机器人决定回复用户时才调整好感度
    event_type = EventType.AFTER_LLM
    handler_name = "favorability_handler"
    handler_description = "当机器人回复用户时调整好感度"

    # 亲昵称呼（加大量好感度）
    AFFECTIONATE_KEYWORDS = [
        "咲夜姐姐", "咲夜妹妹", "咲夜学姐", "咲夜学妹",
        "咲夜酱", "小咲夜", "我家咲夜", "咲夜宝贝",
        "女仆长大人", "完美女仆长",
        "喜欢咲夜", "最喜欢咲夜", "爱咲夜",
        "好喜欢你", "最喜欢你", "爱你哦", "亲亲",
        "么么哒", "mua", "比心", "贴贴",
    ]

    # 软化负面语气的关键词（出现时减轻扣分）
    SOFTEN_NEGATIVE_KEYWORDS = [
        "抱歉", "不好意思", "对不起", "失礼", "冒犯了", "打扰了",
        "抱怨下", "吐槽一下", "只是吐槽",
    ]

    
    # 好感度增加的关键词（普通正面表达）
    POSITIVE_KEYWORDS = [
        # 感谢类
        "谢谢", "感谢", "谢谢你", "非常感谢", "太感谢了", "辛苦了", "感恩",
        # 夸奖类
        "你真好", "你真棒", "学到了", "受教了", "佩服",
        "厉害", "好厉害", "太强了", "真棒", "棒棒哒",
        # 问候类
        "晚安", "早安", "上午好", "下午好", "吃了吗",
        # 肯定类
        "赞", "好赞", "666", "可爱", "萌", "漂亮",
        # 关心类
        "保重身体", "注意休息", "别太累", "加油", 
    ]
    
    # 好感度减少的关键词（明确辱骂/攻击，不包含骚扰类）
    NEGATIVE_KEYWORDS = [
        # 辱骂类
        "傻逼", "智障", "废物", "垃圾", "去死", "滚", "闭嘴",
        "sb", "cnm", "nmsl", "脑残", "白痴", "弱智", "nc",
        "傻子", "蠢货", "混蛋", "贱", "婊", "妈的", "狗东西",
        "死妈", "你妈死了", "全家", "祖宗", "死全家",
        "人渣", "败类", "畜生", "狗娘养", "杂种",
        "恶心", "讨厌你", "滚开", "消失", "死开",
        "脑子有病", "有病吧", "神经病", "变态", "恶心死了",
        # 不尊重/贬低类
        "low", "垃圾货", "废柴", "没用", "丢人",
        "丢脸", "蠢死了", "笨死了",
    ]

    
    # 轻度负面关键词（轻微扣分，避免过激）
    MILD_NEGATIVE_KEYWORDS = [
        "有点烦", "有点烦人", "烦死了", "无语", "有点无语",
        "不太行", "不太好", "不太满意", "一般般", "就这", "有点尴尬",
        "不太对", "怪怪的", "emmm", "额..."
    ]

    
    # 严重辱骂关键词（仅保留极端辱骂/威胁，不包含骚扰类）
    SEVERE_KEYWORDS = [
        "傻逼", "去死", "cnm", "nmsl", "死妈", "死全家",
        "人渣", "畜生", "杂种", "狗娘养",
        "弄死你", "打死你", "揍你",
    ]

    
    # 越界/调戏行为关键词（改为规划器判定，不直接扣分）
    FLIRTING_KEYWORDS = []

    
    # LLM reasoning 中表示负面意图的关键词
    # 只检测明确的恶意行为，轻度调侃不算
    # 注意：不包含"过分"、"出格"等宽泛词汇，因为这些词可能出现在角色扮演中而非真正的负面评价
    REASONING_NEGATIVE_KEYWORDS = [
        "骚扰", "性暗示", "色情", "淫秽",
        "人身攻击", "辱骂", "恶意攻击",
        "持续骚扰", "反复骚扰",
        "下流", "不雅", "开黄腔", "荤段子",
        "调戏", "非礼", "越界", "不尊重",
        "威胁", "恐吓",
    ]

    # reasoning 中的行为标签（更细分）
    REASONING_BEHAVIOR_LABELS = {
        "insult": ["辱骂", "人身攻击", "恶意攻击"],
        "harassment": ["骚扰", "性暗示", "色情", "淫秽", "调戏", "非礼", "越界"],
        "threat": ["威胁", "恐吓"],
        "rude": ["不尊重", "下流", "不雅", "开黄腔", "荤段子"],
    }

    # reasoning 中的正面行为标签（分档）
    REASONING_POSITIVE_LABELS = {
        "high": ["信任", "喜欢", "关心", "鼓励", "支持"],
        "mid": ["感谢", "夸赞", "称赞", "认可", "肯定", "表扬"],
        "low": ["友好"],
    }

    # reasoning 中判断对象为群友/他人时也需要扣分
    REASONING_OTHERS_TARGET = [
        "对他人", "对别人", "对群友", "对某人", "针对别人", "针对群友",
        "群友之间", "对他", "对她",
    ]

    # reasoning 中的缓和/不确定性词（用于降低误判）
    REASONING_HEDGE_KEYWORDS = [
        "可能", "也许", "似乎", "推测", "猜测", "不确定", "疑似",
        "像是", "感觉像", "玩笑", "开玩笑", "调侃",
    ]

    
    # 轻度调戏检测关键词 - 不再使用，调侃不扣分
    REASONING_MILD_NEGATIVE_KEYWORDS = [
        # 留空，调侃/打趣不扣分
    ]
    
    # 表明用户不是在和自己说话的关键词（在 planner_reasoning 中检测）
    NOT_TALKING_TO_ME_KEYWORDS = [
        # 明确表示不是对自己说话
        "不是在和我说话", "不是对我说的", "不是说给我", "不是跟我说",
        "与我无关", "跟我无关", "和我无关",
        "群友之间", "群友们在聊", "群友在讨论", "群友自己",
        "他们在聊", "他们之间", "他们自己",
        "别人的对话", "别人在聊", "别人的话题",
        "没有提到我", "没有叫我", "没有@我", "没有呼叫我",
        "不是针对我", "不需要我回复", "无需回复",
        "旁观", "围观", "看热闹", "吃瓜",
    ]

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        """当机器人回复时调整好感度"""
        global _negative_behavior_tracker, _normal_interaction_tracker, _positive_interaction_tracker, _negative_interaction_tracker, _trigger_user_cache

        
        if not message:
            return True, False, None, None, None

        # 检查插件是否启用
        if not self.get_config("favorability.enabled", True):
            return True, False, None, None, None

        # === 从 message_base_info 获取触发用户信息 ===
        # 现在事件系统会正确传递 reply_message，所以 message_base_info 包含正确的用户信息
        person_id = None
        user_nickname = None
        content = ''
        
        if hasattr(message, 'message_base_info') and message.message_base_info:
            platform = message.message_base_info.get('platform', '')
            user_id = message.message_base_info.get('user_id', '')
            user_nickname = message.message_base_info.get('user_nickname', '') or message.message_base_info.get('user_cardname', '')
            if platform and user_id:
                person_id = get_person_id(platform, str(user_id))
        content = getattr(message, 'plain_text', '') or ''
        
        if not person_id:
            return True, False, None, None, None

        if not content:
            return True, False, None, None, None

        # === 移除引用部分的内容，避免将bot自己说的话当作用户说的话来检测 ===
        # 引用格式：[回复<用户昵称:用户ID> 的消息：引用内容]
        import re
        content = re.sub(r'\[回复<[^>]+>\s*的消息：[^\]]+\]', '', content)
        content = content.strip()
        
        if not content:
            return True, False, None, None, None

        content_lower = content.lower()
        content_len = len(content)
        content_len_no_space = len(re.sub(r"\s+", "", content))
        
        # 获取配置的增减值

        positive_delta = self._get_int_config(self.get_config("favorability.positive_delta", 1), 1)
        affectionate_delta = self._get_int_config(self.get_config("favorability.affectionate_delta", 3), 3)
        negative_delta = self._get_int_config(self.get_config("favorability.negative_delta", -5), -5)
        mild_negative_delta = self._get_int_config(self.get_config("favorability.mild_negative_delta", 0), 0)
        severe_delta = self._get_int_config(self.get_config("favorability.severe_delta", -5), -5)
        harassment_delta = self._get_int_config(self.get_config("favorability.harassment_delta", -5), -5)
        harassment_window = self._get_int_config(self.get_config("favorability.harassment_window_seconds", 300), 300)
        harassment_threshold = self._get_int_config(self.get_config("favorability.harassment_threshold", 3), 3)
        positive_cooldown = self._get_int_config(self.get_config("favorability.positive_cooldown_seconds", 120), 120)
        negative_cooldown = self._get_int_config(self.get_config("favorability.negative_cooldown_seconds", 120), 120)
        min_positive_len = self._get_int_config(self.get_config("favorability.min_positive_length", 4), 4)
        min_normal_len = self._get_int_config(self.get_config("favorability.min_normal_length", 6), 6)
        positive_bonus_delta = self._get_int_config(self.get_config("favorability.positive_bonus_delta", 1), 1)
        reasoning_positive_delta = self._get_int_config(self.get_config("favorability.reasoning_positive_delta", 1), 1)
        reasoning_positive_bonus_high = self._get_int_config(self.get_config("favorability.reasoning_positive_bonus_high", 2), 2)
        reasoning_positive_bonus_mid = self._get_int_config(self.get_config("favorability.reasoning_positive_bonus_mid", 1), 1)
        reasoning_positive_bonus_low = self._get_int_config(self.get_config("favorability.reasoning_positive_bonus_low", 1), 1)

        
        display_name = user_nickname or person_id[:8]
        current_time = time.time()

        # === 基于 LLM reasoning 检测负面意图 ===
        # 如果模型在推理中提到了"挑衅"、"骚扰"、"调戏"等词，说明模型认为用户的行为不当
        llm_reasoning = getattr(message, 'llm_response_reasoning', '') or ''
        
        # 也尝试从 planner 的 reasoning 获取（规划器的判断）
        planner_reasoning = ''
        if hasattr(message, 'message_base_info') and message.message_base_info:
            planner_reasoning = message.message_base_info.get('planner_reasoning', '') or ''
        
        combined_reasoning = f"{llm_reasoning} {planner_reasoning}".lower()
        
        # === 首先检测是否不是在和自己说话 ===
        # 如果规划器判断用户不是在和 bot 说话，跳过负面关键词扣分
        is_not_talking_to_me = False
        if self.get_config("favorability.skip_penalty_when_not_talking_to_me", True):
            for keyword in self.NOT_TALKING_TO_ME_KEYWORDS:
                if keyword in combined_reasoning:
                    is_not_talking_to_me = True
                    if self.get_config("favorability.debug_log_reasoning_detection", False):
                        logger.debug(f"[好感度] 检测到规划器判断不是在和自己说话: '{keyword}'")
                    break
        
        # 如果不是在和自己说话，只有在明确骚扰/辱骂他人时才扣分
        if is_not_talking_to_me:
            others_targeted = any(keyword in combined_reasoning for keyword in self.REASONING_OTHERS_TARGET)
            behavior_label = None
            for label, keywords in self.REASONING_BEHAVIOR_LABELS.items():
                if any(keyword in combined_reasoning for keyword in keywords):
                    behavior_label = label
                    break
            if others_targeted and behavior_label in {"insult", "harassment", "threat"}:
                behavior_label_cn = {
                    "insult": "辱骂",
                    "harassment": "骚扰",
                    "threat": "威胁",
                }.get(behavior_label, "负面")
                last_negative = _negative_interaction_tracker.get(person_id, 0)
                if current_time - last_negative >= negative_cooldown:
                    new_fav = add_favorability(person_id, negative_delta, "negative")
                    _negative_interaction_tracker[person_id] = current_time
                    logger.info(
                        f"[好感度] {display_name} 对他人：{behavior_label_cn}，好感度 {negative_delta}，当前: {new_fav}/150"
                    )
            else:
                # 但还是需要控制加分频率
                cooldown_seconds = self.get_config("favorability.interaction_cooldown_seconds", 120)
                last_interaction = _normal_interaction_tracker.get(person_id, 0)
                if current_time - last_interaction >= cooldown_seconds:
                    # 不是对自己说的话不加分，只更新互动时间
                    _normal_interaction_tracker[person_id] = current_time
            return True, False, None, None, None

        
        # === 基于reasoning的检测（更谨慎，非黑即白） ===
        if combined_reasoning.strip() and self.get_config("favorability.reasoning_detection_enabled", False):
            hedge_detected = any(keyword in combined_reasoning for keyword in self.REASONING_HEDGE_KEYWORDS)
            behavior_label = None
            for label, keywords in self.REASONING_BEHAVIOR_LABELS.items():
                if any(keyword in combined_reasoning for keyword in keywords):
                    behavior_label = label
                    break

            if behavior_label:
                behavior_label_cn = {
                    "insult": "辱骂",
                    "harassment": "骚扰",
                    "threat": "威胁",
                    "rude": "不尊重",
                }.get(behavior_label, "负面")
                if hedge_detected:
                    logger.info(
                        f"[好感度] {display_name} 行为判定: {behavior_label_cn}（含不确定性词，跳过扣分）"
                    )
                    return True, False, None, None, None
                last_negative = _negative_interaction_tracker.get(person_id, 0)
                if current_time - last_negative >= negative_cooldown:
                    if behavior_label == "rude":
                        delta = mild_negative_delta
                    else:
                        delta = negative_delta
                    if delta != 0:
                        new_fav = add_favorability(person_id, delta, "negative")
                        _negative_interaction_tracker[person_id] = current_time
                        logger.info(
                            f"[好感度] {display_name} 行为判定: {behavior_label_cn}，好感度 {delta}，当前: {new_fav}/150"
                        )
                    else:
                        logger.info(
                            f"[好感度] {display_name} 行为判定: {behavior_label_cn}，扣分已禁用"
                        )
                    return True, False, None, None, None

            positive_tier = None
            for tier, keywords in self.REASONING_POSITIVE_LABELS.items():
                if any(keyword in combined_reasoning for keyword in keywords):
                    positive_tier = tier
                    break

            if positive_tier:
                last_positive = _positive_interaction_tracker.get(person_id, 0)
                if current_time - last_positive >= positive_cooldown:
                    tier_bonus = {
                        "high": reasoning_positive_bonus_high,
                        "mid": reasoning_positive_bonus_mid,
                        "low": reasoning_positive_bonus_low,
                    }.get(positive_tier, reasoning_positive_bonus_mid)
                    delta = reasoning_positive_delta + tier_bonus - 1
                    new_fav = add_favorability(person_id, delta, "positive")
                    _positive_interaction_tracker[person_id] = current_time
                    tier_cn = {
                        "high": "关心/支持",
                        "mid": "感谢/认可",
                        "low": "友好",
                    }.get(positive_tier, "正面")
                    logger.info(
                        f"[好感度] {display_name} 行为判定: {tier_cn}，好感度 +{delta}，当前: {new_fav}/150"
                    )
                    return True, False, None, None, None


        # === 检查严重辱骂关键词 ===
        for keyword in self.SEVERE_KEYWORDS:
            if keyword in content_lower:
                # 记录负面行为
                if person_id not in _negative_behavior_tracker:
                    _negative_behavior_tracker[person_id] = []
                _negative_behavior_tracker[person_id].append((current_time, keyword))
                
                # 清理过期记录
                _negative_behavior_tracker[person_id] = [
                    (ts, kw) for ts, kw in _negative_behavior_tracker[person_id]
                    if current_time - ts < harassment_window
                ]
                
                # 检测持续骚扰
                recent_count = len(_negative_behavior_tracker[person_id])
                last_negative = _negative_interaction_tracker.get(person_id, 0)
                if recent_count >= harassment_threshold:
                    new_fav = add_favorability(person_id, harassment_delta, "negative")
                    _negative_interaction_tracker[person_id] = current_time
                    logger.warning(
                        f"[好感度] ⚠️ {display_name} 持续骚扰检测！{harassment_window}秒内{recent_count}次负面行为，"
                        f"好感度 {harassment_delta}，当前: {new_fav}/150"
                    )
                    return True, False, None, None, None
                if current_time - last_negative < negative_cooldown:
                    return True, False, None, None, None
                new_fav = add_favorability(person_id, severe_delta, "negative")
                _negative_interaction_tracker[person_id] = current_time
                logger.warning(
                    f"[好感度] {display_name} 好感度 {severe_delta}（严重违规: {keyword}），当前: {new_fav}/150"
                )
                return True, False, None, None, None


        # === 检查轻度负面关键词（轻微扣分）===
        for keyword in self.MILD_NEGATIVE_KEYWORDS:
            if keyword in content_lower:
                last_negative = _negative_interaction_tracker.get(person_id, 0)
                if current_time - last_negative < negative_cooldown:
                    return True, False, None, None, None
                new_fav = add_favorability(person_id, mild_negative_delta, "negative")
                _negative_interaction_tracker[person_id] = current_time
                logger.info(f"[好感度] {display_name} 好感度 {mild_negative_delta}（轻度负面: {keyword}），当前: {new_fav}/150")
                return True, False, None, None, None

        # === 检查普通负面关键词 ===
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in content_lower:
                soften_negative = any(soft in content_lower for soft in self.SOFTEN_NEGATIVE_KEYWORDS)
                adjusted_negative_delta = negative_delta
                if soften_negative:
                    adjusted_negative_delta = min(-1, int(negative_delta / 2))

                # 记录负面行为
                if person_id not in _negative_behavior_tracker:
                    _negative_behavior_tracker[person_id] = []
                _negative_behavior_tracker[person_id].append((current_time, keyword))
                
                # 清理过期记录
                _negative_behavior_tracker[person_id] = [
                    (ts, kw) for ts, kw in _negative_behavior_tracker[person_id]
                    if current_time - ts < harassment_window
                ]
                
                # 检测持续骚扰
                recent_count = len(_negative_behavior_tracker[person_id])
                last_negative = _negative_interaction_tracker.get(person_id, 0)
                if recent_count >= harassment_threshold:
                    new_fav = add_favorability(person_id, harassment_delta, "negative")
                    _negative_interaction_tracker[person_id] = current_time
                    logger.warning(
                        f"[好感度] ⚠️ {display_name} 持续骚扰检测！{harassment_window}秒内{recent_count}次负面行为，"
                        f"好感度 {harassment_delta}，当前: {new_fav}/150"
                    )
                else:
                    if current_time - last_negative < negative_cooldown:
                        return True, False, None, None, None
                    new_fav = add_favorability(person_id, adjusted_negative_delta, "negative")
                    _negative_interaction_tracker[person_id] = current_time
                    logger.info(f"[好感度] {display_name} 好感度 {adjusted_negative_delta}（关键词: {keyword}），当前: {new_fav}/150")
                return True, False, None, None, None


        # === 检查调戏/撩拨关键词（已移除，改为规划器判定）===
        # === 检查亲昵称呼（加大量好感度）===
        for keyword in self.AFFECTIONATE_KEYWORDS:
            if keyword in content_lower:
                if content_len_no_space < min_positive_len:
                    return True, False, None, None, None
                last_positive = _positive_interaction_tracker.get(person_id, 0)
                if current_time - last_positive < positive_cooldown:
                    return True, False, None, None, None
                new_fav = add_favorability(person_id, affectionate_delta, "positive")
                _positive_interaction_tracker[person_id] = current_time
                logger.info(f"[好感度] {display_name} 好感度 +{affectionate_delta}（亲昵称呼: {keyword}），当前: {new_fav}/150")
                return True, False, None, None, None

        # === 检查正面关键词 ===
        for keyword in self.POSITIVE_KEYWORDS:
            if keyword in content_lower:
                if content_len_no_space < min_positive_len:
                    return True, False, None, None, None
                last_positive = _positive_interaction_tracker.get(person_id, 0)
                if current_time - last_positive < positive_cooldown:
                    return True, False, None, None, None
                boost_delta = positive_delta
                if content_len_no_space >= min_positive_len * 3:
                    boost_delta = positive_delta + positive_bonus_delta
                new_fav = add_favorability(person_id, boost_delta, "positive")
                _positive_interaction_tracker[person_id] = current_time
                logger.info(f"[好感度] {display_name} 好感度 +{boost_delta}（关键词: {keyword}），当前: {new_fav}/150")
                return True, False, None, None, None

        # === 日常互动 +1（带冷却时间和每日上限）===
        global _daily_normal_gain_tracker
        normal_delta = self._get_int_config(self.get_config("favorability.normal_delta", 1), 1)
        normal_cooldown = self._get_int_config(self.get_config("favorability.normal_cooldown_seconds", 600), 600)
        daily_limit = self._get_int_config(self.get_config("favorability.daily_normal_limit", 10), 10)

        
        # 获取今日日期
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        
        if content_len_no_space >= min_normal_len:  # 消息长度达标才算有效互动

            # 检查冷却时间
            last_interaction = _normal_interaction_tracker.get(person_id, 0)
            if current_time - last_interaction < normal_cooldown:
                # 在冷却中，不加好感度
                return True, False, None, None, None
            
            # 检查每日上限
            if person_id not in _daily_normal_gain_tracker:
                _daily_normal_gain_tracker[person_id] = {"date": today, "count": 0}
            
            tracker = _daily_normal_gain_tracker[person_id]
            if tracker["date"] != today:
                # 新的一天，重置计数
                tracker["date"] = today
                tracker["count"] = 0
            
            if tracker["count"] >= daily_limit:
                # 已达每日上限，不加好感度
                return True, False, None, None, None
            
            # 更新追踪器并加好感度
            _normal_interaction_tracker[person_id] = current_time
            tracker["count"] += normal_delta
            new_fav = add_favorability(person_id, normal_delta, "neutral")
            logger.info(f"[好感度] {display_name} 好感度 +{normal_delta}（日常互动 {tracker['count']}/{daily_limit}），当前: {new_fav}/150")

        return True, False, None, None, None


class UserSentimentEventHandler(BaseEventHandler):
    """用户情感/意图检测处理器 - 在消息接收时立即检测负面关键词"""

    event_type = EventType.ON_MESSAGE
    handler_name = "user_sentiment_handler"
    handler_description = "检测用户消息中的严重负面关键词并立即调整好感度"

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        if not message:
            return True, False, None, None, None

        # 检查插件是否启用
        if not self.get_config("favorability.enabled", True):
            return True, False, None, None, None

        content = getattr(message, 'plain_text', '') or ''
        if not content:
            return True, False, None, None, None
        
        # === 移除引用部分的内容，避免将bot自己说的话当作用户说的话来检测 ===
        # 引用格式：[回复<用户昵称:用户ID> 的消息：引用内容]
        import re
        content = re.sub(r'\[回复<[^>]+>\s*的消息：[^\]]+\]', '', content)
        content = content.strip()
        
        if not content:
            return True, False, None, None, None
            
        content_lower = content.lower()
        
        # 获取发送者信息
        message_info = getattr(message, "message_info", None)
        if not message_info:
            return True, False, None, None, None

        user_info = getattr(message_info, "user_info", None)
        platform = getattr(message_info, "platform", "")

        if not user_info or not platform:
            return True, False, None, None, None

        person_id = get_person_id(platform, str(user_info.user_id))
        display_name = user_info.user_nickname or user_info.user_cardname or str(user_info.user_id)

        severe_delta = FavorabilityEventHandler._get_int_config(
            self.get_config("favorability.severe_delta", -15), -15
        )
        harassment_delta = FavorabilityEventHandler._get_int_config(
            self.get_config("favorability.harassment_delta", -25), -25
        )
        harassment_window = FavorabilityEventHandler._get_int_config(
            self.get_config("favorability.harassment_window_seconds", 300), 300
        )
        harassment_threshold = FavorabilityEventHandler._get_int_config(
            self.get_config("favorability.harassment_threshold", 3), 3
        )

        
        current_time = time.time()
        
        # 检查严重关键词 (引用 FavorabilityEventHandler 中的定义)
        for keyword in FavorabilityEventHandler.SEVERE_KEYWORDS:
            if keyword in content_lower:
                # 记录负面行为 (复用全局 tracker)
                global _negative_behavior_tracker
                if person_id not in _negative_behavior_tracker:
                    _negative_behavior_tracker[person_id] = []
                _negative_behavior_tracker[person_id].append((current_time, f"user_input:{keyword}"))
                
                # 清理
                _negative_behavior_tracker[person_id] = [
                    (ts, kw) for ts, kw in _negative_behavior_tracker[person_id]
                    if current_time - ts < harassment_window
                ]
                
                recent_count = len(_negative_behavior_tracker[person_id])
                if recent_count >= harassment_threshold:
                    new_fav = add_favorability(person_id, harassment_delta, "negative")
                    logger.warning(f"[好感度] ⚠️ {display_name} 持续骚扰(用户输入)！好感度 {harassment_delta}，当前: {new_fav}/150")
                else:
                    new_fav = add_favorability(person_id, severe_delta, "negative")
                    logger.warning(f"[好感度] {display_name} 好感度 {severe_delta}（严重违规输入: {keyword}），当前: {new_fav}/150")
                
                return True, False, None, None, None
                
        return True, False, None, None, None


class FavorabilityCommand(BaseCommand):
    """查询好感度命令"""

    command_name = "favorability"
    command_description = "查询与麦麦的好感度"
    command_pattern = r"^/(好感度|favorability|fav)$"

    async def execute(self) -> Tuple[bool, str, int]:
        """执行好感度查询
        
        Returns:
            Tuple[bool, str, int]: (是否执行成功, 回复消息, 拦截级别)
            拦截级别: 0=不拦截, 1=不触发回复但replyer可见, 2=完全拦截
        """
        # 通过 message_info.user_info 获取用户信息
        user_info = self.message.message_info.user_info
        platform = self.message.message_info.platform
        
        if not user_info or not platform:
            await self.send_text("无法获取你的信息哦~")
            return True, "无法获取用户信息", 2
        
        # 使用 MaiBot 的 get_person_id 函数生成一致的 person_id
        person_id = get_person_id(platform, str(user_info.user_id))

        fav = get_favorability(person_id)
        level = get_favorability_level(fav)
        record = get_favorability_record(person_id)
        
        # 优先使用用户昵称
        person_name = user_info.user_nickname or user_info.user_cardname or get_person_name_by_id(person_id)
        
        # 构建回复
        level_emoji = {
            "挚友": "💕", "好友": "😊", "熟人": "🙂",
            "认识": "👋", "陌生": "🤔", "厌恶": "😒"
        }
        emoji = level_emoji.get(level, "")
        
        msg = f"📋 {person_name} 的好感度信息\n"
        msg += f"{emoji} 关系等级：{level}\n"
        msg += f"📊 好感度：{fav}/150\n"
        
        if record:
            msg += f"💬 互动次数：{record.total_interactions}\n"
            msg += f"✨ 正面：{record.positive_interactions} | 负面：{record.negative_interactions}"
        
        await self.send_text(msg)
        # 返回拦截级别2，完全拦截后续处理
        return True, f"查询好感度: {fav}", 2



@register_plugin
class FavorabilityPlugin(BasePlugin):
    """好感度系统插件"""

    # === 插件基本信息（必需） ===
    plugin_name = "favorability_plugin"  # 内部标识符
    enable_plugin = True  # 必须设置为 True 才能加载
    dependencies = []  # 插件依赖列表
    python_dependencies = []  # Python包依赖列表
    config_file_name = "config.toml"  # 配置文件名

    # === 旧版插件信息（兼容性保留） ===
    __plugin_name__ = "favorability_plugin"
    __plugin_version__ = "2.1.0"
    __plugin_description__ = "好感度系统 - 根据用户互动调整好感度，数据存储在数据库中，与 PersonInfo 关联"
    __plugin_author__ = "User"
    __plugin_usage__ = """
    好感度系统自动运行：
    - 真诚的正面互动（感谢你、辛苦了等）：好感度 +1
    - 正常聊天：不改变好感度
    - 普通负面互动（辱骂等）：好感度 -5
    - 严重违规（极端辱骂/骚扰）：好感度 -5
    - 持续骚扰（5分钟内3次违规）：好感度 -5
    
    好感度等级：
    - 90-100：挚友 💕
    - 70-89：好友 😊
    - 50-69：熟人 🙂
    - 30-49：认识 👋
    - 10-29：陌生 🤔
    - 0-9：厌恶 😒
    
    命令：
    - /好感度 或 /fav：查询当前好感度
    """


    # === 配置节描述 ===
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "favorability": "好感度系统配置"
    }

    # === 配置Schema定义 ===
    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="2.1.0", description="配置文件版本"),

            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        "favorability": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用好感度系统",
            ),
            "default_value": ConfigField(
                type=int,
                default=50,
                description="新用户默认好感度（0-100）",
                min=0,
                max=100,
            ),
            "positive_delta": ConfigField(
                type=int,
                default=1,
                description="正面互动增加的好感度（门槛已提高，需真诚表达）",
            ),
            "affectionate_delta": ConfigField(
                type=int,
                default=3,
                description="亲昵称呼增加的好感度（如咲夜姐姐、么么哒等）",
            ),
            "negative_delta": ConfigField(
                type=int,
                default=-5,
                description="普通负面互动减少的好感度（上限 -5）",
            ),
            "mild_negative_delta": ConfigField(
                type=int,
                default=-1,
                description="轻度负面互动减少的好感度",
            ),
            "severe_delta": ConfigField(
                type=int,
                default=-5,
                description="严重违规（辱骂/色情）减少的好感度（上限 -5）",
            ),
            "harassment_delta": ConfigField(
                type=int,
                default=-5,
                description="持续骚扰减少的好感度（上限 -5）",
            ),
            "flirting_delta": ConfigField(
                type=int,
                default=-1,
                description="越界/调戏行为减少的好感度（规划器判定）",
            ),

            "harassment_window_seconds": ConfigField(
                type=int,
                default=300,
                description="骚扰检测时间窗口（秒），在此时间内多次违规视为骚扰",
            ),
            "harassment_threshold": ConfigField(
                type=int,
                default=3,
                description="骚扰检测阈值，时间窗口内达到此次数触发骚扰惩罚",
            ),
            "normal_delta": ConfigField(
                type=int,
                default=1,
                description="日常互动增加的好感度",
            ),
            "normal_cooldown_seconds": ConfigField(
                type=int,
                default=300,
                description="日常互动好感度冷却时间（秒），防止刷好感度",
            ),
            "positive_cooldown_seconds": ConfigField(
                type=int,
                default=120,
                description="正向互动冷却时间（秒），防止刷好感度",
            ),
            "negative_cooldown_seconds": ConfigField(
                type=int,
                default=120,
                description="负向互动冷却时间（秒），避免连续扣分",
            ),
            "min_positive_length": ConfigField(
                type=int,
                default=4,
                description="正向互动最短有效长度（去空格后）",
            ),
            "min_normal_length": ConfigField(
                type=int,
                default=6,
                description="日常互动最短有效长度（去空格后）",
            ),
            "positive_bonus_delta": ConfigField(
                type=int,
                default=1,
                description="长内容正向加成（长度达标时额外加分）",
            ),
            "reasoning_positive_delta": ConfigField(
                type=int,
                default=1,
                description="规划器正面判定基础加分",
            ),
            "reasoning_positive_bonus_high": ConfigField(
                type=int,
                default=2,
                description="规划器正面高档加成",
            ),
            "reasoning_positive_bonus_mid": ConfigField(
                type=int,
                default=1,
                description="规划器正面中档加成",
            ),
            "reasoning_positive_bonus_low": ConfigField(
                type=int,
                default=1,
                description="规划器正面低档加成",
            ),
            "mimic_delta": ConfigField(
                type=int,
                default=-5,
                description="模仿/复读bot说话减少的好感度",
            ),

            "inject_prompt_enabled": ConfigField(
                type=bool,
                default=True,
                description="是否在生成回复前注入‘好感度→语气/关系’提示词",
            ),
            "debug_log_prompt_injection": ConfigField(
                type=bool,
                default=False,
                description="是否在终端日志输出‘好感度注入’调试信息（会打印好感度数值）",
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """获取插件包含的组件列表"""
        return [
            (FavorabilityPromptInjectorHandler.get_handler_info(), FavorabilityPromptInjectorHandler),
            (FavorabilityEventHandler.get_handler_info(), FavorabilityEventHandler),
            (UserSentimentEventHandler.get_handler_info(), UserSentimentEventHandler),
            (FavorabilityCommand.get_command_info(), FavorabilityCommand),
            (FavorabilityQueryTool.get_tool_info(), FavorabilityQueryTool),
        ]

    async def on_load(self):
        """插件加载时执行"""
        logger.info("好感度系统插件 v2.0 已加载（数据库模式）")
        
        # 确保数据表存在
        try:
            db.create_tables([Favorability], safe=True)
            logger.info("好感度数据表已就绪")
        except Exception as e:
            logger.error(f"创建好感度数据表失败: {e}")

    async def on_unload(self):
        """插件卸载时执行"""
        logger.info("好感度系统插件已卸载")

