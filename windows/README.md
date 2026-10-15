# Windows 10/11 本地部署

本方案在你的 PC 原生运行 Python，不需要 WSL、Docker、云服务器或域名。IBKR 密码只在官方 TWS/IB Gateway 登录；项目只连接本机 API，不保存 IBKR 密码。看板需要独立密码，默认中文、醒目标注“模拟交易”。

**当前验证机器是 Linux 云环境。已实际验证跨平台代码中的独立进程、登录、互斥和研究流程；尚未在 Windows 10/11、Windows PowerShell 5.1、你的 TWS/Gateway 和模拟账户上执行验收。** 初次使用先保持只读监控，连接成功不等于已经完成模拟下单验收。

## 1. 解压与安装

在 [MyQuant 仓库](https://github.com/ShirakawaRyou/MyQuant) 选择 **Code → Download ZIP**，或使用本任务提供的 `myquant-windows.zip`。在压缩包属性中选择“解除锁定”（如果有），再用 Windows 解压功能解压到本机目录。打开包含 `README.md`、`pyproject.toml` 和 `windows` 文件夹的项目根目录；GitHub 下载的目录通常名为 `MyQuant-main`。不要放到共享网络盘或同步数据库的网盘目录；项目源码与运行数据库分开保存。

在普通 PowerShell 中安装 uv：

```powershell
winget install --id astral-sh.uv --exact
```

如果没有 winget，按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 获取 Windows 版本。安装后关闭并重新打开终端，使 PATH 生效。

双击 `windows\Setup-Windows.cmd`。它会用 uv 安装 Python 3.12 和锁定依赖，配置 TWS 模拟端口 7497，并让你隐藏输入看板密码两次，至少 14 个字符。看板用户名固定使用 `owner`。**这里输入的是新建的看板密码，不是 IBKR 密码。** 脚本不需要管理员权限，也不修改电脑的永久执行策略。

如果使用 IB Gateway 模拟模式，在项目目录的 PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\windows\Setup-Windows.ps1 -ApiPort 4002
```

首次安装需要联网下载 Python 和依赖，使用正常的 TLS 与包校验。之后运行已缓存的历史回测不需要 IBKR；账户同步和模拟交易需要网络。

## 2. 登录官方 IBKR 客户端

从 IBKR 官方网站下载安装 TWS（初次联调更便于观察）或 IB Gateway。在客户端选择 **Paper Trading／模拟交易** 登录，按官方要求完成认证。

在 TWS 的全局配置 → API → Settings 中核对：

- 启用 ActiveX 和 Socket 客户端连接。
- 模拟 Socket 端口为 **7497**；原生 IB Gateway 模拟端口通常为 **4002**，须以客户端设置为准。
- 初次测试保留 **Read-Only API／只读 API**。
- 只允许本机连接；若有可信 IP 设置或连接提示，仅允许本机 `127.0.0.1`。

本地启动器固定连接本机，不使用云端容器的 4004 转发端口。程序还会检查实际账户必须为 `DU` 模拟账户，端口正确不等于账户检查可以省略。多个模拟账户时可用配置脚本的 `-Account DU账户号` 指定，勿填写实盘号。

## 3. 启动并查看

保持 TWS/Gateway 登录后，双击 `windows\Start-Local.cmd`。脚本会分别启动策略后台和看板，并尝试在默认浏览器中打开本机看板。使用 `owner` 和你设置的看板密码登录。如果浏览器未自动打开，查看配置中的看板端口，手动访问本机 localhost 的该端口；默认端口为 8090。

双击 `windows\Status-Local.cmd` 查看进程、连接状态、账户快照和数据目录。正常启动但客户端尚未就绪时，会明确显示“未连接／尚无数据”，不会虚构余额或成交。看板最初没有曲线，首次成功同步后才开始记录。

先确认：模拟账户正确，账户资产和持仓与官方界面一致，日线及更新时间正常，策略原因可见。历史与实时行情权限需单独检查；只有延迟行情时可以显示账户，但当前自动执行要求新鲜实时买卖报价。缺权限时不伪造行情、不提交订单。

关闭浏览器或启动脚本的窗口，不会停止两个后台进程。重复启动会复用已确认身份的进程，不会另外启动一套策略。看板只监听本机；本地 HTTP 登录仅在明确的本机模式使用，公网云部署仍要求 HTTPS 和 Secure Cookie。不要把本机端口转发到公网。

## 4. 在本机重跑历史回测

双击 `windows\Backtest.cmd`，默认重跑 2022–2025 年区间，**不需要 TWS、IBKR 登录或行情订阅**。本地包附带已校验的五只股票 2009–2025 年快照、原始文件和清单，不会重新下载或偷偷更换数据。

结果保存到当前用户本地应用数据目录的 `MyQuant\reports`，终端显示完整路径。打开 `report.md`、`equity.png` 和 `成交记录.csv`。要选择其他区间：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\windows\Backtest.ps1 -Stage development
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\windows\Backtest.ps1 -Stage validation
```

参数仍为原来的 20/60 均线、五只股票、每只目标 20%、相同手续费和滑点模型。2022–2025 年已经被查看，这只是复现，不是新的未见样本检验。代码校验路径现统一为正斜杠，使用 `research/frozen-20261015-portable.json`；原记录与源码归档保留。

## 5. 启用 IBKR 模拟下单

先确认只读监控、行情权限和账户预算正确。双击 `Stop-Local.cmd` 停止本机服务，在官方客户端取消 Read-Only API，再在项目目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\windows\Configure-Local.ps1 -EnablePaperOrders
```

如果使用 Gateway，追加 `-ApiPort 4002`；若此前指定了 DU 账户或其他看板端口，请继续传入对应参数。该步骤不改看板密码或历史记录。重新运行 `Start-Local.cmd`，状态应显示允许模拟下单。恢复监控时，停止服务后重新运行配置脚本，不传 `-EnablePaperOrders`，并恢复客户端只读 API。

后台只在美股常规交易时段检查执行条件。现有预算为 10 万美元与账户美元净值的较小值，每只目标为预算的 20%；存在手工持仓、现金不足、过期行情、挂单或待核对提交时会等待。限价 DAY 模拟订单不保证成交，不能等同回测的下一开盘价。

先核对少量模拟订单的状态、独立成交回报、手续费与原因。项目不自动接管你此前手工建立的持仓。看板的刷新、登录和关闭均不会下单。

## 6. 每天开机与停止

日常流程：开机 → 登录官方客户端的模拟模式 → 运行 Start-Local → 用 Status-Local/看板确认同步。开盘前完成，测试阶段建议覆盖整个常规时段。按当前芝加哥时区，美股常规时段通常为工作日 08:30–15:00，节假日及提前收盘日另计。

在 Windows“设置 → 系统 → 电源”中按需将插电时的自动睡眠设为“从不”；关闭显示器不等于让电脑休眠。项目不会自动修改电源计划。关机、休眠、断网或客户端退出会暂停策略，之后会重新核对状态，不能承诺完整补齐停机期间的历史。晚开机可能在盘中成交，与开盘回测不同。

停止服务用 `Stop-Local.cmd`。**停止、关机或断网不会自动撤销已进入 IBKR 的订单，也不会自动平仓。** 在官方模拟界面核对剩余挂单。Windows 终止后台进程后，未确认提交会在下次连接时核对，无法确定则保持待核对，不盲目重发。

若以后需要开机启动，可在 Windows“任务计划程序”中创建普通用户登录后的任务，程序选 `powershell.exe`，参数为 `-NoProfile -ExecutionPolicy RemoteSigned -File "项目绝对路径\windows\Start-Local.ps1"`。先手工联调稳定后再启用；TWS/Gateway 的登录与认证仍需完成，不因添加启动任务而自动授权。

## 数据与故障排查

- 数据默认位于 `%LOCALAPPDATA%\MyQuant`：`local.json` 是端口/模拟执行配置，`processes.json` 是进程身份；`trading\paper.sqlite3` 是持久交易账本，`auth\auth.sqlite3` 保存看板密码哈希和会话，日志为 `worker.log` 和 `web.log`。Windows 访问权限依赖当前用户配置文件的 NTFS 权限，不声称 POSIX 的 0600 等同 Windows ACL。
- 程序更新前先停止本机服务，保留此应用数据目录；不要删除数据库来“解决”待核对订单。重置看板密码可重新运行安装脚本，现有交易账本仍保留；配置默认恢复仅监控。
- 显示未连接：检查客户端已登录模拟模式、API 已启用、端口一致、连接提示已允许、客户端编号未冲突。凭据或账户日志不要发到公共网站。
- 显示行情未就绪：检查 API 的历史及实时行情权限；模拟账户存在不代表已订阅行情。
- 看板端口被占用：先停止本机服务，再通过配置脚本指定其他 `-DashboardPort`，不要强制结束未知程序。
- Windows 原生安装、脚本执行、启动器的 Windows 分离进程行为以及你的实际模拟成交，仍需在本机验收。仓库中的 Windows CI 结果可在 GitHub Actions 查看，不能以 Linux 测试代替 Windows 验收。
