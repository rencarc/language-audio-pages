import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo


SITE_BASE = "https://rencarc.github.io/language-audio-pages"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
ROOT = Path(__file__).resolve().parents[1]
LESSONS = ROOT / "lessons"
DATA = ROOT / "data"
LESSONS.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

SWEDISH_TOPICS = [
    "Stress och hälsa", "Rutiner och vanor", "Familj och relationer", "Boende och grannar",
    "Fritid och återhämtning", "Arbetsliv och ansvar", "Studier och motivation", "Samarbete och konflikter",
    "Att söka jobb", "Kommunikation på jobbet", "Vård och hälsa", "Ekonomi och konsumtion",
    "Miljö och hållbarhet", "Regler och trygghet", "Integration och språk", "Sociala medier",
    "Barn och skola", "Jämställdhet", "Ensamhet och gemenskap", "Framtidsplaner",
    "Kultur och traditioner", "Nyheter och samhälle", "Resor och kollektivtrafik", "Mat och hälsa",
    "Digitalt liv", "Myndigheter och service", "Vänskap och nätverk", "Repetition med nya ord och uttryck",
]

CV_CONTEXT = """Zhen Xu targets AI Automation Engineer / Workflow Business Systems roles.
Experience: Insutex AI & Automation Intern using Copilot Studio, SharePoint, REST APIs, knowledge workflows, domain-specific AI agents.
Akavia AI Developer Intern using Azure AI Search, Hybrid RAG, Dataverse, Power Automate, Copilot Studio; two-stage quality gate with top-k semantic retrieval, reranker score delta filtering, and LLM validation.
Sustainable AI Solutions Full Stack Intern using OpenAI, RAG, Docker, Azure.
Projects: CAN bus intrusion detection with Python and Random Forest; GOAT Notes with Next.js, TypeScript, Supabase, OpenAI API.
Skills: AI workflow automation, Copilot Studio, RAG, semantic retrieval, embeddings, Azure OpenAI, Power Automate, Power Apps, Dataverse, SharePoint, Python, TypeScript, REST APIs, Docker, Azure, Information Security.
"""


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required secret/env: {name}")
    return value


