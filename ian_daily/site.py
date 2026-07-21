from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from . import config
from .models import EpisodeBundle, QualityReport
from .storage import EpisodeStore


CSS = """
:root{--ink:#171916;--paper:#f7f5ef;--muted:#686c66;--line:#d7d4ca;--accent:#008c7a;--warm:#e4572e;--green:#3a6b35}*{box-sizing:border-box}html{scroll-behavior:smooth;max-width:100%}body{margin:0;max-width:100%;overflow-x:hidden;background:var(--paper);color:var(--ink);font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;letter-spacing:0}a{color:inherit}header{border-bottom:1px solid var(--line);position:sticky;top:0;background:rgba(247,245,239,.96);z-index:5}.nav{max-width:1180px;margin:auto;height:58px;display:flex;align-items:center;gap:28px;padding:0 24px}.brand{font:700 22px Georgia,"Songti SC",serif;text-decoration:none;margin-right:auto;flex:none}.nav a:not(.brand){font-size:14px;text-decoration:none;flex:none}.wrap{width:100%;max-width:1180px;margin:auto;padding:40px 24px 80px}.eyebrow{color:var(--muted);font-size:13px}.hero{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:48px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:34px}.hero>div{min-width:0;max-width:100%}.hero h1{width:100%;max-width:100%;font:700 clamp(42px,6vw,78px)/1.05 Georgia,"Songti SC",serif;margin:14px 0 20px;letter-spacing:0;overflow-wrap:anywhere;word-break:break-all}.lead{width:100%;font:18px/1.8 Georgia,"Songti SC",serif;color:#40443f;max-width:760px;overflow-wrap:anywhere;word-break:break-all}.metrics{border-left:1px solid var(--line);padding-left:26px}.metric strong{display:block;font:52px Georgia,serif}.metric span{font-size:13px;color:var(--muted)}.player{width:100%;max-width:100%;overflow:hidden;background:#161816;color:white;margin:28px 0 38px;border-top:6px solid var(--accent);padding:18px 20px;min-width:0}.controls{width:100%;min-width:0;display:grid;grid-template-columns:auto minmax(0,1fr) auto auto auto;gap:14px;align-items:center;max-width:100%}.play{width:42px;height:42px;border:1px solid #777;background:transparent;color:#fff;font-size:18px;cursor:pointer;flex:none}.timeline{width:100%;min-width:0;accent-color:#16a68f}.time{font-variant-numeric:tabular-nums;color:#c7cbc6;font-size:12px;white-space:nowrap}.speed{background:#242724;color:#fff;border:1px solid #555;padding:8px}.chapters{display:flex;gap:8px;max-width:100%;overflow-x:auto;margin-top:14px;padding-bottom:4px}.chapter{border:1px solid #555;background:transparent;color:#ddd;padding:7px 10px;white-space:nowrap;cursor:pointer}.chapter.active{background:var(--accent);border-color:var(--accent);color:#fff}.article-layout{display:grid;grid-template-columns:72px minmax(0,740px) 1fr;gap:28px}.section-number{font:50px Georgia,serif;color:#c7c3b8}.story{padding:16px 0 54px;border-bottom:1px solid var(--line);min-width:0}.story h2{font:700 34px/1.25 Georgia,"Songti SC",serif;margin:0 0 12px;overflow-wrap:anywhere}.dek{font:18px/1.7 Georgia,"Songti SC",serif;color:#525650;border-left:3px solid var(--accent);padding-left:14px}.story-image{width:100%;max-height:460px;object-fit:cover;margin:20px 0 6px;background:#ddd}.credit{font-size:11px;color:var(--muted)}.body{font:18px/2 Georgia,"Songti SC",serif;white-space:pre-wrap}.takeaway{font-weight:650;border-top:1px solid var(--line);padding-top:16px}.sources{font-size:13px;color:var(--muted);align-self:start;position:sticky;top:86px}.sources a{display:block;margin:0 0 12px;line-height:1.5;overflow-wrap:anywhere}.transcript{max-width:840px;margin:46px auto;border-top:1px solid var(--line);padding-top:20px}.transcript summary{cursor:pointer;font-weight:650}.transcript p{line-height:1.8}.speaker{color:var(--accent);font-weight:650}.home-title{font:700 64px/1.05 Georgia,"Songti SC",serif;margin:30px 0 12px}.channel-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-top:1px solid var(--line);margin-top:42px}.channel{min-width:0;max-width:100%;padding:26px 24px 30px 0;border-right:1px solid var(--line);margin-right:24px}.channel p,.archive-row>*{min-width:0;max-width:100%;overflow-wrap:anywhere;word-break:break-word}.channel:last-child{border-right:0}.channel h2{font:700 32px Georgia,"Songti SC",serif}.channel a{text-decoration:none}.channel .date{font-size:12px;color:var(--muted)}.empty{color:var(--muted);padding:40px 0}.archive{margin-top:64px;border-top:1px solid var(--line)}.archive-row{display:grid;grid-template-columns:150px 100px minmax(0,1fr);padding:16px 0;border-bottom:1px solid var(--line);text-decoration:none}@media(max-width:800px){.nav{width:100%;gap:18px;padding:0 16px;overflow:hidden}.nav a:not(.brand){display:none}.wrap{padding:28px 16px 60px}.hero{grid-template-columns:minmax(0,1fr)}.metrics{border-left:0;padding:0;display:flex;gap:34px}.hero h1,.home-title{font-size:40px}.article-layout{grid-template-columns:36px minmax(0,1fr);gap:12px}.sources{grid-column:2;position:static}.story h2{font-size:27px}.section-number{font-size:34px}.channel-grid{grid-template-columns:minmax(0,1fr)}.channel{width:100%;padding-right:0;border-right:0;border-bottom:1px solid var(--line);margin:0}.player{padding:14px 12px}.controls{display:flex;flex-wrap:wrap;gap:10px}.timeline{flex:1 1 0;max-width:calc(100% - 54px)}.time{order:3;flex:1 1 auto}.speed{order:4;margin-left:auto}.controls>a{order:5;flex:0 0 100%}.chapters{width:100%}.archive-row{grid-template-columns:88px 54px minmax(0,1fr);gap:8px;font-size:13px}}
"""


