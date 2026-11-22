"""アフィリエイト: 動画に合うテーマを選び、説明欄の商品リンクとまとめページを作る。

設定は affiliate.yaml。ID は環境変数 AMAZON_ASSOCIATE_TAG / RAKUTEN_AFFILIATE_ID でも渡せる。
"""
from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, quote_plus

import yaml

from . import rakuten_api
from .models import VideoPlan

DISCLOSURE = "※この説明欄・リンク先にはアフィリエイト広告（PR）が含まれます。"
AMAZON_NOTICE = "Amazonのアソシエイトとして、当チャンネルは適格販売により収入を得ています。"


@dataclass
class Link:
    shop: str
    url: str


def load(root: Path) -> dict:
    p = root / "affiliate.yaml"
    if not p.exists():
        return {}
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg["amazon_tag"] = os.environ.get("AMAZON_ASSOCIATE_TAG") or cfg.get("amazon_tag") or ""
    cfg["rakuten_id"] = os.environ.get("RAKUTEN_AFFILIATE_ID") or cfg.get("rakuten_id") or ""
    return cfg


def site_url(cfg: dict) -> str:
    url = (cfg.get("site_url") or "").strip()
    if url:
        return url.rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def item_links(item: dict, cfg: dict) -> list[Link]:
    links: list[Link] = []
    if item.get("url"):
        links.append(Link(item.get("shop", "商品ページ"), item["url"]))
    if item.get("rakuten_url") and cfg.get("rakuten_id"):
        # 楽天の好きなページ（ふるさと納税の特集など）をアフィリエイトリンクにする
        links.append(Link("楽天", f"https://hb.afl.rakuten.co.jp/hgc/{cfg['rakuten_id']}/?pc={quote(item['rakuten_url'], safe='')}"))
    kw = item.get("search")
    if kw:
        if cfg.get("amazon_tag"):
            links.append(Link("Amazon", f"https://www.amazon.co.jp/s?k={quote_plus(kw)}&tag={quote(cfg['amazon_tag'])}"))
        if cfg.get("rakuten_id"):
            target = f"https://search.rakuten.co.jp/search/mall/{quote(kw)}/"
            links.append(Link("楽天", f"https://hb.afl.rakuten.co.jp/hgc/{cfg['rakuten_id']}/?pc={quote(target, safe='')}"))
    return links


def enrich_theme(theme: dict, cfg: dict) -> dict:
    """search: の商品を、楽天の商品検索APIで選んだ「人気の具体的な商品」に置き換える。

    API のキーが無いとき・失敗したときは、今までどおり検索結果へのリンクのまま。
    """
    if theme.get("_enriched") or not (cfg.get("auto_pick", True) and rakuten_api.available()):
        return theme
    used: set[str] = set()
    items = []
    for it in theme.get("items") or []:
        kw = it.get("search")
        if not kw or it.get("url") or it.get("auto_pick") is False:
            items.append(it)
            continue
        got = rakuten_api.pick(kw, cfg.get("rakuten_id", ""), site_url(cfg), used,
                               int(cfg.get("min_reviews", 20)), float(cfg.get("min_review_average", 4.0)))
        if not got:
            items.append(it)
            continue
        used.add(got["code"])
        note = f"★{got['review_average']:.1f}（レビュー{got['review_count']:,}件）"
        if got["price"]:
            note += f"・{got['price']:,}円前後"
        items.append({"name": got["name"], "shop": "楽天", "url": got["url"],
                      "comment": f"{it.get('comment', '')}　{note}".strip(), "search": None})
        print(f"[rakuten] 「{kw}」→ {got['name']}")
    theme = dict(theme, items=items, _enriched=True)
    return theme


def choose_theme(plan: VideoPlan, cfg: dict) -> dict | None:
    """タイトル・タグ・台本にキーワードが一番多く入っているテーマを選ぶ。"""
    themes = cfg.get("themes") or []
    if not themes:
        return None
    text = " ".join([plan.title, plan.header, plan.subheader, " ".join(plan.tags)] +
                    [f"{s.text} {s.narration}" for s in plan.scenes])
    # タイトル・タグに入っている語は重みを大きくする
    strong = " ".join([plan.title, plan.subheader, " ".join(plan.tags)])

    def score(t: dict) -> int:
        return sum((3 if k in strong else 0) + text.count(k) for k in t.get("keywords", []))

    best = max(themes, key=score)
    if score(best) > 0:
        return best
    return next((t for t in themes if t.get("default")), themes[0])