def post_json(url, payload, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def model_text(prompt):
    api_key = require_env("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(api_key)}"
    data = post_json(url, {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7},
    })
    chunks = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    text = "\n".join(chunks).strip()
    if not text:
        raise ValueError("Gemini returned no text")
    return text


def send_push(title, content):
    post_json("https://www.pushplus.plus/send", {
        "token": require_env("PUSHPLUS_TOKEN"),
        "title": title,
        "content": content,
        "template": "markdown",
        "channel": "wechat",
    })


def extract_json(text):
    match = re.search(r"```json\s*(.*?)```", text, re.S)
    if match:
        text = match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found")
    return json.loads(text[start:end + 1])


def day(now):
    return now.strftime("%Y-%m-%d")


def load_used_terms():
    path = DATA / "used_swedish_terms.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"terms": []}


def save_used_terms(used):
    (DATA / "used_swedish_terms.json").write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")


def swedish_prompt(now):
    topic = SWEDISH_TOPICS[(now.toordinal() - dt.date(2026, 6, 14).toordinal()) % len(SWEDISH_TOPICS)]
    used = load_used_terms().get("terms", [])[-1200:]
    return f"""
Create today's Swedish learning content as strict JSON only.
Date: {day(now)}
Level: Svenska Grund 4 / light B1.
Topic: {topic}
Avoid these already-used target terms/phrases: {json.dumps(used, ensure_ascii=False)}

Schema:
{{
  "date": "...",
  "topic_sv": "...",
  "topic_cn": "...",
  "terms": [{{"term": "...", "cn": "...", "spoken_sentence": "...", "cn_sentence": "..."}}],
  "opinions": [{{"sv": "...", "cn": "..."}}],
  "listening": [{{"sv": "...", "cn": "..."}}]
}}

Rules:
- exactly 50 terms/phrases, no repeats or obvious variants from used list.
- each term has one natural spoken Swedish sentence and Chinese meaning.
- exactly 10 opinion sentences.
- listening has 12-16 independent sentences and does not repeat previous content.
- Chinese support is full sentence-by-sentence.
"""


def esc(value):
    return html.escape(str(value), quote=True)


def audio_button(key, label):
    return f"""<div class="audio">
  <button data-speech="{key}">{esc(label)}</button>
  <button class="stop">停止</button>
  <p class="status" id="status-{key}">1 倍速，分句朗读，句间停顿。</p>
</div>"""


def term_rows(items, start):
    rows = []
    for i, item in enumerate(items, start):
        speech = esc(f"{item['term']}. {item['spoken_sentence']}")
        rows.append(f"""<article class="item">
  <div class="speak-text" data-speech="{speech}"></div>
  <h3>{i}. {esc(item['term'])}</h3>
  <p><strong>中文：</strong>{esc(item['cn'])}</p>
  <p><strong>瑞典语口语句：</strong><span class="sv">{esc(item['spoken_sentence'])}</span></p>
  <p><strong>中文对照：</strong>{esc(item['cn_sentence'])}</p>
</article>""")
    return "\n".join(rows)


def sentence_rows(items):
    rows = []
    for i, item in enumerate(items, 1):
        rows.append(f"""<article class="item">
  <div class="speak-text" data-speech="{esc(item['sv'])}"></div>
  <p><strong>{i}. </strong><span class="sv">{esc(item['sv'])}</span></p>
  <p><strong>中文对照：</strong>{esc(item['cn'])}</p>
</article>""")
    return "\n".join(rows)


def swedish_html(data):
    terms = data["terms"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>瑞典语 Grund 4 - {esc(data['topic_sv'])}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8f6f0; color: #172326; }}
    main {{ max-width: 860px; margin: 0 auto; padding: 22px 16px 48px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; line-height: 1.2; }}
    h2 {{ font-size: 21px; margin: 30px 0 12px; color: #0b6470; }}
    h3 {{ font-size: 17px; margin: 0 0 8px; color: #17373b; }}
    p {{ font-size: 16px; line-height: 1.6; margin: 6px 0; }}
    .meta {{ color: #526164; font-size: 14px; }}
    .audio {{ border: 1px solid #d6cec1; background: #fffdf8; border-radius: 8px; padding: 14px; margin: 16px 0; }}
    .audio button {{ width: 100%; min-height: 52px; border: 0; border-radius: 8px; background: #0b6470; color: white; font-size: 17px; font-weight: 700; }}
    .audio button.stop {{ margin-top: 9px; background: #49585b; }}
    .item {{ border-top: 1px solid #ded7cb; padding: 13px 0; }}
    .sv {{ font-weight: 700; }}
    .status {{ color: #5d6668; font-size: 14px; }}
  </style>
</head>
<body>
  <main>
    <h1>今日瑞典语 Grund 4</h1>
    <p class="meta">推送日期：{esc(data['date'])}</p>
    <p class="meta">今日主题：{esc(data['topic_sv'])} / {esc(data['topic_cn'])}</p>
    <h2>一、50 个单词/短语 + 口语句</h2>
    <section id="terms1" data-audio-group="terms1">{audio_button("terms1", "播放音频 1：词汇 1-25")}{term_rows(terms[:25], 1)}</section>
    <section id="terms2" data-audio-group="terms2">{audio_button("terms2", "播放音频 2：词汇 26-50")}{term_rows(terms[25:], 26)}</section>
    <h2>二、今日观点表达：{esc(data['topic_sv'])}</h2>
    <section id="opinions" data-audio-group="opinions">{audio_button("opinions", "播放音频 3：观点表达")}{sentence_rows(data['opinions'])}</section>
    <h2>三、独立听力短文</h2>
    <section id="listening" data-audio-group="listening">{audio_button("listening", "播放音频 4：听力短文")}{sentence_rows(data['listening'])}</section>
  </main>
  <script>
    let stopped = false;
    let playSession = 0;
    const pauseMs = 850;
    function statusFor(key, text) {{ const el = document.getElementById("status-" + key); if (el) el.textContent = text; }}
    function pickVoice() {{
      const voices = window.speechSynthesis.getVoices();
      return voices.find(v => v.lang === "sv-SE") || voices.find(v => v.lang && v.lang.startsWith("sv")) || null;
    }}
    function speakOne(text, key, index, total, voice, session) {{
      return new Promise(resolve => {{
        if (session !== playSession || stopped) {{ resolve(); return; }}
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "sv-SE"; utterance.rate = 1.0; utterance.pitch = 1.0;
        if (voice) utterance.voice = voice;
        utterance.onstart = () => {{ if (session === playSession) statusFor(key, `正在播放 ${{index}} / ${{total}}`); }};
        utterance.onend = () => setTimeout(resolve, pauseMs);
        utterance.onerror = () => setTimeout(resolve, pauseMs);
        window.speechSynthesis.speak(utterance);
      }});
    }}
    async function play(key) {{
      playSession += 1;
      const session = playSession;
      stopped = false;
      window.speechSynthesis.cancel();
      const voice = pickVoice();
      const group = document.querySelector(`[data-audio-group="${{key}}"]`);
      const lines = group ? Array.from(group.querySelectorAll(".speak-text")).map(el => el.dataset.speech).filter(Boolean) : [];
      for (let i = 0; i < lines.length; i++) {{
        if (stopped || session !== playSession) break;
        await speakOne(lines[i], key, i + 1, lines.length, voice, session);
      }}
      if (session === playSession) statusFor(key, stopped ? "已停止。" : "播放完成，可以再次点击跟读。");
    }}
    document.querySelectorAll("button[data-speech]").forEach(button => button.addEventListener("click", () => play(button.dataset.speech)));
    document.querySelectorAll("button.stop").forEach(button => button.addEventListener("click", () => {{ playSession += 1; stopped = true; window.speechSynthesis.cancel(); }}));
    if (speechSynthesis.onvoiceschanged !== undefined) speechSynthesis.onvoiceschanged = () => pickVoice();
  </script>
</body>
</html>"""


def update_index(now, swedish_url):
    (ROOT / "index.html").write_text(f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Language Audio Pages</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 760px; margin: 0 auto; padding: 28px 18px;">
  <h1>Language Audio Pages</h1>
  <p>Latest update: {day(now)}</p>
  <p><a href="{swedish_url}">今日瑞典语 Grund 4</a></p>
</body>
</html>""", encoding="utf-8")


def swedish_push_markdown(data, audio_url):
    lines = [
        "## 今日瑞典语 Grund 4",
        "",
        f"推送日期：{data['date']}",
        f"主题：{data['topic_sv']} / {data['topic_cn']}",
        "",
        "### 一、50 个单词/短语 + 口语句",
        "",
        f"音频 1：词汇 1-25",
        f"{audio_url}#terms1",
    ]
    for i, item in enumerate(data["terms"][:25], 1):
        lines.extend([
            "",
            f"**{i}. {item['term']}**",
            f"中文：{item['cn']}",
            f"口语句：{item['spoken_sentence']}",
            f"中文对照：{item['cn_sentence']}",
        ])

    lines.extend([
        "",
        f"音频 2：词汇 26-50",
        f"{audio_url}#terms2",
    ])
    for i, item in enumerate(data["terms"][25:], 26):
        lines.extend([
            "",
            f"**{i}. {item['term']}**",
            f"中文：{item['cn']}",
            f"口语句：{item['spoken_sentence']}",
            f"中文对照：{item['cn_sentence']}",
        ])

    lines.extend(["", "### 二、今日观点表达"])
    lines.extend([
        "",
        "音频 3：观点表达",
        f"{audio_url}#opinions",
    ])
    for i, item in enumerate(data["opinions"], 1):
        lines.extend([
            "",
            f"**{i}. {item['sv']}**",
            f"中文对照：{item['cn']}",
        ])

    lines.extend(["", "### 三、独立听力短文"])
    lines.extend([
        "",
        "音频 4：听力短文",
        f"{audio_url}#listening",
    ])
    for i, item in enumerate(data["listening"], 1):
        lines.extend([
            "",
            f"**{i}. {item['sv']}**",
            f"中文对照：{item['cn']}",
        ])

    lines.extend([
        "",
        "---",
        "如果微信内暂时无法打开音频入口，不影响上面的正文学习。",
    ])
    return "\n".join(lines)


def push_swedish(now):
    data = extract_json(model_text(swedish_prompt(now)))
    if len(data.get("terms", [])) != 50:
        raise ValueError("Swedish content must contain exactly 50 terms")
    filename = f"{day(now)}-sv-grund4.html"
    (LESSONS / filename).write_text(swedish_html(data), encoding="utf-8")
    used = load_used_terms()
    used["terms"] = list(dict.fromkeys(used.get("terms", []) + [item["term"] for item in data["terms"]]))[-1600:]
    save_used_terms(used)
    url = f"{SITE_BASE}/lessons/{filename}"
    update_index(now, url)
    send_push(f"今日瑞典语 Grund 4：{data['topic_sv']}", swedish_push_markdown(data, url))


def google_news(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            root = ET.fromstring(resp.read())
        return [{"title": item.findtext("title") or "", "pubDate": item.findtext("pubDate") or ""} for item in root.findall(".//item")[:8]]
    except Exception:
        return []


def english_prompt(now):
    news = []
    for q in ["enterprise AI agents workflow automation", "Microsoft Copilot Studio Azure AI Search RAG", "AI automation job market enterprise AI security"]:
        news.extend(google_news(q))
    return f"""
Create today's English-first AI interview briefing for Zhen Xu.
Date: {day(now)}
CV context:
{CV_CONTEXT}
Recent news candidates:
{json.dumps(news[:18], ensure_ascii=False)}

Rules:
- English 80%, Chinese 20%. No full Chinese translation.
- No links. No fake grammar correction.
- Put AI career news first.
- Include at least 3 news items. If candidates are weak, discuss broader current trends without inventing specific company announcements.
- Then one combined Interview & CV Drill section.

Markdown structure:
推送日期: ...
Target direction: ...

## 1. Daily AI Career News
For each of 3 items:
- English headline
- English summary, 3-5 sentences
- Interview talking point, one ready-to-say paragraph
- 中文短提示: keywords/core meaning only

## 2. Interview & CV Drill
- Interview question
- What the interviewer is testing, 2-3 bullets in English
- Ready-to-say answer, one structured answer in English
- Follow-up questions, 3 questions
- Short answer bullets, 2-3 English sentences for each follow-up
- 中文短提示: answer structure/keywords/cautions only
"""


def push_english(now):
    send_push(f"English AI Interview Brief：{day(now)}", model_text(english_prompt(now)))


def should_run(kind, now, force):
    if force:
        return True
    if now.hour != 4:
        return False
    if kind == "swedish":
        return now.minute < 20
    if kind == "english":
        return 10 <= now.minute < 30
    return False


def main():
    now = dt.datetime.now(STOCKHOLM)
    kind = os.getenv("PUSH_KIND", "both")
    force = os.getenv("FORCE_RUN", "false").lower() == "true"
    if not should_run(kind, now, force):
        print(f"Skipping {kind}; Stockholm time is {now.isoformat()}")
        return
    if kind in ("both", "swedish"):
        push_swedish(now)
    if kind in ("both", "english"):
        push_english(now)


if __name__ == "__main__":
    main()
