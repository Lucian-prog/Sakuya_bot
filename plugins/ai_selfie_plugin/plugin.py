"""
AI 自拍生图插件
通过关键词触发，使用 SiliconFlow 的图生图模型基于参考图生成 AI 自拍图片
"""

import base64
import aiohttp
import os
from pathlib import Path
from typing import Tuple, Type, List

from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseAction,
    ComponentInfo,
    ActionActivationType,
    ConfigField,
)
from src.common.logger import get_logger

logger = get_logger("ai_selfie_plugin")


class AISelfieAction(BaseAction):
    """AI 自拍动作 - 使用 AI 生成自拍图片"""

    # === 激活设置 ===
    activation_type = ActionActivationType.KEYWORD  # 关键词激活
    activation_keywords = ["发张自拍", "自拍", "发自拍", "来张自拍", "看看你的照片", "想看你", "你长什么样", "发个照片"]
    keyword_case_sensitive = False  # 不区分大小写
    parallel_action = False  # 不并行执行

    # === 基本信息（必须填写）===
    action_name = "ai_selfie"
    action_description = "生成一张 AI 自拍图片并发送"

    # === 动作参数定义 ===
    action_parameters = {
        "style": "自拍风格描述，如：可爱、酷炫、日常、搞怪等",
    }

    # === 动作使用场景 ===
    action_require = [
        "当用户要求发送自拍时使用",
        "当用户想看你的照片时使用",
        "当用户问你长什么样子时使用",
    ]

    # === 关联类型 ===
    associated_types = ["image"]

    async def execute(self) -> Tuple[bool, str]:
        """执行 AI 自拍生图动作"""
        logger.info(f"{self.log_prefix} 执行 AI 自拍动作: {self.reasoning}")

        try:
            # 获取配置
            api_key = self.get_config("generation.api_key", "sk-vbgrvihcjcmewxkiwbeinaxhezxsmohdlofnxfqmggfywqap")
            base_url = self.get_config("generation.base_url", "https://api.siliconflow.cn/v1")
            model = self.get_config("generation.model", "Qwen/Qwen-Image-Edit")
            character_prompt = self.get_config("generation.character_prompt", "")
            image_size = self.get_config("generation.image_size", "1024x1024")
            reference_image_path = self.get_config("generation.reference_image_path", "")
            cfg = self.get_config("generation.cfg", 4.0)
            num_inference_steps = self.get_config("generation.num_inference_steps", 50)

            if not api_key:
                logger.error(f"{self.log_prefix} 未配置 API Key")
                await self.send_text("哎呀，我还没有配置好自拍功能呢~")
                return False, "未配置 API Key"

            # 获取用户请求的风格
            style = self.action_data.get("style", "可爱日常")
            
            # 如果没有预设角色描述，使用默认的
            if not character_prompt:
                character_prompt = "same character as reference, anime style, cute, high quality"

            # 构建完整的 prompt
            full_prompt = f"{character_prompt}, {style} style, selfie, high quality, detailed"
            
            logger.info(f"{self.log_prefix} 生成图片 Prompt: {full_prompt}")

            # 读取参考图片（如果存在）
            reference_base64 = None
            if reference_image_path:
                reference_base64 = self._load_reference_image(reference_image_path)
                if reference_base64:
                    logger.info(f"{self.log_prefix} 已加载参考图片，使用图生图模式")
                else:
                    logger.warning(f"{self.log_prefix} 参考图片加载失败，将使用文生图模式")

            # 调用 SiliconFlow API 生成图片
            image_base64 = await self._generate_image(
                api_key=api_key,
                base_url=base_url,
                model=model,
                prompt=full_prompt,
                image_size=image_size,
                reference_image=reference_base64,
                cfg=cfg,
                num_inference_steps=num_inference_steps,
            )

            if not image_base64:
                logger.error(f"{self.log_prefix} 图片生成失败")
                await self.send_text("呜呜，自拍失败了，相机好像坏了~")
                return False, "图片生成失败"

            # 发送图片
            success = await self.send_image(image_base64)

            if success:
                # 记录动作信息
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"你发送了一张自拍照片，风格：{style}",
                    action_done=True,
                )
                logger.info(f"{self.log_prefix} AI 自拍发送成功")
                return True, f"成功发送 AI 自拍，风格：{style}"
            else:
                logger.error(f"{self.log_prefix} 图片发送失败")
                return False, "图片发送失败"

        except Exception as e:
            logger.error(f"{self.log_prefix} AI 自拍动作执行失败: {e}", exc_info=True)
            await self.send_text("哎呀，自拍的时候出问题了~")
            return False, f"AI 自拍失败: {str(e)}"

    def _load_reference_image(self, image_path: str) -> str | None:
        """
        加载参考图片并转换为 base64
        
        Args:
            image_path: 图片路径（相对于项目根目录或绝对路径）
            
        Returns:
            图片的 base64 编码，失败返回 None
        """
        try:
            # 处理相对路径
            path = Path(image_path)
            if not path.is_absolute():
                # 相对于项目根目录
                project_root = Path(__file__).parent.parent.parent
                path = project_root / image_path
            
            if not path.exists():
                logger.warning(f"{self.log_prefix} 参考图片不存在: {path}")
                return None
            
            with open(path, "rb") as f:
                image_bytes = f.read()
                return base64.b64encode(image_bytes).decode("utf-8")
                
        except Exception as e:
            logger.error(f"{self.log_prefix} 加载参考图片失败: {e}")
            return None

    async def _generate_image(
        self,
        api_key: str,
        base_url: str,
        model: str,
        prompt: str,
        image_size: str = "1024x1024",
        reference_image: str | None = None,
        cfg: float = 4.0,
        num_inference_steps: int = 50,
    ) -> str | None:
        """
        调用 SiliconFlow 图片生成 API（支持图生图）
        
        Args:
            api_key: API 密钥
            base_url: API 基础 URL
            model: 模型标识符
            prompt: 图片描述 prompt
            image_size: 图片尺寸
            reference_image: 参考图片的 base64 编码（用于图生图）
            cfg: CFG 值，控制生成精度（Qwen 模型使用）
            num_inference_steps: 推理步数
            
        Returns:
            图片的 base64 编码，失败返回 None
        """
        url = f"{base_url.rstrip('/')}/images/generations"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        # 根据模型类型构建不同的 payload
        is_qwen_edit = "Qwen" in model and "Edit" in model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "num_inference_steps": num_inference_steps,
        }
        
        if is_qwen_edit:
            # Qwen 图像编辑模型：使用 cfg，不使用 image_size
            payload["cfg"] = cfg
            if reference_image:
                payload["image"] = f"data:image/png;base64,{reference_image}"
        else:
            # Kolors/FLUX 等模型：使用 image_size 和 guidance_scale
            payload["image_size"] = image_size
            payload["batch_size"] = 1
            payload["guidance_scale"] = 7.5
            if reference_image:
                payload["image"] = f"data:image/png;base64,{reference_image}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=60) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"{self.log_prefix} API 请求失败: {response.status} - {error_text}")
                        return None

                    result = await response.json()
                    
                    # SiliconFlow 返回格式
                    if "images" in result and len(result["images"]) > 0:
                        image_data = result["images"][0]
                        # 如果返回的是 URL，需要下载图片
                        if isinstance(image_data, dict) and "url" in image_data:
                            return await self._download_image_as_base64(session, image_data["url"])
                        # 如果直接返回 base64
                        elif isinstance(image_data, str):
                            return image_data
                    
                    # OpenAI 格式兼容
                    if "data" in result and len(result["data"]) > 0:
                        image_data = result["data"][0]
                        if "b64_json" in image_data:
                            return image_data["b64_json"]
                        elif "url" in image_data:
                            return await self._download_image_as_base64(session, image_data["url"])

                    logger.error(f"{self.log_prefix} 未知的响应格式: {result}")
                    return None

        except aiohttp.ClientError as e:
            logger.error(f"{self.log_prefix} 网络请求错误: {e}")
            return None
        except Exception as e:
            logger.error(f"{self.log_prefix} 图片生成异常: {e}", exc_info=True)
            return None

    async def _download_image_as_base64(self, session: aiohttp.ClientSession, url: str) -> str | None:
        """下载图片并转换为 base64"""
        try:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    image_bytes = await response.read()
                    return base64.b64encode(image_bytes).decode("utf-8")
                else:
                    logger.error(f"{self.log_prefix} 下载图片失败: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"{self.log_prefix} 下载图片异常: {e}")
            return None


@register_plugin
class AISelfiePlugin(BasePlugin):
    """AI 自拍插件

    通过关键词触发，使用 SiliconFlow 的图生图模型基于参考图生成 AI 自拍图片。

    支持的触发词：
    - 发张自拍、自拍、发自拍、来张自拍
    - 看看你的照片、想看你、你长什么样、发个照片
    """

    # === 插件基本信息 ===
    plugin_name: str = "ai_selfie_plugin"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    # === 配置节描述 ===
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "generation": "图片生成配置",
    }

    # === 配置Schema定义 ===
    config_schema: dict = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        },
        "generation": {
            "api_key": ConfigField(
                type=str,
                default="",
                description="SiliconFlow API Key",
                input_type="password",
                required=True,
            ),
            "base_url": ConfigField(
                type=str,
                default="https://api.siliconflow.cn/v1",
                description="API 基础 URL",
            ),
            "model": ConfigField(
                type=str,
                default="Kwai-Kolors/Kolors",
                description="图片生成模型",
                choices=["Kwai-Kolors/Kolors", "stabilityai/stable-diffusion-3-5-large", "black-forest-labs/FLUX.1-schnell"],
            ),
            "character_prompt": ConfigField(
                type=str,
                default="same character as reference, anime style cute girl, friendly smile, high quality, detailed",
                description="角色基础描述 Prompt",
            ),
            "image_size": ConfigField(
                type=str,
                default="1024x1024",
                description="生成图片尺寸",
                choices=["512x512", "768x768", "1024x1024", "768x1024", "1024x768"],
            ),
            "reference_image_path": ConfigField(
                type=str,
                default="plugins/ai_selfie_plugin/reference.png",
                description="参考图片路径（用于图生图模式）",
            ),
            "strength": ConfigField(
                type=float,
                default=0.35,
                description="图生图强度 0.0-1.0，值越小越接近原图",
                min=0.0,
                max=1.0,
                step=0.05,
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        return [
            (AISelfieAction.get_action_info(), AISelfieAction),
        ]