def apply(plan: VideoPlan, cfg: dict) -> dict | None:
    """plan の説明欄に商品リンクを足し、締めのナレーションに一言加える。使ったテーマを返す。"""
    if not cfg or not cfg.get("enabled", True):
        return None
    theme = choose_theme(plan, cfg)
    if not theme:
        return None
    theme = enrich_theme(theme, cfg)

    lines: list[str] = []
    for item in (theme.get("items") or [])[: int(cfg.get("max_items_in_description", 3))]:
        links = item_links(item, cfg)
        if not links:
            continue
        lines.append(f"▶ {item['name']}")
        lines += [f"　{l.shop}: {l.url}" for l in links]
    url = site_url(cfg)
    if not lines and not url:
        print("[affiliate] ID もまとめページURLも無いのでスキップします（affiliate.yaml を設定してください）")
        return None

    block = ["", "━━━━━━━━━━", f"🛒 {theme['name']}", DISCLOSURE]
    if url:
        block.append(f"紹介アイテムの一覧はこちら → {url}#{theme['id']}")
    block += lines
    if cfg.get("amazon_tag") and any("amazon.co.jp" in l for l in lines):
        block.append(AMAZON_NOTICE)
    block.append("━━━━━━━━━━")

    # ハッシュタグ行は最後に残したいので、その手前に差し込む
    desc = plan.description.rstrip().split("\n")
    tail = [desc.pop()] if desc and desc[-1].lstrip().startswith("#") else []
    while desc and not desc[-1].strip():
        desc.pop()
    plan.description = "\n".join(desc + block + ([""] + tail if tail else []))

    cta = (cfg.get("outro_cta") or "").strip()
    if cta and url:
        for s in plan.scenes:
            if s.kind == "outro" and cta not in s.narration:
                s.narration = f"{s.narration.rstrip()}{cta}"
    print(f"[affiliate] テーマ「{theme['name']}」のリンクを説明欄に入れました")
    return theme


# ---------------------------------------------------------------- まとめページ
_CSS = """
:root{--bg:#f7f5f0;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e6e2d8;--accent:#e4572e;--btn:#1d1d1f;--btntext:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--text:#f2f2f4;--muted:#a0a0a8;--line:#2e2e34;--accent:#ff7a50;--btn:#f2f2f4;--btntext:#141416}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;line-height:1.7}
main{max-width:720px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.5rem;margin:8px 0 4px}.pr{font-size:.8rem;color:var(--muted);margin:0 0 20px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px}nav a{font-size:.85rem;padding:4px 12px;border:1px solid var(--line);border-radius:999px;color:var(--text);text-decoration:none;background:var(--card)}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:18px;scroll-margin-top:16px}
section:target{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent)}
h2{font-size:1.15rem;margin:0 0 12px}.item{padding:12px 0;border-top:1px solid var(--line)}.item:first-of-type{border-top:0;padding-top:0}
.name{font-weight:700}.comment{color:var(--muted);font-size:.9rem;margin:2px 0 8px}
.btns{display:flex;flex-wrap:wrap;gap:8px}.btns a{display:inline-block;padding:8px 16px;border-radius:8px;background:var(--btn);color:var(--btntext);text-decoration:none;font-size:.9rem;font-weight:600}
footer{font-size:.75rem;color:var(--muted);margin-top:32px}
"""


