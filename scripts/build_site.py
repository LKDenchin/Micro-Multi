"""Build the public introduction and documentation site from repository guides."""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "site"
BASE = "/Micro-Multi/"
SITE = "https://lkdenchin.github.io/Micro-Multi/"
REPO = "https://github.com/LKDenchin/Micro-Multi"
GUIDE_PAIRS = {
    "README.md": ("Getting started", "开始使用"),
    "PRODUCT_DEVELOPMENT_SPEC.md": ("Task examples", "任务示例"),
    "docs/MODELS.md": ("Model configuration", "模型配置"),
    "docs/WORKSPACE.md": ("Projects and conversations", "项目与对话"),
    "docs/AUTONOMOUS_COLLABORATION.md": ("Team collaboration", "团队协作"),
    "docs/extensions.md": ("Skills, MCP and plugins", "Skills、MCP 与插件"),
    "docs/NATIVE_CORDIS.md": ("Native dsh plugins", "原生 dsh 插件"),
    "docs/sandbox.md": ("Permissions", "权限"),
    "docs/DURABLE_TURNS_AND_MODEL_RECOVERY.md": ("Saving and resuming work", "保存与继续工作"),
    "docs/replay.md": ("Conversation history", "对话记录"),
    "docs/TROUBLESHOOTING.md": ("Troubleshooting", "常见问题"),
    "docs/architecture.md": ("Architecture and technology", "架构与技术栈"),
    "docs/AGENT_DESIGN.md": ("Agent design and tradeoffs", "Agent 设计与取舍"),
    "docs/deployment.md": ("Run from source", "源码部署"),
    "docs/DESKTOP_RELEASE.md": ("Desktop installation and builds", "桌面安装与构建"),
    "docs/contracts.md": ("Runtime interfaces", "运行时接口"),
    "docs/UPSTREAM_RUNTIME_PROVENANCE.md": ("Runtime provenance", "运行时溯源"),
    "CONTRIBUTING.md": ("Contributing", "贡献指南"),
    "SECURITY.md": ("Security", "安全政策"),
    "CODE_OF_CONDUCT.md": ("Community conduct", "社区规范"),
}
GUIDE_SECTIONS = [
    (
        ("Start here", "入门"),
        ["README.md", "PRODUCT_DEVELOPMENT_SPEC.md", "docs/MODELS.md", "docs/WORKSPACE.md"],
    ),
    (
        ("Using the app", "使用指南"),
        [
            "docs/AUTONOMOUS_COLLABORATION.md",
            "docs/extensions.md",
            "docs/NATIVE_CORDIS.md",
            "docs/sandbox.md",
            "docs/DURABLE_TURNS_AND_MODEL_RECOVERY.md",
            "docs/replay.md",
            "docs/TROUBLESHOOTING.md",
        ],
    ),
    (
        ("Development", "开发与部署"),
        [
            "docs/architecture.md",
            "docs/AGENT_DESIGN.md",
            "docs/deployment.md",
            "docs/DESKTOP_RELEASE.md",
            "docs/contracts.md",
            "docs/UPSTREAM_RUNTIME_PROVENANCE.md",
        ],
    ),
    (("Project", "项目"), ["CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"]),
]


def localized_source(source: str, chinese: bool) -> str:
    original = source.replace(".zh-CN.md", ".md")
    return original.removesuffix(".md") + ".zh-CN.md" if chinese else original


GUIDES = {
    localized_source(source, chinese): titles[int(chinese)]
    for source, titles in GUIDE_PAIRS.items()
    for chinese in (False, True)
}


def doc_url(source: str) -> str:
    return BASE + "docs/" + Path(source).stem.lower().replace("_", "-").replace(".", "-") + ".html"


