# Attention 机制的数学推导 —— 从 Q、K、V 到 softmax

> 问题来源：笔记深度补充——Agent 面试最容易被追问的底层知识
> 关联：`docs/learning/v3-why-llm-can-call-tools.md`、`src/agent_raw/react_loop.py`（模型调用测与 Attention 的关系）

## 1. 为什么需要 Attention

RNN（循环神经网络）处理序列时的问题：

```
处理第 100 个词时，第 1 个词的信息已经"遗忘"得差不多了
因为信息在每一步传递中不断被压缩和衰减
```

Attention 的核心思想：**不要按顺序传递信息，而是让每个位置直接"关注"序列中所有其他位置**。

类比 Java：RNN 像一个链表——要访问第 100 个元素必须从头遍历。Attention 像一个 HashMap——每个位置可以直接 O(1) 访问任何其他位置。

## 2. Q、K、V 的直观理解

在讲解数学之前，先用一个类比理解 Q、K、V：

**类比：你在图书馆查资料**

| 概念 | 类比 | 实际含义 |
|---|---|---|
| **Q（Query）** | 你脑中想查的问题 | "我现在想要什么信息？" |
| **K（Key）** | 每本书封面的标题和标签 | "我这本书提供什么信息？" |
| **V（Value）** | 书的实际内容 | "这本书的具体信息是什么？" |

Attention 做的事：
1. 拿 Q（你的问题）和每本书的 K（标题标签）做匹配 → 算出"匹配度"
2. 根据匹配度，决定从每本书的 V（内容）里取多少信息
3. 加权汇总取出来的信息，就是最终结果

## 3. 数学推导

### 3.1 输入：三个矩阵

```
X: 输入序列的嵌入矩阵，维度 [seq_len, d_model]
   例：seq_len=10（10 个词），d_model=512（每个词用 512 维向量表示）
```

通过三个可学习的权重矩阵，计算出 Q、K、V：

```
Q = X × W_Q    # Query 矩阵，[seq_len, d_k]
K = X × W_K    # Key 矩阵，  [seq_len, d_k]
V = X × W_V    # Value 矩阵，[seq_len, d_v]

其中 W_Q, W_K, W_V 是可学习的参数矩阵
d_k = d_v = d_model / num_heads（多头注意力中每个头的维度）
```

这三个矩阵中，W_Q、W_K、W_V 是**模型训练中学到的**——它们决定了模型认为什么是"好的匹配方式"。类比 Java：就像三个不同的 `Function<X, Y>`，把同一个输入 X 映射到三个不同的特征空间。

### 3.2 核心公式

```
Attention(Q, K, V) = softmax(QK^T / √d_k) × V
```

分四步解释：

**第一步：QK^T —— 计算注意力分数**

```
QK^T: [seq_len, d_k] × [d_k, seq_len] → [seq_len, seq_len]

结果矩阵中，[i][j] 表示：第 i 个词对第 j 个词的"原始关注度"
```

这是**点积**（dot product）：两个向量的对应位置相乘再求和。点积越大 = 两个向量方向越一致 = 两个词越相关。

类比 Java：`IntStream.range(0, d_k).map(k -> q[i][k] * k[j][k]).sum()`

**第二步：/ √d_k —— Scale（缩放）**

```
QK^T / √d_k
```

**为什么需要这个除法？**

当 d_k 很大时（比如 64），点积的值也很大。Softmax 在输入值很大时，输出会趋近于 one-hot（只有最大值接近 1，其他接近 0）。这意味着梯度几乎为零——模型无法更新参数。

除以 √d_k 后，点积的方差被归一化为 1，Softmax 的输入保持在一个合理的范围内。

**数学原因**：假设 Q 和 K 的每个元素独立，均值为 0，方差为 1，则点积 Q_i · K_j 的方差是 d_k，标准差是 √d_k。除以 √d_k 后标准差变为 1。

**第三步：softmax —— 归一化为概率分布**

```
softmax(score_i) = exp(score_i) / Σ_j exp(score_j)
```

对每一行（每个查询位置）做 softmax，输出是一个概率分布——所有权重之和为 1。

为什么要 exp？三个原因：
- exp 永远是正数——保证权重非负
- exp 让大的值更大，小的值更小——放大差异化
- exp 处处可导——反向传播时有梯庿

类比 Java：就像 `List<Double>` → `stream().map(Math::exp)` → normalize to sum=1

**第四步：× V —— 加权求和**

```
softmax(QK^T / √d_k) × V: [seq_len, seq_len] × [seq_len, d_v] → [seq_len, d_v]
```

结果矩阵中，第 i 行 = 所有位置的 V 的加权和，权重 = 第 i 个词对各位置的注意力。

类比 Java：对代码的每个 token，把所有其他 token 的信息按"相关性权重"加权求和。

### 3.3 带上 Mask（Decoder 独有的操作）

在 Decoder（自回归生成）中，生成第 t 个词时，不能看到第 t+1 个词及之后的词（因为还没生成）。所以要加 mask：

```
mask[i][j] = 0  (if j ≤ i)   # 可以看
mask[i][j] = -∞ (if j > i)   # 不能看

Attention(Q, K, V) = softmax(QK^T / √d_k + mask) × V
```

-∞ 经过 softmax → exp(-∞) = 0 → 被 mask 的位置权重为 0。

类比 Java：类似 `SELECT * FROM tokens WHERE position <= current_position`——只能看到当前位置及之前。

## 4. Multi-Head Attention

单头注意力只学习一种"相关性模式"。多头注意力并行学习多种模式：

```
MultiHead(Q, K, V) = Concat(head_1, ..., head_h) × W_O

其中 head_i = Attention(Q × W_Qi, K × W_Ki, V × W_Vi)
```

每个 head 有自己独立的 W_Q、W_K、W_V，所以每个 head 学的是不同的"关注模式"：
- Head 1 可能学会关注语法关系
- Head 2 可能学会关注语义关系
- Head 3 可能学会关注位置关系

类比 Java：类似 Strategy Pattern——多个策略各自独立判断"谁跟谁相关"，最后合并结果。

## 5. 和 Agent 开发的关系

你不需要自己实现 Attention。但理解 Attention 对 Agent 开发有实际帮助：

1. **Prompt 设计**：你知道模型的注意力计算是 O(n²)（n 是 token 数），所以 prompt 越长推理越慢、注意力越分散。这就是为什么 ReAct 用 `scratchpad` 而不是无限堆 prompt——控制有效上下文长度。

2. **上下文窗口**：模型能处理的 max token 数由 Attention 的内存消耗决定。知道 QK^T 是 [seq_len, seq_len] 矩阵，你就能理解为什么 128K 上下文的模型推理极慢（矩阵是 128K × 128K）。

3. **工具调用设计**：你知道模型在生成 `{"name":"search_notes"` 时，它正在 attention 所有已注入的工具描述。如果工具太多（100+），attention 会分散，模型可能选错工具。

4. **面试叙事**：能从 Attention 的数学原理讲到 prompt 设计，比你只讲"用 React 模式写 prompt"有说服力得多。

## 6. 面试讲法

**30 秒版**：Attention 让每个词直接关注序列中所有其他词。Q 是你的问题，K 是每本书的标题，V 是书的内容。`softmax(QK^T/√d_k)` 算出关注权重，加权汇总 V 得到结果。

**追问深度**：
- 为什么除以 √d_k → 防止点积方差过大导致 softmax 梯度消失
- Multi-Head 的意义 → 多个注意力模式并行，各学不同的关系
- Mask 的作用 → 自回归生成时防止"看到未来"