def build_site(cfg: dict, out_dir: Path) -> Path:
    """affiliate.yaml からテーマごとの商品一覧ページ（index.html）を作る。"""
    e = html.escape
    title = cfg.get("site_title", "紹介アイテムまとめ")
    themes = [enrich_theme(t, cfg) for t in cfg.get("themes") or []]
    nav = "".join(f'<a href="#{e(t["id"])}">{e(t["name"])}</a>' for t in themes)
    secs = []
    for t in themes:
        items = []
        for it in t.get("items") or []:
            links = item_links(it, cfg)
            if not links:
                continue
            btns = "".join(f'<a href="{e(l.url)}" target="_blank" rel="sponsored noopener">{e(l.shop)}で見る</a>' for l in links)
            items.append(f'<div class="item"><div class="name">{e(it["name"])}</div>'
                         f'<div class="comment">{e(it.get("comment", ""))}</div><div class="btns">{btns}</div></div>')
        if items:
            secs.append(f'<section id="{e(t["id"])}"><h2>{e(t["name"])}</h2>{"".join(items)}</section>')
    if not secs:
        secs.append("<section><p>準備中です。</p></section>")
    notice = f"<p>{e(AMAZON_NOTICE)}</p>" if cfg.get("amazon_tag") else ""
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="robots" content="noindex"><style>{_CSS}</style></head>
<body><main><h1>{e(title)}</h1>
<p class="pr">【PR】このページはアフィリエイト広告を利用しています。リンクから購入されると、運営者に紹介料が入ることがあります。</p>
<nav>{nav}</nav>{"".join(secs)}
<footer>{notice}<p>価格・在庫は各ショップでご確認ください。</p><p><a href="privacy.html">プライバシーポリシー</a></p></footer></main></body></html>
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    (out_dir / "privacy.html").write_text(_privacy_page(cfg), encoding="utf-8")
    return out


def _privacy_page(cfg: dict) -> str:
    """Google の OAuth 同意画面（アプリの公開）に必要なプライバシーポリシー。"""
    amazon = ("<li>Amazonアソシエイト・プログラム（Amazon.co.jp を宣伝しリンクすることで紹介料を獲得できる手段を提供する"
              "アフィリエイトプログラム）</li>") if cfg.get("amazon_tag") else ""
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>プライバシーポリシー</title><style>{_CSS} h2{{margin-top:28px}} li{{margin:4px 0}}</style></head>
<body><main><h1>プライバシーポリシー</h1>
<p>本ページは、当方が運営する YouTube チャンネル、動画自動投稿ツール「shorts」、および紹介アイテムまとめページ（以下「本サービス」）における情報の取り扱いを定めるものです。</p>

<h2>1. 動画自動投稿ツール（YouTube API）について</h2>
<ul>
<li>本ツールは、運営者自身の YouTube チャンネルに動画をアップロードする目的でのみ、YouTube API サービスを利用します。</li>
<li>利用する権限は動画のアップロード（youtube.upload）のみで、視聴者や第三者のアカウント情報・個人情報を取得・保存・共有することはありません。</li>
<li>認証情報は運営者のみが管理する環境に保管し、第三者に提供しません。</li>
<li>本ツールは YouTube API サービスを使用しています。<a href="https://www.youtube.com/t/terms">YouTube 利用規約</a>および
<a href="https://policies.google.com/privacy">Google プライバシーポリシー</a>もあわせてご確認ください。</li>
<li>Google のセキュリティ設定ページ（<a href="https://security.google.com/settings/security/permissions">https://security.google.com/settings/security/permissions</a>）から、いつでもアクセス権を取り消せます。</li>
</ul>

<h2>2. アフィリエイトプログラムについて</h2>
<p>本サービスは、以下のアフィリエイトプログラムに参加しています。リンク先のショップでは、成果の計測のために Cookie 等が使われることがあります。</p>
<ul><li>楽天アフィリエイト</li>{amazon}</ul>
<p>Cookie の取り扱いは各ショップのプライバシーポリシーをご確認ください。ブラウザの設定で Cookie を無効にすることもできます。</p>

<h2>3. アクセス解析・個人情報</h2>
<p>まとめページでは、アクセス解析ツールや問い合わせフォームを設置しておらず、閲覧者の個人情報を収集していません。</p>

<h2>4. 免責事項</h2>
<p>紹介している商品の価格・在庫・内容は変わることがあります。購入の際は各ショップの情報をご確認ください。</p>

<h2>5. 改定</h2>
<p>本ポリシーは必要に応じて改定することがあります。</p>

<p><a href="./">← 紹介アイテムまとめに戻る</a></p>
<footer><p>制定日：2026年11月22日</p></footer></main></body></html>
"""
