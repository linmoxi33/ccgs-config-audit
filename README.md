# ccgs-config-audit

离线一致性审计器：给 Claude Code 的 agent/skill 配置包做静态解析，抓悬空引用和状态双写漂移。现在需要它，是因为这类配置包已经涨到几十个 agent、上百个 skill，而现有校验脚本只打印观察、不阻断。

Upstream: https://github.com/Donchitos/Claude-Code-Game-Studios

## 上游是什么，它缺什么

[Claude Code Game Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) 用 49 个 agent、74 个 skill、15 个 hook 把一次 Claude Code 会话编排成一个游戏工作室。配置全在 `.claude/` 下，`project.stage` 还双写到 `production/stage.txt`。

它自己已经有 `skill-lint.sh` 和 `agent-check.sh`，但两者都自称 "OBSERVATIONS, NEVER VERDICTS"，退出码恒为 0；写入 skill 的 hook 只打印一句提示就 `exit 0`（[validate-skill-change.sh:94](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/main/.claude/hooks/validate-skill-change.sh#L94)）。更关键的是，`agent-check.sh` 的 `names_in()` 只遍历已存在的 agent 名去匹配正文（[agent-check.sh:301](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/main/.claude/scripts/agent-check.sh#L301)）——把 `subagent_type` 拼错成 `qa-testr`，永远匹配不上，也永远不会报错。

状态文件那一半有公开的未修复 issue：[#147](https://github.com/Donchitos/Claude-Code-Game-Studios/issues/147) 记录 `set-stage.sh` 先写 `project.yaml`、再写 `stage.txt`、最后才回读，失败路径上自带的 split-stage 检查不可达；[#133](https://github.com/Donchitos/Claude-Code-Game-Studios/issues/133) 记录同一条规则在 hook / 模板 / skill 三处各存一份并已漂移。

## 这个工具做什么

- 解析 `.claude/skills/*/SKILL.md` 与 `.claude/agents/*.md` 的 frontmatter（自写解析器，零依赖）
- 反向解析正文引用：`subagent_type: X`、`/skill-name`、`.claude/{rules,hooks,scripts}/file`
- 对账文档与磁盘：`hooks-reference.md` / `rules-reference.md` 表格里列的，磁盘上是否真的有
- 对账 `project.yaml` 的 `project.stage` 与 `production/stage.txt`
- 输出 `--json`，用退出码区分「干净 / 有问题 / 用法错误」

**不做什么**：不联网、不调用 `gh`、不改任何文件、不判断 skill 写得好不好（那是 `/skill-test` 的事）。只回答「引用能不能解析、两份状态是否一致」。

## 安装与用法

只要 Python 3.8+，无第三方依赖：

```bash
git clone git@github-linmoxi33:linmoxi33/ccgs-config-audit.git
cd ccgs-config-audit
./bin/ccgs-config-audit /path/to/a/claude-code-pack
```

跑自带的样例（故意留了 4 处问题，退出码 1）：

```bash
./bin/ccgs-config-audit examples/in/mini-pack --json
```

`--json` 输出（节选，完整见 `examples/out/report.json`）：

```json
{
  "ok": false,
  "counts": {"skills": 2, "agents": 1, "errors": 4, "warnings": 0},
  "findings": [
    {"code": "REF001", "severity": "error", "path": ".claude/skills/alpha/SKILL.md", "line": 3,
     "message": "dangling subagent_type: ghost (no .claude/agents/ghost.md)"},
    {"code": "STG001", "severity": "error", "path": "project.yaml", "line": 1,
     "message": "stage drift: project.yaml='Production' but production/stage.txt='Polish'"}
  ]
}
```

退出码：

| 码 | 含义 |
| --- | --- |
| 0 | 没有 error（`--strict` 时连 warning 也不允许） |
| 1 | 检出问题 |
| 2 | 用法错误或输入错误（目录不存在、没有 `.claude/`） |

规则码：`FM001` frontmatter 不可解析、`FM002` 缺必填键、`FM003` name 与文件名/目录名不符、`FM004` model 取值未知、`FM005` 工具名未知（warn）、`FM006` 正文缺 H1（warn）、`REF001` 悬空 `subagent_type`、`REF002` 悬空 `/skill`、`REF003` 悬空路径引用、`REF004` 预加载 skill 不存在、`DOC001` 文档列了但磁盘没有、`DOC002` 磁盘有但文档没列（warn）、`STG001` 双写值不同、`STG002` stage 不在 7 个枚举内、`STG003` 只写了一边。

## 在真实上游上的运行结果

在 `Donchitos/Claude-Code-Game-Studios` HEAD（1.2.0，`05ad7c8`）上实跑：

```text
$ ./bin/ccgs-config-audit /tmp/ccgs
.claude/docs/hooks-reference.md:1: warn [DOC002] log-instructions.sh exists on disk but is not documented
.claude/docs/hooks-reference.md:1: warn [DOC002] update-check.sh exists on disk but is not documented
.claude/docs/hooks-reference.md:1: warn [DOC002] yaml-helper.sh exists on disk but is not documented
skills=74 agents=49 errors=0 warnings=3 -> PASS
```

0 error 是真实结果，不是没检查：74 个 skill 和 49 个 agent 的引用全部解析成功，3 条 warning 是真实的文档漂移（三个 hook 在磁盘上、不在 `hooks-reference.md` 的表格里）。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

25 个用例，覆盖退出码 0/1/2、悬空引用、方括号占位符、glob 路径、代码块排除、frontmatter 错误、stage 双写、`--json` 可解析。

## 局限

- 只认 `.claude/skills/<name>/SKILL.md` 和 `.claude/agents/<name>.md` 这一种布局；别的 agent 框架要改路径常量。
- frontmatter 解析器只支持 `key: value` 和单行流式列表，不支持嵌套 map 与多行 block scalar。
- `/skill` 引用在代码块里会被跳过，所以写在代码块里的真实引用查不出来。
- `DOC002` 把 hook 目录里的库文件（如 `yaml-helper.sh`）也算作「未文档化」，属于保守误报。
- 不做语义检查：`description` 写得烂、skill 内容跑不通，它不管。

## License

MIT
