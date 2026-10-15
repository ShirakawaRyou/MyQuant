# 中文图表与结果输出

默认展示语言为简体中文。回测图表的标题、坐标轴、图例，Markdown 报告、终端运行摘要，以及登录看板与默认导出均使用中文。股票代码、程序接口和原始数据字段保持稳定。

当前中文报告：

- [开发区间](../reports/research-portable-20261015/development/report.md)
- [验证区间](../reports/research-portable-20261015/validation/report.md)
- [最终检验区间](../reports/research-portable-20261015/holdout/report.md) · [中文逐笔成交](../reports/research-portable-20261015/holdout/成交记录.csv) · [净资产及回撤曲线](../reports/research-portable-20261015/holdout/equity.png)

每个区间新增六份中文 CSV：成交记录、基准成交记录、资产曲线、每日持仓、公司行动、未成交记录。编码为带字节顺序标记的 UTF-8；买卖、拆股、分红、策略与基准等标签均已翻译。成交价已经包含滑点，滑点成本用于披露，不能再次扣除；手续费另计。原始英文字段 CSV 和 summary.json 仍可用于程序读取及完整溯源。

项目打包了 Noto Sans CJK SC 字体及 SIL 开放字体许可证，不依赖本地电脑、服务器系统字体或外部字体网站。wheel 中已验证包含字体及许可证。三个真实研究区间渲染均未出现缺字警告。

## 冻结记录与一致性

原冻结记录 `frozen-20261015.json` 未修改。改动前的代码、项目依赖声明与锁文件保存在 `source-before-chinese-20261015.zip`，可重建原代码校验值。

本次仅修改原项目中的 `src/myquant/cli.py` 和 `src/myquant/reporting.py`，并增加字体文件。计算引擎、数据校验、信号、实验校验逻辑、协议和依赖逐字节保持一致。

由于原代码校验值包括命令行和报告源码，中文展示版本单独使用 `frozen-20261015-zh.json`，其中记录父冻结文件及其 SHA-256，并明确标记最终检验区间已经被查看。这不是重新调参，也不把旧区间重新称为未见样本。旧冻结文件不能直接配合已改动的展示源码运行；不要关闭冻结校验。

三个区间重新运行后，`equity.csv`、`trades.csv`、`benchmark_trades.csv`、`positions.csv`、`corporate_actions.csv`、`rejections.csv` 均与原报告逐字节相同；除实验溯源元数据外，summary.json 的所有字段完全相同。中文成交记录分别为 5,525、1,682、1,843 行，与原成交数一致。

复现命令见根目录 README；请使用新的输出目录。中文导出的生成不连接或操作任何交易账户。

## 后续跨平台兼容更新

Windows 本地入口要求跨系统代码身份一致，因此 `study.py` 中用于计算校验值的相对文件路径现统一调用 `as_posix()`，不再使用随系统改变的路径分隔符。其他研究代码、引擎、协议、依赖与数据不变。

当前代码改用 `frozen-20261015-portable.json`；其父记录是中文展示记录，改动前代码保存在 `source-before-portable-20261015.zip`。原始两个冻结记录均保留，不能混用源码与校验值。跨平台版本在 Linux 再次复现三个区间，全部原始 CSV 与非溯源业绩字段仍与最初报告一致。Windows 原生验收尚未执行。
