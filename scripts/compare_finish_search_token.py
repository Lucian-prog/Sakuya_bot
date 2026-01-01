import argparse
import asyncio
import os
import sys
import time
import json
import importlib
from typing import Dict, Any
from datetime import datetime

# 强制使用 utf-8，避免控制台编码报错
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 确保能导入 src.*
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.common.logger import initialize_logging, get_logger
from src.common.database.database import db
from src.common.database.database_model import LLMUsage

logger = get_logger("compare_finish_search_token")


def get_token_usage_since(start_time: float) -> Dict[str, Any]:
    """获取从指定时间开始的token使用情况
    
    Args:
        start_time: 开始时间戳
        
    Returns:
        包含token使用统计的字典
    """
    try:
        start_datetime = datetime.fromtimestamp(start_time)
        
        # 查询从开始时间到现在的所有memory相关的token使用记录
        records = (
            LLMUsage.select()
            .where(
                (LLMUsage.timestamp >= start_datetime)
                & (
                    (LLMUsage.request_type.like("%memory%"))
                    | (LLMUsage.request_type == "memory.question")
                    | (LLMUsage.request_type == "memory.react")
                    | (LLMUsage.request_type == "memory.react.final")
                )
            )
            .order_by(LLMUsage.timestamp.asc())
        )
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_cost = 0.0
        request_count = 0
        model_usage = {}  # 按模型统计
        
        for record in records:
            total_prompt_tokens += record.prompt_tokens or 0
            total_completion_tokens += record.completion_tokens or 0
            total_tokens += record.total_tokens or 0
            total_cost += record.cost or 0.0
            request_count += 1
            
            # 按模型统计
            model_name = record.model_name or "unknown"
            if model_name not in model_usage:
                model_usage[model_name] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                    "request_count": 0,
                }
            model_usage[model_name]["prompt_tokens"] += record.prompt_tokens or 0
            model_usage[model_name]["completion_tokens"] += record.completion_tokens or 0
            model_usage[model_name]["total_tokens"] += record.total_tokens or 0
            model_usage[model_name]["cost"] += record.cost or 0.0
            model_usage[model_name]["request_count"] += 1
        
        return {
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "request_count": request_count,
            "model_usage": model_usage,
        }
    except Exception as e:
        logger.error(f"获取token使用情况失败: {e}")
        return {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "request_count": 0,
            "model_usage": {},
        }


def _import_memory_retrieval():
    """使用 importlib 动态导入 memory_retrieval 模块，避免循环导入"""
    try:
        # 先导入 prompt_builder，检查 prompt 是否已经初始化
        from src.chat.utils.prompt_builder import global_prompt_manager
        
        # 检查 memory_retrieval 相关的 prompt 是否已经注册
        # 如果已经注册，说明模块可能已经通过其他路径初始化过了
        prompt_already_init = "memory_retrieval_question_prompt" in global_prompt_manager._prompts
        
        module_name = "src.memory_system.memory_retrieval"
        
        # 如果 prompt 已经初始化，尝试直接使用已加载的模块
        if prompt_already_init and module_name in sys.modules:
            existing_module = sys.modules[module_name]
            if hasattr(existing_module, 'init_memory_retrieval_prompt'):
                return (
                    existing_module.init_memory_retrieval_prompt,
                    existing_module._react_agent_solve_question,
                )
        
        # 如果模块已经在 sys.modules 中但部分初始化，先移除它
        if module_name in sys.modules:
            existing_module = sys.modules[module_name]
            if not hasattr(existing_module, 'init_memory_retrieval_prompt'):
                # 模块部分初始化，移除它
                logger.warning(f"检测到部分初始化的模块 {module_name}，尝试重新导入")
                del sys.modules[module_name]
                # 清理可能相关的部分初始化模块
                keys_to_remove = []
                for key in sys.modules.keys():
                    if key.startswith('src.memory_system.') and key != 'src.memory_system':
                        keys_to_remove.append(key)
                for key in keys_to_remove:
                    try:
                        del sys.modules[key]
                    except KeyError:
                        pass
        
        # 在导入 memory_retrieval 之前，先确保所有可能触发循环导入的模块都已完全加载
        # 这些模块在导入时可能会触发 memory_retrieval 的导入，所以我们需要先加载它们
        try:
            # 先导入可能触发循环导入的模块，让它们完成初始化
            import src.config.config
            import src.chat.utils.prompt_builder
            # 尝试导入可能触发循环导入的模块（这些模块可能在模块级别导入了 memory_retrieval）
            # 如果它们已经导入，就确保它们完全初始化
            try:
                import src.chat.replyer.group_generator  # noqa: F401
            except (ImportError, AttributeError):
                pass  # 如果导入失败，继续
            try:
                import src.chat.replyer.private_generator  # noqa: F401
            except (ImportError, AttributeError):
                pass  # 如果导入失败，继续
        except Exception as e:
            logger.warning(f"预加载依赖模块时出现警告: {e}")
        
        # 现在尝试导入 memory_retrieval
        # 如果此时仍然触发循环导入，说明有其他模块在模块级别导入了 memory_retrieval
        memory_retrieval_module = importlib.import_module(module_name)
        
        return (
            memory_retrieval_module.init_memory_retrieval_prompt,
            memory_retrieval_module._react_agent_solve_question,
        )
    except (ImportError, AttributeError) as e:
        logger.error(f"导入 memory_retrieval 模块失败: {e}", exc_info=True)
        raise


