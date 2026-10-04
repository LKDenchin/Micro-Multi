"""Build the public introduction and documentation site from repository guides."""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "site"
BASE = "/Micro-Multi/"
SITE = "https://lkdenchin.github.io/Micro-Multi/"
REPO = "https://github.com/LKDenchin/Micro-Multi"
GUIDE_PAIRS = {
    "README.md": ("Getting started", "开始使用"),
    "docs/CURRENT_CHANGES.md": ("Current source changes", "当前源码变化"),
    "docs/NATIVE_CORDIS.md": ("Native dsh plugins", "原生 dsh 插件"),
    "docs/AUTONOMOUS_COLLABORATION.md": ("Reviewed team collaboration", "经审核的团队协作"),
    "docs/DURABLE_TURNS_AND_MODEL_RECOVERY.md": ("Conversations and recovery", "对话与恢复"),
    "docs/architecture.md": ("Architecture", "架构"),
    "docs/extensions.md": ("Extensions and tools", "扩展与工具"),
    "docs/deployment.md": ("Local deployment", "本地部署"),
    "docs/contracts.md": ("Runtime interfaces", "运行时接口"),
    "docs/sandbox.md": ("Execution and permissions", "执行与权限"),
    "docs/replay.md": ("Session history", "会话历史"),
    "docs/DESKTOP_RELEASE.md": ("Desktop installation and builds", "桌面安装与构建"),
    "docs/RELEASE_NOTES.md": ("Release notes", "发布说明"),
    "docs/RELEASE_VALIDATION.md": ("Historical release validation", "历史发布验证"),
    "docs/UPSTREAM_RUNTIME_PROVENANCE.md": ("Runtime provenance", "运行时溯源"),
    "CONTRIBUTING.md": ("Contributing", "贡献指南"),
    "SECURITY.md": ("Security", "安全政策"),
    "CODE_OF_CONDUCT.md": ("Community conduct", "社区规范"),
    "CHANGELOG.md": ("Changelog", "更新记录"),
    "PRODUCT_DEVELOPMENT_SPEC.md": ("Product guide", "产品指南"),
}


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
    return f'''<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Micro-Multi</title><meta name="description" content="{html.escape(description, quote=True)}">
<meta name="theme-color" content="#172033"><link rel="canonical" href="{SITE}{path}">
<link rel="alternate" hreflang="{"en" if chinese else "zh-CN"}" href="https://lkdenchin.github.io{alternate}">
<meta property="og:title" content="{html.escape(title, quote=True)} · Micro-Multi"><meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:type" content="website"><meta property="og:image" content="{SITE}assets/micro-multi.png">
<link rel="icon" href="{BASE}assets/micro-multi.svg"><link rel="stylesheet" href="{BASE}assets/site.css">
<script src="{BASE}assets/site.js" defer></script></head><body>
<a class="skip" href="#content">{"跳转到正文" if chinese else "Skip to content"}</a>
<header class="header"><nav class="nav" aria-label="{"主导航" if chinese else "Main navigation"}">
<a class="brand" href="{home}"><img src="{BASE}assets/micro-multi.svg" width="34" height="34" alt=""><span>Micro-Multi</span></a>
<div class="navlinks"><a href="{docs}">{"文档" if chinese else "Docs"}</a><a href="{REPO}/releases/latest">{"下载" if chinese else "Download"}</a><a href="{REPO}">GitHub ↗</a><a class="language" href="{alternate}">{"English" if chinese else "简体中文"}</a></div>
</nav></header><main id="content">{body}</main>
<footer class="footer"><a class="brand" href="{home}">Micro-Multi</a><p>{"在本地，让 Agent 团队一起工作。" if chinese else "A local workspace for your agent team."}</p>
<div><a href="{doc_url(localized_source("CONTRIBUTING.md", chinese))}">{"参与贡献" if chinese else "Contribute"}</a><a href="{doc_url(localized_source("SECURITY.md", chinese))}">{"安全" if chinese else "Security"}</a><a href="{REPO}/discussions">{"社区" if chinese else "Community"}</a><a href="{REPO}/blob/main/LICENSE">Apache-2.0</a></div><small>© 2026 LKDenchin · Micro-Multi contributors</small></footer></body></html>'''


