import json

from core.providers.tools.base import ToolDefinition, ToolExecutor, ToolType
from plugins_func.register import Action, ActionResponse

IMAGE_TOOL = {'type': 'function', 'function': {'name': 'generate_companion_image',
    'description': '根据用户要求生成图片，并发送给当前支持图片的聊天客户端。生成图片不代表真实历史照片。',
    'parameters': {'type': 'object', 'properties': {'prompt': {'type': 'string', 'description': '要生成的图片内容'}},
                   'required': ['prompt'], 'additionalProperties': False}}}


class PluginCenterExecutor(ToolExecutor):
    def __init__(self, conn): self.conn = conn

    def get_tools(self):
        runtime = getattr(self.conn, 'plugin_runtime', None)
        if runtime and runtime.image_tool_ready():
            return {'generate_companion_image': ToolDefinition(name='generate_companion_image', description=IMAGE_TOOL, tool_type=ToolType.PLUGIN_CENTER)}
        return {}

    def has_tool(self, name): return name in self.get_tools()

    async def execute(self, conn, tool_name, arguments):
        if tool_name != 'generate_companion_image' or not self.has_tool(tool_name):
            return ActionResponse(Action.NOTFOUND, response='生图插件尚未启用或未就绪')
        try:
            result = await conn.plugin_runtime.execute_image(arguments.get('prompt', ''))
            return ActionResponse(Action.REQLLM, result=json.dumps(result, ensure_ascii=False), response='图片已发送。')
        except Exception:
            return ActionResponse(Action.ERROR, response='这次图片没有发送成功，可以查看插件中心的状态后再试。')
