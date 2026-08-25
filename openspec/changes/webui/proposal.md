## Why

现有 WebUI 只是 React 默认页面，用户无法通过它与 Agent 对话。需要将其重写为真正可用的聊天网页。

## What Changes

- 使用 React 重写 WebUI。
- 页面以 Agent 对话为核心，而不是展示项目或技术信息。
- 用户可以输入问题、发送消息并查看 Agent 回复。
- 页面清楚展示等待回复和请求失败状态。
- 聊天界面适配电脑和手机。

## Capabilities

### New Capabilities

- `web-chat`：用户可以在浏览器中与 Agent 进行对话。

### Modified Capabilities

无。

## Impact

- 替换 `webui/frontier` 当前的 React 默认页面。
- 不改变 Agent 本身的能力和行为。

