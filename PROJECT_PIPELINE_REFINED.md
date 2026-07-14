# Investment Project Pipeline (Refined)

## 当前状态结论
你的项目已经完成了从“信息采集”到“候选池审批”再到“周度复盘”的核心闭环雏形，当前唯一硬阻塞是 **Tushare Token**（用于阶段3正式跑数）。

---

## 一、当前链路（提纯后）

### 阶段1：情报采集与赛道信号
- 脚本：`01_Data_Harvest/playwright_spider.py`
- 配置：`config/settings.json -> playwright_spider`
- 产物：`01_Data_Harvest/VIP_Txt_Dumps/*_Insights_*.txt`
- 机制：
  - 多站点抓取（已扩展）
  - 关键词+负向词过滤
  - 赛道置信度写入
  - 去重索引 `seen_urls.txt`

### 阶段1.5：主题抽取
- 脚本：`03_Quant_Data/extract_themes_from_vip.py`
- 产物：`03_Quant_Data/A_Share_Reports/themes.json`
- 机制：从高置信文章抽取赛道强度和关键词。

### 阶段1.6：手工硬核增强
- 文件：`03_Quant_Data/A_Share_Reports/themes_manual_boost.json`
- 来源：
  - `AI_Computing_Infrastructure.txt`
  - `Interconnect.txt`
  - `Liquid_Cooling.txt`
- 机制：将“咽喉点+量化证据+映射环节”结构化为可加权信号。

### 阶段2（你手工主导）：咽喉点逻辑审批
- 手册：`02_Audit_Prompts/Tactical_Execution_Manual_v2.md`
- 新增第零闸口：赛道咽喉点真实性（BMS）

### 阶段3：A股候选池与量化数据
- 候选池：`03_Quant_Data/tushare_pool_builder.py`
  - 强制排除：`688*`、`300*`
  - 输出：`candidate_pool_pending_review.json`
- 主数据引擎：`03_Quant_Data/akshare_stock_upgrade.py`
  - 当前模式：`tushare_only`
  - 输出：个股JSON + 汇总JSON + data_quality

### 阶段3总编排
- Runner：`03_Quant_Data/run_pipeline_stage3.py`
- 快捷脚本：`run_stage3_pipeline.sh`
- 产物：
  - `candidate_pool_approval_sheet.json`
  - `stage3_pipeline_summary.json`
  - `runs/{run_id}/`归档

### 阶段4：影子审计（抽检）
- 脚本：`03_Quant_Data/time_slice_tester.py`
- 用途：历史切片反作弊验证（防未来函数污染）

### 阶段5：审批后输入打包
- 脚本：`03_Quant_Data/build_approved_prompt_input.py`
- 用途：将 `approved` 标的打包为审计输入。

### 阶段6：周度健康复盘
- 文件夹：`04_Weekly_Review/`
- 脚本：`weekly_review.py`
- 用途：每周收益/纪律/风控健康打分与建议。

---

## 二、建议保留的“执行主线”

1. 运行抓取：`playwright_spider.py`
2. 提取主题：`extract_themes_from_vip.py`
3. 运行阶段3：`run_stage3_pipeline.sh 20`
4. 人工审批：`candidate_pool_approval_sheet.json`
5. 生成审计输入：`build_approved_prompt_input.py`
6. 按手册给出 GO/HOLD/REJECT 与下单参数
7. 周末运行 `04_Weekly_Review/weekly_review.py`

---

## 三、还可优化的点（按优先级）

### P0（建议尽快）
1. **将 `themes_manual_boost.json` 接入 `tushare_pool_builder.py`**
   - 当前已生成增强包，但尚未与建池评分正式融合。
2. **修正赛道历史文件命名不一致问题**
   - `Chip_Memory` 与 `Next_Gen_Storage`、`Robotics_Hardware` 与 `Humanoid_Robotics` 建议统一映射，减少主题分裂。

### P1（稳定性）
3. **抓取质量体检脚本**
   - 每次抓取后统计：每赛道文章数、平均置信度、噪音比例、缺料方向。
4. **审批单执行闭环字段自动回填**
   - 将 `execution_status/execution_price/execution_time` 自动同步到周复盘。

### P2（交易质量）
5. **周复盘增加基准比较**
   - 比较沪深300/中证红利，输出超额收益。
6. **月度复盘脚本**
   - 汇总四周纪律分、回撤、胜率、盈亏比。

---

## 四、你现在的准备度评估
- 数据与流程准备：**高**
- 可执行性：**高**
- 唯一外部依赖：**Tushare Token**

结论：
> 新电脑到位并配置 Token 后，你可以立即进入“正式分析 + 候选审批 + 试仓执行 + 周复盘”的完整实战周期。

