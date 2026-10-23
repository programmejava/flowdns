# 局域网性能基线

在电脑安装 Python 3；使用自己控制或明确允许测速的 HTTPS 文件服务，文件至少 8 MiB。每种模式使用相同目标、节点、画质/负载、连接方式和时段，至少重复 3 次。优先使用有线连接，并分别测单连接和 `--parallel 4`。

| 模式 | 手动设置 | 目标 |
| --- | --- | --- |
| direct | 停止 FlowDNS 与透明代理 | 国内 HTTPS 文件 |
| flowdns-direct | 启用 FlowDNS，SSR/PassWall 只提供 SOCKS | 相同国内文件 |
| ssr-proxy | 停止 FlowDNS，由 SSR/PassWall 独立透明代理 | 海外 HTTPS 文件 |
| flowdns-proxy | 关闭插件透明代理，恢复 FlowDNS | 相同海外文件、同一节点 |

不要同时启用两套透明代理。此工具不会替你修改路由器设置；`--mode` 是记录实验条件，不会改变出口。测完恢复 FlowDNS 正常设置，并验证国内/国外网站。

```sh
python flowdns-benchmark.py --mode flowdns-proxy --url https://YOUR-SERVER/test.bin --output flowdns-proxy.json
python flowdns-benchmark.py --mode flowdns-proxy --url https://YOUR-SERVER/test.bin --parallel 4 --output flowdns-proxy-4.json
```

记录下载量、总吞吐、每连接首字节时间、系统 DNS 解析时间。默认每次/每连接最多 8 MiB、3 次，支持 1～64 MiB；输出 URL 的主机和路径，不记录查询串。仅接受 HTTPS，验证证书，忽略 HTTP_PROXY/HTTPS_PROXY，测量通过路由器的路径。

可选：电脑配置 SSH 密钥后加 `--ssh root@路由器IP`，通过只读 `/usr/libexec/flowdns metrics` 在样本前后采集每核忙碌率、sing-box/xray/SS 系列进程 CPU 与 RSS、可用内存。不读取代理节点参数或订阅。首次连接请自行确认 SSH 主机密钥；工具不会禁用主机密钥检查。状态页“采样 CPU/内存”也可记录 5 秒样本。

实际 UDP 另需自己控制的 iperf3 服务及电脑端 iperf3：

```sh
python flowdns-benchmark.py --mode flowdns-proxy --url https://YOUR-SERVER/test.bin --udp --iperf-server YOUR-SERVER --output flowdns-proxy-udp.json
```

UDP 测试固定请求 10 秒、10 Mbps，结果包含接收吞吐、丢包和抖动；SOCKS UDP 握手不等于此测试通过。QUIC 还需浏览器或支持 HTTP/3 的受控端点验证，不能用 TCP/UDP 接口握手代替。

比较 `direct` 与 `flowdns-direct` 确定国内转发开销；比较两个 proxy 模式确定新增处理开销。报告中的 CPU 单进程百分比按单核计算，可超过 100%。外部目标、节点或 CDN 变化都会影响比较，不能把模拟测试的吞吐当作路由器实测。