def _init_tools_without_finish_search():
    """初始化工具但不注册 finish_search"""
    from src.memory_system.retrieval_tools import (
        register_query_chat_history,
        register_query_person_info,
        register_query_words,
    )
    from src.memory_system.retrieval_tools.tool_registry import get_tool_registry
    from src.config.config import global_config
    
    # 清空工具注册器
    tool_registry = get_tool_registry()
    tool_registry.tools.clear()
    
    # 注册除 finish_search 外的所有工具
    register_query_chat_history()
    register_query_person_info()
    register_query_words()
    
    # 如果启用 LPMM agent 模式，也注册 LPMM 工具
    if global_config.lpmm_knowledge.lpmm_mode == "agent":
        from src.memory_system.retrieval_tools.query_lpmm_knowledge import register_tool as register_lpmm_knowledge
        register_lpmm_knowledge()
    
    logger.info("已初始化工具（不包含 finish_search）")


def _init_tools_with_finish_search():
    """初始化工具并注册 finish_search"""
    from src.memory_system.retrieval_tools.tool_registry import get_tool_registry
    from src.memory_system.retrieval_tools import init_all_tools
    
    # 清空工具注册器
    tool_registry = get_tool_registry()
    tool_registry.tools.clear()
    
    # 初始化所有工具（包括 finish_search）
    init_all_tools()
    logger.info("已初始化工具（包含 finish_search）")


