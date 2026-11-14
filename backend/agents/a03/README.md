# Cheetah A03 Pi 研究执行器

Node.js 24，TypeScript；由 Python worker 在已发布 pi-research v1 规则下启动。Pi Agent 核心负责模型／工具循环，Python 宿主负责证据、权限、预算、外部请求账本与 D04 交付。只加载本目录的专业资源，不自动扫描工作区或个人插件。

在本目录运行 `npm ci --ignore-scripts`、`npm run check`、`npm test`。实际执行由 `python -m app.worker` 发起，不通过交互式 Pi CLI 操作真实候选人。

版本、配置、插件选择、工具合同与验证限制见 [A03 开发说明](../../../docs/a03-pi-agent.md)。标准工具 schema 从 Python 模型导出，并由宿主传给 Pi；禁止在 TS 中另建不兼容的 schema。
