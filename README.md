# MyQuant：美股日线研究与模拟交易

首版提供固定规则历史回测、中文图表与逐笔记录、登录看板及 IBKR 模拟账户连接模块。Linux 云环境中 **82 项测试通过**；Windows 原生运行和个人 IBKR 模拟账户的实际连接、订单与成交仍待验收。默认只监控，不自动下单。

**Windows 10/11 本地部署**：从本仓库选择 **Code → Download ZIP**，解压后按 [Windows 安装与运行说明](windows/README.md) 操作。本地使用官方 TWS/Gateway、独立后台与中文看板，不需要云服务器、域名、Docker 或 WSL。

查看现成结果：[中文回测报告](reports/research-portable-20261015/holdout/report.md) · [收益及回撤曲线](reports/research-portable-20261015/holdout/equity.png) · [中文逐笔成交](reports/research-portable-20261015/holdout/成交记录.csv)。最终区间策略收益 33.23%、最大回撤 18.10%；买入持有基准收益 55.80%、最大回撤 24.26%。这些是历史模型结果。

历史研究与回测继续使用本页说明，不需要你的电脑安装软件。新增的 **IBKR 模拟交易登录看板** 在 [services/dashboard](services/dashboard/README.md)，云服务器、HTTPS 与 Gateway 部署及查看步骤见 [部署说明](deploy/DEPLOYMENT.md)。研究 CLI 保持独立；新增服务不修改已经冻结的研究规则或历史结果。

**展示语言默认为简体中文**：图表标题、坐标、图例、报告、运行摘要、看板和面向人工查看的 CSV 均使用中文。股票代码、命令参数、原始 CSV/JSON 字段保持稳定，供程序读取。项目自带授权中文字体，不需要在电脑或服务器另装字体。

已确定的首轮方案：

| 项目 | 规则 |
|---|---|
| 固定股票池 | AAPL、MSFT、AMZN、JPM、JNJ |
| 临时数据来源 | Yahoo 日线、拆股、现金分配记录；长期数据源以后再讨论 |
| 买卖条件 | 因果总回报指数的 20 日均线高于 60 日均线时做多，否则空仓 |
| 成交时点 | 收盘判断，下一交易日开盘按目标仓位再平衡 |
| 仓位 | 每只目标 20%，保留未投资现金；不融资、不做空 |
| 研究初始资金 | 每段独立从 100,000 美元开始，不代表你的账户余额 |
| 开发区间 | 2010–2018 |
| 验证区间 | 2019–2021 |
| 最终检验区间 | 2022–2025 |

这轮运行固定规则，**没有训练机器学习模型，也没有自动搜索最优参数**。选择当前仍存续的五只股票存在幸存者和选择偏差，结果只适用于这组固定股票，不能解释为全市场效果。

## 运行环境与测试

Python 3.12，依赖通过 `uv.lock` 固定。在云端终端运行：

```bash
cd /workspace/MyQuant
export UV_CACHE_DIR=/workspace/.cache/uv
export UV_PYTHON_DOWNLOADS=never
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen myquant --help
```

不需要数据库、Web 服务、券商软件或 API 密钥。已缓存真实行情在 `data/research-20261015/`；原始数据、标准化 CSV 与文件校验值均保留。各股票 2009–2025 年共 4,276 根日线，2009 年仅用于首个开发区间的指标预热。

## 复现已冻结的研究

规则在 [research/protocol.json](research/protocol.json)，当前跨平台中文版本的冻结记录在 `research/frozen-20261015-portable.json`。原冻结记录及源码存档均保留。展示更新之外，仅将校验路径统一为正斜杠，避免 Windows 路径分隔符造成不一致；计算引擎、数据、参数和研究依赖未改。三个区间的原始 CSV 及指标逐项核对一致，详见 [中文输出说明](research/CHINESE_OUTPUT.md)。冻结记录绑定代码、依赖锁、规则和数据清单的 SHA-256，运行前还会核验原始文件与 CSV。任何改变都会拒绝使用旧冻结记录。

使用现有数据与冻结记录，选择新的报告路径运行：

```bash
uv run --frozen myquant study --config research/protocol.json --data data/research-20261015 --freeze research/frozen-20261015-portable.json --stage development --out reports/my-run/development
uv run --frozen myquant study --config research/protocol.json --data data/research-20261015 --freeze research/frozen-20261015-portable.json --stage validation --out reports/my-run/validation
uv run --frozen myquant study --config research/protocol.json --data data/research-20261015 --freeze research/frozen-20261015-portable.json --stage holdout --out reports/my-run/holdout
```

每段独立重置资金与持仓；此前数据只用于预热指标，不能把三段净值直接拼接成连续投资业绩。最终区间不参与参数选择。**一旦查看最终结果，这段历史就已经被揭示；后续不能根据它反复改规则，再声称它仍是未见样本。** 哈希记录约束可复现性，不能阻止人在程序外查看历史。

实际运行结果见 [research/RESULTS.md](research/RESULTS.md)。仓库包含固定快照 `data/research-20261015/` 和三个区间的中文参考报告 `reports/research-portable-20261015/{development,validation,holdout}/`，可直接从 GitHub 下载后复现。新下载的快照不保证与此固定快照相同。凭据、运行数据库、会话、日志和其他临时输出不提交。

