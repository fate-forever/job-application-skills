# 资料与任务入口

每个使用者自行指定工作区、公司池、当前简历、最新投递主档、结果文档与续查断点。没有历史任务时，不假设存在已经查过的公司或正在流程中的申请。

使用者可把本技能 `templates/workspace-config.example.json` 复制为自己工作区的 `private/workspace.json`，再填入实际路径。路径相对该工作区，不相对技能安装目录。配置文件不存在时，询问路径；不要默默使用旧工作区。

只读检查命令：

```text
python scripts/inspect_state.py --workspace <使用者工作区> --config private/workspace.json
```

参数由当前工具的路径引用规则正确传递；上述尖括号是文档占位符。配置项 `screening_data` 指向包含 `companies`、`jobs` 和 `coverage` 的 JSON。公司对象含 `name`、`status`；岗位对象含 `company`、`jobId`。本技能 `templates/screening.example.json` 是空模板。现有系统字段不同时，先确认映射，不转换或覆盖用户系统。

可选项：`document_pointer`、`local_backup`、`resume_checkpoint`、`application_ledger`。无对应文件时留空。`application_ledger` 采用 `records` 数组时可直接统计；其他结构先适配。

公司状态可沿用 `未检索`、`查阅中`、`已检查`、`已检查（当前机会未核实）`、`入口受限`。已有系统状态优先，未知不等于没有岗位。

当前资料、用户确认、投递记录和实际招聘页面优先于旧断点。文档指针只在使用者私有配置中保存，不能写入公共技能。事实按需读取，不把整个主档复制进技能。

结构化断点采用本技能 `templates/checkpoint.example.json`，必须记录当前数据的 `data_sha256`、正在查的公司、下一步和待同步事项。检查脚本会指出主档与断点是否对应、重复公司与岗位实体、分页覆盖声明矛盾及未读 JD 数；这些检查不证明官方信息仍有效。
