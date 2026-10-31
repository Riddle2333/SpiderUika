from story_scraper import story_scraper
from character_scraper import character_voice_scraper
from tools import audio_to_list,build_id_to_speaker,write_character_voice_json,make_session,fetch_character_data,setup_logging,load_failed
from config import FAILED_FILE,EXTRA_CHARACTERS


def main():
    logger,log_path=setup_logging()
    logger.info("="*40)
    
    session=make_session()
    character_data = fetch_character_data(session)
    write_character_voice_json(character_data)
    character_id=input("请输入角色id（编外角色输入0）：").strip()
    
    if character_id=="0":
        character_in_band=False
        character_id=input("请输入编外角色id：").strip()
        speaker_id=EXTRA_CHARACTERS.get(character_id,{}).get("speaker_id",character_id)
    else:
        character_in_band=True
        id_to_speaker_map = build_id_to_speaker()
        speaker_id=id_to_speaker_map[character_id]
    
    logger.info(f"角色 ID = {character_id}，日志 = {log_path}")

    last_failed=load_failed()
    if last_failed:
        logger.warning(f"上次有 {len(last_failed)} 个文件失败，详见 {FAILED_FILE}")

    story_scraper(session,character_id,speaker_id,character_in_band,log=logger.info)
    
    if character_in_band:
        character_voice_scraper(session,character_data,character_id,log=logger.info)

    audio_to_list(character_id, character_in_band=character_in_band, log=logger.info)

    logger.info("任务结束")
    
if __name__ == "__main__":
    main()