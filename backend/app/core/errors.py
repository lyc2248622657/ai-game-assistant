"""统一错误码与异常体系"""
from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。HTTP 状态码保持 4xx/5xx，响应体中携带 code/message 供前端定位。"""

    OK = 0
    INTERNAL = 10000          # 内部错误
    INVALID_REQUEST = 10001   # 请求参数非法
    GAME_NOT_FOUND = 10002    # 游戏不存在或未启用
    SESSION_NOT_FOUND = 10003 # 会话不存在
    LLM_CALL_FAILED = 10004   # 模型调用失败（重试后仍失败）
    TOOL_FAILED = 10005       # 工具执行失败
    RETRIEVAL_EMPTY = 10006   # 检索无结果
    CONFIG_ERROR = 10007      # 配置缺失（如未填写 API Key）
    UNAUTHORIZED = 10008      # 未通过接口鉴权（缺少/错误访问令牌）


# 每个错误码的默认 HTTP 状态：语义为"找不到"的应回 404 而非 400。
# 调用方显式传 http_status 时以显式值为准。
_DEFAULT_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.OK: 200,
    ErrorCode.INTERNAL: 500,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.GAME_NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.LLM_CALL_FAILED: 502,
    ErrorCode.TOOL_FAILED: 500,
    ErrorCode.RETRIEVAL_EMPTY: 404,
    ErrorCode.CONFIG_ERROR: 400,
    ErrorCode.UNAUTHORIZED: 401,
}


class AppError(Exception):
    """业务异常基类：携带错误码与用户可读消息"""

    def __init__(self, code: ErrorCode, message: str, http_status: int | None = None):
        self.code = code
        self.message = message
        self.http_status = http_status or _DEFAULT_HTTP_STATUS.get(code, 400)
        super().__init__(message)
