import csv
import requests
import time
import os

# 从CSV读取单词并生成音频
def generate_audio_files(csv_file, start_id=None):
    # 创建audios文件夹（如果不存在）
    if not os.path.exists('audios'):
        os.makedirs('audios')
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row['word_diac']
            word_id = row['id']
            audio_path = os.path.join('audios', f"audio_{word_id}.mp3")
            
            # 如果指定了起始ID，跳过之前的
            if start_id and int(word_id) < start_id:
                continue
            
            # 检查文件是否已存在
            if os.path.exists(audio_path):
                print(f"跳过已存在的音频 - ID: {word_id}, 单词: {word}")
                continue
            
            # 使用Google TTS API
            url = f"http://translate.google.com/translate_tts?ie=UTF-8&q={word}&tl=ar&client=tw-ob"
            
            response = requests.get(url)
            if response.status_code == 200:
                with open(audio_path, 'wb') as audio:
                    audio.write(response.content)
                print(f"生成成功 - ID: {word_id}, 单词: {word}")
            else:
                print(f"生成失败 - ID: {word_id}, 单词: {word}")
            
            time.sleep(1)  # 避免请求过快

# 生成更新后的CSV（包含音频引用）
def create_anki_csv(csv_file, output_file):
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        with open(output_file, 'w', encoding='utf-8', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['word', 'word_diac', 'ipa', 'meaning_en', 'meaning_cn', 'audio'])
            
            for row in reader:
                writer.writerow([
                    row['word'],
                    row['word_diac'],
                    row['ipa'],
                    row['meaning_en'],
                    row['meaning_cn'],
                    f"[sound:audio_{row['id']}.mp3]"
                ])

# 使用 - 修改为你的文件名
csv_file = 'arabicWords-003.csv'
output_file = 'anki_ready.csv'

# 执行 - 正常模式（跳过已存在的）
print("开始生成音频（跳过已存在的）...")
generate_audio_files(csv_file)

# 如果想从特定ID开始生成，比如从ID 10开始：
# generate_audio_files(csv_file, start_id=10)

# create_anki_csv(csv_file, output_file)
print("完成！")