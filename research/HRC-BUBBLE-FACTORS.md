# 泡沫因子与风险溢价

对象：本机HRC 4.1.0.202603231401。独立工具使用与主训练相同的ICM/MTT/KO/PKO终局权益；不读取训练策略，不需要运行原程序。

原`eC.a(kG,double[],ph)`先移除本手盲注和额外底池，让每一对玩家按有效筹码全下。基准是交盲前权益，赢/输后权益包含相应淘汰和赏金。FGS场景在此原工具中同样选静态ICM或赏金权益，不能把表格称作FGS风险溢价。

行玩家对列玩家：`BF=(base−lose)/(win−base)`；原`D.a(double)`显示`RP=100×(BF/(BF+1)−0.5)`，单位为百分点。这是无死钱、两人等额投入模型相对50%门槛的风险溢价，不是实际某个有盲注/边池局面的跟注胜率要求。

原字节码审计与未修改原纯数值类对照见[报告](../reports/hrc-original-bubble-validation.json)。27组2–10人ICM/KO/PKO，990有序玩家对、1,980个原版终局；金额最大误差1.42e-14，BF最大误差3.78e-15，RP最大误差7.78e-14百分点。此矩阵未直接初始化GUI handler，也不覆盖MTT；MTT复用单独验证的原近似模型，并有有限场排列枚举测试，其积分误差不能冒称精确ICM。

相同固定奖金等退化输入的0/0被保留为undefined，JSON值为null；无穷比值同样单列状态，不填成0。明细给出每一对的base/win/lose供复核。

实现：`native/hrc_tournament_analysis.cpp`、`preflop_lab/hrc_analysis.py`。接口：`POST /api/tournament-analysis {config}`或`GET /api/jobs/:id/tournament-analysis`。资源与FGS表不会被加载。结果包括金额权益、BF矩阵、RP矩阵与逐对明细；同一初始场景不受当前选中的行动节点影响。
