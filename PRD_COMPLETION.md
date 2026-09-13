# PRD 完成对照 · V2

本轮在 V1 现有 Flask / Jinja2 应用上补齐上轮列出的 P0 缺口与全部 P1，不加入 PRD 明确排除的社交排名、强制锁机或未来预言。

| PRD 模块 | 本轮交付与入口 | 主要实现 |
|---|---|---|
| ONB-03 动态五问 | 前答个性化、静态题即时可答、请求防竞态、五问确认 | modeling.onboarding_question / onboarding.js |
| CHAT-03/04 | 行动卡编辑草稿、持久收起、快捷反馈、已存在任务复用 | chat.js / messages.feedback / drafts |
| AI 上下文 | 当前任务、完成标准、活动沉浸、明确偏好与授权证据 | app.py / modeling.chat_reply |
| FOCUS-04 离线 | 本地 FIFO、服务端时间锚、重发幂等、异常时间待校正 | focus.js / focus_actions / focus_intervals |
| ECHO-02 纠正 | 全行动分页、单条来源深链、改时长/结果/反思 | events APIs / echoes.js |
| MAIL-02 生成 | 欢迎与行动同人格来信、持久异步、失败重试、重写替换 | jobs / modeling.make_letter |
| PROFILE/MEM | 字段化候选、理由、多来源、冲突、手动锁定与修正 | memories / modeling.extract_candidates |
| 授权与拒绝 | 五问复用与记忆学习独立；拒绝清除原文只留签名 | users / session_profiles / memory_tombstones |
| 目标与计划 | 目标CRUD、手动里程碑、任务/里程碑关联、逐项确认AI拆分 | goals / milestones / extras.py |
| P1 语音 | 麦克风按钮，识别先入草稿、用户发送；逐条朗读/停止 | FS.voice / 浏览器原生语音API |
| P1 环境声 | 合成雨声、溪流、棕噪，音量与明确开关 | FS.audio / Web Audio |
| P1 定时信 | UTC日期锁封、到期后开信、去重站内通知 | letters.open_at / notifications |
| P1 画像历史 | 版本差异、恢复进编辑框再确认、永久删除快照 | profile_versions / profile_history_deleted |
| P1 授权导入 | 文本、TXT/MD/CSV/JSON/DOCX，逐项授权/撤回/删除 | imports / queued memory jobs |
| P1 多设备 | 同服务器账号记录刷新、草稿版本冲突保留两份 | sync_versions / drafts / FS.syncDrafts |
| P1 周回顾 | 周期、时区、手动生成、定时生成、历史回看 | preferences / reviews / background tick |
| METRIC-02 | 实际卡片曝光、行动/回响/开信、帮助度/自主感 | analytics_events / feedback |

## 生成与事实分离

未配置服务端 AI_API_KEY 时，所有生成明确显示本地规则；配置 AI_API_KEY、AI_BASE_URL、AI_MODEL 后，同接口启用远程模型。远程响应有格式和引用检查，最多一次结构修复、15秒预算。没有训练一个真实的“人格预测模型”，没有把时间当作注意力评分。

## 验证口径

只保留 smoke.py 一条临时库流程：授权、CSRF与隔离、动态问、记忆确认/拒绝、异步失败恢复、90秒离线区间、重复结算、源更正/来信替换、目标关联、到期开信、导入撤权、历史删除、草稿409冲突和周回顾。无真实第三方模型请求，无真实用户库写入。

浏览器定向查看了新增入口、聊天反馈与画像模块。没有替用户授予麦克风或通知权限，未把原生语音设备支持当作已实测结果。服务运行与升级/回滚哈希证据记录在 artifacts/v2/VERIFICATION.txt。

## 明确的运行条件

- 离线依赖提前访问后的设备缓存；已开始的沉浸可离线操作，新会话先在线创建。
- 同步要求设备访问同一后端。当前交付为本机运行服务，不包含擅自开通的公网托管。
- 定时回顾需服务器运行；服务器重启恢复未完成任务。关闭浏览器后不承诺系统推送，站内到期提醒会在打开时呈现。
- 语音依赖浏览器与用户许可，环境音由本机合成；识别可能经过浏览器厂商服务，启用前说明。
- 数据迁移保留旧账号记录。回滚恢复源码，不覆盖升级后的用户数据；升级前数据库备份保留在本机 instance/backups/before-v2.db。
