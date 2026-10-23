# 移植与跨平台构建

## 是否只复制 flowdns 文件夹

复制 `package/myapp/flowdns` 和 `package/myapp/luci-app-flowdns` **源码目录到目标 OpenWrt/ImmortalWrt SDK**，再由目标工具链构建，是移植起点。不能把当前 ARM64 IPK、运行目录或私有 DNS 二进制直接复制到 x86/ARM32 运行。LuCI 包架构为 all，服务包包含架构相关 ELF；sing-box、Xray、Lua 原生库、libc 和内核模块也须匹配固件。

当前没有专用 CPU 指令或固定 aarch64 业务逻辑，普通 x86_64/ARM64 firewall4 平台通常不需重写策略。目标原生依赖、SDK/固件 ABI、插件生成器和内核网络功能才是主要移植工作。firewall3/iptables 或非 OpenWrt 属于另外的适配工程。

## 平台契约

| 层 | 要求 | 检查 |
| --- | --- | --- |
| 系统服务 | procd、ubus、UCI、rc.common | 启停、reload、接口事件、开机注册 |
| Lua | 5.1、libuci-lua、luci-lib-jsonc、luci-lib-nixio | 真实库加载、内核锁、socket、进程检查 |
| 网络 | firewall4、nftables-json、ip-full、nft tproxy 内核模块、IPv4/IPv6 策略路由 | 实际 `nft -c`、正式接管与 TCP/UDP 测试 |
| 加密 DNS | sing-box、curl、ca-bundle、coreutils-timeout、正确系统时间 | 实际配置校验、TLS 证书与 DNS 应答 |
| 私有前端 | dnsmasq 2.93，由本包工具链编译，HAVE_NFTSET；关闭 DHCP/TFTP/脚本 | ELF 架构、`--version`、`--test`、正式 TCP fork 并发 |
| 透明模式 | xray-core 与兼容 SSR Plus gen_config.lua | 所选节点生成、`xray run -test`、真实节点访问 |
| LuCI | luci-base、RPC/ACL、当前资源路径 | 两个标签页、apply 任务、错误反馈、浏览器旧缓存升级 |

以 Makefile DEPENDS 为构建依赖权威来源。透明模式的 Xray/SSR 是条件运行依赖，不强迫只使用 SOCKS 的目标安装 Xray。不要跨固件下载 kmod；内核 ABI 不匹配应重编目标固件或使用它的同版本软件源。

发布/测试工具使用Python 3.9+、Node.js、openssl及Linux网络命名空间工具；打包本身不需要pip第三方模块。主机测试需要允许user/net namespace和本地监听套接字。

## 在匹配 SDK 中构建

1. 选择与目标固件相同分支、目标/子目标、libc、内核 ABI 的 SDK 或完整源码。已有 SDK 的用户 feeds、网络加速/防火墙补丁不要为了 FlowDNS 覆盖。
2. 源码归档解开后，将其中 `package/myapp/flowdns`、`package/myapp/luci-app-flowdns` 放到 SDK 同一路径。归档附 `dl/dnsmasq-2.93.tar.xz`，可复制到 SDK dl 缓存，哈希由 Makefile 校验；仍需目标其余依赖。
3. 配置/安装目标 SDK 的 LuCI 及所需依赖 feeds。使用 `make menuconfig` 选中 FlowDNS 服务和界面，确认目标 `CONFIG_TARGET_ARCH_PACKAGES`。完整仓库示例：

```sh
make defconfig
make package/myapp/flowdns/compile package/myapp/luci-app-flowdns/compile -j2 V=s CONFIG_PACKAGE_flowdns=m CONFIG_PACKAGE_luci-app-flowdns=m
```

4. 输出通常在 `bin/packages/<架构>/<feed>/`；按真实产物路径运行包检查：

```sh
python3 package/myapp/flowdns/tests/release.py /path/to/flowdns_1.0.0-r1_TARGET.ipk /path/to/luci-app-flowdns_1.0.0-r1_all.ipk
```