async def get_prompt_tokens_for_tools(
    question: str,
    chat_id: str,
    use_finish_search: bool,
) -> Dict[str, Any]:
    """获取使用不同工具配置时的prompt token消耗
    
    Args:
        question: 要查询的问题
        chat_id: 聊天ID
        use_finish_search: 是否使用 finish_search 工具
        
    Returns:
        包含prompt token信息的字典
    """
    # 先初始化 prompt（如果还未初始化）
    # 注意：init_memory_retrieval_prompt 会调用 init_all_tools，所以我们需要在它之后重新设置工具
    from src.chat.utils.prompt_builder import global_prompt_manager
    if "memory_retrieval_question_prompt" not in global_prompt_manager._prompts:
        init_memory_retrieval_prompt, _ = _import_memory_retrieval()
        init_memory_retrieval_prompt()
    
    # 初始化工具（根据参数决定是否包含 finish_search）
    # 必须在 init_memory_retrieval_prompt 之后调用，因为它会调用 init_all_tools
    if use_finish_search:
        _init_tools_with_finish_search()
    else:
        _init_tools_without_finish_search()
    
    # 获取工具注册器
    from src.memory_system.retrieval_tools.tool_registry import get_tool_registry
    tool_registry = get_tool_registry()
    tool_definitions = tool_registry.get_tool_definitions()
    
    # 验证工具列表（调试用）
    tool_names = [tool["name"] for tool in tool_definitions]
    if use_finish_search:
        if "finish_search" not in tool_names:
            logger.warning("期望包含 finish_search 工具，但工具列表中未找到")
    else:
        if "finish_search" in tool_names:
            logger.warning("期望不包含 finish_search 工具，但工具列表中找到了，将移除")
            # 移除 finish_search 工具
            tool_registry.tools.pop("finish_search", None)
            tool_definitions = tool_registry.get_tool_definitions()
            tool_names = [tool["name"] for tool in tool_definitions]
    
    # 构建第一次调用的prompt（模拟_react_agent_solve_question的第一次调用）
    from src.config.config import global_config
    bot_name = global_config.bot.nickname
    time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    
    # 构建head_prompt
    head_prompt = await global_prompt_manager.format_prompt(
        "memory_retrieval_react_prompt_head",
        bot_name=bot_name,
        time_now=time_now,
        question=question,
        collected_info="",
        current_iteration=1,
        remaining_iterations=global_config.memory.max_agent_iterations - 1,
        max_iterations=global_config.memory.max_agent_iterations,
    )
    
    # 构建消息列表（只包含system message，模拟第一次调用）
    from src.llm_models.payload_content.message import MessageBuilder, RoleType
    messages = []
    system_builder = MessageBuilder()
    system_builder.set_role(RoleType.System)
    system_builder.add_text_content(head_prompt)
    messages.append(system_builder.build())
    
    # 调用LLM API来计算token（只调用一次，不实际执行）
    from src.llm_models.utils_model import LLMRequest, RequestType
    from src.config.config import model_config
    
    # 创建LLM请求对象
    llm_request = LLMRequest(model_set=model_config.model_task_config.tool_use, request_type="memory.react.compare")
    
    # 构建工具选项
    tool_built = llm_request._build_tool_options(tool_definitions)
    
    # 直接调用 _execute_request 以获取完整的响应对象（包含 usage）
    response, model_info = await llm_request._execute_request(
        request_type=RequestType.RESPONSE,
        message_factory=lambda _client, *, _messages=messages: _messages,
        temperature=None,
        max_tokens=None,
        tool_options=tool_built,
    )
    
    # 从响应中获取token使用情况
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    
    if response and hasattr(response, 'usage') and response.usage:
        prompt_tokens = response.usage.prompt_tokens or 0
        completion_tokens = response.usage.completion_tokens or 0
        total_tokens = response.usage.total_tokens or 0
    
    return {
        "use_finish_search": use_finish_search,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "tool_count": len(tool_definitions),
        "tool_names": [tool["name"] for tool in tool_definitions],
    }


