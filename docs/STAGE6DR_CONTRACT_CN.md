# 6D-R俯仰数值边界契约与最小修复

研究者已确认本方案。基点为PR #12准确HEAD `e753954ea007412da74a2fb6917c45f15a14f2df`；6D全部原件及其BLOCKED事实保持冻结。本文件和确定性验收协议先于修复实验提交。

## F0：真实根因

本轮用原始`terrain_1/input.json`和未修改的6D probe重新执行，仍在索引89（8.9—9.0s）得到冻结区间期望1步、官方SI实际0步，pitch比名义界高`2.7755575615628914e-16rad`。位置、yaw和连续几何通过。新审计原件另存在`local_only/stage6dr_audit/f0_original_probe`，没有覆盖6D证据。

令L为冻结C++ `pitch_limit=pi/9`、t为冻结`pitch_tolerance=1e-12`，T为浮点运算实际得到的`L+t`。冻结模型对有限pitch采用`abs(theta)<=T`，原6C pitch子空间却以`[-L,L]`加OMPL机器epsilon判断。累积积分的舍入误差落在两个数值边界之间。原13例通过并不覆盖这一贴边序列。

## 唯一修复与备选比较

选择**组合复用原6C information()，仅将其pitch子空间bounds设为[-T,T]并重新setup**。不复制传播器、状态检查器、模型、目标或几何实现。命名新适配器`auv_pitch_contract_v1`，提供独立确定性验收入口。

不选择额外自定义StateSpace类：它会增加需要验证的覆盖行为，本次无此必要。clamp会改变积分状态，移除`satisfiesBounds`会绕开必要检查，修改模型容差/物理界/角速率或几何余量会改变冻结科学定义，均排除。官方OMPL和6B/6C/6D源码不改。

## 精确语义与证明边界

对同一有限五状态q，修复后的有效性仍为：

```text
V(q) = space.satisfiesBounds(q)
       AND frozen_validate_state(q)
       AND full_sphere_point_geometry(q)
```

模型允许的pitch满足`abs(theta)<=T`，因此落在新声明的pitch区间内，不会再被较窄名义边界误拒。OMPL自身epsilon可能使`T`外少量ULP仍满足其bounds，但这些状态会被**未改的冻结模型最终判据**拒绝；这不是新增可接受状态。按实际binary64的T及nextafter相邻值验收，不把十进制注释当精确阈值。

传播器继续逐0.1s调用冻结`check_interval`，包含原速率/俯仰、解析积分、曲线弦偏差和完整球扫掠认证。候选状态不截断；拒绝时保留原sentinel及`propagateWhileValid`返回安全源状态的语义，实际接受步数才是传播成功证据。

初态速度是固定参数，非法速度在映射到五维SI前拒绝，不能通过read_state固定写回1掩盖。对于非法源状态，不违反官方propagateWhileValid“源状态已有效”的前提强行传播；记录未调用及真实状态/入口拒绝结果，不能把空值伪造为传播测量。

## 采样域与其他不变量

实际pitch子空间数值端点各向外移动已有t（以binary64差值为准）；这一微小数值域变化必须透明披露，不能声称声明bounds逐位未变。名义±20°科学限制和模型已有容差不变。位置/SO2、权重、控制范围、0.1s步长、1—50步、目标球和原目标姿态采样均复用冻结实现；不运行采样规划，也不靠随机样本证明全域性质。setup后检验端点、度量和元数据一致。

## 验收与权限

先做正负界限、上下ULP、容差内外、近零、非法初态/控制及穿障/障碍接触/工作空间逃逸确定性验收；任何不一致停止。通过后重跑原13例和六图给定控制，逐区间核对真实SI、冻结C++和独立Python连续认证。terrain_1要求完整370步，不能用Python单独通过代替。

工程构建、原始故障继续被检测、新模型接口通过三种状态在本机与最终HEAD Windows CI分开记录。唯一最终结论为MODEL-INTERFACE PASS或BLOCKED；即使PASS也停止，不恢复54规划，不授予H1权限。
