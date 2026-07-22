from __future__ import annotations

import html
import json
import shutil
from collections import defaultdict
from pathlib import Path

from . import config
from .audio import waveform_peaks
from .models import EpisodeBundle, QualityReport
from .images import resolve_story_images
from .storage import EpisodeStore

CSS = r"""
:root{--ink:#171815;--paper:#fbfaf6;--soft:#f0eee7;--muted:#6f716a;--line:#dcd9cf;--accent:#087f70;--sport:#d95632;--edu:#487444}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans SC","Microsoft YaHei",sans-serif;letter-spacing:0}a{color:inherit}header{height:60px;border-bottom:1px solid var(--line);background:rgba(251,250,246,.96);position:sticky;top:0;z-index:20}.nav{max-width:1120px;height:60px;margin:auto;padding:0 22px;display:flex;align-items:center;gap:25px}.brand{font:700 23px Georgia,"Songti SC",serif;text-decoration:none;margin-right:auto}.nav-link{text-decoration:none;font-size:14px}.wrap{width:min(100% - 36px,1120px);margin:auto}.home-intro{padding:72px 0 48px;border-bottom:1px solid var(--line)}.eyebrow{font-size:13px;color:var(--muted);margin-bottom:16px}.home-intro h1{font:700 64px/1.08 Georgia,"Songti SC",serif;margin:0 0 20px}.home-intro p{font:20px/1.8 Georgia,"Songti SC",serif;color:#454842;max-width:760px;margin:0}.channel-shelf{padding:42px 0 22px}.channel-shelf h2{font:700 30px Georgia,"Songti SC",serif;margin:0 0 22px}.today-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}.channel-card{min-width:0;border-top:5px solid var(--channel);background:#fff;padding:18px;box-shadow:0 8px 28px rgba(30,31,27,.07)}.channel-card img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover;background:var(--soft)}.channel-meta{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:16px}.channel-card h3{font:700 25px/1.35 Georgia,"Songti SC",serif;margin:12px 0}.channel-card p{font-size:14px;line-height:1.75;color:#50534e;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}.card-actions{display:flex;gap:15px;align-items:center;margin-top:18px}.primary-link{font-weight:700;text-decoration:none}.archive-link{font-size:13px;color:var(--muted)}.recent{border-top:1px solid var(--line);margin-top:22px;padding-top:15px}.recent a{display:block;text-decoration:none;font-size:13px;line-height:1.5;padding:8px 0;border-bottom:1px solid #ebe8df}.category-head{padding:66px 0 34px;border-bottom:1px solid var(--line)}.category-head h1{font:700 54px Georgia,"Songti SC",serif;margin:0 0 12px}.month{padding:34px 0 8px}.month h2{font:700 22px Georgia,"Songti SC",serif}.episode-row{display:grid;grid-template-columns:110px 90px minmax(0,1fr);gap:18px;padding:18px 0;border-top:1px solid var(--line);text-decoration:none}.episode-row span{font-size:13px;color:var(--muted)}.episode-row strong{line-height:1.5}.article{width:min(100% - 36px,800px);margin:auto}.article-hero{padding:52px 0 28px}.article-hero .channel-name{color:var(--channel);font-weight:700;font-size:14px}.article-hero h1{font:700 48px/1.18 Georgia,"Songti SC",serif;margin:16px 0}.article-lead{font:19px/1.85 Georgia,"Songti SC",serif;color:#484b46}.hero-cover{width:100%;aspect-ratio:16/9;object-fit:cover;margin-top:25px;background:var(--soft)}.hero-credit,.credit{font-size:11px;color:var(--muted);margin-top:7px}.player-shell{position:sticky;top:60px;z-index:15;background:#171916;color:#fff;border-top:5px solid var(--channel);box-shadow:0 8px 24px rgba(0,0,0,.18)}.player{width:min(100% - 28px,940px);margin:auto;padding:14px 0}.player-main{display:grid;grid-template-columns:42px minmax(0,1fr) auto auto auto;gap:12px;align-items:center}.icon-button{width:42px;height:42px;border:1px solid #666;background:transparent;color:white;font-size:18px;cursor:pointer}.wave{width:100%;height:44px;cursor:pointer;display:block}.time{font-size:12px;color:#d0d2cc;white-space:nowrap}.speed,.volume{accent-color:var(--channel)}.speed{background:#292c29;color:white;border:1px solid #60645f;padding:7px}.download{font-size:13px;text-decoration:none}.chapters{display:flex;gap:7px;overflow-x:auto;padding-top:10px;scrollbar-width:thin}.chapter{border:1px solid #5c605b;background:transparent;color:#ddd;padding:7px 10px;white-space:nowrap;cursor:pointer}.chapter.active{background:var(--channel);border-color:var(--channel);color:#fff}.story{padding:54px 0;border-bottom:1px solid var(--line);scroll-margin-top:170px}.story-index{color:var(--channel);font:700 15px Georgia,serif}.story h2{font:700 34px/1.3 Georgia,"Songti SC",serif;margin:10px 0 14px}.dek{font:18px/1.75 Georgia,"Songti SC",serif;color:#51544e;border-left:3px solid var(--channel);padding-left:16px}.story-image{width:100%;max-height:520px;object-fit:cover;margin:24px 0 0;background:var(--soft)}.body{font:18px/2 Georgia,"Songti SC",serif;white-space:pre-wrap;margin-top:25px}.takeaway{background:var(--soft);padding:18px 20px;line-height:1.8;margin-top:24px}.story-tools{display:flex;align-items:center;gap:16px;margin-top:18px}.listen-here{border:0;background:var(--channel);color:white;padding:9px 14px;cursor:pointer;font-weight:700}.sources{font-size:13px;color:var(--muted)}.sources summary{cursor:pointer}.sources a{display:block;margin-top:9px;line-height:1.5}.transcript{padding:38px 0}.transcript summary{cursor:pointer;font-weight:700}.transcript p{line-height:1.8}.speaker{color:var(--channel);font-weight:700}.episode-nav{display:grid;grid-template-columns:1fr auto 1fr;gap:15px;padding:35px 0 70px}.episode-nav a{text-decoration:none;font-size:13px;line-height:1.5}.episode-nav a:last-child{text-align:right}@media(max-width:760px){header{height:54px}.nav{height:54px;padding:0 16px}.nav-link{display:none}.wrap,.article{width:min(100% - 28px,800px)}.home-intro{padding:45px 0 34px}.home-intro h1{font-size:42px}.home-intro p{font-size:17px}.today-grid{grid-template-columns:minmax(0,1fr)}.category-head{padding:44px 0 28px}.category-head h1{font-size:42px}.episode-row{grid-template-columns:82px minmax(0,1fr)}.episode-row span:nth-child(2){display:none}.article-hero{padding-top:36px}.article-hero h1{font-size:34px}.article-lead{font-size:17px}.player-shell{top:54px}.player{width:calc(100% - 20px)}.player-main{grid-template-columns:40px minmax(0,1fr) auto}.time{grid-column:2}.speed{grid-column:3;grid-row:2}.volume,.download{display:none}.story{padding:42px 0}.story h2{font-size:28px}.body{font-size:17px}.episode-nav{grid-template-columns:1fr 1fr}.episode-nav .back{display:none}}
html,body{max-width:100%}.wrap{width:min(calc(100% - 36px),1120px)}.article{width:min(calc(100% - 36px),800px)}.player{width:min(calc(100% - 28px),940px)}
@media(max-width:760px){.wrap,.article{width:min(calc(100% - 28px),800px)}.article-hero h1,.story h2{overflow-wrap:anywhere}.hero-cover,.story-image{max-width:100%}}
"""


