# 阶段二版本与运行指南

本指南说明方法身份、配置和运行口径，不预设实验成功率。实际运行范围、结果和PR以[阶段二报告](STAGE2_REPORT_CN.md)为准，测试记录见[阶段二测试结果](STAGE2_TEST_RESULTS_CN.md)。阶段一结果保留在[原报告](STAGE1_REPORT_CN.md)，不与本阶段的新计时直接合并。

## 1. 三个G-Sunlight版本与两个对照方法

| 名称 / 方法ID | 实现版本 | 身份与边界 |
| --- | --- | --- |
| Author-Original / `author_original` | `author-zip-2026-stage2-observation-v1` | 运行用户本机作者原件；跳过明确列出的纯显示调用，增加只读观测包装；不加父边过滤、当前太阳直连捷径或更改原搜索参数。阶段二将同坐标的合成地图对象交给原入口，不把它冒称作者原始地图 |
| Paper-Reimplementation / `paper_reimplementation` | `stage2-paper-v1` | 独立重建算法1—5；按论文先检查当前太阳到目标、移除当前网格成员、保留历史长度、插索引1与删末项；未公开细节采用明确记录的解释，不声称与作者隐藏实现完全一致 |
| Safety-Reference / `safety_reference` | `stage2-safety-v1` | 独立自编安全参考，共享自编采样、网格及论文控制核心，显式增加父边和完整目标路径检查；不是阶段一作者hooks改名，也没有A*兜底 |
| A* / `astar` | `stage2-astar-v1` | 26邻居体素中心图，欧氏边代价与启发函数，保留真实起终点的虚拟连接，连续等价supercover禁止对角穿角；确定性方法 |
| RRT-Connect / `rrt_connect` | `stage2-rrt-connect-v1` | 自编双树扩展，固定seed，逐边及最终连接严格检查，保留真实端点；默认步长5、目标偏置.05，最近邻为透明的线性NumPy查询 |

可共用地图类型、严格几何检查、指标、预算和日志格式；共用基础设施不使三个G-Sunlight版本变成同一实验。具体论文对应及偏离见[三版本差异表](STAGE2_PAPER_CODE_DIFF_CN.md)和[重建假设](STAGE2_ASSUMPTIONS_CN.md)。作者文件仅保存在仓库外，原仓库未见明确 `LICENSE`，不在此再分发。

## 2. 地图与坐标

地图配置为 [`configs/stage2_maps.json`](../configs/stage2_maps.json)，`schema_version=1`。公共 `profile` 固定单元维度 `(100,80,80)`、origin `(0,0,0)`、spacing `(1,1,1)`，即物理坐标域 `[0,100]×[0,80]×[0,80]`。所有方法使用作者原始起点 `(2,2,2)`、终点 `(95,75,75)`，不以体素中心替换端点。维度指占用单元数，若构造VTK点网格则点维度为 `(101,81,81)`。

| 场景 | 固定配方 | 可达性证据 |
| --- | --- | --- |
| S0 | 全空三维空间 | 原始起终点严格直连见证 |
| S1 | 错位长方体和静态球形障碍 | 预先设计、严格验证的绕行折线 |
| S2 | 两堵厚2体素墙、宽6体素错位窗口和U形障碍 | 穿窗及绕行的严格有效见证 |
| S3 | 自编高斯峰谷海床和静态球形障碍 | 高处绕行的严格有效见证 |
| S4 | 完整封闭墙分隔起终点 | 验证全轴墙连续占用且端点位于两侧的解析不可达证书 |

所有场景使用确定性配方，没有障碍随机抽样。`map_seed`是冻结配方的标识，不是生成器随机数输入；在同一场景上运行seed 0—4只是五次规划调用，不代表五套随机地图。可达见证仅供场景质量校验，不作为规划器输入或失败后的替代路径。S4不可达结论来自几何证书，不能用某算法超时来证明。

S3搜索和占用数据仍采用正的地图z坐标；`world_z_offset=-80`仅说明显示关系 `z_world=z_map−80`，可将地图顶面显示为0。它不改变搜索数据、不新增洋流，也不等于论文100m×100m、45个球障碍的海床重建。全部长度使用地图坐标单位，不能自动与论文px或m列做同量纲数值复现。

## 3. 实验配置与schema

实验配置为 [`configs/stage2_experiment.json`](../configs/stage2_experiment.json)，`schema_version=2`。有效参数和场景配方写入本地 `environment.json`；CSV与路径JSONL使用结果 `schema_version=2`，每行记录 `run_id/scene_id/map_seed/method/version/seed`。

| 配置项 | 当前声明 | 含义 |
| --- | --- | --- |
| `limits.time_limit` | 30秒 | 独立方法入口开始的搜索截止时间，含本方法初始化；地图生成和加载在外 |
| `limits.max_nodes` | 100000 | 独立方法的节点资源保护；各算法原生节点含义仍应单列 |
| `limits.max_iterations` | 10000 | 独立方法适用的外部迭代保护；A*不以该上限替代其节点/时间预算，作者原生100计数保持原样 |
| `hard_timeout_seconds` | 32秒 | 各方法统一的外部进程保护，超时回收worker；不等同于允许32秒搜索成功 |
| `startup_timeout_seconds` | 30秒 | 启动和地图初始化的独立超时，不占首seed搜索额度 |
| `planning_seeds` | `[0,1,2,3,4]` | 提前声明的规划种子列表；预检可只运行0，实际运行列表由显式 `--seeds`记录 |
| `method_parameters` | 五方法分别保存 | 不按场景成功率逐图调参；完整展开参数随每次结果保存 |

