"""BFF：WebSocket、静态资源、会话、外部 API 编排。

core/ 不直接联网；所有外部调用都在这里，通过实现 ``core.ports`` 的适配器完成。
"""
