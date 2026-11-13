# 阶段6A实际验收与交付记录

## 预登记与真实执行

提交`4bffc9a`先冻结[执行边界](STAGE6A_PROTOCOL_CN.md)与[12个验收输入](../configs/stage6a_feasibility_protocol.json)，然后才编写/运行解析验收。没有增加随机规划或参数搜索；未来协议的`execution_authorized=false`。

在仓库根目录、Python 3.11已有环境中实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_stage6a_feasibility.py -q
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6a.feasibility --local-dir ..\local_only\stage6a_feasibility
.\.venv\Scripts\python.exe -m gsunlight_repro.stage6a.review
.\.venv\Scripts\python.exe scripts/stage6a_figures.py --trace ..\local_only\stage6a_feasibility\acceptance.json.gz
```

验收CLI拒绝已存在的本地运行目录，历史结果路径也被保护。完整逐步控制/接受及拒绝记录只保存一份压缩文件在仓库外；公开逐次CSV及摘要JSON不是虚构数据。首轮三个核心测试实际通过，后续完整质量检查以机器记录为准。

12例全部符合预登记预期：6个给定控制的运动可行见证、6个拒绝输入/场景，930个接受区间、27个独立50子步RK4核对，最大位置偏差`1.2079226507921703e-13 m`。负例拒绝原因分别为航向率、俯仰率、俯仰角、物理障碍、任务顶界、速度不属于冻结模型。没有将其称为规划器成功率或真实AUV动力学验证。

首次核心Ruff发现一条说明字符串超过88列，已换行修复；首次全量静态检查又发现绘图行超长与两个新文件格式问题，已修复。两次失败的简要记录在`local_checks.json`，首次静态命令没有单独捕获完整日志，不声称该日志文件存在。

## 完整质量检查

本机实际489项测试通过（11.74秒），编译、Ruff及205个Python文件格式检查均退出0。完整执行命令、退出码、测试数量、时间和精简输出记录在[本机检查](../results/stage6a/local_checks.json)，每条测试见[逐测试CSV](../results/stage6a/pytest_results.csv)。完整日志/JUnit保留本地`local_only/stage6a_audit`，不上传Git。图示随后仅调整排版，不重跑数值验收；最终图已目视检查，并单列最终静态复查。

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe -m pytest -q --junitxml=..\local_only\stage6a_audit\pytest.xml
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

新增测试覆盖解析左右圆弧、标量曲率/独立率反例、拒绝候选不能计入接受轨迹、历史路径输出保护、缺失布尔值必须显式报错、历史不同分母、文献证据深度和未来协议未授权状态。没有为纯报告文字编写镜像测试。

官方Windows证据见[CI记录](../results/stage6a/windows_ci.json)，对应`.github/workflows/stage6a-windows.yml`，在`windows-latest`上实际检查Python编译、完整pytest、Ruff与格式；只使用自编代码/合成数据，不依赖私有作者资料或完整轨迹。CI成功不表示OMPL安装成功，工作流没有安装或测试OMPL。

## 科研与文件范围验收

公开结果不包括完整轨迹、作者论文/源码/地图、环境、完整日志或额外文件hash清单。新增源码只读复用既有ODE/几何/RK4，不改冻结LOS、速度、率限制、球形认证和目标阈值。相对5A-F基点的范围核对见[交付审查](../results/stage6a/delivery_review.json)。

文献元数据22个DOI已核验，但部分全文/官方代码仍未核验，不能把文献数量或CI通过当作创新证明。结论保持`Need-Baseline-Evidence`。新分支`research/auv-executable-planning-stage6a`的PR目标为`audit/auv-stage5af-terminal`，不合并main；阶段结束后等待审核。
