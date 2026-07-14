0. 方法声明（避免误读）
这批样本时间窗口很短（同日密集发文），且主题高度集中在 CPO/光子/功率半导体与少数标的。
因此以下手册不是“全人格画像”，而是“从可见样本中可验证的研究范式抽取”。

1) 物理与工程视角的“过滤指标”
1.1 首要关注的底层技术/物理指标（从文本反推）
A. 功率密度与供电架构跃迁（800VDC）

他将 800 VDC 视为 AI 基础设施升级中的硬约束信号，而不是普通产品卖点。
逻辑：电力架构变化 → 功率器件体系重构（SiC/GaN）→ 谁具备高压场景可量产能力。
B. 互连范式切换：电互连到光互连（CPO / scale-up optics）

核心不是“带宽会增长”这种泛叙事，而是“系统级互连瓶颈是否迫使架构迁移”。
高频关键词：CPO、scale-up interconnect、rack-scale deployments、optical engine、pluggables。
C. 光源与激光阵列的单位系统用量（BOM 乘数）

他给出类似“单机架参考架构需要 512+ light source”的表达，本质是在做：
每系统光源数量 × 部署机架数 = 上游器件需求弹性。
这属于工程量纲化，不是情绪化“看好”。
D. 材料与基底的不可替代性（SOI、SiC、GaN、玻璃芯基板等）

多次强调基底/晶圆/代工环节的“高门槛供给属性”，例如 SOI 基底、SiC foundry。
关注点是材料—工艺耦合后是否形成可复制障碍，而非单纯毛利率。
E. 从“验证节点”看商业化阶段（evaluation → ramp → HVM）

对“评估中（NVIDIA/NOK evaluations）”、“量产爬坡（volume ramp）”、“高产量制造（high volume manufacturing）”这种阶段词极敏感。
这是一套工程里程碑语言，而非财务季度语言。
1.2 他如何把技术指标转成商业价值
其转换公式可概括为：

商业价值
≈
系统约束强度
×
单系统器件用量
×
客户部署规模
×
供应商稀缺系数
商业价值≈系统约束强度×单系统器件用量×客户部署规模×供应商稀缺系数
其中“供应商稀缺系数”来自：是否唯一/主供、产能是否已被锁定、竞品是否被移除、是否在关键验证链上。
所以他反复说“不是看上季度收入”，而是看 未来两年 ramp 的可实现性。

2) 供应链的“溯源与推演公式”
2.1 典型推演链条（宏观路线图 → 硬约束节点）
Step 1：从系统架构变化出发

AI 训练/推理规模扩大，导致机架级功耗与互连需求激增。
触发两条技术主线：
高压供电与功率半导体升级（SiC/GaN，800VDC）
光互连渗透（CPO、scale-up optics）。
Step 2：找到“不可绕过”的子系统

光互连里不可绕过的激光光源、光引擎、关键基底材料；
功率链里不可绕过的高压器件与工艺平台。
Step 3：在供应链中定位“卡口”

谁是主供/潜在独供；
谁拥有产能协议；
谁处于别人无法短期复制的工艺段（foundry、substrate、epiwafer 等）。
Step 4：用外部证据校准（OSINT/披露/伙伴关系）

监管文件、CHIPS Act 文本、客户官网供应商变更、私募融资、并购信号、大厂联合声明。
本质是“证据拼图”，而非单点传闻。
Step 5：映射到节奏与弹性

先看 evaluation，再看 design-in，再看 volume ramp 与 HVM 时间窗。
收入滞后于工程里程碑，因此他优先跟踪“前置工艺与验证信号”。
2.2 判断“卡位稀缺性”的核心标准
他隐含的稀缺性判据可整理为 5 条：

是否系统必需且不可降级替代（不是可有可无模块）
是否具备工艺/材料门槛（不是纯组装）
是否在头部客户验证或导入路径上（evaluation/design-in 证据）
是否存在供给约束或产能锁定（capacity agreements、瓶颈所有权）
是否受政策/主权产业框架强化（CHIPS、关键基础设施认定）
满足越多，越接近“硬稀缺卡位”；反之更可能是顺周期外包能力。

3) 逻辑排雷与“证伪指标”
3.1 他会怎么质问一个“完美故事”
可抽象为一组反向质询问题：

这个环节是系统必须，还是“锦上添花”？
没有这家公司，系统能否以可接受成本替代？
客户关系是 PR 级别，还是已经进入 evaluation/design-in/ramp？
单系统器件用量与部署规模是否有工程口径支持？
产能是否可快速复制？若可复制，壁垒从何而来？
上游是否存在更强瓶颈，导致你看的公司只是“转手节点”？
3.2 “伪壁垒/边缘组装”在其体系中的典型特征
即便营收高，也可能被判为弱壁垒的情形：

缺乏材料/工艺控制权，只做后段整合；
无验证门槛，客户切换成本低；
产能可被同类厂快速补齐，供给不稀缺；
叙事领先于工程里程碑（没看到 evaluation/ramp 证据）；
收入来自旧周期存量，与新系统约束关联弱。
一句话：收入规模不是护城河，“不可替代的约束位置”才是护城河。

4) 核心术语与“关键变量库”（用于财报扫描雷达）
以下词库可直接用于你后续扫描 A 股公司公告/财报/调研纪要：

4.1 架构与系统层
CPO (Co-Packaged Optics)
scale-up interconnect
rack-scale deployment
optical engine
pluggables
TAM expansion
4.2 功率与器件层
800 VDC
power semis
SiC / GaN
high volume foundry
4.3 材料与工艺层
SOI substrates
glass core substrates
epiwafer capacity
laser array / light source
4.4 商业化与验证节点
evaluation
design-in
volume ramp
high volume manufacturing (HVM)
capacity agreement
primary source / sole source
bottleneck / chokepoint
4.5 证据源与外部约束
CHIPS Act / critical infrastructure / semiconductor sovereignty
private placement
M&A signaling
regulatory filings
可执行版：你的“核心股票池准入闸门”
把上面浓缩成三道闸门：