async def compare_prompt_tokens(
    question: str,
    chat_id: str = "compare_finish_search",
) -> Dict[str, Any]:
    """对比使用 finish_search 工具与否的输入 token 差异
    
    只运行一次，只计算输入 token 的差异，确保除了工具定义外其他内容一致
    
    Args:
        question: 要查询的问题
        chat_id: 聊天ID
        
    Returns:
        包含对比结果的字典
    """
    print("\n" + "=" * 80)
    print("finish_search 工具 输入 Token 消耗对比测试")
    print("=" * 80)
    print(f"\n[测试问题] {question}")
    print(f"[聊天ID] {chat_id}")
    print("\n注意: 只对比第一次LLM调用的输入token差异，不运行完整迭代流程")
    
    # 第一次测试：不使用 finish_search
    print("\n" + "-" * 80)
    print("[测试 1/2] 不使用 finish_search 工具")
    print("-" * 80)
    result_without = await get_prompt_tokens_for_tools(
        question=question,
        chat_id=f"{chat_id}_without",
        use_finish_search=False,
    )
    
    print(f"\n[结果]")
    print(f"  工具数量: {result_without['tool_count']}")
    print(f"  工具列表: {', '.join(result_without['tool_names'])}")
    print(f"  输入 Prompt Tokens: {result_without['prompt_tokens']:,}")
    
    # 等待一下，确保数据库记录已写入
    await asyncio.sleep(1)
    
    # 第二次测试：使用 finish_search
    print("\n" + "-" * 80)
    print("[测试 2/2] 使用 finish_search 工具")
    print("-" * 80)
    result_with = await get_prompt_tokens_for_tools(
        question=question,
        chat_id=f"{chat_id}_with",
        use_finish_search=True,
    )
    
    print(f"\n[结果]")
    print(f"  工具数量: {result_with['tool_count']}")
    print(f"  工具列表: {', '.join(result_with['tool_names'])}")
    print(f"  输入 Prompt Tokens: {result_with['prompt_tokens']:,}")
    
    # 对比结果
    print("\n" + "=" * 80)
    print("[对比结果]")
    print("=" * 80)
    
    prompt_token_diff = result_with['prompt_tokens'] - result_without['prompt_tokens']
    prompt_token_diff_percent = (prompt_token_diff / result_without['prompt_tokens'] * 100) if result_without['prompt_tokens'] > 0 else 0
    
    tool_count_diff = result_with['tool_count'] - result_without['tool_count']
    
    print(f"\n[输入 Prompt Token 对比]")
    print(f"  不使用 finish_search: {result_without['prompt_tokens']:,} tokens")
    print(f"  使用 finish_search:    {result_with['prompt_tokens']:,} tokens")
    print(f"  差异: {prompt_token_diff:+,} tokens ({prompt_token_diff_percent:+.2f}%)")
    
    print(f"\n[工具数量对比]")
    print(f"  不使用 finish_search: {result_without['tool_count']} 个工具")
    print(f"  使用 finish_search:    {result_with['tool_count']} 个工具")
    print(f"  差异: {tool_count_diff:+d} 个工具")
    
    print(f"\n[工具列表对比]")
    without_tools = set(result_without['tool_names'])
    with_tools = set(result_with['tool_names'])
    only_with = with_tools - without_tools
    only_without = without_tools - with_tools
    
    if only_with:
        print(f"  仅在 '使用 finish_search' 中的工具: {', '.join(only_with)}")
    if only_without:
        print(f"  仅在 '不使用 finish_search' 中的工具: {', '.join(only_without)}")
    if not only_with and not only_without:
        print(f"  工具列表相同（除了 finish_search）")
    
    # 显示其他token信息
    print(f"\n[其他 Token 信息]")
    print(f"  Completion Tokens (不使用 finish_search): {result_without.get('completion_tokens', 0):,}")
    print(f"  Completion Tokens (使用 finish_search):    {result_with.get('completion_tokens', 0):,}")
    print(f"  总 Tokens (不使用 finish_search): {result_without.get('total_tokens', 0):,}")
    print(f"  总 Tokens (使用 finish_search):    {result_with.get('total_tokens', 0):,}")
    
    print("\n" + "=" * 80)
    
    return {
        "question": question,
        "without_finish_search": result_without,
        "with_finish_search": result_with,
        "comparison": {
            "prompt_token_diff": prompt_token_diff,
            "prompt_token_diff_percent": prompt_token_diff_percent,
            "tool_count_diff": tool_count_diff,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="对比使用 finish_search 工具与否的 token 消耗差异"
    )
    parser.add_argument(
        "--chat-id",
        default="compare_finish_search",
        help="测试用的聊天ID（默认: compare_finish_search）",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="将结果保存到JSON文件（可选）",
    )
    
    args = parser.parse_args()
    
    # 初始化日志（使用较低的详细程度，避免输出过多日志）
    initialize_logging(verbose=False)
    
    # 交互式输入问题
    print("\n" + "=" * 80)
    print("finish_search 工具 Token 消耗对比测试工具")
    print("=" * 80)
    question = input("\n请输入要查询的问题: ").strip()
    if not question:
        print("错误: 问题不能为空")
        return
    
    # 连接数据库
    try:
        db.connect(reuse_if_open=True)
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        print(f"错误: 数据库连接失败: {e}")
        return
    
    # 运行对比测试
    try:
        result = asyncio.run(
            compare_prompt_tokens(
                question=question,
                chat_id=args.chat_id,
            )
        )
        
        # 如果指定了输出文件，保存结果
        if args.output:
            # 将thinking_steps转换为可序列化的格式
            output_result = result.copy()
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(output_result, f, ensure_ascii=False, indent=2)
            print(f"\n[结果已保存] {args.output}")
        
    except KeyboardInterrupt:
        print("\n\n[中断] 用户中断测试")
    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        print(f"\n[错误] 测试失败: {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

