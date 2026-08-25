## ADDED Requirements

### Requirement: React Agent 聊天页面
系统 SHALL 提供名为 `Frontier` 的 React Agent 聊天页面。

#### Scenario: 用户打开 WebUI
- **WHEN** 用户打开 WebUI
- **THEN** 页面显示 Frontier 标题、欢迎内容、聊天区域、输入框和发送按钮

#### Scenario: 默认模板已被移除
- **WHEN** 页面完成加载
- **THEN** 页面不显示 React Logo、Learn React 链接或其他脚手架示例内容

### Requirement: 发送消息
系统 SHALL 允许用户向 Agent 发送非空文本消息。

#### Scenario: 用户发送消息
- **WHEN** 用户输入消息并点击发送按钮或按下 `Enter`
- **THEN** 用户消息立即显示在聊天区域并发送给 Agent

#### Scenario: 用户输入换行
- **WHEN** 用户按下 `Shift+Enter`
- **THEN** 输入框插入换行且不发送消息

#### Scenario: 用户输入空白内容
- **WHEN** 输入内容为空或只有空白字符
- **THEN** 页面不发送消息

### Requirement: 显示 Agent 回复
系统 SHALL 将 Agent 回复追加到对应用户消息之后。

#### Scenario: Agent 成功回复
- **WHEN** Agent 返回消息
- **THEN** 页面按对话顺序显示该回复并滚动到最新内容

### Requirement: 等待状态
系统 SHALL 在 Agent 处理消息时显示清楚的等待状态。

#### Scenario: Agent 正在回复
- **WHEN** 消息已经发送但 Agent 尚未返回结果
- **THEN** 页面显示 Agent 正在回复，并禁止用户重复发送

#### Scenario: Agent 完成回复
- **WHEN** Agent 返回成功或失败结果
- **THEN** 页面结束等待状态并恢复消息输入

### Requirement: 失败处理
系统 SHALL 在消息发送失败后保留当前对话并允许重试。

#### Scenario: 消息请求失败
- **WHEN** 页面未能获得 Agent 回复
- **THEN** 页面显示失败提示，保留已有消息并提供重试操作

#### Scenario: 用户重新发送
- **WHEN** 用户点击重试
- **THEN** 页面再次发送失败的消息

### Requirement: 响应式页面
系统 SHALL 保证聊天页面在电脑和手机浏览器中均可正常使用。

#### Scenario: 使用电脑浏览器
- **WHEN** 用户在宽屏设备上打开页面
- **THEN** 对话内容以易读宽度居中显示

#### Scenario: 使用手机浏览器
- **WHEN** 用户在窄屏设备上打开页面
- **THEN** 消息和输入区域完整可见且不产生横向滚动