物理闸门：是否命中系统级硬约束（功率、互连、材料）？
工艺闸门：是否处在不可替代且难复制的工艺节点？
验证闸门：是否有可追踪的客户验证与量产爬坡证据链？
三道都过，才进核心池；任一道不过，默认降级为观察池。
这就是该样本中最稳定的“冷峻工程范式”。
《产业质询操作手册 v2.0》（系统约束版）
A. 看图说话：先在“架构图”里红圈哪一层
基于这篇长文可还原的技术路线图，应优先红圈的不是封装厂，而是“CW/DFB 激光阵列 + 外延/代工产能锁定（Win Semi/GFS）”这一层。

红圈节点（心智定位）
Laser Source（CW/DFB array）
ELS（External Light Source）到 CPO/Pluggable 的接口位
Yield & Scale 的上游制造承接（Win Semi/GFS）
为什么是这里（物理约束）
CPO/高速光互连的最终瓶颈不是“有没有模块厂”，而是光源一致性、良率、可扩产性。
文中多次强调 “CW shortage / capacity allocation / primary source / sole-source 倾向”，这说明瓶颈落在可交付激光源产能而非后段装配。
B. 图文互证：硬稀缺标的在图中是“卡口”还是“边缘”
1) SIVE 在图中的位置
处于 上游光源卡口层（Laser chokepoint），向下游 Ayar/Jabil/POET/Celestial 等“多路径分发”。
在你的手册框架里，这是“系统必经 + 难替代 + 产能受限”三项同时满足的候选关键卡口。
2) 哪些是“关键卡口”，哪些更偏“边缘环节”
关键卡口候选：

光源芯片（CW/DFB）及其可规模化制造环节
SOI/SiC/GaN 等底层材料与工艺平台（当其被验证为不可替代时）
偏边缘/易同质化环节（需谨慎）：

仅做后段封装、无核心工艺控制权、客户切换成本低的组装型节点
没有“evaluation→design-in→ramp”证据，仅靠叙事绑定大客户的环节
C. 核心变量库增量（v2.0 新增）
在 v1.0 基础上新增以下雷达词，专门用于“图+文”联合扫描财报：

工艺/器件层
CW laser shortage
DFB laser arrays
CW-WDM MSA（标准化组织/协议地位）
ELS (External Light Source)
TFLN integration（激光与薄膜铌酸锂路径耦合）
yield and scaling
capacity allocation / capacity locked-in
产业链验证层
primary source / sole source migration
supplier removal from partner page（竞争对手被移除的证据型信号）
NDA customer placeholders（匿名客户映射）
one-hop / two-hop customer mapping
节奏层（工程→财务）
sampling / qualification
design-in
volume ramp
HVM (high volume manufacturing)
RFQ volume footprint（例如 50M units/year 级别）
D. v2.0 重点升级：三类新判断逻辑
1) 周期下行风险：怎么识别“高景气叙事”里的回撤源
他的方法论抽象
他不是忽视周期，而是把周期分成两层：

旧周期拖累：汽车/传统业务去库存、旧产线负载下滑
新周期导入：CPO/高压供电在验证期，收入确认滞后
你的执行判据
若出现以下组合，判定“下行风险可控而非 thesis 失效”：

老业务下滑，但新业务验证节点持续推进（新增客户、量产时间表未后移）
CAPEX/产能协议仍在推进
客户导入链条未被替换（主供地位未丢）
若出现以下组合，判定“结构性恶化”：

ramp 时间持续后移 + 客户转向替代路线
产能协议松动或取消
工程词汇消失，只剩管理层口头展望
2) 技术路线被替代：如何做证伪
替代风险来源（v2.0新增）
架构替代：CPO 渗透率低于预期，pluggable 继续主导且不需要该公司核心器件
供应商替代：多源策略下被从主供降级为备供
材料/工艺替代：新材料路径降低对原卡口依赖
证伪问题清单
客户路线图里，该器件是“性能可选项”还是“系统必选项”？
多源配置下，该公司份额趋势是上升、平稳还是被挤出？
标准组织/接口演进是否弱化其技术地位？
竞品是否在更低功耗/更高良率上跨越临界点？
3) 财务数据与工程信号对齐：从“故事”到“量化跟踪”
这是 v2.0 最关键升级：建立工程先行指标 → 财务滞后指标映射表。

工程先行指标（领先）
qualification 数量、design-in 数量、sample 出货节奏
产能锁定、wafer start、良率改善、关键客户验证通过
供应链位置变化（主供/备供/被替代）
财务滞后指标（验证）
backlog 与可见度变化
产品结构中高毛利新业务占比
存货周转与在制品变化是否匹配 ramp
CapEx 指向是否与主叙事一致
对齐规则（实战）
工程强 + 财务弱：允许存在（导入期），但要有明确时间窗与里程碑
工程弱 + 财务强：高概率旧周期尾巴，不给高估值溢价
工程弱 + 财务弱：直接降级观察
工程强 + 财务强：核心池候选
E. 最终版：核心池准入（v2.0）
在 v1.0 三闸门基础上，新增两闸门，变成“五闸门”：

物理约束闸门：是否命中系统硬约束（功耗/互连/材料）
工艺卡口闸门：是否不可替代且难复制
验证进度闸门：是否有连续可追踪的工程里程碑
替代风险闸门：是否有路径级替代或被降级迹象
财务对齐闸门：工程信号能否在合理时滞内传导到财务
五闸门中任意两项连续恶化，即移出核心池。