def _e(value: object) -> str:
    return html.escape(str(value or ""))


def _color(category: str) -> str:
    return config.CATEGORIES[category].color


def _shell(title: str, body: str, depth: int = 0, category: str = "tech") -> str:
    prefix = "../" * depth
    nav = "".join(f'<a class="nav-link" href="{prefix}{slug}/">{profile.name}</a>' for slug, profile in config.CATEGORIES.items())
    return f'<!doctype html><html lang="zh-CN" style="--channel:{_color(category)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title><link rel="stylesheet" href="{prefix}assets/site.css"></head><body><header><nav class="nav"><a class="brand" href="{prefix}">伊恩每日</a>{nav}</nav></header>{body}</body></html>'


def _episode_page(bundle: EpisodeBundle, report: QualityReport, previous: EpisodeBundle | None, following: EpisodeBundle | None) -> str:
    story_titles = {item.story_id: item.title for item in bundle.reading.sections}
    buttons = "".join(
        f'<button class="chapter" data-start="{item.start_sec}" data-story="{_e(item.story_id)}">'
        f'{_e(story_titles.get(item.story_id, item.title))}</button>'
        for item in bundle.podcast.chapters
    )
    chapter_by_story = {item.story_id: item.start_sec for item in bundle.podcast.chapters if item.story_id}
    stories = []
    for index, section in enumerate(bundle.reading.sections, 1):
        image = f'<img class="story-image" src="{_e(section.image_url)}" alt="{_e(section.title)}"><div class="credit">图片来源：{_e(section.image_credit)}</div>'
        sources = "".join(f'<a href="{_e(source.url)}" target="_blank" rel="noopener">{_e(source.source)} · {_e(source.title)}</a>' for source in section.source_refs)
        start = chapter_by_story.get(section.story_id, 0)
        stories.append(f'<section class="story" id="story-{_e(section.story_id)}"><div class="story-index">{index:02d}</div><h2>{_e(section.title)}</h2><p class="dek">{_e(section.dek)}</p>{image}<div class="body">{_e(section.body)}</div><div class="takeaway"><strong>伊恩的观察</strong><br>{_e(section.takeaway)}</div><div class="story-tools"><button class="listen-here" data-start="{start}">从这里听</button><details class="sources"><summary>查看本章来源</summary>{sources}</details></div></section>')
    cover = bundle.reading.sections[0].image_url if bundle.reading.sections else ""
    credit = bundle.reading.sections[0].image_credit if bundle.reading.sections else ""
    peaks = json.dumps(bundle.podcast.waveform_peaks, ensure_ascii=False)
    transcript = "".join(f'<p><span class="speaker">{"听众" if block.speaker == "listener" else "伊恩"}</span> {_e(block.text)}</p>' for block in bundle.podcast.blocks)
    previous_link = f'<a href="../{previous.episode_id}/">← {_e(previous.podcast.title)}</a>' if previous else "<span></span>"
    next_link = f'<a href="../{following.episode_id}/">{_e(following.podcast.title)} →</a>' if following else "<span></span>"
    body = f'''<main class="article"><section class="article-hero"><div class="channel-name">伊恩每日 · {_e(bundle.category_name)}</div><h1>{_e(bundle.podcast.title)}</h1><p class="article-lead">{_e(bundle.reading.lead or bundle.podcast.description)}</p><div class="eyebrow">{_e(bundle.date_bjt)} · {report.story_count} 个事件 · {report.audio_duration_sec / 60:.1f} 分钟</div><img class="hero-cover" src="{_e(cover)}" alt="节目封面"><div class="hero-credit">图片来源：{_e(credit)}</div></section></main><section class="player-shell"><div class="player"><audio id="audio" preload="metadata" src="episode.mp3"></audio><div class="player-main"><button class="icon-button" id="play" aria-label="播放">▶</button><canvas class="wave" id="wave" aria-label="音频时间轴"></canvas><span class="time" id="time">00:00 / 00:00</span><select class="speed" id="speed" aria-label="播放速度"><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select><input class="volume" id="volume" type="range" min="0" max="1" step="0.05" value="1" aria-label="音量"><a class="download" href="episode.mp3" download>下载</a></div><div class="chapters">{buttons}</div></div></section><main class="article">{''.join(stories)}<section class="transcript"><details><summary>无障碍文字记录</summary>{transcript}</details></section><nav class="episode-nav">{previous_link}<a class="back" href="../">返回{_e(bundle.category_name)}频道</a>{next_link}</nav></main><script>
const A=document.querySelector('#audio'),P=document.querySelector('#play'),W=document.querySelector('#wave'),T=document.querySelector('#time'),S=document.querySelector('#speed'),V=document.querySelector('#volume'),C=[...document.querySelectorAll('.chapter')],H=[...document.querySelectorAll('.listen-here')],PEAKS={peaks},KEY='ian-daily:'+location.pathname;const fmt=s=>`${{Math.floor(s/60).toString().padStart(2,'0')}}:${{Math.floor(s%60).toString().padStart(2,'0')}}`;function draw(){{const d=devicePixelRatio||1,w=W.clientWidth,h=W.clientHeight;W.width=w*d;W.height=h*d;const x=W.getContext('2d');x.scale(d,d);x.clearRect(0,0,w,h);const progress=A.duration?A.currentTime/A.duration:0;PEAKS.forEach((p,i)=>{{const px=i*w/PEAKS.length,bh=Math.max(2,p*h*.9);x.fillStyle=i/PEAKS.length<=progress?'{_color(bundle.category)}':'#676b66';x.fillRect(px,(h-bh)/2,Math.max(1,w/PEAKS.length-1),bh)}})}}function active(){{let index=0;C.forEach((b,i)=>{{if(+b.dataset.start<=A.currentTime)index=i;b.classList.toggle('active',i===index)}})}}A.addEventListener('loadedmetadata',()=>{{const saved=+localStorage.getItem(KEY)||0;if(saved<A.duration-10)A.currentTime=saved;T.textContent=fmt(A.currentTime)+' / '+fmt(A.duration);draw()}});P.onclick=()=>A.paused?A.play():A.pause();A.onplay=()=>P.textContent='Ⅱ';A.onpause=()=>P.textContent='▶';A.ontimeupdate=()=>{{T.textContent=fmt(A.currentTime)+' / '+fmt(A.duration||0);localStorage.setItem(KEY,A.currentTime);active();draw()}};W.onclick=e=>{{if(A.duration)A.currentTime=(e.offsetX/W.clientWidth)*A.duration}};S.onchange=()=>A.playbackRate=+S.value;V.oninput=()=>A.volume=+V.value;C.forEach(b=>b.onclick=()=>{{A.currentTime=+b.dataset.start;A.play();const id=b.dataset.story;if(id)document.querySelector('#story-'+id)?.scrollIntoView({{behavior:'smooth',block:'start'}})}});H.forEach(b=>b.onclick=()=>{{A.currentTime=+b.dataset.start;A.play()}});addEventListener('resize',draw);
</script>'''
    return _shell(f"{bundle.podcast.title} · 伊恩每日", body, 2, bundle.category)