包检查读取 control 架构并验证私有 DNS 的 ELF machine/class/endian，已覆盖 aarch64、x86_64、ARM、MIPS、RISC-V、PowerPC 常用命名。遇新命名应显式增加映射；通过静态 ELF 检查不等于该目标能运行。新增功能造成原生动态库依赖时须同步 Makefile，不能只看链接成功。

本源码针对 IPK/opkg 构建流程。使用 apk 的其它分支需适配打包检查/安装步骤，不能把改后缀当成支持。

## 测试顺序

1. 在 Linux 主机构建真实 Lua/nixio/jsonc、sing-box、Xray、私有 DNS，运行 `tests/run.sh`。它使用本机 TLS 及独立 user/net namespaces，不能用生产 LAN 替代隔离测试。
2. 在目标用 `opkg print-architecture`、`ubus call system board` 核对架构/固件，安装匹配依赖；备份配置和可恢复旧包。先关闭分流、测试私有 ELF 能执行与依赖检查。
3. 先 SOCKS：显式节点、退出其它接管，正式 UDP/TCP DNS，LAN 国内/国外网页，Fake-IP 策略、应用/失败回退。
4. 再透明模式：真实 IP、集合学习、国内内核旁路、国外 Xray TCP/UDP、QUIC 策略、128 次正式 TCP fork DNS 并发、DNS-only 更新和持续下载、模式切回。
5. 再验收重启/断电、依赖晚就绪、DNS/代理恢复、规则更新/回退、防火墙 reload、资源占用和长时运行。公网 IPv6、强制 QUIC/游戏需真实环境，不能由 AAAA 应答代替。
6. 同节点、同 IP/CDN、同协议、同一有线客户端比较吞吐。记录 CPU 单核/总负载、RSS、温度、重传与时间；低内存 ARM/MIPS 要评估 SRS 编译和双核心模式的 RAM/存储，不填未经测试的最低容量承诺。

目标适配结果必须补进 COMPATIBILITY.md 与 diagnostics，记录固件、架构、内核、依赖版本、包 SHA256、模式和每项测试范围。当前 ARM64 真机与 x86_64 主机隔离回归不能冒充 x86_64 OpenWrt 或其它 ARM 真机通过。

## 发布新架构产物

```sh
python3 package/myapp/flowdns/tools/make-release.py --service /path/to/flowdns.ipk --ui /path/to/luci-app-flowdns.ipk --output /path/outside/source/release
```

脚本先检查目标包，固定上游源码哈希，打包双目录源码/测试/文档/授权与 dnsmasq 源码，输出安装包、源代码包、manifest 和 SHA256SUMS。不会收集 `.config`、运行快照、节点凭据、SSH 文件或 `/tmp` 日志。原生 IPK 按架构分发，源码可共用。

## 多地址 LAN 的额外验收边界

本次SOCKS隔离客户端使用临时附加子网时，UDP请求发往桥主地址，sing-box通配监听的应答选择了该附加子网网关地址/16553，未匹配DNS重定向的反向连接，客户端超时；生产主LAN的自检/实际业务仍正常。将仅该测试子网的路由首选源地址设为桥主地址后复验。正式代码未新增多地址应答适配；同一桥多IPv4地址或跨子网访问的移植须专测UDP应答源IP/端口，不应只看监听和TCP结果。测试路由/附加地址在结束时删除，不能照抄到其它网络。

## 可选私有核心和R5S适配

系统核心较旧时可构建并安装package/myapp/flowdns-core，1.0.1只在FlowDNS进程树内优先选择私有引擎，系统路径保持。无需升级其它插件共享的sing-box，也无需安装未被生成规则使用的nft-socket模块。依赖/源码交付和R5S具体构建方式见RELEASE-1.0.1.md；源包新增第三个可选目录，打包工具--core必须配套--core-source（包含vendor的完整上游源）。
