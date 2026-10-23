# FlowDNS 可选私有核心

打包未经修改的上游sing-box 1.12.25，仅安装/usr/libexec/flowdns-bin/sing-box及授权，不安装init、UCI或/usr/bin/sing-box，不提供/替换系统sing-box包。适用于系统核心较旧、其它插件仍依赖旧版的目标。

FlowDNS从1.0.1起在其后端和业务监管子进程PATH中优先使用此目录；其它插件的环境与核心不变。系统sing-box原依赖仍保留，本包并非卸载系统核心的替代品。路径选择会改变FlowDNS规则编译/配置检查/版本检测所使用的引擎，因此所有这些环节必须一起验证。

构建配方固定源码SHA256、with_quic/with_utls标签及版本。上游LICENSE和完整GPL文本随包安装，部署/源码交付说明见../flowdns/RELEASE-1.0.1.md。当前只有R5S基础安装烟测，完整LAN接管另验收。