def build_site(store: EpisodeStore | None = None, include_ids: set[str] | None = None) -> Path:
    store = store or EpisodeStore()
    include_ids = include_ids or set()
    bundles = [item for item in store.list_bundles() if item.status == "published" or item.episode_id in include_ids]
    config.SITE_DIR.mkdir(parents=True, exist_ok=True)
    assets = config.SITE_DIR / "assets"; assets.mkdir(exist_ok=True)
    (assets / "site.css").write_text(CSS, encoding="utf-8")
    by_category: dict[str, list[EpisodeBundle]] = defaultdict(list)
    for bundle in bundles:
        by_category[bundle.category].append(bundle)
    for items in by_category.values():
        items.sort(key=lambda item: item.date_bjt, reverse=True)
    for bundle in bundles:
        episode_dir = store.episode_dir(bundle.episode_id)
        needs_images = any(not section.image_url.startswith("images/") or not (episode_dir / section.image_url).exists() for section in bundle.reading.sections)
        if needs_images:
            resolve_story_images(bundle.category, bundle.story_set.articles, bundle.reading, episode_dir)
            store.save_bundle(bundle)
        target = config.SITE_DIR / bundle.category / bundle.episode_id; target.mkdir(parents=True, exist_ok=True)
        audio_source = episode_dir / bundle.podcast.full_audio_file if bundle.podcast.full_audio_file else None
        if audio_source and audio_source.exists():
            shutil.copy2(audio_source, target / "episode.mp3")
        published_audio = target / "episode.mp3"
        if not bundle.podcast.waveform_peaks and published_audio.exists():
            bundle.podcast.waveform_peaks = waveform_peaks(published_audio)
            store.save_bundle(bundle)
        image_source = episode_dir / "images"
        if image_source.exists():
            shutil.copytree(image_source, target / "images", dirs_exist_ok=True)
        sequence = list(reversed(by_category[bundle.category]))
        index = sequence.index(bundle)
        previous = sequence[index - 1] if index > 0 else None
        following = sequence[index + 1] if index + 1 < len(sequence) else None
        (target / "index.html").write_text(_episode_page(bundle, store.load_quality(bundle.episode_id), previous, following), encoding="utf-8")
    cards = []
    for slug, profile in config.CATEGORIES.items():
        items = by_category.get(slug, [])
        if not items:
            continue
        latest = items[0]
        report = store.load_quality(latest.episode_id)
        cover = latest.reading.sections[0].image_url if latest.reading.sections else ""
        recent = "".join(f'<a href="{slug}/{item.episode_id}/">{_e(item.date_bjt)} · {_e(item.podcast.title)}</a>' for item in items[1:4])
        cards.append(f'<article class="channel-card" style="--channel:{profile.color}"><img src="{slug}/{latest.episode_id}/{_e(cover)}" alt="{_e(latest.podcast.title)}"><div class="channel-meta"><span>{profile.name}</span><span>{latest.date_bjt} · {report.audio_duration_sec / 60:.0f} 分钟</span></div><h3>{_e(latest.podcast.title)}</h3><p>{_e(latest.podcast.description)}</p><div class="card-actions"><a class="primary-link" href="{slug}/{latest.episode_id}/">阅读并收听 →</a><a class="archive-link" href="{slug}/">全部{profile.name}节目</a></div><div class="recent">{recent}</div></article>')
    home = f'<main class="wrap"><section class="home-intro"><div class="eyebrow">科技 · 教育 · 运动</div><h1>伊恩每日</h1><p>把每天真正值得理解的事情，写成可以慢慢读的文章，也做成可以随时听的播客。</p></section><section class="channel-shelf"><h2>今日更新</h2><div class="today-grid">{"".join(cards)}</div></section></main>'
    (config.SITE_DIR / "index.html").write_text(_shell("伊恩每日", home), encoding="utf-8")
    for slug, profile in config.CATEGORIES.items():
        target = config.SITE_DIR / slug; target.mkdir(exist_ok=True)
        groups: dict[str, list[EpisodeBundle]] = defaultdict(list)
        for item in by_category.get(slug, []):
            groups[item.date_bjt[:7]].append(item)
        months = []
        for month, items in groups.items():
            rows = "".join(f'<a class="episode-row" href="{item.episode_id}/"><span>{_e(item.date_bjt)}</span><span>{round(item.podcast.total_duration_sec / 60)} 分钟</span><strong>{_e(item.podcast.title)}</strong></a>' for item in items)
            months.append(f'<section class="month"><h2>{_e(month)}</h2>{rows}</section>')
        body = f'<main class="wrap"><section class="category-head"><div class="eyebrow">伊恩每日</div><h1>{profile.name}</h1><p>{_e(profile.tone)}</p></section>{"".join(months)}</main>'
        (target / "index.html").write_text(_shell(f"{profile.name} · 伊恩每日", body, 1, slug), encoding="utf-8")
    return config.SITE_DIR
