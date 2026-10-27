# 私有资料的共同约定

技能自带 `templates/candidate_profile.template.json` 为版本 2 空模板。已有主档不必迁移，不为普通岗位推荐建立完整画像。只提取当前判断需要的事实，个人资料永远放在用户自己的工作区。

`facts` 每条有稳定 `id`、语义 `field`、原始 `value`、`precision`、`status`、`source: {kind, ref}` 和带时区的 `confirmed_at`。`kind` 为 `document / user_confirmed / user_entered_saved`。第三种表示本人填写并保存，不表示证书已验证。

`precision` 为 `day / month / year / text / number / boolean`。`status` 为 `confirmed / unconfirmed / superseded`。日期保留原精度，未来计划与进行中状态分开，不把年月补成未经确认的日。

真实事实使用 `usage: fact`；某次申请的暂填日期、目录映射或特殊答案使用 `usage: form_answer`，必须有 `scope.company` 及 `scope.job_id` 或 `scope.application_id`，可再限定部门与届别。全局事实的 `scope` 为 `{}`。

不同已确认来源冲突时不自动采用较新时间或更高成绩。用户明确更正后，用同字段、同用途、同范围的 `supersedes` 指向旧事实编号；保留原证据。另一家公司答案、旧待办、旧简历均不能覆盖本次已确认事实。

`resumes` 包含 `{id, path, version, sha256?}`，文件路径相对用户工作区。推荐材料前核对内容与版本，不凭文件名排序选择最新。`preferences` 与 `application_contexts` 分别记录全局偏好和单次申请选择，不相互覆盖。

如已安装 `resume-application`，可选用其资料包与保存核验工具；本技能本身不依赖另一个技能安装位置。未安装时按上述约定人工准备即可。
