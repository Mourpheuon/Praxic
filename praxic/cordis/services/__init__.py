"""cordis 服务壳层：把 Praxic 现有能力包装为组合可声明的服务。

- ``llm.py``  LLM 服务壳（get_llm() 入口包装）
- ``host.py`` host 级服务壳（workspace / memory / permission-policy / skill-manager）
- ``tools.py`` 工具注册表兼容层 + 工具行服务

这些壳只做薄包装，不改变底层行为；组合路径（assembly.build_loop_from_composition）
通过它们把 agent.yml 声明装配成与旧构造路径等价的结果。
"""
