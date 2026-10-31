import os
import time
from config import CHARACTERS,ASSET_BASE,DELAY,FAILED_FILE,MIN_VOICE_LEN
from tools import safe_filename,downloader,save_failed



def character_voice_scraper(session,character_data,character_id,
                            log=print,stop_event=None,on_progress=None):
    sets=character_data["sets"][character_data["servers"]["jp"]]
    voices=sets[character_id]
    save_dir = CHARACTERS.get(character_id, {}).get("short", character_id)
    os.makedirs(save_dir, exist_ok=True)
    ok = skip = fail = 0
    failed=[]
    total=len(voices)

    for i,voice in enumerate(voices,1):
        if stop_event is not None and stop_event.is_set():
            log("已收到停止信号，中止")
            break
        if on_progress:
            on_progress(i-1,total)

        voice_file_path=voice["sound"]
        jp_text=character_data["texts"][voice["text"]]["japanese"]
        if len(jp_text)>=MIN_VOICE_LEN:
            download_link=f"{ASSET_BASE}/{voice_file_path}.m4a"

            
            filename = safe_filename(jp_text) + ".wav"
            save_path=os.path.join(save_dir,filename)
            download_result=downloader(session,download_link,save_path)
            
            if download_result=="ok":
                ok+=1
            elif download_result=="skip":
                skip+=1
            else:
                fail+=1
                failed.append({
                    "url": download_link,
                    "path": save_path,
                    "voice": jp_text,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
            log(f"[{i}/{len(voices)}] in character voices {'OK' if download_result == 'ok' else download_result}")
        else:
            skip+=1
            log(f"[{i}/{len(voices)}] in character voices 'skip'")
        time.sleep(DELAY)
    if on_progress:
        on_progress(total,total)
    log(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}")
    save_failed(failed)
    log(f"本次共失败 {len(failed)} 个，已写入 {FAILED_FILE}")