def landing(chinese: bool) -> str:
    def t(en: str, zh: str) -> str:
        return zh if chinese else en

    readme = doc_url("README.zh-CN.md" if chinese else "README.md")
    features = [
        (
            "01",
            t("One task. A whole team.", "一个任务，一支团队。"),
            t(
                "Review and confirm a team plan, then follow specialists and inspect their results.",
                "审核并确认团队方案，再跟踪专业成员并检查交付结果。",
            ),
        ),
        (
            "02",
            t("Your models. Your workspace.", "你的模型，你的工作区。"),
            t(
                "Connect compatible model endpoints and work directly with your local Git projects.",
                "连接兼容的模型接口，直接使用本地 Git 项目，为不同成员选择模型。",
            ),
        ),
        (
            "03",
            t("Tools that grow with you.", "随工作一起扩展的工具。"),
            t(
                "Bring Skills, MCP tools, command plugins and native dsh packages into your workflow.",
                "将 Skills、MCP 工具、本地命令插件和原生 dsh 扩展带入日常工作。",
            ),
        ),
        (
            "04",
            t("Follow every step.", "看见每一步。"),
            t(
                "Keep conversations, inspect changes and tool records, and resume work across sessions.",
                "保存对话，查看文件改动、工具记录与验证结果，在下次打开时继续工作。",
            ),
        ),
    ]
    cards = "".join(
        f'<article class="feature"><span class="number">{n}</span><h3>{title}</h3><p>{text}</p></article>'
        for n, title, text in features
    )
    downloads = [
        ("Windows", "x64 · NSIS", "Micro-Multi-Setup-0.1.0-x64.exe"),
        ("Debian / Ubuntu", "x64 · .deb", "Micro-Multi-0.1.0-amd64.deb"),
        ("Linux", "x64 · AppImage", "Micro-Multi-0.1.0-x86_64.AppImage"),
    ]
    download_cards = "".join(
        f'<a class="download-card" href="{REPO}/releases/download/v0.1.0/{asset}"><span>{system}</span><small>{kind}</small><b>{t("Download", "下载")} ↗</b></a>'
        for system, kind, asset in downloads
    )
    steps = [
        (
            t("Connect a model", "连接模型"),
            t("Add your endpoint, model and key.", "添加接口地址、模型与密钥。"),
        ),
        (
            t("Open a project", "打开项目"),
            t("Create or import a local repository.", "新建项目或导入本地仓库。"),
        ),
        (
            t("Describe the outcome", "描述目标"),
            t("Review the team plan before members start.", "审核团队方案后启动成员。"),
        ),
        (
            t("Review the result", "检查结果"),
            t("Inspect changes, reviews and verification.", "检查改动、审查与验证记录。"),
        ),
    ]
    step_cards = "".join(
        f"<article><span>{i:02}</span><h3>{title}</h3><p>{text}</p></article>"
        for i, (title, text) in enumerate(steps, 1)
    )
    return f'''
<section class="hero wrap"><div class="hero-copy"><span class="eyebrow">{t("LOCAL · MULTI-AGENT · OPEN SOURCE", "本地 · 多 Agent · 开源")}</span>
<h1>{t("A team of agents.<br>Your local workspace.", "一支 Agent 团队。<br>你的本地工作区。")}</h1>
<p class="lead">{t("Bring conversations, code and tools together. Give your team an outcome, follow the work, and review what it builds.", "将对话、代码和工具放进同一个桌面工作台。描述目标，跟踪团队的工作，检查最终交付。")}</p>
<div class="actions"><a class="button primary" href="#download">{t("Download Micro-Multi", "下载 Micro-Multi")} ↓</a><a class="button secondary" href="{readme}">{t("Read the docs", "阅读文档")} →</a></div>
<p class="platforms">Windows · Linux · {t("Bilingual interface", "双语界面")} · Apache-2.0</p></div>
<div class="team-board" aria-label="{t("Example agent collaboration workflow", "Agent 协作流程示意")}"><div class="board-top"><span class="dots">● ● ●</span><span>Micro-Multi / {t("workspace", "工作区")}</span></div>
<div class="task"><span class="label">{t("YOUR OUTCOME", "你的目标")}</span><p>{t("Add API pagination and verify the behavior.", "为 API 添加分页，并验证行为。")}</p></div>
<div class="agent lead-agent"><span class="agent-icon">M</span><div><strong>{t("Lead agent", "主 Agent")}</strong><small>{t("Plan · delegate · review", "规划 · 委派 · 审查")}</small></div><span class="status">{t("Coordinating", "协作中")}</span></div>
<div class="workers"><div class="agent"><span class="agent-icon blue">01</span><div><strong>{t("Implementation", "实现成员")}</strong><small>{t("Code & changes", "代码与改动")}</small></div></div><div class="agent"><span class="agent-icon green">02</span><div><strong>{t("Verification", "验证成员")}</strong><small>{t("Tests & evidence", "测试与验证记录")}</small></div></div></div>
<div class="board-bottom"><span>↳ {t("Local project", "本地项目")}</span><span>Skills · MCP · dsh</span></div></div></section>
<section class="wrap section"><h2>{t("Current source update", "当前源码更新")}</h2><p>{t("Native plugin loading, managed dependencies, isolated settings, durable streaming and reviewed teams. Existing 0.1.0 downloads remain the published baseline; no new installer is published with this source update.", "原生插件加载、受管理依赖、独立设置、持久化流与团队审核。现有 0.1.0 下载保持发布基线，本次源码更新不发布新安装包。")}</p><a class="text-link" href="{doc_url(localized_source("docs/CURRENT_CHANGES.md", chinese))}">{t("Read all changes", "查看完整变化")} →</a></section><section class="compat wrap"><div><span class="eyebrow">{t("DEEPSEEK-HARNESS ECOSYSTEM", "DEEPSEEK-HARNESS 插件生态")}</span><h2>{t("Compatible with dsh plugins.", "兼容 dsh 插件体系。")}</h2><p>{t("Run native deepseek-harness Cordis Host packages. Their tools are available to both the lead agent and specialist agents.", "原生运行 deepseek-harness Cordis Host 扩展包，让插件工具参与主 Agent 和专业成员的协作。")}</p><a class="text-link" href="{doc_url(localized_source("docs/NATIVE_CORDIS.md", chinese))}">{t("Explore the plugin guide", "查看插件指南")} →</a></div><div class="plugin-pills"><span>{t("Tools", "工具")}</span><span>{t("Services", "服务")}</span><span>{t("Dependency injection", "依赖注入")}</span><span>{t("Events", "事件")}</span><span>{t("Lifecycle", "生命周期")}</span><span>Skills</span><span>MCP</span></div></section>
<section class="wrap section"><span class="eyebrow">{t("BUILT FOR EVERYDAY WORK", "为日常工作而构建")}</span><h2>{t("From an idea to a result you can inspect.", "从一个想法，到可检查的结果。")}</h2><div class="features">{cards}</div></section>
<section id="download" class="download section"><div class="wrap"><span class="eyebrow">{t("PUBLISHED DESKTOP BASELINE · V0.1.0", "已发布桌面基线 · V0.1.0")}</span><h2>{t("Make room for your team.", "让团队进入你的工作区。")}</h2><p>{t("Python and Node are included. Install the package for your system, then connect your own model.", "安装包内置 Python 和 Node。选择对应系统的软件包，然后连接自己的模型。")}</p><div class="downloads">{download_cards}</div><p class="download-note"><a href="{REPO}/releases/download/v0.1.0/SHA256SUMS.txt">SHA256SUMS.txt</a> · <a href="{doc_url(localized_source("docs/DESKTOP_RELEASE.md", chinese))}">{t("Installation and Ubuntu AppImage setup", "安装与 Ubuntu AppImage 配置")}</a> · <a href="{REPO}/releases/latest">{t("Release notes", "版本说明")}</a></p></div></section>
<section class="wrap section"><span class="eyebrow">{t("GET STARTED", "开始使用")}</span><h2>{t("Four steps to your first conversation.", "四步，开始第一次协作。")}</h2><div class="steps">{step_cards}</div><a class="text-link" href="{readme}">{t("Open the getting started guide", "打开入门指南")} →</a></section>
<section class="wrap community"><div><h2>{t("Build with the community.", "与社区一起构建。")}</h2><p>{t("Share ideas, report issues, contribute improvements and create extensions.", "分享想法、反馈问题、贡献改进，或编写自己的扩展。")}</p></div><div class="actions"><a class="button primary" href="{REPO}">GitHub ↗</a><a class="button secondary" href="{REPO}/discussions">{t("Join the discussion", "参与交流")} →</a></div></section>'''


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
                "本地多 Agent 桌面工作台" if chinese else "Your local agent workspace",
                "兼容 deepseek-harness（dsh）插件体系的本地多 Agent 桌面工作台。"
                if chinese
                else "A local multi-agent desktop workspace compatible with the deepseek-harness (dsh) plugin ecosystem.",
                landing(chinese),
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
            f'<a href="{doc_url(guide)}">{html.escape(label)}</a>'
            for guide, label in GUIDES.items()
            if guide.endswith(".zh-CN.md") == chinese
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
