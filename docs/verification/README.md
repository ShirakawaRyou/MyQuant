# 首版验证材料

Linux 云环境中研究测试 43 项、服务测试 39 项通过，无失败或跳过。完整验证范围见 [验证说明](../../deploy/VERIFICATION.md)。

两张看板截图由真实 Chromium 对隔离测试账户生成，画面中的 DU123、资产、订单和成交均为软件测试样本，顶部已标注“界面测试样本 · 非真实 IBKR 账户数据”。这些截图不证明个人 IBKR 账户已连接或模拟订单已成交。

- [桌面看板测试样本](dashboard-test-fixture-desktop.png)
- [手机看板测试样本](dashboard-test-fixture-mobile.png)

`container-check.json` 保留此前云部署版本的四项容器检查结果；当前 Windows 兼容版本没有重新运行 Docker 构建和容器验收。Windows 原生测试以仓库 Actions 的实际执行结果为准，个人券商联调仍待执行。
