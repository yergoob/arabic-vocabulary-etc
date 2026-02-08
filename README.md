# arabic-vocabulary-etc
## 阿拉伯语单词

### 几年前的故事
之前背英文单词的时候，用过henry liang frm的一个方法，大致思路如何：
    1. 每日词量 200-400，
    2. 听语音背，3s一词，听3遍，读随意
    3. 早中晚各来一次，几千词语，7天一循环，三个月就差不多熟悉了
时间一久，词基本都熟悉了，想用在阿拉伯语方面

### 阿拉伯语词库生成步骤steps
**词汇**：通过这个网址[https://github.com/sandbach/arabic_vocabulary],我得到了原始阿拉伯语词汇，有词频，难度等，但是没有中文意思，所以，我通过**deepseek_enrich_words.py**生成中文意思，最终生成了新的词汇数据**arabicWords-003.csv**。
**语音**：语音我没有找到合适的方法生成，百度阿里都不支持tts阿拉伯语，googleTTS的注册不了，也无法哟个。我选择本地TTS去生成，先用这个[https://github.com/coqui-ai/TTS],生成的有错音且单个单词的时长有点长，它不适合做单个单词的TTS，它可以克隆声音，读长句子。这个[https://github.com/nipponjo/tts-arabic-pytorch]生成的还可以。不知道还会遇到更好的吗，或者其他人做的更好。
