# 新闻来源目录

新闻池每两小时按 `config.json` 中启用的来源抓取。所有条目保留来源名、原文链接和发布时间；来源失败只记录本轮失败，不会阻塞其余来源入池或触发 AI 润色。

| 订阅分类 | 默认来源 | 说明 |
| --- | --- | --- |
| AI | Google News、机器之心、VentureBeat | 国际 AI 动态及直接 RSS。 |
| 科技 | Google News、开源中国、36Kr、Hacker News、Lobsters、Ars Technica、Phoronix | 科技产业、开源和开发者社区。 |
| 消费电子 | Google News、The Verge | 手机、PC、可穿戴设备等。 |
| 财经 | Google News：Business、华尔街见闻 | 公司、宏观与商业动态。 |
| 投资市场 | Google News：stock markets、东方财富、新浪财经 | 市场和交易相关信息。 |
| 时政 | Google News：politics | 国际政治与公共政策。 |
| 体育 | Google News：Sports | 主要体育赛事。 |
| 娱乐 | Google News：Entertainment | 影视、音乐与文化娱乐。 |
| 社会热搜 | Google News：social media trends、微博热搜 | 社会议题与网络趋势；热搜不等于事实确认。 |
| GitHub | GitHub Blog、Trending、近期高星新仓库 | GitHub 官方产品、社区与开源动态。 |

来源目录是显式启用制：`config.json` 未列出的来源不会抓取。若服务器网络无法访问某个外部来源，该来源会在本轮失败记录中出现，其他来源仍会继续工作；上线前应在目标服务器执行一次仅抓取的健康检查，再根据网络可达性调整启用项。
