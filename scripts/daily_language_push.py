import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import time
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
TOPIC_ANCHOR_DATE = dt.date(2026, 6, 21)

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


def post_json(url, payload, headers=None, retries=3):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"HTTP {exc.code} from {url}; retrying in {wait}s ({attempt + 1}/{retries})")
            time.sleep(wait)
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt == retries - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"Network error calling {url}; retrying in {wait}s ({attempt + 1}/{retries}): {exc}")
            time.sleep(wait)
    if last_error:
        raise last_error


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
    node_code = r"""
const https = require('https');

const payload = JSON.stringify({
  token: process.env.PUSHPLUS_TOKEN,
  title: process.env.PUSHPLUS_TITLE,
  content: process.env.PUSHPLUS_CONTENT,
  template: 'markdown',
  channel: 'wechat',
});

const req = https.request(
  'https://www.pushplus.plus/send',
  {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
    rejectUnauthorized: false,
  },
  res => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
      console.log('status=' + res.statusCode);
      console.log(data);
      if (res.statusCode < 200 || res.statusCode >= 300) process.exitCode = 1;
    });
  }
);

req.on('error', err => {
  console.error('error=' + err.message);
  process.exitCode = 1;
});

req.write(payload);
req.end();
"""
    node_exe = shutil.which("node") or r"C:\Users\79834\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    env = os.environ.copy()
    env["PUSHPLUS_TITLE"] = title
    env["PUSHPLUS_CONTENT"] = content
    result = subprocess.run(
        [node_exe, "-e", node_code],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PushPlus send failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def extract_json(text):
    match = re.search(r"```json\s*(.*?)```", text, re.S)
    if match:
        text = match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found")
    return json.loads(text[start:end + 1])


def validate_swedish_content(data, used, now):
    if data.get("date") != day(now):
        raise ValueError("date field does not match today")

    expected_topic = SWEDISH_TOPICS[(now.toordinal() - TOPIC_ANCHOR_DATE.toordinal()) % len(SWEDISH_TOPICS)]
    if data.get("topic_sv") != expected_topic:
        raise ValueError("topic does not match today's 28-day cycle")

    terms = data.get("terms", [])
    opinions = data.get("opinions", [])
    listening = data.get("listening", [])
    if len(terms) != 50:
        raise ValueError("must contain exactly 50 terms")
    if len(opinions) != 10:
        raise ValueError("must contain exactly 10 opinions")
    if not (12 <= len(listening) <= 16):
        raise ValueError("listening must contain 12-16 sentences")

    used_set = set(used)
    seen_terms = set()
    for item in terms:
        term = item.get("term", "").strip()
        if not term:
            raise ValueError("every term needs a phrase")
        if term in seen_terms:
            raise ValueError("terms repeat within the same day")
        if term in used_set:
            raise ValueError(f"term already used this month: {term}")
        seen_terms.add(term)
        if not item.get("cn") or not item.get("spoken_sentence") or not item.get("cn_sentence"):
            raise ValueError("each term needs Chinese support and a spoken sentence")

    for item in opinions:
        if not item.get("sv") or not item.get("cn"):
            raise ValueError("each opinion needs Swedish and Chinese")
    for item in listening:
        if not item.get("sv") or not item.get("cn"):
            raise ValueError("each listening sentence needs Swedish and Chinese")


def day(now):
    return now.strftime("%Y-%m-%d")


def load_used_terms():
    path = DATA / "used_swedish_terms.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"terms": []}


def save_used_terms(used):
    (DATA / "used_swedish_terms.json").write_text(json.dumps(used, ensure_ascii=False, indent=2), encoding="utf-8")


def swedish_prompt(now, used, previous_error=None):
    topic = SWEDISH_TOPICS[(now.toordinal() - TOPIC_ANCHOR_DATE.toordinal()) % len(SWEDISH_TOPICS)]
    prompt = f"""
Create today's Swedish learning content as strict JSON only.
Date: {day(now)}
Level: Svenska Grund 4 / lätt B1.
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
- Exactly 50 terms/phrases.
- Exactly 10 opinion sentences.
- Listening has 12-16 independent sentences.
- Do not repeat any used term or obvious variant.
- Each term must have one natural spoken Swedish sentence and one Chinese translation sentence.
- Each opinion and listening item must be a standalone Swedish sentence with Chinese support.
- The output must be valid JSON only.
"""
    if previous_error:
        prompt += f"\nPrevious validation error: {previous_error}\nPlease correct it.\n"
    return prompt


def esc(value):
    return html.escape(str(value), quote=True)


def audio_button(key, label):
    return f"""<div class="audio">
  <button data-speech="{key}">{esc(label)}</button>
  <button class="stop">停止</button>
  <p class="status" id="status-{key}">1 倍速，分句朗读，句间停顿约 850 毫秒。</p>
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
    .page-note {{ background: linear-gradient(135deg, #f1eadc, #fffdf8); border: 1px solid #e2d8c8; border-radius: 14px; padding: 14px 16px; margin: 18px 0 8px; }}
    .audio {{ border: 1px solid #d6cec1; background: #fffdf8; border-radius: 8px; padding: 14px; margin: 16px 0; }}
    .audio button {{ width: 100%; min-height: 52px; border: 0; border-radius: 8px; background: #0b6470; color: white; font-size: 17px; font-weight: 700; }}
    .audio button.stop {{ margin-top: 9px; background: #49585b; }}
    .item {{ border-top: 1px solid #ded7cb; padding: 13px 0; }}
    .item:first-child {{ border-top: 0; }}
    .sv {{ font-weight: 700; }}
    .status {{ color: #5d6668; font-size: 14px; }}
    code {{ background: #f0ece4; border-radius: 5px; padding: 0 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>今日瑞典语 Grund 4</h1>
    <p class="meta">推送日期：{esc(data['date'])}</p>
    <p class="meta">今日主题：{esc(data['topic_sv'])} / {esc(data['topic_cn'])}</p>
    <p class="meta">水平：Svenska Grund 4 / lätt B1</p>
    <div class="page-note">
      <p class="meta">音频采用逐句朗读，句间停顿约 850 毫秒；每个播放按钮只读取本 section 内的 <code>data-speech</code>。</p>
      <p class="meta">第二部分音频只读取观点表达 section，不能读取词汇或例句 section。</p>
    </div>

    <h2>一、50 个单词 / 短语 + 口语句</h2>
    <section id="terms1" data-audio-group="terms1">{audio_button("terms1", "播放音频 1：词汇 1-25")}{term_rows(terms[:25], 1)}</section>
    <section id="terms2" data-audio-group="terms2">{audio_button("terms2", "播放音频 2：词汇 26-50")}{term_rows(terms[25:], 26)}</section>

    <h2>二、围绕今日主题的观点表达</h2>
    <section id="opinions" data-audio-group="opinions">{audio_button("opinions", "播放音频 3：观点表达")}{sentence_rows(data['opinions'])}</section>

    <h2>三、独立听力短文</h2>
    <section id="listening" data-audio-group="listening">{audio_button("listening", "播放音频 4：听力短文")}{sentence_rows(data['listening'])}</section>
  </main>
  <script>
    let stopped = false;
    let playSession = 0;
    const pauseMs = 850;

    function statusFor(key, text) {{
      const el = document.getElementById("status-" + key);
      if (el) el.textContent = text;
    }}

    function pickVoice() {{
      const voices = window.speechSynthesis.getVoices();
      return voices.find(v => v.lang === "sv-SE") || voices.find(v => v.lang && v.lang.startsWith("sv")) || null;
    }}

    function speakOne(text, key, index, total, voice, session) {{
      return new Promise(resolve => {{
        if (session !== playSession || stopped) {{ resolve(); return; }}
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "sv-SE";
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        if (voice) utterance.voice = voice;
        utterance.onstart = () => {{ if (session === playSession) statusFor(key, `正在朗读 ${{index}} / ${{total}}`); }};
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
        "### 一、50 个单词 / 短语 + 口语句",
        "",
        "音频 1：词汇 1-25",
        f"{audio_url}#terms1",
    ]
    for i, item in enumerate(data["terms"][:25], 1):
        lines.extend([
            "",
            f"**{i}. {item['term']}**",
            f"中文：{item['cn']}",
            f"瑞典语口语句：{item['spoken_sentence']}",
            f"中文对照：{item['cn_sentence']}",
        ])

    lines.extend([
        "",
        "音频 2：词汇 26-50",
        f"{audio_url}#terms2",
    ])
    for i, item in enumerate(data["terms"][25:], 26):
        lines.extend([
            "",
            f"**{i}. {item['term']}**",
            f"中文：{item['cn']}",
            f"瑞典语口语句：{item['spoken_sentence']}",
            f"中文对照：{item['cn_sentence']}",
        ])

    lines.extend(["", "### 二、围绕今日主题的观点表达"])
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
    used = load_used_terms().get("terms", [])[-1200:]
    previous_error = None
    data = None
    for _ in range(3):
        data = extract_json(model_text(swedish_prompt(now, used, previous_error)))
        try:
            validate_swedish_content(data, used, now)
            break
        except ValueError as exc:
            previous_error = str(exc)
            data = None
    if data is None:
        raise ValueError(previous_error or "Swedish content validation failed")

    filename = f"{day(now)}-sv-grund4.html"
    (LESSONS / filename).write_text(swedish_html(data), encoding="utf-8")
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
    for q in [
        "enterprise AI agents workflow automation",
        "Microsoft Copilot Studio Azure AI Search RAG",
        "AI automation job market enterprise AI security",
        "Microsoft Copilot enterprise AI July 2026",
    ]:
        news.extend(google_news(q))
    return f"""
Create today's Chinese-first AI interview briefing for Zhen Xu.
Date: {day(now)}
CV context:
{CV_CONTEXT}
Recent news candidates:
{json.dumps(news[:18], ensure_ascii=False)}

Rules:
- Chinese 80%, English 20%. No full sentence-by-sentence translation.
- No links. No fake grammar correction.
- Put AI career news first.
- Include at least 3 news items from today or the last 7 days. If candidates are weak, discuss broader current trends without inventing specific company announcements.
- Then one combined Interview & CV Drill section.
- Add one small AI Tech Teaching section after the drill so the user learns one concrete concept each day.

Markdown structure:
推送日期: ...
目标岗位方向: ...

## 1. Daily AI Career News
For each of 3+ items:
- English headline
- English summary, 3-5 sentences, describing what happened, the trend, and what enterprises care about
- Interview talking point, one ready-to-say paragraph
- 中文短提示: keywords/core meaning only

## 2. Interview & CV Drill
- Interview question
- What the interviewer is testing, 2-3 bullets in English
- Ready-to-say answer, one structured answer in English
- Follow-up questions, 3 questions
- Short answer bullets, 2-3 English sentences for each follow-up
- 中文短提示: answer structure/keywords/cautions only

## 3. AI Tech Teaching
- Teach one concrete AI concept in simple Chinese
- Give one short English explanation
- Give one practical example related to Copilot Studio, RAG, Azure AI Search, Power Automate, SharePoint, Dataverse, API integration, or security
- Keep it concise and actionable
"""


def push_english(now):
    send_push(f"中文 AI 面试简报 - {day(now)}", model_text(english_prompt(now)))


def should_run(kind, now, force):
    if force:
        return True
    # Run whenever the workflow is invoked for the configured kind.
    # This avoids missing a daily push when the job starts later than planned.
    return kind in ("both", "swedish", "english")


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
