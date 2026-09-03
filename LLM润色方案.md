# LLM 润色（Phase 2）实现方案 · DeepSeek

> 目标：在纯模板版基础上加入 LLM 润色，把"标题+一句话简述"升级为 100–200 字新闻体段落。
> 铁律（用户明确要求）：**总结严格基于已获取的新闻，禁止编造**。
> 原则：无 key 自动降级纯模板；单条失败自动回退，绝不让 LLM 的幻觉污染整份早报。

---

## 一、流水线位置

```
fetch_sources.py → build_report.py(模板版) → llm_polish.py(新增) → send_feishu.py
                        │                              │
                        └── 简述直出(兜底) ←── 单条回退 ←┘
```

- `llm_polish.py` 只改早报正文段落，**标题保持模板清洗版不动**（控制面最小，防止标题被改错）；
- 无 `DEEPSEEK_API_KEY` 或 API 报错 → 自动跳过/回退，早报永远能发出（纯模板兜底）。

## 二、DeepSeek 接入

| 项 | 值 |
| --- | --- |
| API | `https://api.deepseek.com/chat/completions`（OpenAI 兼容格式） |
| 模型 | `deepseek-chat` |
| 鉴权 | `.env` 新增 `DEEPSEEK_API_KEY=sk-xxx`（与 `FEISHU_WEBHOOK` 同文件） |
| 参数 | `temperature=0.3`（压制自由发挥）｜ `max_tokens=300` ｜ `timeout=20` |
| 并发 | 22 条 × 6 workers 并发，预计总耗时 15–30 秒 |
| 成本 | 约 ¥0.02–0.1 / 次（输入~5K token + 输出~4.5K token，DeepSeek 远低于 OpenAI） |

**Prompt 结构（单条）**：
```
system: 你是严谨的新闻早报编辑。你会收到一条今日抓取到的真实新闻材料，
要求改写为 100-200 字的中文新闻段落。硬性规则：
1. 只能使用材料中已有的信息，禁止新增任何材料里没有的事实、数字、人名、机构、时间。
2. 材料不足时，只写材料能支撑的内容，宁可简短，不可虚构。
3. 全用陈述句，禁止出现任何问号（？和 ?）。
4. 不写"据悉/报道称/消息人士/数据显示"等无来源引述词。
5. 只输出正文段落本身，不要标题、不要解释、不要列表。

user: 【新闻标题】{title}
【材料内容】{summary}
【来源】{source}
```

## 三、防编造机制（核心，三层防线）

**第一层 · 输入白盒**：每条 prompt 只包含**该条**的 title/summary/url/source/bucket，不跨条、不喂无关信息——LLM 没有机会"借用"其他条目的内容。

**第二层 · 输出校验（脚本硬校验，不靠自觉）**——`check_output()`：
1. **数字/日期一致性**：从材料中提取所有数字（金额、百分比、年份等）形成集合 A；从 LLM 输出提取数字集合 B；**B 中存在 A 没有的数字 → 判定该条可疑**（LLM 编造最爱编具体数字）；
2. **禁词扫描**：输出含"据悉 / 报道称 / 消息人士 / 数据显示 / 据了解"等无源引述词 → 可疑；
3. **格式校验**：字数 80–250 字、零问号、无 Markdown 符号、无"标题:"前缀。

**第三层 · 自动回退**：以上任一项不过，或 API 超时/报错 → **该条自动回退为模板版简述**，并在统计中记录。**整份早报不会因此失败**，最多出现"22 条中润色成功 20、回退 2"。

**终检**：润色完成后仍跑 `build_report.py` 的校验函数（配比 / 字数≤5000 / 零问号 / 文末来源），全部通过才允许发送。

## 四、改动文件清单

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `llm_polish.py` | 新增 | 读 raw JSON + 模板 md → 并发润色 → 校验回退 → 覆盖输出 md |
| `.env` | 追加一行 | `DEEPSEEK_API_KEY=sk-xxx` |
| crontab | 更新一行 | 命令链中加入 `polish` 步骤（见下） |

> 无需改 `fetch_sources.py` / `build_report.py` / `send_feishu.py`（校验函数复用 build 的逻辑）。

## 五、部署步骤（服务器上）

```bash
# 1. 上传 llm_polish.py 到 /root/newsdigest/
# 2. 配置 key(与 webhook 同一文件):
echo 'DEEPSEEK_API_KEY=sk-你的key' >> /root/newsdigest/.env

# 3. 更新 crontab,命令链加 polish 一步:
crontab -e
# 把原来那行改成:
# 0 8 * * * cd /root/newsdigest && .venv/bin/python fetch_sources.py >> run.log 2>&1 && .venv/bin/python build_report.py >> run.log 2>&1 && .venv/bin/python llm_polish.py >> run.log 2>&1 && .venv/bin/python send_feishu.py >> run.log 2>&1

# 4. 手动全链测试:
cd /root/newsdigest && .venv/bin/python fetch_sources.py && .venv/bin/python build_report.py && .venv/bin/python llm_polish.py && .venv/bin/python send_feishu.py
```

## 六、观测与验收

- `run.log` 会记录润色统计：`[polish] 成功 20/22,回退 2(原因:数字不一致 x1, 超时 x1)`;
- 连跑 3 天，每天人工重点核对：**数字/人名/机构是否都在抓取材料里**（防编造验收点）;
- 若某类材料（如 HN 无正文）频繁回退，属正常——材料本身信息不足，回退模板比让 LLM 硬编更符合要求。

## 七、风险与边界

- **成本**：按每天一次算，月成本约 ¥1–3，可忽略；
- **速度**：并发后 15–30 秒，加在 08:00 链路里不影响（现在整体 1 分钟内）；
- **准确性**：LLM 润色是"表达升级"而非"事实新增"，材料不足宁回退；
- **回退日志**：回退原因会留痕，方便发现哪些源的材料质量需要提升（如未来给 HN 补抓正文）。

---
*待你确认后实施：先本地出全量 LLM 样稿对比，再上服务器。*
