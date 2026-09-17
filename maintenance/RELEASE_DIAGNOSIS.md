# Windows v0.1.8 发布诊断

核对日期：2026-09-17。范围为诊断，尚未修改启动链路或重新发布。

## 证据身份

- GitHub 最新 release：v0.1.8，发布时间 2026-08-14；附件 Setup.0.1.8.exe，113547767 字节。
- 远端附件 digest 与本机 dist-electron/即物穷理 Setup 0.1.8.exe SHA256 一致：
  `326b640648cbd4a616fe9f54f3733ba151f5c6c424adc6295af20ed302844a0e`。
- Authenticode 状态：NotSigned。
- 使用 7-Zip 只提取安装器内的 resources/backend/praxic-backend.exe，未执行安装器。
- 提取后端 SHA256：`c6578cd500ed32a4edbccaac592c97c1f9052c860729f6a6f6b523afd4c7acf9`，与本机 unpacked 产物一致。

## 已复现：安装后的后端无法启动

v0.1.8 标签中的 praxic/__main__.py 使用：

```python
subprocess.Popen([sys.executable, '-m', 'uvicorn', 'praxic.api.server:app', ...])
```

冻结环境中 sys.executable 是 praxic-backend.exe，不是 Python 解释器。对子进程实际参数进行复现：

```text
praxic-backend.exe -m uvicorn praxic.api.server:app --host 127.0.0.1 --port 19481 --log-level info
error: unrecognized arguments: -m uvicorn praxic.api.server:app --log-level info
exit code: 2
```

Electron 等待后端健康接口，因此这一错误可以解释“安装后启动超时/打不开”。该缺陷不专属于 Windows 11。
后续修复方向：冻结模式直接调用 uvicorn.run，保留源码开发启动分支；增加真实冻结后端的健康检查，而非仅检查文件存在。

## 其他风险，尚未作为用户故障根因确认

- 未签名安装包可能触发 SmartScreen 或设备策略；需要实际提示截图。不要通过关闭系统安全保护来代替诊断。
- 后端把工作目录切到 exe 所在目录并写入配置/数据；安装到受保护目录时可能产生权限错误。
- Electron 缺少 --no-browser 参数，并且未消费 stdout；启动和错误收集还需完善。
- PyInstaller 仅打包 index.html，未包含 API 所需的 public 静态目录；前端又依赖外部 CDN，可能导致丢失资源或空白页。
- CI Python 依赖列表漏了 python-multipart；非 Windows 产物命名与 extraResources 的硬编码 .exe 不匹配；当前检查只有文件存在检查。均需另行修复并验收。
- 7-Zip 提取提示安装器内嵌归档尾部还有数据；提取成功，不能据此断言安装器损坏。

## 尚待用户提供

安装失败出现在哪一步、完整错误文字/截图、安装路径、Win11 系统架构及安全软件提示。
没有进行干净 Win11 虚拟机的安装/卸载测试，所以不能把已复现的启动失败等同于安装器本身失败。

## 参考

- [原始 release](https://github.com/Mourpheuon/Praxic/releases/tag/v0.1.8)
- [PyInstaller 冻结运行时说明](https://www.pyinstaller.org/en/stable/runtime-information.html)
- [electron-builder 故障分类](https://github.com/electron-userland/electron-builder/blob/master/website/docs/troubleshooting.md)