def _e(value: object) -> str:
    return html.escape(str(value or ""))


def _shell(title: str, body: str, depth: int = 0) -> str:
    prefix = "../" * depth
    nav = "".join(f'<a href="{prefix}{slug}/">{profile.name}</a>' for slug, profile in config.CATEGORIES.items())
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title><link rel="stylesheet" href="{prefix}assets/site.css"></head><body><header><nav class="nav"><a class="brand" href="{prefix}">伊恩每日</a>{nav}</nav></header>{body}</body></html>'


def _episode_page(bundle: EpisodeBundle, report: QualityReport, audio_href: str) -> str:
    chapters = [{"title": item.title, "start": item.start_sec, "story_id": item.story_id} for item in bundle.podcast.chapters]
    chapter_buttons = "".join(f'<button class="chapter" data-start="{item.start_sec}">{_e(item.title)}</button>' for item in bundle.podcast.chapters)
    stories = []
    for index, section in enumerate(bundle.reading.sections, 1):
        image = f'<img class="story-image" src="{_e(section.image_url)}" alt="{_e(section.title)}"><div class="credit">图片来源：{_e(section.image_credit or "原文来源")}</div>' if section.image_url else ""
        sources = "".join(f'<a href="{_e(source.url)}" target="_blank" rel="noopener">{_e(source.source)} · {_e(source.title)}</a>' for source in section.source_refs)
        stories.append(f'<div class="section-number">{index:02d}</div><article class="story" id="story-{_e(section.story_id)}"><h2>{_e(section.title)}</h2><p class="dek">{_e(section.dek)}</p>{image}<div class="body">{_e(section.body)}</div><p class="takeaway">伊恩的观察：{_e(section.takeaway)}</p></article><aside class="sources"><strong>本章来源</strong>{sources}</aside>')
    transcript = "".join(f'<p><span class="speaker">{"听众" if block.speaker == "listener" else "伊恩"}</span> {_e(block.text)}</p>' for block in bundle.podcast.blocks)
    duration = max(1, round(report.audio_duration_sec / 60))
    body = f'''<main class="wrap"><section class="hero"><div><div class="eyebrow">{_e(bundle.date_bjt)} · 伊恩的{_e(bundle.category_name)}频道</div><h1>{_e(bundle.podcast.title)}</h1><p class="lead">{_e(bundle.podcast.description)}</p></div><div class="metrics"><div class="metric"><strong>{report.story_count}</strong><span>个事件</span></div><div class="metric"><strong>{duration}</strong><span>分钟</span></div></div></section><section class="player"><audio id="audio" preload="metadata" src="{_e(audio_href)}"></audio><div class="controls"><button class="play" id="play" aria-label="播放">▶</button><input class="timeline" id="timeline" type="range" min="0" max="100" value="0"><span class="time" id="time">00:00 / 00:00</span><select class="speed" id="speed" aria-label="播放速度"><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select><a href="{_e(audio_href)}" download aria-label="下载音频">下载</a></div><div class="chapters">{chapter_buttons}</div></section><section class="article-layout">{''.join(stories)}</section><section class="transcript"><details><summary>无障碍文字记录</summary>{transcript}</details></section></main><script>const A=document.querySelector('#audio'),P=document.querySelector('#play'),R=document.querySelector('#timeline'),T=document.querySelector('#time'),S=document.querySelector('#speed'),C=[...document.querySelectorAll('.chapter')],K='ian-daily:'+location.pathname;const fmt=s=>`${{Math.floor(s/60).toString().padStart(2,'0')}}:${{Math.floor(s%60).toString().padStart(2,'0')}}`;A.addEventListener('loadedmetadata',()=>{{const saved=+localStorage.getItem(K)||0;if(saved<A.duration-10)A.currentTime=saved;T.textContent=fmt(A.currentTime)+' / '+fmt(A.duration)}});P.onclick=()=>A.paused?A.play():A.pause();A.onplay=()=>P.textContent='Ⅱ';A.onpause=()=>P.textContent='▶';A.ontimeupdate=()=>{{R.value=A.duration?A.currentTime/A.duration*100:0;T.textContent=fmt(A.currentTime)+' / '+fmt(A.duration||0);localStorage.setItem(K,A.currentTime);let active=0;C.forEach((b,i)=>{{if(+b.dataset.start<=A.currentTime)active=i;b.classList.toggle('active',i===active)}});const id={json.dumps(chapters,ensure_ascii=False)}[active]?.story_id;if(id&&Math.abs(A.currentTime-(+C[active].dataset.start))<1)document.querySelector('#story-'+id)?.scrollIntoView({{block:'center'}})}};R.oninput=()=>A.currentTime=A.duration*R.value/100;S.onchange=()=>A.playbackRate=+S.value;C.forEach(b=>b.onclick=()=>{{A.currentTime=+b.dataset.start;A.play()}});</script>'''
    return _shell(f"{bundle.podcast.title} · 伊恩每日", body, 2)