Paper/Safety默认半锥角30°、锥内角步长5°、方位步长10°、径向步长5、长度差阈值15、前进距离3、容量网格边长5、容量1、`n_max=100`、`epsilon=.8`、`alpha=.5`。参数依据和补足项逐项列于[假设文档](STAGE2_ASSUMPTIONS_CN.md)。

作者原版不能在内部协作检查新截止时间，保留原计算并使用共同外部保护；若原生观测搜索耗时超过30秒，即使得到有效路径也不能计入预算内成功。不能宣称所有原生迭代或每个节点的计算量完全相同。启动、请求墙钟、搜索、独立验证、共同后处理分别记录；作者原生时间在原后处理之前截止，不能拿含后处理的其他时间直接排名。

## 4. Windows运行与扩展门槛

需要Python 3.11及README中的依赖安装。在仓库根目录运行；作者材料位于仓库外的 `..\LIU3Dsunlight-main`。以下名称仅为命令示例，如果目录或CSV已存在，应给整次运行换新标识和新输出，禁止覆盖或混合旧记录。

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --source-dir ..\LIU3Dsunlight-main `
  --map-config configs/stage2_maps.json `
  --experiment-config configs/stage2_experiment.json `
  --scenes S0 --seeds 0 --run-id stage2-s0-example `
  --local-dir ..\local_only\stage2_s0_example `
  --output results/stage2/s0_example.csv
```

默认运行五个方法。只运行自编方法时可明确指定，例如 `--methods paper_reimplementation safety_reference astar rrt_connect`，此时不要求作者材料。阶段二合成场景由配置在内存生成，不使用 `--map-path`替换单张作者VTI；该参数属于阶段一入口。

扩展顺序如下，门槛是记录正确和资源可控，不是要求所有算法成功：

1. S0、seed 0，核对五方法能正确启动、结束、写退出状态和路径证据。
2. S1单次核对后扩到五seed，核对失败原因、预算回收、严格验证和场景见证；路径失败与地图无解分开。
3. 以上可信后扩展其余地图五seed，S1原始25条保留并合并；五场景×五方法×五seed共125条。下面也给出一次完整重跑的命令，实际分批命令以运行记录为准。

```powershell
.\.venv\Scripts\python.exe -m gsunlight_repro.benchmark `
  --source-dir ..\LIU3Dsunlight-main `
  --map-config configs/stage2_maps.json `
  --experiment-config configs/stage2_experiment.json `
  --scenes S0 S1 S2 S3 S4 --seeds 0 1 2 3 4 `
  --run-id stage2-five-seed-example `
  --local-dir ..\local_only\stage2_five_seed_example `
  --output results/stage2/five_seed_example.csv
```

保持串行批量、同一场景定义与占用数据、相同端点、不打开绘图窗口；各worker在初始化后重用本场景。不因失败移动障碍、重挑场景或静默改变参数。二十seed的扩展需先核对当前预算与记录，不自动进行。阶段完成后停止等待研究者审核。

## 5. 如何读结果

| 字段 | 正确解释 |
| --- | --- |
| `reported_success` | 实际捕获的规划器是否报告/形成完整路径；不证明安全或在预算内 |
| `strict_valid` | 对保留原始路径做连续闭体素碰撞与真实端点检查后的结果 |
| `within_search_budget` | 有可测搜索耗时且不超过30秒；缺时间证据时未知 |
| `budget_valid_success` | 同时满足 `status=ok`、报告有路径、原始路径严格有效、搜索时间在预算内 |
| `status/termination_reason` | 正常结束、候选耗尽、论文迭代上限、外部资源耗尽、超时、异常或输入错误分列 |
| 空值 | JSON为 `null`、CSV为空；表示缺路径或缺观测证据，不等于 `False`，更不能写成零长度 |

超时前若方法保留了候选解，可以有 `reported_success=True`和严格有效路径，同时 `status=timeout/budget_exhausted`，仍不能成为正常预算成功。未捕获作者返回值的异常/硬超时保留未知；不伪造报告成功标志或缺失参数。异常中的作者局部状态若实际捕获，则按部分证据保留，不冒充正常完成。

主要路径质量比较 `raw_path_length`，只对严格有效路径解释长度。共同shortcut只对严格有效原始路径执行，结果用 `common_post_valid/common_post_length`单列；作者自带的原生后处理使用 `native_post_valid/native_post_length`单列，不能用原生处理后路径替换主要原始结果。无效原始路径不通过共同后处理“修成成功”并覆盖证据。

`sampled_nodes`在作者原版为作者图节点数，在Paper/Safety为射线查询数，在A*为发现的图节点，在RRT为树节点数；不能直接横向解释为相同“采样节点数”或据此排名。实际展开、生成候选、容量淘汰、碰撞检查也有方法相关语义，详见完整参数和事件。空扩展、候选拒绝、容量淘汰是实际观察事件，不是已建立因果的失败解释，不能把同时发生的计数冒充单因素消融。

A*是确定性方法，其五seed主要衡量重复运行的时间变化，不是五个独立随机成功事件。所有方法共享五个规划seed也不使五张固定地图成为随机环境总体样本；结果只支持本次固定场景范围。

公开汇总入口为[阶段二汇总](../results/stage2/summary.csv)。完整逐点路径、日志及环境证据留在仓库外，不提交作者材料、虚拟环境或额外文件校验清单。汇总、报告及PR只能在真实生成后说明完成情况。