def page(
    title: str,
    description: str,
    body: str,
    *,
    lang: str = "en",
    path: str = "",
    alternate: str | None = None,
) -> str:
    chinese = lang == "zh-CN"
    docs = doc_url("README.zh-CN.md" if chinese else "README.md")
    alternate = alternate or (BASE if chinese else BASE + "zh/")
    home = BASE + "zh/" if chinese else BASE
    display_title = title if title.startswith("Micro-Multi") else title + " · Micro-Multi"
    return f'''<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(display_title)}</title><meta name="description" content="{html.escape(description, quote=True)}">
<meta name="theme-color" content="#172033"><link rel="canonical" href="{SITE}{path}">
<link rel="alternate" hreflang="{"en" if chinese else "zh-CN"}" href="https://lkdenchin.github.io{alternate}">
<meta property="og:title" content="{html.escape(display_title, quote=True)}"><meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:type" content="website"><meta property="og:image" content="{SITE}assets/micro-multi.png">
<link rel="icon" href="{BASE}assets/micro-multi.svg"><link rel="stylesheet" href="{BASE}assets/site.css">
<script src="{BASE}assets/site.js" defer></script></head><body>
<a class="skip" href="#content">{"跳转到正文" if chinese else "Skip to content"}</a>
<header class="header"><nav class="nav" aria-label="{"主导航" if chinese else "Main navigation"}">
<a class="brand" href="{home}"><img src="{BASE}assets/micro-multi.svg" width="34" height="34" alt=""><span>Micro-Multi</span></a>
<div class="navlinks"><a href="{docs}">{"文档" if chinese else "Docs"}</a><a href="{REPO}/releases/latest">{"下载" if chinese else "Download"}</a><a href="{REPO}">GitHub ↗</a><a class="language" href="{alternate}">{"English" if chinese else "简体中文"}</a></div>
</nav></header><main id="content">{body}</main>
<footer class="footer"><a class="brand" href="{home}">Micro-Multi</a><p>{"多 Agent 协作工作区，兼容 DeepSeek Harness 插件。" if chinese else "A multi-agent workspace compatible with DeepSeek Harness plugins."}</p>
<div><a href="{doc_url(localized_source("CONTRIBUTING.md", chinese))}">{"参与贡献" if chinese else "Contribute"}</a><a href="{doc_url(localized_source("SECURITY.md", chinese))}">{"安全" if chinese else "Security"}</a><a href="{REPO}/discussions">{"社区" if chinese else "Community"}</a><a href="{REPO}/blob/main/LICENSE">Apache-2.0</a></div><small>© 2026 LKDenchin · {"Micro-Multi 贡献者" if chinese else "Micro-Multi contributors"}</small></footer></body></html>'''


def release_downloads(release: dict) -> dict[str, str]:
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Downloads must use a published stable release")
    patterns = {
        "windows": "Micro-Multi-Setup-*-x64.exe",
        "debian": "Micro-Multi-*-amd64.deb",
        "appimage": "Micro-Multi-*-x86_64.AppImage",
        "checksums": "SHA256SUMS*",
    }
    links = {}
    for key, pattern in patterns.items():
        matches = [
            asset
            for asset in release.get("assets", [])
            if asset.get("state") == "uploaded" and fnmatch.fnmatchcase(asset["name"], pattern)
        ]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous release asset: {key}")
        if matches:
            url = matches[0]["browser_download_url"]
            if not url.startswith(REPO + "/releases/download/"):
                raise ValueError(f"Unexpected release asset URL: {key}")
            links[key] = url
    return links