def build_site(store: EpisodeStore | None = None, include_ids: set[str] | None = None) -> Path:
    store = store or EpisodeStore()
    include_ids = include_ids or set()
    bundles = [item for item in store.list_bundles() if item.status == "published" or item.episode_id in include_ids]
    config.SITE_DIR.mkdir(parents=True, exist_ok=True)
    assets = config.SITE_DIR / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "site.css").write_text(CSS, encoding="utf-8")
    for bundle in bundles:
        episode_dir = store.episode_dir(bundle.episode_id)
        target = config.SITE_DIR / bundle.category / bundle.episode_id
        target.mkdir(parents=True, exist_ok=True)
        audio_name = "episode.mp3"
        if bundle.podcast.full_audio_file:
            shutil.copy2(episode_dir / bundle.podcast.full_audio_file, target / audio_name)
        page = _episode_page(bundle, store.load_quality(bundle.episode_id), audio_name)
        (target / "index.html").write_text(page, encoding="utf-8")

    cards = []
    for slug, profile in config.CATEGORIES.items():
        latest = next((item for item in bundles if item.category == slug), None)
        if latest:
            cards.append(f'<article class="channel"><div class="date">{_e(latest.date_bjt)}</div><h2><a href="{slug}/{latest.episode_id}/">{_e(profile.name)}</a></h2><p>{_e(latest.podcast.description)}</p><a href="{slug}/{latest.episode_id}/">收听并阅读 →</a></article>')
        else:
            cards.append(f'<article class="channel"><h2>{_e(profile.name)}</h2><p class="empty">今天尚无通过质量门禁的节目。</p></article>')
    rows = "".join(f'<a class="archive-row" href="{b.category}/{b.episode_id}/"><span>{_e(b.date_bjt)}</span><span>{_e(b.category_name)}</span><strong>{_e(b.podcast.title)}</strong></a>' for b in bundles)
    body = f'<main class="wrap"><div class="eyebrow">三种视角，同一份对世界的好奇</div><h1 class="home-title">伊恩每日</h1><p class="lead">科技、教育与运动。每期既是一篇可以慢慢读的深度文章，也是一档为耳朵重新创作的完整播客。</p><section class="channel-grid">{"".join(cards)}</section><section class="archive"><h2>往期节目</h2>{rows or "<p class=empty>首期正在制作中。</p>"}</section></main>'
    (config.SITE_DIR / "index.html").write_text(_shell("伊恩每日", body), encoding="utf-8")
    for slug, profile in config.CATEGORIES.items():
        target = config.SITE_DIR / slug
        target.mkdir(exist_ok=True)
        items = [item for item in bundles if item.category == slug]
        list_html = "".join(f'<a class="archive-row" href="{item.episode_id}/"><span>{_e(item.date_bjt)}</span><span>{round(item.podcast.total_duration_sec/60)} 分钟</span><strong>{_e(item.podcast.title)}</strong></a>' for item in items)
        (target / "index.html").write_text(_shell(f"{profile.name} · 伊恩每日", f'<main class="wrap"><h1 class="home-title">{profile.name}</h1><section class="archive">{list_html or "<p class=empty>暂无节目。</p>"}</section></main>', 1), encoding="utf-8")
    return config.SITE_DIR
