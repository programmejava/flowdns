# FlowDNS 1.0.0 正式发布

发布日期：2026-10-23。版本：服务和界面均 `1.0.0-r1`。以 0.4.0 已验证功能为基线冻结，补齐授权、文档、架构校验和可分发源码，未更改转发/健康/DNS事务算法。LuCI资源路径更新为v1，透明模式名称取消“实验”，仍明确仅SSR Plus/Xray支持范围。

## 本版交付

- `flowdns_1.0.0-r1_<target>.ipk`：服务、Lua/监管、目标架构私有DNS2.93与两个组件许可证。
- `luci-app-flowdns_1.0.0-r1_all.ipk`：状态优先、设置、RPC/ACL及新版本资源。
- `flowdns-1.0.0-source.tar.gz`：双包源码、配方、测试、开发/排查/移植文档、GPL文本、未经修改的dnsmasq2.93上游源码；不包含节点、SSH或运行备份。
- `manifest.json`：版本/架构/组件及安装包摘要；`SHA256SUMS`：全部分发文件校验。

本次“发布”指生成可分发版本化安装包和源码包并部署用户路由器；没有另行创建公共托管仓库或向第三方网站公开节点资料。

## 安装/升级

先核对固件及`opkg print-architecture`。服务必须匹配目标架构/ABI，不加`--force-depends`、不强装跨架构包。基础依赖见Makefile，透明模式另需兼容SSR Plus和xray-core。opkg提示不同conffile并生成flowdns-opkg时，表示保留原自定义配置；不要直接覆盖成默认文件。首次安装默认关闭；升级保留`/etc/config/flowdns`和规则，不自动切换模式、不改代理节点。

下载后在电脑或路由器包目录执行：

```sh
sha256sum -c SHA256SUMS
```

将对应服务与界面包传到路由器私有暂存目录。先保存`/etc/config/flowdns`、`/etc/flowdns`、原服务/UI安装包和原模式，权限700。正在远程管理时准备独立超时恢复，不在没有恢复途径时重启整台路由器。

以下以当前ARM64目标为例，其他架构替换实际文件名；在同一目录执行一整行：

```sh
opkg install ./flowdns_1.0.0-r1_aarch64_cortex-a53.ipk ./luci-app-flowdns_1.0.0-r1_all.ipk
```

依赖软件源需匹配固件；这不是升级全系统命令。为避免运行中加载到新旧混合Lua文件，维护窗口先`/etc/init.d/flowdns stop`，安装后`/etc/init.d/flowdns start`。短暂停机是预期；安装后ready可能需等待网络/出口与规则，不反复apply。

状态页面应加载v1资源。验证`/usr/libexec/flowdns ready`、完整诊断、实际LAN国内/国外DNS及网页；检查原模式/SSR配置保留。首装在LuCI设置启用后生效。CLI改UCI需显式reload；不以commit隐式重启。

## 验收范围

已验证：主机真实库/双栈隔离回归、VLESS与Reality/Vision、正式fork并发DNS、模式与恢复逻辑、透明模式QUIC边界、DNS-only长连接/回退、ARM64目标安装包内容。0.4真机有20MB持续下载跨两次DNS切换，用户确认网页立即加载、视频约43Mbps；用户进一步确认SOCKS和透明速度相近。

1.0.0当前安装、两模式与最终恢复结果见 diagnostics/2026-10-23-1.0.0-release.md。历史重启自启动为用户早期版本实测；本版若未重启，不能以开机注册检查冒充本版重启验收。公网IPv6、强制QUIC应用、断电冷启动、一天以上稳定性及其它平台仍需目标验收。没有发布最大吞吐或最低内存保证。

## 可重复交付流程

先按PORTING构建、完整回归和包检查，再运行：

```sh
python3 package/myapp/flowdns/tools/make-release.py --service /path/to/flowdns.ipk --ui /path/to/luci-app-flowdns.ipk --output /path/to/release-directory
```

输出目录必须在源码目录之外且为空；脚本只收集两包源码白名单、根构建说明和固定上游源码，不读取路由器或用户配置。归档条目排序、时间归零，不把本机用户名写入tar；相同输入可重复生成相同源码归档。目标IPK可受SDK环境/工具链影响，不能把归档可重复性当成全工具链可复现保证。

依赖版本变化时先实际配置/业务测试再更新兼容记录，不能只提高硬编码版本门槛。变更组件或授权时同步Makefile、COPYING、README、manifest和上游哈希。