def landing(chinese: bool, release_links: dict[str, str] | None = None) -> str:
    def t(en: str, zh: str) -> str:
        return zh if chinese else en

    def guide(source: str) -> str:
        return doc_url(localized_source(source, chinese))

    features = [
        (
            t("Split work by responsibility", "按职责拆分任务"),
            t(
                "The lead proposes assignments for implementation, tests and docs. Review the members, their files and models before execution.",
                "主 Agent 提出实现、测试、文档等分工。启动前检查每位成员的任务、负责文件和模型。",
            ),
        ),
        (
            t("Run independent work together", "独立任务并行执行"),
            t(
                "Independent members work concurrently. Tasks with dependencies wait for predecessor reports. You choose the concurrency limit.",
                "互不依赖的成员同时工作；有依赖的任务等待前置报告。并发上限由你设置。",
            ),
        ),
        (
            t("Coordinate shared files", "协调共享文件"),
            t(
                "File ownership and path locks coordinate writes. The scheduler reuses running assignments when the lead dispatches them again.",
                "文件归属和路径锁协调写入。主 Agent 重复派发同一任务时，调度器复用已有执行。",
            ),
        ),
        (
            t("Share dsh tools with the team", "让团队使用 dsh 工具"),
            t(
                "Enabled dsh plugins supply tools to the lead and members. Plugin settings and interface components live in the same workspace.",
                "启用的 dsh 插件向主 Agent 和成员提供工具，插件设置与界面组件也放在同一个工作区。",
            ),
        ),
    ]
    cards = "".join(
        f'<article class="feature"><span class="number">{i:02}</span><h3>{title}</h3><p>{copy}</p></article>'
        for i, (title, copy) in enumerate(features, 1)
    )
    steps = [
        (
            t("Connect a model", "连接模型"),
            t(
                "In Settings → Models, add the API base URL, model ID and key. Test the connection before starting.",
                "在“设置 → 模型”添加 API 地址、模型 ID 和密钥，开始前测试连接。",
            ),
        ),
        (
            t("Open a local folder", "打开本地目录"),
            t(
                "Add your project and choose whether to link the original directory. Check the path before confirming.",
                "添加项目，选择是否直接关联原目录，确认前检查路径。",
            ),
        ),
        (
            t("Review the assignments", "审核成员分工"),
            t(
                "Choose team mode, describe the job, and inspect the proposed members, files, dependencies and models.",
                "选择协作模式，说明需求，检查方案中的成员、文件、依赖和模型。",
            ),
        ),
        (
            t("Confirm and follow the work", "确认并跟踪执行"),
            t(
                "Confirm the plan in chat. Follow each member, then check the combined diff and test output.",
                "在聊天中确认方案，跟踪每位成员的进展，再检查合并后的差异和测试输出。",
            ),
        ),
    ]
    step_cards = "".join(
        f"<article><span>{i:02}</span><h3>{title}</h3><p>{copy}</p></article>"
        for i, (title, copy) in enumerate(steps, 1)
    )
    stack = [
        (
            t("Desktop", "桌面"),
            "Electron",
            t("Folder selection and desktop integration.", "目录选择与桌面集成。"),
        ),
        (
            t("Backend", "后端"),
            "Python · FastAPI",
            t("Local APIs, conversations and task execution.", "本地接口、对话与任务执行。"),
        ),
        (
            t("Interface", "界面"),
            "HTML · CSS · JavaScript",
            t(
                "The main workspace; React for native plugin components.",
                "主工作区；React 渲染原生插件组件。",
            ),
        ),
        (
            t("Agent and plugin runtime", "智能体与插件运行时"),
            "Node.js · Cordis · dsh",
            t("Native tools, services and plugin contributions.", "原生工具、服务及插件贡献。"),
        ),
        (
            t("Storage", "存储"),
            "SQLite · keyring",
            t(
                "Local records and OS-backed model credentials.",
                "本地记录与系统凭据库中的模型密钥。",
            ),
        ),
        (
            t("Connections", "通信"),
            "HTTP · SSE · WebSocket",
            t(
                "API calls, streamed replies and plugin subscriptions.",
                "接口请求、流式回复与插件订阅。",
            ),
        ),
    ]
    stack_cards = "".join(
        f"<div><span>{label}</span><h3>{technology}</h3><p>{copy}</p></div>"
        for label, technology, copy in stack
    )
    downloads = [
        ("Windows", "x64 · NSIS", "windows"),
        ("Debian / Ubuntu", "x64 · .deb", "debian"),
        ("Linux", "x64 · AppImage", "appimage"),
    ]
    release_links = release_links or {}
    latest_url = REPO + "/releases/latest"
    checksum_url = html.escape(release_links.get("checksums", latest_url), quote=True)
    checksum_label = (
        "SHA256SUMS" if "checksums" in release_links else t("Release files", "Release 文件")
    )
    download_cards = "".join(
        f'<a class="download-card" href="{html.escape(release_links.get(key, latest_url), quote=True)}"><span>{system}</span><small>{kind}</small><b>{t("Download", "下载") if key in release_links else t("View release", "查看 Release")} ↗</b></a>'
        for system, kind, key in downloads
    )
    return f'''
<section class="hero wrap"><div class="hero-copy"><span class="eyebrow">MICRO-MULTI</span>
<h1>{t("Micro-Multi:<br>A next-generation<br>multi-agent workbench", "Micro-Multi：<br>新一代多Agent工作台")}</h1>
<p class="lead">{t("The lead splits the job. You approve the assignments and choose each member's model. Compatible with DeepSeek Harness plugins.", "主 Agent 拆分任务，你确认分工，为每位成员选择模型。兼容 DeepSeek Harness 插件。")}</p>
<div class="actions"><a class="button primary" href="#download">{t("Download", "下载")} ↓</a><a class="button secondary" href="{guide("README.md")}">{t("Get started", "开始使用")} →</a></div>
<p class="platforms">Windows · Linux · {t("English and Chinese", "中英文界面")} · Apache-2.0</p></div>
<div class="team-board" aria-label="{t("Example team assignment", "团队分工示例")}"><div class="board-top"><span class="dots">● ● ●</span><span>{t("Example task", "任务示例")}</span></div>
<div class="task"><span class="label">{t("PROJECT TASK", "项目任务")}</span><p>{t("Add pagination to the order API and test boundary cases.", "为订单接口添加分页，并测试边界情况。")}</p></div>
<div class="agent lead-agent"><span class="agent-icon">M</span><div><strong>{t("Lead agent", "主智能体")}</strong><small>{t("Prepare the plan and review the changes", "准备方案并审查改动")}</small></div><span class="status">{t("Review the plan", "审核方案")}</span></div>
<div class="workers"><div class="agent"><span class="agent-icon blue">01</span><div><strong>{t("Implementation", "实现成员")}</strong><small>{t("Update the endpoint", "修改接口")}</small></div></div><div class="agent"><span class="agent-icon green">02</span><div><strong>{t("Testing", "测试成员")}</strong><small>{t("Cover boundary cases", "覆盖边界情况")}</small></div></div></div>
<div class="board-bottom"><span>{t("Approve → Schedule → Combine", "确认 → 调度 → 汇总")}</span><span>dsh · {t("Shared tools", "共享工具")}</span></div></div></section>
<section id="features" class="wrap section"><h2>{t("Collaboration needs a scheduler", "协作，需要程序来调度")}</h2><div class="features">{cards}</div><a class="text-link" href="{guide("docs/AUTONOMOUS_COLLABORATION.md")}">{t("How team execution works", "了解团队执行流程")} →</a></section>
<section id="extensions" class="compat wrap"><div><h2>{t("Compatible with DeepSeek Harness plugins", "兼容 DeepSeek Harness 插件")}</h2><p>{t("Install DeepSeek Harness plugins in Micro-Multi and share their tools across the team. Manage plugin settings in the app, and add Skills or MCP services when you need them.", "在 Micro-Multi 中安装 DeepSeek Harness 插件，让团队成员使用插件提供的工具。插件设置可在应用内管理，也支持接入 Skills 和 MCP 服务。")}</p><a class="text-link" href="{guide("docs/NATIVE_CORDIS.md")}">{t("See supported plugins and setup", "查看兼容范围与安装方法")} →</a></div><div class="plugin-pills"><span>{t("Plugin tools", "插件工具")}</span><span>{t("Plugin settings", "插件设置")}</span><span>Skills</span><span>MCP</span></div></section>
<section id="comparison" class="wrap section"><h2>{t("When to use multiple agents", "何时使用多Agent工作？")}</h2><p class="section-intro">{t("Use one agent for a small edit. Use multiple agents when a job includes implementation, tests and documentation, or spans several parts of a project.", "小改动可以交给一个 Agent。涉及实现、测试与文档，或需要处理多个模块时，可以让多个 Agent 分工完成。")}</p>
<div class="comparison"><table><thead><tr><th>{t("Problem", "问题")}</th><th>{t("A single loop / uncoordinated agents", "单循环 / 无协调的分工")}</th><th>Micro-Multi</th></tr></thead><tbody>
<tr><th>{t("Waiting", "等待时间")}</th><td>{t("Implementation, tests and docs run in sequence.", "实现、测试和文档依次处理。")}</td><td>{t("Independent tasks run together; dependent tasks wait.", "独立任务同时执行，依赖任务等待前置报告。")}</td></tr>
<tr><th>{t("Shared files", "共享文件")}</th><td>{t("Concurrent edits need manual coordination.", "并发修改需要手动协调。")}</td><td>{t("Declared ownership and path locks coordinate writes.", "负责文件和路径锁协调写入。")}</td></tr>
<tr><th>{t("Model choice", "模型选择")}</th><td>{t("One model often handles every role.", "常由同一模型处理所有职责。")}</td><td>{t("Choose individual member models in the plan.", "在方案中单独选择成员模型。")}</td></tr>
<tr><th>{t("Retries", "任务重试")}</th><td>{t("An assignment may be dispatched again.", "可能再次派发同一任务。")}</td><td>{t("Reuse running or completed assignments.", "复用正在运行或已完成的任务。")}</td></tr>
</tbody></table></div><p class="section-intro">{t("More agents can cost more. This is an execution comparison, not a speed or price benchmark. Use only the members the job needs.", "更多 Agent 也可能增加费用。这是执行方式的对比，不是速度或价格基准测试。只安排任务需要的成员。")}</p><a class="text-link" href="{guide("docs/AGENT_DESIGN.md")}">{t("Design choices and tradeoffs", "设计选择与取舍")} →</a></section>
<section id="workflow" class="wrap section"><h2>{t("Start with a model and a project", "从模型和项目开始")}</h2><p class="section-intro">{t("You supply the model endpoint and credentials. The app handles the conversation and workspace; your project keeps its own build tools and dependencies.", "模型接口和凭据由你配置，应用负责对话与工作区；项目继续使用自己的构建工具和依赖。")}</p><div class="steps">{step_cards}</div><a class="text-link" href="{guide("docs/WORKSPACE.md")}">{t("Read the workspace guide", "阅读项目与对话指南")} →</a></section>
<section id="technology" class="wrap section"><h2>{t("Technology", "技术栈")}</h2><p class="section-intro">{t("An Electron desktop shell runs a local Python backend. Node.js hosts the agent and plugin runtimes, while the interface shows their work and records.", "Electron 桌面外壳启动本地 Python 后端，Node.js 承载智能体和插件运行时，界面展示执行过程与记录。")}</p><div class="stack-grid">{stack_cards}</div><a class="text-link" href="{guide("docs/architecture.md")}">{t("Read the architecture guide", "阅读架构说明")} →</a></section>
<section id="download" class="download section"><div class="wrap"><h2>{t("Install Micro-Multi", "安装 Micro-Multi")}</h2><p>{t("Choose a package for your system. Python and Node.js are included; install Git for repository work and any external tools your extensions require.", "选择对应系统的软件包。安装包包含 Python 和 Node.js，仓库工作需要另装 Git，扩展所需的外部工具也按需安装。")}</p><div class="downloads">{download_cards}</div><p class="download-note"><a href="{checksum_url}">{checksum_label}</a> · <a href="{guide("docs/DESKTOP_RELEASE.md")}">{t("Installation and Linux requirements", "安装与 Linux 环境要求")}</a> · <a href="{guide("docs/deployment.md")}">{t("Run from source", "从源码运行")}</a></p></div></section>
<section class="wrap community"><div><h2>{t("Help and contributions", "帮助与贡献")}</h2><p>{t("Check the troubleshooting guide when something fails. You can report bugs, discuss ideas or contribute code and documentation on GitHub.", "遇到问题时先查看常见问题，也可以在 GitHub 报告问题、讨论建议，或贡献代码与文档。")}</p></div><div class="actions"><a class="button primary" href="{guide("docs/TROUBLESHOOTING.md")}">{t("Troubleshooting", "常见问题")}</a><a class="button secondary" href="{REPO}">GitHub ↗</a></div></section>'''


