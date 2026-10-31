import re
import requests
import os
import io
import time
import json
from pydub import AudioSegment
import logging
from config import WAV_SAMPLE_RATE,FLIGHT_PATTERN,VOICES_JSON_URL,USER_AGENT, TIMEOUT, RETRIES,VOICES_JSON,LOG_DIR,FAILED_FILE,CHARACTERS,DEFAULT_PREFIX,EXTRA_CHARACTERS

def build_id_to_speaker(character_voices_path=VOICES_JSON):
    with open(character_voices_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sets = data["sets"][data["servers"]["jp"]]

    mapping = {}
    for cid, voices in sets.items():
        parts = voices[0]["sound"].split("/")[-1].split("_")
        if len(parts) >= 2:
            mapping[cid] = f"adv_{parts[1].lower()}"

    return mapping

def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s

def safe_filename(name, max_len=100):
    name = re.sub(r'[\\/:*?"<>|]', "", name)   # 删掉 \ / : * ? " < > |
    name = name.strip().rstrip(".")             # 去首尾空格和结尾的点
    name = re.sub(r"\s+", " ", name)            # 换行/多空格压成一个空格
    return name[:max_len] or "untitled"         # 截断 + 兜底

def fetch_character_data(session):
    r = session.get(VOICES_JSON_URL, timeout=30)
    r.raise_for_status()
    character_data = r.json()
    return character_data

def write_character_voice_json(character_data, path=VOICES_JSON):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(character_data, f, ensure_ascii=False, indent=2)

def unwrap(v):
        if isinstance(v, list) and len(v) == 2 and v[0] in (0, 1):
            return unwrap(v[1])
        return v

def downloader(session, url, save_path, timeout=TIMEOUT, retries=RETRIES,sample_rate=WAV_SAMPLE_RATE):
    if os.path.exists(save_path) and os.path.getsize(save_path)>0:
        return "skip"

    parent=os.path.dirname(save_path)
    if parent:
        os.makedirs(parent,exist_ok=True)

    tmp_path=save_path+".part"

    for attempt in range(1,retries+1):
        try:
            resp=session.get(url,timeout=timeout)
            resp.raise_for_status()

            seg = AudioSegment.from_file(io.BytesIO(resp.content), format="m4a")
            seg = seg.set_channels(1)
            if sample_rate:
                seg = seg.set_frame_rate(sample_rate)
            seg.export(tmp_path, format="wav", codec="pcm_s16le")

            os.replace(tmp_path, save_path)
            return "ok"
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            if attempt<retries:
                time.sleep(2*attempt)
    return "fail"

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir,exist_ok=True)
    filename = os.path.join(log_dir, time.strftime("%Y%m%d_%H%M%S") + ".log")

    logger=logging.getLogger("spider")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt=logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",datefmt="%H:%M:%S")

    fh=logging.FileHandler(filename,encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch=logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger,filename

def load_failed(path=FAILED_FILE):
    if not os.path.exists(path):
        return []
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError,OSError):
        return []

def save_failed(items, path=FAILED_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)



def audio_to_list(character_id,root_dir=None,lang="ja",exts=(".wav",),
                  prefix_pattern=DEFAULT_PREFIX,output_path=None,character_in_band=True,log=print):
    if character_in_band:
        info = CHARACTERS.get(character_id)
    else:
        info = EXTRA_CHARACTERS.get(character_id)
    if info is None:
        log(f"未知角色 ID: {character_id}")
        return None

    speaker = info["short"]
    root = os.path.abspath(root_dir or f"./{speaker}")

    if not os.path.isdir(root):
        log(f"文件夹不存在: {root}")
        log("（提示：先跑一次下载，目录会自动创建）")
        return None

    entries = []
    empty = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in exts:
                continue

            full = os.path.join(dirpath, fn)
            if os.path.getsize(full) == 0:
                empty += 1
                continue

            text = stem
            if prefix_pattern:
                text = re.sub(prefix_pattern, "", text, count=1)
            if not text:
                text = stem


            entries.append((full, text))

    if not entries:
        log(f"{root} 里没找到 {exts[0]} 音频")
        return None

    if output_path is None:
        output_path = root.strip("\\/") + ".list" 

    with open(output_path, "w", encoding="utf-8") as f:
        for full, text in entries:
            f.write(f"{full}|{speaker}|{lang}|{text}\n")

    log(f"扫描: {root}")
    log(f"共 {len(entries)} 条"
        + (f" | 跳过空文件 {empty}" if empty else ""))
    log(f"已生成: {output_path}")
    return output_path

def decode_flight(raw_html):
    """把 Next.js 的 flight 负载拼成可读文本"""
    chunks = []
    for mt in re.finditer(FLIGHT_PATTERN, raw_html):
        try:
            chunks.append(json.loads('"' + mt.group(1) + '"'))
        except json.JSONDecodeError:
            continue
    return "\n".join(chunks)


def extract_json_object(text, key):
    """在 text 里找 "key":{...}，用花括号配对取出完整对象"""
    marker = f'"{key}":'
    idx = text.find(marker)
    if idx < 0:
        return None

    start = text.find("{", idx + len(marker))
    if start < 0:
        return None

    depth = 0
    in_str = False
    esc = False

    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue

        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def parse_story_page(raw_html):
    """从故事页提取 initialScript（失败返回 None）"""
    return extract_json_object(decode_flight(raw_html), "initialScript")


def parse_related_page(raw_html):
    """从 related 页提取故事 ID 列表"""
    text = decode_flight(raw_html)
    ids = re.findall(r'"advId":(\d+)', text)
    return sorted({int(x) for x in ids})