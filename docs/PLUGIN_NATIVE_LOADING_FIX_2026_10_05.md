# DSH 原生插件加载修复（2026-10-05）

## 已确认根因

1. 宿主使用 DSH 0.2.0-rc.1 Config 表单服务，但生态中的插件仍使用命名空间 SettingsProvider 的 get/register/watch 协议。旧桥接 register 返回 disposer，缺少 get，不能满足真实发布接口。
2. dsh.client.inject/external 与 npm dependencies 是两份声明。只安装 npm 生产依赖不能保证客户端图完整；package.json 也不一定通过 exports 公开。
3. 浏览器载入 Node Loader 的内部探测代码，访问 process.versions.node。此前在 Node 全局环境中执行渲染测试掩盖了错误。
4. 宿主预先声明插件自己的子槽位，触发原生槽位注册器的重复声明错误。
5. 固定客户端 URL 与仅按包更新时间复用的 Host，使修复后的源码不能正确使旧运行缓存失效。

## 通用修复

- Host 插件、依赖服务和客户端插件使用官方 Cordis Loader 创建 Entry，保留原始 entry id、inject、isolate、intercept、disabled 和表达式处理，以及原生生命周期与导出解包。服务目录继续从官方基础组合与包元数据按需发现提供者。
- 客户端工厂注册、require、require.async、分块注册及模块缓存接入官方 ClientModuleSystem；原生工厂源码不改写。仅由构建包装把注册入口连接到嵌入式模块系统。
- 对工厂调用及子槽位声明做 JavaScript AST 分析，避免把注释和错误文本误判为依赖。插件声明的子槽位交给原生父槽位管理；移除对原生 conversation、session、sidebar 提供者的错误预声明，使用实际原生组合。语言接口采用官方 LocaleRuntime，避免不完整替代接口。
- 浏览器构建禁用 Node 内部探测，并把 Loader.internal 注入为真实客户端模块系统。测试移除 process 全局，并增加独立浏览器 realm 验证。
- 通用依赖解析遵循包依赖、peer/dev 声明和 DSH 客户端图；缺包安装到应用拥有的依赖缓存。官方未指定版本的依赖选择与宿主相同版本，或不高于宿主的发布版本，避免 registry latest 标签和 alpha 版本漂移。支持未公开 package.json 的导出表。安装不执行依赖脚本。
- 原生命名空间服务来自 @deepseek-ai/dsh-settings@0.0.1-rc.3 未修改的发布源码，保存于 native/vendor，随附许可证和来源摘要。通过 Cordis 隔离作用域与新版设置表单共存；读取、注册返回值、监听、校验、写队列、版本冲突和注销由官方实现执行。存储层原子持久化，并读取旧桥接已保存的配置。
- 服务端与浏览器缓存使用当前原生源码内容版本，页面 JS/CSS URL 使用实际生成版本。Host 也把原生源码版本纳入复用条件。

## 程序验证

- @dickpy/dsh-imagegen：真实发布包及其原生客户端组合编译，独立浏览器 realm 中设置页实际显示。
- @liustack/modlens@3.26.6：真实发布包编译、真实 Cordis Host 激活、真实 HTTP 设置路由、无 process 的浏览器 realm 设置页渲染。
- 缺少 dsh-client-ui-settings-plugins 的独立插件：自动补齐到宿主版本、原生 Loader 激活、设置页渲染。
- 未知插件缺少开发依赖库：Host 与客户端自动解析、安装、调用，并复用缓存；package.json 未公开仍可解析。
- 命名空间设置读取、注册 handle、更新、无效值拒绝、持久化和进程重启恢复。
- require.async 分块模块、压缩 factory 参数、嵌套槽位、异步设置页、设置页面与对话页面隔离。
- 配置校验、启动失败回滚、缺少真实服务时撤销安装、ESM/CJS 匿名标准插件导出，以及 SDK 完整性保护。

全部通过程序断言与真实接口验证；未使用模拟点击。