def render_guide(source: str, renderer: MarkdownIt) -> str:
    text = (ROOT / source).read_text("utf-8")
    tokens = renderer.parse(text)
    used: dict[str, int] = {}
    for i, token in enumerate(tokens):
        if token.type == "heading_open":
            slug = re.sub(r"[^\w -]", "", tokens[i + 1].content.lower()).replace(" ", "-")
            count = used.get(slug, 0)
            used[slug] = count + 1
            token.attrSet("id", slug + (f"-{count}" if count else ""))
    rendered = renderer.renderer.render(tokens, renderer.options, {})

    def link(match: re.Match[str]) -> str:
        attribute, quote, target = match.groups()
        if target.startswith(("http:", "https:", "mailto:", "#", "data:")):
            return match.group(0)
        parsed = urlsplit(html.unescape(target))
        resolved = (ROOT / source).parent / parsed.path
        relative = resolved.resolve().relative_to(ROOT).as_posix()
        if relative in GUIDES:
            destination = doc_url(relative)
        elif relative.startswith("src/masp/web/micro-multi."):
            destination = BASE + "assets/" + Path(relative).name
        else:
            destination = (
                REPO + "/" + ("tree" if resolved.is_dir() else "blob") + "/main/" + relative
            )
        if parsed.fragment:
            destination += "#" + parsed.fragment
        return f"{attribute}={quote}{html.escape(destination, quote=True)}{quote}"

    return re.sub(r"""(href|src)=(['"])(.*?)\2""", link, rendered)


