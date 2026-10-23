# FlowDNS 1.0.1-r1：RK3568 用户态适配

本版面向NanoPi R5S（RK3568）的aarch64_generic用户态安装，基于1.0.0数据策略。服务与LuCI均1.0.1-r1，新增可选flowdns-core 1.12.25-r1，不覆盖此前已冻结的1.0.0发行目录。

## 改动

- 后端、监管和业务进程优先从/usr/libexec/flowdns-bin选择私有sing-box；未安装私有包时保留原系统核心路径。私有核心包不包含系统服务、UCI或/usr/bin/sing-box替换文件。
- 移除未被生成规则使用的kmod-nft-socket依赖。现有策略使用nft TProxy，没有socket表达式；仍依赖kmod-nft-tproxy并执行候选nft检查，不能因此认为所有内核功能已支持。
- 私有核心固定上游1.12.25和SHA256，用with_quic/with_utls构建。只扩展启动路径，未修改上游协议实现，也未改写SOCKS/透明分流算法。
- 发布校验扩展为可选第三包，核对架构/许可及无系统覆盖文件。源码归档包含三个配方、原始dnsmasq/sing-box源码，交付私有核心时另嵌入包含vendor的完整上游源码归档。

## 安装

R5S接受aarch64_generic；不能改名或强制安装aarch64_cortex-a53包。已有系统sing-box1.11.15不支持当前typed DNS格式，使用私有核心兼容，不升级共享核心。

```sh
opkg install ./flowdns-core_1.12.25-r1_aarch64_generic.ipk ./flowdns_1.0.1-r1_aarch64_generic.ipk ./luci-app-flowdns_1.0.1-r1_all.ipk
```

首次安装统一分流仍默认关闭，开机服务注册不代表已启用接管。当前R5S保留原SmartDNS:53和SSR主节点配置，FlowDNS未接管；启用前应显式配置独立SOCKS并处理原接管冲突。不要仅勾选FlowDNS同时让其它服务继续接管。

## 构建与源码

常规使用目标SDK构建三个源码目录。此次复用本仓库AArch64/musl1.2.5工具链，显式使用ARMv8-A通用指令和aarch64_generic包标签，未构建或上传6.6内核模块，目标仍保留其6.12.41内核。构建记录与实际R5S执行验收见diagnostics/2026-10-23-rk3568-install.md，不冒充完整固件SDK构建。

```sh
make package/myapp/flowdns-core/compile package/myapp/flowdns/compile package/myapp/luci-app-flowdns/compile -j2 V=s CONFIG_PACKAGE_flowdns-core=m CONFIG_PACKAGE_flowdns=m CONFIG_PACKAGE_luci-app-flowdns=m ARCH_PACKAGES=aarch64_generic TARGET_CFLAGS='-Os -pipe -march=armv8-a -mtune=generic -fno-plt -fstack-protector-strong -D_FORTIFY_SOURCE=1'
```

以上命令用于本仓库已有匹配用户态ABI的工具链；新平台优先使用它自己的SDK和默认目标参数，不盲目复制工具链或内核模块。

```sh
python3 package/myapp/flowdns/tools/make-release.py --service /path/to/flowdns.ipk --ui /path/to/luci-app-flowdns.ipk --core /path/to/flowdns-core.ipk --core-source /path/to/sing-box-1.12.25-with-vendor.tar.gz --output /path/to/empty-release-directory
```

上游原始源码固定哈希881435f07b5ab8170ccf3cb69e87130759521dc0ed1ae4bfeacbe7772a93a158。core-source是从该源码解开后，按go.mod/go.sum补齐go mod vendor生成的归档，不包含本机缓存、节点配置或工具私钥。完整来源和各组件授权随包交付；vendor保留依赖自身许可证。

## 验证边界

完整主机回归包含两模式、Reality/Vision、双栈转发、并发DNS、QUIC、DNS更新/回退，以及私有核心选择/缺失回退。R5S实际安装、私有核心执行、typed DNS校验、nft TProxy只检查、回环TCP/UDP加密DNS通过。没有启用现有LAN接管，未做R5S实际节点代理、视频、完整LAN分流、IPv6公网、重启或长期压力验收。不要把基础安装烟测等同于已完成业务切换。
