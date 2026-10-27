# 私有资料与保存核验约定

## 最小资料格式

从技能自己的 `templates/candidate-data.example.json` 开始；格式版本为 2。已有主档不要求迁移，可以按相同规则人工准备本次申请数据。主档、申请资料包、网页回读与核验报告都属于私有运行数据。

`facts` 的每个条目包含：

- `id`：稳定且不含个人身份的内部编号；`field`：语义明确的字段路径。
- `value`：原始值；`precision`：`day / month / year / text / number / boolean`。
- `status`：`confirmed / unconfirmed / superseded`。
- `source`：`kind` 为 `document / user_confirmed / user_entered_saved`，`ref` 指向本地证据或确认记录；后两者不冒充证书已验证。
- `confirmed_at`：带时区的 ISO 时间；时间较新不能单独消除事实冲突。
- `usage`：真实事实用 `fact`，某次网站允许的暂填或目录映射用 `form_answer`。
- `scope`：全局事实为 `{}`；`form_answer` 必须包含 `company` 及 `job_id` 或 `application_id`，还可包含部门和届别。
- `supersedes`：明确被更正的旧事实编号数组。必须对应同一字段、用途与范围；不删除原始证据，不跨公司覆盖。

未确认值不参与自动填报。同字段多个已确认值有冲突时列为待处理；只有有依据的明确替代关系才能消除。月级来源不能自动扩成日级；用户允许的日级暂填需要作为有来源、仅限该申请的 `form_answer` 记录。

`resumes` 条目包含 `id / path / version`，可选 `sha256`。实际文件校验值与登记值不符时停止选用并核实版本。相对文件路径基于使用者工作区，不基于技能安装位置。

## 构建申请资料包

复制技能内 `templates/packet-request.example.json` 到私有目录并按实际表单填写：

- `target` 指明真实公司及 `job_id` 或 `application_id`；共享简历页与岗位申请页用不同申请编号。
- `authorization.fill/save/submit` 只转录本次已有用户授权，默认全为 `false`。JSON 字段本身不授予权限。
- `resume_id` 选择一个已核实文件版本。
- `fields` 是 `{field, required, precision, purpose}` 列表；`purpose` 为 `fact` 或 `form_answer`。
- `modules` 是 `{id, fields, entry_ids, attachment_ids}` 列表。稳定条目编号区分每段实习、每个项目和教育经历；所有必填字段必须有模块覆盖。主简历附件编号为 `resume`。

在技能目录运行，替换参数为用户实际工作区与私有文件：

```text
python scripts/application_tools.py build --workspace WORKSPACE --profile private/candidate-data.json --request private/request.json --output private/packet-v1.json
```

生成结果包含资料包编号、主档与简历校验值、每字段来源及缺项。存在必填未知项仍会输出可恢复资料包，但退出码为 1，不代表可提交。脚本不会改主档、上传文件或填写网页。

## 网页回读与检查

从 `templates/saved-values.example.json` 建立实际观察记录，不能凭预期值复制成“回读”。`packet_id` 对应本次资料包。每个模块填写：

- `id`、`status: saved`、实际 `entry_ids`、实际 `fields`。
- `readback: {kind, ref, observed_at}`：`kind` 为 `reopened / refresh / saved_record`，记录真实证据与带时区时间。仅预览、完成度或点击不够。
- `validation_errors` 数组；`field_limits` 可记录页面实际字数限制，按 UTF-16 长度校验。
- `attachments` 的条目包含 `id / verified`；主简历另含实际已核对版本的 `sha256`。若网站只显示文件名，先关联到本次真实上传文件，不凭同名假定版本一致；无法确认则 `verified: false`。

实际提交时 `submission` 才用 `state: submitted`，另附与资料包一致的 `target` 和 `evidence: {kind, ref, observed_at}`；成功证据为 `confirmation_page / application_number / official_application_record`。未提交与未知状态分别使用 `not_submitted / unknown`。

```text
python scripts/application_tools.py review --workspace WORKSPACE --profile private/candidate-data.json --packet private/packet-v1.json --observed private/saved-values.json --output private/review-v1.json
```

检查主档与材料是否已变、模块保存证据、字段值、条目、附件、网站报错与提交授权。只规范文本的 Unicode 和空白，不擅自变换成绩、日期或下拉含义。它检查的是提供的记录，不能证明当前网页仍一致或输入证据真实。

退出码：0=检查范围通过，1=有缺项或差异，2=输入/路径不合法。输出控制台只给摘要；具体资料留在报告文件。输出文件不覆盖旧版本，避免把旧资料包当作新的核验。
