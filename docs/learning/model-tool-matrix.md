> **创建**：2026-06-20 · **更新**：2026-06-20（GPT 对话决策定稿）
> **用途**：记录当前可用的 AI IDE / 模型订阅与接入方案，作为 Agent 开发中模型选型与工具链决策的基础参考。
>
> **关联**：[[Agent开发学习计划]] · [[RenxinOS-执行规格]]
>
> **结论**：模型四层递进 **Flash → V4 Pro → Qwen 3.7 Max → GPT-5.5**。学习阶段 Agent 开发 **Qoder + Claude Code**（均 V4 Pro）；实战阶段主力切 **OpenCode + Qoder**。Obsidian 维护全程 Flash 为主。

---

## 一、工具与订阅总览

| 工具 | 付费方式 | 可接入模型 | 到期/余额 | 当前角色 |
|---|---|---|---|---|
| **Qoder** | 月付 | 国产主力模型 | 下月到期 | 学习阶段主力（Agent 开发 + Obsidian） |
| **Claude Code（本地）** | API Key | DeepSeek V4 Pro / Flash | 按 API 用量 | 学习阶段主力（Agent 编码） |
| **OpenCode（本地）** | API Key | 国产模型 + 国外模型（中转） | 按 API 用量 | 已安装，实战阶段切主力 |
| **Cursor** | 年付 | 仅 Cursor 自有模型 | 2026-08 月底（不续） | 已停用，到期自然结束 |
| **CodeBuddy** | 赠送额度 | 国产模型 | 额度未用完 | 备用，额度用完即停 |
| **Codex（本地）** | API Key | DeepSeek 系列 / Qwen（可配） | 走 DeepSeek 余额 | 备用，API 直连通道 |
| **DeepSeek（充值）** | 按量 | DeepSeek 系列 | ~十几元余额 | API 底座，按量续充 |

---

## 二、模型选型原则与场景映射（GPT 对话决策定稿）

### 核心原则

> **优先使用便宜模型完成任务，只有在能力不足时才升级模型。**

```text
Flash ──→ V4 Pro ──→ Qwen 3.7 Max ──→ GPT-5.5
 80%         15%           4%             1%
```

### 四层模型梯队

> 占比为**长期目标配比**。当前学习阶段实际占比：V4 Pro ≈ 60% / Flash ≈ 40% / Qwen 3.7 Max ≈ 0% / GPT-5.5 < 1%。

| 层级 | 模型 | 长期占比 | 角色 |
|---|---|---|---|
| **L1** | DeepSeek V4 Flash | **80%** | 日常主力：Obsidian 维护、文档、笔记、知识库更新 |
| **L2** | DeepSeek V4 Pro | **15%** | 深度思考：Agent 学习、架构设计、RAG/MCP 设计 |
| **L3** | Qwen 3.7 Max | **4%** | Agent 工程：多步骤执行、Tool Calling、仓库级修改 |
| **L4** | GPT-5.5（中转） | **1%** | 战略决策：职业规划、顶层设计、跨领域融合、架构评审 |

### 场景一：Obsidian 知识库维护

| 任务 | 推荐模型 |
|---|---|
| 整理笔记 | L1 Flash |
| 读书笔记生成 | L1 Flash |
| YAML / Properties 生成 | L1 Flash |
| 标签分类 | L1 Flash |
| 双链建议 | L1 Flash |
| Markdown 转换 | L1 Flash |
| 整个 Vault 分析 | L2 V4 Pro |
| 知识体系梳理 | L2 V4 Pro |
| 方法论提炼 | L2 V4 Pro |
| 思维模型审查 | L4 GPT-5.5 |

### 场景二：学习 Agent 开发

| 阶段 | 推荐模型 |
|---|---|
| 学习 RAG / MCP / Agent 概念 | L2 V4 Pro |
| 学习 LangGraph | L2 V4 Pro |
| Agent Demo 开发 | L2 V4 Pro |
| Python 项目开发 | L2 V4 Pro |
| 多 Agent 协作系统 | L3 Qwen 3.7 Max |
| 长流程 Tool Calling | L3 Qwen 3.7 Max |
| 自动修复大型代码仓库 | L3 Qwen 3.7 Max |
| 架构评审 | L4 GPT-5.5 |

### 当前阶段最优方案

> 当前重点：建设 Obsidian 知识库 → 学习 Agent 六层架构 → 开发第一个完整 Agent 项目

| 角色 | 模型 | 工具 | 说明 |
|---|---|---|---|
| **主力** | DeepSeek V4 Pro | **Qoder + Claude Code** | Agent 开发学习与编码 |
| **辅助** | DeepSeek V4 Flash | Qoder | 知识库日常维护、文档处理 |

**判断**：当前瓶颈是项目落地，而不是模型能力。

---

## 三、时间线与过渡计划

```
学习阶段（现在） ─── 下月 ─────── 8月底 ──────→ 实战阶段（长期）
      │               │            │              │
      │ Qoder 月付     │ 续/停？    │              │ ← 按需续
      │ Claude Code    │──────────────────────→   │ ← 全程可用
      │ Cursor 年付 ─┤ 已停用，到期自然结束     │
      │ CB 赠送        │ 用完即停   │              │
      │ DS API         │──────────────────────→   │ 按量续充
      │ OpenCode       │──────────────────────→   │ 实战阶段主力
```

- **学习阶段（现在 ~ 8 月底）**：Agent 开发 Qoder + Claude Code（V4 Pro）；Obsidian 维护 Qoder（Flash）；OpenCode 已安装，实战阶段前不强制使用；Cursor 已停用
- **实战阶段（9 月起）**：OpenCode 绝对主力 + Qoder 按需续费；Claude Code 保留作为辅助 Agent 编码工具；DeepSeek API 按量续充
- **长期稳定**：OpenCode + DeepSeek V4 Flash/Pro 直连 + GPT-5.5 中转，不依赖任何单一平台订阅

---

## 四、待办

- [x] 确定未来主力 Agent：OpenCode + Qoder ✅ 2026-06-20
- [x] 确定模型四层梯队与场景路由（GPT 对话产出）✅ 2026-06-20
- [x] 确定当前阶段主力 V4 Pro + 辅助 Flash ✅ 2026-06-20
- [ ] 配置 OpenCode 接入 DeepSeek V4 Flash + V4 Pro
- [ ] 搭建/确认 GPT-5.5 中转服务可用性
- [ ] 评估 Qwen 3.7 Max 接入路径（进入 Agent 工程实战阶段时）
- [ ] 8 月底前完成 Cursor → OpenCode 全量迁移