def main() -> None:
    from markdown_it import MarkdownIt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", type=Path, help="Latest GitHub Release metadata")
    args = parser.parse_args()
    release_links = (
        release_downloads(json.loads(args.release_json.read_text("utf-8")))
        if args.release_json
        else None
    )
    if OUT.resolve() != ROOT / "build" / "site":
        raise ValueError("Site output must remain in the generated workspace directory")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "assets").mkdir(exist_ok=True)
    (OUT / "docs").mkdir(exist_ok=True)
    (OUT / "zh").mkdir(exist_ok=True)
    for asset in (ROOT / "site" / "assets").iterdir():
        shutil.copyfile(asset, OUT / "assets" / asset.name)
    for suffix in ("svg", "png"):
        shutil.copyfile(
            ROOT / "src/masp/web" / f"micro-multi.{suffix}",
            OUT / "assets" / f"micro-multi.{suffix}",
        )
    for chinese, destination in ((False, OUT / "index.html"), (True, OUT / "zh/index.html")):
        destination.write_text(
            page(
                "Micro-Multi：新一代多Agent工作台"
                if chinese
                else "Micro-Multi: A Next-Generation Multi-Agent Workbench",
                "主 Agent 拆分任务，成员按文件归属和依赖协作，汇总执行结果。兼容 DeepSeek Harness 原生插件，支持自选成员模型。"
                if chinese
                else "The lead splits tasks, members coordinate files and dependencies, and results come back to one workspace. Compatible with native DeepSeek Harness plugins, with per-member model choice.",
                landing(chinese, release_links),
                lang="zh-CN" if chinese else "en",
                path="zh/" if chinese else "",
            ),
            "utf-8",
        )
    renderer = MarkdownIt("commonmark", {"html": True}).enable("table").enable("strikethrough")
    index = []
    for source, title in GUIDES.items():
        chinese = source.endswith(".zh-CN.md")
        lang = "zh-CN" if chinese else "en"
        counterpart = localized_source(source, not chinese)
        sidebar = "".join(
            f"<h3>{html.escape(labels[int(chinese)])}</h3>"
            + "".join(
                f'<a href="{doc_url(localized_source(guide, chinese))}">{html.escape(GUIDE_PAIRS[guide][int(chinese)])}</a>'
                for guide in sources
            )
            for labels, sources in GUIDE_SECTIONS
        )
        content = render_guide(source, renderer)
        body = f'''<div class="docs-layout wrap"><aside class="sidebar"><span class="eyebrow">{"文档" if chinese else "DOCUMENTATION"}</span><div class="search"><label for="doc-search">{"搜索文档" if chinese else "Search docs"}</label><input id="doc-search" type="search" placeholder="{"搜索文档…" if chinese else "Search docs…"}" autocomplete="off"><div id="search-results" hidden></div></div><nav aria-label="{"文档" if chinese else "Documentation"}">{sidebar}</nav></aside><article class="doc"><div class="doc-meta"><span>MICRO-MULTI / {"文档" if chinese else "DOCS"}</span><a href="{REPO}/blob/main/{source}">{"查看源码" if chinese else "View source"} ↗</a></div>{content}</article></div>'''
        path = doc_url(source).removeprefix(BASE)
        (OUT / path).write_text(
            page(
                title,
                title + (" — Micro-Multi 文档" if chinese else " — Micro-Multi documentation"),
                body,
                lang=lang,
                path=path,
                alternate=doc_url(counterpart),
            ),
            "utf-8",
        )
        index.append(
            {
                "title": title,
                "url": doc_url(source),
                "lang": lang,
                "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)),
            }
        )
    (OUT / "assets/search-index.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    urls = [SITE, SITE + "zh/"] + [SITE + doc_url(s).removeprefix(BASE) for s in GUIDES]
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{html.escape(url)}</loc></url>" for url in urls)
        + "</urlset>",
        "utf-8",
    )
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE}sitemap.xml\n", "utf-8"
    )
    (OUT / ".nojekyll").touch()
    print(f"Built bilingual introduction pages and {len(GUIDES)} documentation pages: {OUT}")


if __name__ == "__main__":
    main()
