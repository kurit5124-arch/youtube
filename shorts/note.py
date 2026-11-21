"""note の記事を作る（動画と同じ事件を、読み物として深掘りした版）。

note には公式の投稿 API が無いので、次の 2 つのファイルを書き出す。
  *_note.md   … 読みやすい下書き（そのまま確認用）
  *_note.html … ブラウザで開いて「コピー」→ note のエディタに貼ると、見出しや太字がそのまま入る
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from .saiban import DISCLAIMER

HASHTAGS = ["みんなの裁判", "あなたならどうする", "究極の選択", "考え方", "人間関係"]


def saiban_article(case: dict, no: int, video_id: str | None = None,
                   prev: dict | None = None, verdict=None) -> tuple[str, str]:
    """(記事タイトル, 本文の Markdown) を返す。"""
    title = f"【みんなの裁判 No.{no}】{case['title']}｜あなたならどう裁く？"
    md: list[str] = [
        "正解のない身近なトラブルを、読んでいるあなたに裁いてもらう企画「みんなの裁判」です。",
        "YouTube ショートでも毎回の事件を公開しています。今回の事件はこちら。", "",
    ]
    if prev and verdict is not None and verdict.total:
        pc = prev["case"]
        pa = round(verdict.a * 100 / verdict.total)
        res = ("同数で引き分け" if verdict.a == verdict.b else
               f"**A「{pc['option_a']}」が {pa}%** で原告の勝ち" if verdict.a > verdict.b else
               f"**B「{pc['option_b']}」が {100 - pa}%** で被告の勝ち")
        md += [f"## 前回の判決：{pc['title']}", "",
               f"前回の「{pc['question']}」は、{res}でした（A {verdict.a}票 / B {verdict.b}票）。", ""]
        if verdict.a_voice:
            md += [f"- A派の声：「{verdict.a_voice}」"]
        if verdict.b_voice:
            md += [f"- B派の声：「{verdict.b_voice}」"]
        md += ["", "投票してくれた皆さん、ありがとうございました。", ""]

    md += ["## 事件の概要", "", case["summary_narration"], "",
           "## 原告（訴えた側）の言い分", "", f"**「{case['plaintiff_claim']}」**", "", case["plaintiff_narration"], "",
           "## 被告（訴えられた側）の言い分", "", f"**「{case['defendant_claim']}」**", "", case["defendant_narration"], ""]
    hints = case.get("hints") or []
    if hints:
        md += ["## 考えるヒント", "", "判決を出す前に、こんな視点から考えてみてください。", ""]
        for i, h in enumerate(hints, 1):
            md += [f"### {i}. {h['title']}", "", h["text"], ""]
    md += ["## あなたの判決は？", "", f"争点：**{case['question']}**", "",
           f"- **A：{case['option_a']}**（原告の勝ち）",
           f"- **B：{case['option_b']}**（被告の勝ち）", "",
           "コメント欄に **A か B** を書いてください。理由も書いてもらえると、次回の記事で紹介するかもしれません。",
           "結果は次回の記事と動画で発表します。", "",
           "## 動画でも見られます", "",
           f"https://youtube.com/shorts/{video_id}" if video_id else "（ここに YouTube ショートの URL を貼ってください）", "",
           "---", "", DISCLAIMER, "",
           " ".join("#" + t for t in HASHTAGS + [t for t in case.get("tags", []) if t not in HASHTAGS][:4])]
    return title, "\n".join(md)


def _inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)


def to_html(title: str, md: str) -> str:
    body: list[str] = []
    in_list = False
    for line in md.split("\n"):
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline(line[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line == "---":
            body.append("<hr>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    if in_list:
        body.append("</ul>")
    article = "\n".join(body)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#fff;--fg:#222;--muted:#666;--line:#e5e5e5;--accent:#2cb696}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181d;--fg:#eee;--muted:#aaa;--line:#333}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:"Hiragino Sans","Noto Sans JP",sans-serif;line-height:1.9}}
main{{max-width:680px;margin:0 auto;padding:24px 16px 80px}}
.bar{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 0;margin-bottom:16px}}
button{{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 16px;font-size:15px;cursor:pointer;margin:4px 8px 4px 0}}
.hint{{color:var(--muted);font-size:13px}}
h1{{font-size:26px;line-height:1.5}} h2{{font-size:21px;margin-top:2em}} h3{{font-size:17px}}
</style></head><body><main>
<div class="bar">
<button onclick="copyText('t')">① タイトルをコピー</button><button onclick="copyRich()">② 本文をコピー</button>
<div class="hint">note の「記事を書く」でタイトル欄に①、本文欄に②を貼り付けてください。見出しと太字はそのまま入ります。</div>
</div>
<h1 id="t">{html.escape(title)}</h1>
<article id="a">
{article}
</article>
</main>
<script>
function done(b){{const e=document.activeElement;if(e&&e.tagName==='BUTTON'){{const o=e.textContent;e.textContent='コピーしました';setTimeout(()=>e.textContent=o,1500)}}}}
function copyText(id){{navigator.clipboard.writeText(document.getElementById(id).innerText).then(done)}}
function copyRich(){{const el=document.getElementById('a');
 try{{navigator.clipboard.write([new ClipboardItem({{'text/html':new Blob([el.innerHTML],{{type:'text/html'}}),'text/plain':new Blob([el.innerText],{{type:'text/plain'}})}})]).then(done)}}
 catch(e){{const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r);document.execCommand('copy');s.removeAllRanges();done()}}}}
</script></body></html>
"""


def write(out_base: Path, title: str, md: str) -> tuple[Path, Path]:
    mdp = out_base.with_name(out_base.name + "_note.md")
    htp = out_base.with_name(out_base.name + "_note.html")
    mdp.write_text(f"# {title}\n\n{md}\n", encoding="utf-8")
    htp.write_text(to_html(title, md), encoding="utf-8")
    return mdp, htp
