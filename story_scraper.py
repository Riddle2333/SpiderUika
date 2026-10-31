
import os
import time
from config import CHARACTERS,RELATED_URL,DELAY,STORY_URL,TIMEOUT,FAILED_FILE,MIN_VOICE_LEN,MULTI_SPEAKER_SEPS,EXTRA_CHARACTERS_STORIES,EXTRA_CHARACTERS
from tools import safe_filename, downloader, save_failed,parse_story_page, parse_related_page


def story_id_scraper(session,character_id,character_in_band):
    if character_in_band:
        related_link = RELATED_URL.format(cid=character_id)
        resp=session.get(related_link,timeout=TIMEOUT)
        resp.raise_for_status()
        ids = parse_related_page(resp.text)
    else:
        ids=EXTRA_CHARACTERS_STORIES.get(character_id,[])
    return sorted(int(id) for id in ids)

def story_scraper(session,character_id,speaker_id,character_in_band,
                  log=print,stop_event=None,on_progress=None):

    story_ids=story_id_scraper(session,character_id,character_in_band)
    total=len(story_ids)
    failed=[]
    for idx,story_id in enumerate(story_ids,1):
        if stop_event is not None and stop_event.is_set():
            log("已收到停止信号，中止")
            break
        if on_progress:
            on_progress(idx-1,total)

        resp=session.get(STORY_URL.format(sid=story_id),timeout=TIMEOUT)
        resp.raise_for_status()
        raw=resp.text
        
        data = parse_story_page(raw)
        if data is None:
            log(f"  story/{story_id} 解析失败，跳过")
            continue

        script = data
        lines = script["lines"]
        
        picked=[]
        for e in lines:
            if e.get("speakerId")!=speaker_id:
                continue

            speaker_name = e.get("speaker") or ""
            if any(sep in speaker_name for sep in MULTI_SPEAKER_SEPS):
                continue
            
            text =e.get("text") or ""
            if len(text) < MIN_VOICE_LEN:
                continue

            urls=[y for y in (e.get("voiceUrls")) or []]
            if not urls:
                continue
            picked.append({
                "text": e.get("text"),
                "url": urls[0],
                "index": e.get("index"),
                "kind": e.get("kind"),
            })
        if character_in_band:
            characters=CHARACTERS
        else:
            characters=EXTRA_CHARACTERS
        savedir=characters.get(character_id, {}).get("short", character_id)
        
        ok=skip=fail=0

        for i,item in enumerate(picked,1):
            if stop_event is not None and stop_event.is_set():
                log("已收到停止信号，中止")
                save_failed(failed)
                return

            filename=safe_filename(f"{speaker_id}_{item["index"]}_{item["text"]}")+".wav"
            kind_dir=os.path.join(savedir,item["kind"])
            os.makedirs(kind_dir,exist_ok=True)
            save_path=os.path.join(kind_dir,filename)
            download_result=downloader(session,item["url"],save_path)
            if download_result=="ok":
                ok+=1
            elif download_result=="skip":
                skip+=1
            else:
                fail+=1
                failed.append({
                    "url": item["url"],
                    "path": save_path,
                    "story": story_id,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
            log(f"[{i}/{len(picked)}] in character voices {'OK' if download_result == 'ok' else download_result}")
            time.sleep(DELAY)
        log(f"story/{story_id} 完成：成功 {ok} 跳过 {skip} 失败 {fail}")
        save_failed(failed)
        if on_progress:
            on_progress(idx,total)
    log(f"本次共失败 {len(failed)} 个，已写入 {FAILED_FILE}")