## 新数据快照与 CSV 导入

需要重新下载时，用一个新目录：

```bash
uv run --frozen myquant fetch --config research/protocol.json --out data/new-snapshot
uv run --frozen myquant freeze --config research/protocol.json --data data/new-snapshot --out research/new-frozen.json
```

新快照属于新实验身份；提供商数据可能修订，不保证重新下载与旧快照逐字节相同。想精确复现本次结果应保留已有缓存与冻结记录。行情请求使用 HTTPS 的 `query1.finance.yahoo.com`。原始响应会获取至下载当天，以还原后来拆股对早期行情单位的影响；研究仅使用配置指定的历史区间。

CSV 导入无需连接 IBKR，也不要求任何交易权限。每只股票一个同名文件，如 `AAPL.csv`，必须含以下列：

```text
date,open,high,low,close,volume,dividend,split_ratio
2024-01-02,100,102,99,101,1000000,0,1
```

OHLC 必须是当时的实际价格单位；`dividend` 是当日除息、按当日拆股后每股计的现金分配，无分配填 0；`split_ratio` 是新股数/旧股数，无拆股填 1。**未知企业行动不能直接填零，复权价也不能冒充当时价格。** 部分券商导出数据已经复权，需要先确认口径、补齐行动记录。

```bash
uv run --frozen myquant import-csv --config research/protocol.json --input-dir /workspace/my-csv --source-label "verified historical CSV" --price-basis as-traded --out data/imported-snapshot
```

下载或导入缺股票、缺交易日、缺企业行动列、出现非法价格或校验值不符时，会停止并明确报错；不补造行情、不悄悄缩小股票池。失败快照保留 `manifest.json` 的错误，不生成完整研究业绩。

## 拆股、分红与防前视

- Yahoo 的普通 OHLC 也已按后续拆股调整。数据层结合完整快照内的拆股事件还原当时价格、分红和成交量单位；实际持仓层再在事件日调整股数，避免重复计算拆股。
- 信号使用逐日前推的总回报指数：当日增长因子为 `(当日收盘价 + 当日每股分配) × 当日拆股比例 / 上日收盘价`。只在当日收盘后获得该值，不使用未来分红对历史均线反向复权。
- 每个交易日先处理跨越除息日的原有持仓权益，再执行昨日信号。当日新买入不获得该日分红，除息日卖出仍保留分红权益。
- Yahoo 未提供完整历史派息日，因此现金分配在除息日计入**隔离余额**，纳入净值，但整个区间都不用于再投资。这不是实际到账流水；策略与基准采用相同假设，避免虚构可用资金。
- 正常买入取整股；拆股产生的零碎股允许按同样费用及滑点模型卖出，属于模型简化。

## 成交、费用和基准

默认手续费每股 0.005 美元、每笔最低 1 美元；双边各加 5 bps 不利滑点。先卖后买，多只股票共享现金；资金不足时按比例缩放买单并向下取整，不按代码顺序优先耗尽现金。

20% 是每日开盘再平衡时、按不含隔离分红的可投资净值计算的**目标**；取整、费用和盘中价格波动会使实际比例偏离，不是连续生效的硬风控上限。

基准在每段第一个开盘以同样 100,000 美元、同样费用和滑点等权买入五只股票，之后不再平衡，分红不再投资。策略和基准结束时都按最后收盘价估值，不强制卖出。

报告提供：

- `成交记录.csv`、`基准成交记录.csv`、`资产曲线.csv`、`每日持仓.csv`、`公司行动.csv`、`未成交记录.csv`：中文列名和买卖等中文标签，带 UTF-8 字节顺序标记，供人工查看。
- `report.md`、`summary.json`：总收益、年化收益、最大回撤、Sharpe、波动率、平均仓位、费用与数据来源。
- `equity.png`、`equity.csv`：策略与扣费买入持有基准的净值和回撤曲线。
- `trades.csv`、`benchmark_trades.csv`：双方成交、价格、数量、手续费、滑点成本与余额。
- `positions.csv`、`corporate_actions.csv`、`rejections.csv`：每日持股、拆股及分红核算、拒绝成交的原因。

日线模型不完整模拟成交量限制、冲击成本、税、现金利息、交收限制或实际券商收费。所有收益均为历史模型结果，不是盈利承诺。交易日检查不等于逐条行情和企业行动已由独立来源核验；当前 Yahoo 快照也不是严格的历史时点数据库，可能存在事后修订。

## 仅验证软件的演示

```bash
uv run --frozen myquant demo --output data/demo-new.csv
uv run --frozen myquant backtest --csv data/demo-new.csv --out reports/demo-new
```

演示数据是合成数据，不能作为策略有效性的证据。单 CSV 的 `backtest` 命令属于探索性实验，不会伪称已经留出最终检验区间。仓库早期的旧 AAPL 样本与报告不符合本阶段完整企业行动及区间要求，不用于本次结论。

云任务已有隔离环境，直接使用现有 checkout；不需要创建 Git worktree。
