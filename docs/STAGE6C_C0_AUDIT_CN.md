# 6C：6B最终交付独立审核

实际GitHub查询确认[PR #10](https://github.com/Whsjbwy/erqulunwengfx/pull/10)的HEAD为`73bfd383971659833373434b15c499ae909c92f4`，相对6A准确基点`4553d0f7e14207c92eb69dafd444cfdab395bcf7`仅有47个新增文件，未合并。[该HEAD的Windows CI](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/43694473392)为success。实际快照见[pr10_verification.json](../results/stage6c/pr10_verification.json)。

从公开CSV和仓库外36个唯一任务目录重算K/M/E/S=36/21/21/11；RRT为18/13/13/7，SST为18/8/8/4。15条approximate未升级；4条独立证书晚于10秒，均未计M。6个解析任务共用空旷网格，不是6张独立地图。

逐任务核对输入、地图字节、共同初态、隐藏见证未进入请求、原生输出与原始汇总。重新积分和认证27661个原生区间，并重新检查16259个已保存LOS区间。没有发现不一致或严格安全假阳性。审核没有启动搜索或新LOS模拟。[机器摘要](../results/stage6c/c0_audit.json) · [逐任务审核](../results/stage6c/c0_jobs.csv)

6B源码通过`find_package(ompl 2.0.2 EXACT CONFIG REQUIRED)`链接官方`ompl::ompl`，实际构造官方control SST/RRT，树核未另写。C0复读官方SST的solve、incumbent回调与保护成员，及冻结模型/完整球扫掠适配。原21条构建命令中的6次失败保留，未清洗成首次通过。官方源码、依赖和二进制未进入Git。

时钟核查区分原生内部事件与外部进程：规划10秒包含请求序列化、完整原生进程、结果读回与独立控制证书，搜索最多8秒；参考/LOS上限20秒，规划和执行阶段合计30秒。曲线上的native事件时间不能代替独立证书实际完成时间。[冻结映射](STAGE6B_MODEL_MAPPING_CN.md)

C0通过后才开展C1。新适配器又通过13例真实SI接口验收，930个接受区间、936次传播调用，与冻结6B状态差为0；本机CTest2/2通过。这里验证五状态仿真一致性，不声称完成实物AUV或6DOF辨识。
