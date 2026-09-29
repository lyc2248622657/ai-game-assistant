"""统一错误码与异常体系"""
from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。HTTP 状态码保持 4xx/5xx，detail 中携带 code 供前端定位。"""

    OK = 0
    INTERNAL = 10000          # 内部错误
    INVALID_REQUEST = 10001   # 请求参数非法
    GAME_NOT_FOUND = 10002    # 游戏不存在或未启用
    SESSION_NOT_FOUND = 10003 # 会话不存在
    LLM_CALL_FAILED = 10004   # 模型调用失败（重试后仍失败）
    TOOL_FAILED = 10005       # 工具执行失败
    RETRIEVAL_EMPTY = 10006   # 检索无结果
    CONFIG_ERROR = 10007      # 配置缺失（如未填写 API Key）


class AppError(Exception):
    """业务异常基类：携带错误码与用户可读消息"""

    def __init__(self, code: ErrorCode, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)
