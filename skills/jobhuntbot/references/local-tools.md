# 资格检查与台账预览

两个脚本仅依赖 Python 标准库，不浏览官网、不填表、不提交申请，也不修改台账。输入必须来自实际官方规则、个人已确认事实与最新记录。所有输入、输出放私有目录；控制台只输出数量或状态。

## 明确资格与志愿限额

`templates/eligibility-input.example.json` 是空模板。输入含 `target`、`facts`、`rules`。每条规则有 `id / kind / required / source: {ref, checked_at}`，`checked_at` 为核实日期；可用 `scope` 指定公司、岗位、部门、届别、专项等范围。

- `graduation_window`：规则含 `start/end` 日级边界，`field` 默认 `graduation_date`。对应事实含 `value / precision / confirmed: true / source_ref`。只有年月而边界在月中时，返回未知，不自行补日。
- `requirement`：规则含 `field / expected`；事实同样必须已确认且有来源。论文“优先”应为 `required: false`，缺少仅记加分劣势。
- `quota`：含 `used / maximum / ledger_evidence_ref`。计数必须来自官方限额与实际申请记录，不按推荐数计算；普通和专项批次不能未经证实合并或相加。

```text
python scripts/check_eligibility.py --input private/eligibility.json --output private/eligibility-result-v1.json
```

结果为 `ineligible / unknown / eligible_for_checked_rules`，只覆盖输入的已查规则，不等于岗位全部资格已满足，更不是匹配分或通过率。跨项目规则不适用时忽略；当前缺少适用硬规则仍为未知。职责匹配、证据强弱与方向转换代价仍需 Agent 阅读完整 JD 判断。

## 台账变更预览

输入台账支持包含 `records` 的 JSON、JSON 记录数组，或 CSV。默认字段沿用 `company / role / jobId / department / cohort / id / updatedAt / status`。CSV 等其他系统可使用 `templates/tracker-mapping.example.json` 指定字段与已有状态顺序；不要求改变原系统。

`templates/tracker-events.example.json` 是空数组。每个待记录事件含：

- `event_id`：本次证据事件的稳定编号；重复输入同一事件不会生成第二条变更。
- `identity`：`company`、`job_id` 或 `title`，以及适用的 `department / cohort`；明确识别了旧记录时可填 `record_id`。
- `observed_at`：带时区的实际证据时间。旧记录时间缺少时区或含义未知时先核实映射，不编时间。
- `evidence: {kind, ref}` 和 `patch`：只修改有证据的字段，不通过 patch 改实体身份。

```text
python scripts/tracker_plan.py --ledger private/applications.json --events private/events.json --mapping private/mapping.json --output private/change-plan-v1.json
```

真实提交的证据种类为 `submission_confirmation / official_application_record / user_confirmed_submission`；`saved_record` 不足以更新成已投递。旧截图不能回退新状态。确有官方纠错或本人明确更正时，使用 `correction: true` 和 `official_application_record / user_confirmed_correction`，不能永久禁止合法更正。

同公司不同岗位、部门、批次分别识别；旧记录缺编号而新事件有编号时先解决身份歧义，不按同名自动合并，也不盲目新增。需要合并的别名、集团与子公司关系必须有人或官方来源确认，工具不猜。

结果保存原文件 `source_sha256`、变更摘要、冲突和私有的 `proposed_records`。`safe_to_apply: false` 时不能应用部分结果。为 true 时也先核对当前原文件校验值未变，再由原系统在已有授权范围内写入；保留全部无关字段和记录，之后读回。此脚本始终只生成预览。

退出码 0=预览无冲突或已查资格通过，1=有冲突/资格不满足或未知，2=输入或输出错误。再次执行使用新的输出文件，不覆盖上次证据。
