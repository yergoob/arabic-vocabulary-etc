// 阿拉伯语单词听播系统
let words = []
let queue = []
let currentIndex = 0
let isAutoPlaying = false
let autoTimer = null
let currentAudio = null
let isPlayingAudio = false
// 新增：随机音色相关变量
let isRandomVoice = false // 是否开启随机音色
const voiceList = ['google_TTS', 'fastpitch', 'tacotron2', 'xtts_f2'] // 所有音色列表

// 新增：移动端音频相关
let audioContext = null
let isAudioInitialized = false

// 新增：音频预加载相关
let audioCache = new Map() // 缓存已加载的音频
let preloadQueue = [] // 预加载队列
let isPreloading = false // 是否正在预加载
let preloadSize = 5 // 预加载数量（只向前预加载3-5个单词）

// 新增：获取音频路径
function getAudioPath(wordId, voiceType) {
  if (voiceType === 'google_TTS') {
    return `audios/${voiceType}/audio_${wordId}.mp3`
  } else {
    return `audios/${voiceType}/${wordId}.wav`
  }
}

// 新增：预加载音频
async function preloadAudio(wordId, voiceType) {
  const audioPath = getAudioPath(wordId, voiceType)
  const cacheKey = `${voiceType}_${wordId}`
  
  // 如果已经在缓存中，直接返回
  if (audioCache.has(cacheKey)) {
    return audioCache.get(cacheKey)
  }
  
  try {
    console.log(`开始预加载音频: ${audioPath}`)
    const audio = new Audio()
    audio.preload = 'auto'
    
    // 设置src开始加载
    audio.src = audioPath
    
    // 等待音频加载完成
    await new Promise((resolve, reject) => {
      audio.addEventListener('canplaythrough', () => {
        console.log(`音频预加载完成: ${audioPath}`)
        audioCache.set(cacheKey, audio)
        resolve(audio)
      }, { once: true })
      
      audio.addEventListener('error', (e) => {
        console.warn(`音频预加载失败: ${audioPath}`, e)
        reject(e)
      }, { once: true })
      
      // 设置超时
      setTimeout(() => {
        console.log(`音频预加载超时: ${audioPath}`)
        // 即使超时也缓存，可能部分加载
        audioCache.set(cacheKey, audio)
        resolve(audio)
      }, 5000) // 5秒超时
    })
    
    return audio
  } catch (error) {
    console.warn(`预加载音频失败: ${audioPath}`, error)
    // 创建空的音频对象作为降级
    const fallbackAudio = new Audio()
    audioCache.set(cacheKey, fallbackAudio)
    return fallbackAudio
  }
}

// 新增：智能预加载 - 只向前预加载3-5个单词
async function smartPreload() {
  if (isPreloading || queue.length === 0) return
  
  isPreloading = true
  
  // 只向前预加载（不向后预加载已经播放过的单词）
  const startIdx = currentIndex + 1 // 从下一个单词开始
  const endIdx = Math.min(queue.length - 1, currentIndex + preloadSize) // 向前预加载3-5个
  
  if (startIdx > endIdx) {
    // 没有需要预加载的单词（可能是最后一个单词）
    isPreloading = false
    return
  }
  
  console.log(`开始向前预加载，范围: ${startIdx}-${endIdx}，当前索引: ${currentIndex}`)
  
  // 创建预加载任务
  const preloadTasks = []
  for (let i = startIdx; i <= endIdx; i++) {
    const word = queue[i]
    if (word) {
      // 为每个单词获取正确的音色（在随机音色模式下，每个单词有固定的音色）
      const voiceType = getCurrentVoice(word.id)
      preloadTasks.push(preloadAudio(word.id, voiceType))
    }
  }
  
  // 并行预加载，但限制并发数
  const concurrentLimit = 2 // 同时预加载2个，避免网络拥堵
  for (let i = 0; i < preloadTasks.length; i += concurrentLimit) {
    const batch = preloadTasks.slice(i, i + concurrentLimit)
    try {
      await Promise.allSettled(batch)
    } catch (error) {
      console.warn('批量预加载失败:', error)
    }
    
    // 短暂延迟，避免阻塞
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  
  console.log(`向前预加载完成，缓存大小: ${audioCache.size}`)
  isPreloading = false
}

// 新增：简化缓存管理 - 不自动清理，让浏览器管理
function cleanupAudioCache() {
  // 简化版本：只记录缓存大小，不自动清理
  // 让浏览器自己管理缓存，避免复杂的清理逻辑
  console.log(`当前音频缓存大小: ${audioCache.size}`)
  
  // 可选：只在调试时显示详细信息
  if (audioCache.size > 50) {
    console.log('缓存较多，浏览器会自动管理内存')
  }
}

// 新增：初始化音频上下文（需要在用户手势后调用）
function initAudio() {
  if (isAudioInitialized) return true
  
  try {
    // 创建音频上下文
    audioContext = new (window.AudioContext || window.webkitAudioContext)()
    
    // 创建一个空的音频源来激活上下文
    const silentSource = audioContext.createOscillator()
    silentSource.frequency.value = 1
    silentSource.connect(audioContext.destination)
    silentSource.start()
    silentSource.stop(audioContext.currentTime + 0.001)
    
    // 恢复/启动音频上下文
    if (audioContext.state === 'suspended') {
      audioContext.resume().then(() => {
        console.log('音频上下文已恢复')
        isAudioInitialized = true
      })
    } else {
      isAudioInitialized = true
    }
    
    console.log('音频初始化成功，状态:', audioContext.state)
    return true
  } catch (e) {
    console.warn('音频初始化失败，可能不支持Web Audio API', e)
    // 降级处理：仍然尝试播放
    isAudioInitialized = true
    return false
  }
}

// 新增：检查音频是否可以播放
function canPlayAudio() {
  if (!isAudioInitialized) {
    console.log('音频未初始化，尝试初始化')
    return initAudio()
  }
  
  // 检查AudioContext状态
  if (audioContext && audioContext.state === 'suspended') {
    console.log('音频上下文被挂起，尝试恢复')
    audioContext.resume()
    return false // 需要等待恢复
  }
  
  return true
}

// 加载单词数据 - 仅保留真实加载逻辑，移除所有模拟测试数据
fetch('words.json')
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response.json()
  })
  .then(data => {
    words = data
    console.log(`加载了 ${words.length} 个单词`)
    
    if (words.length > 0) {
      const firstId = parseInt(words[0].id)
      const lastId = parseInt(words[words.length-1].id)
      console.log(`ID范围: ${firstId} - ${lastId}`)
    }
  })
  .catch(error => {
    console.error('加载失败:', error)
    // 彻底移除：所有模拟测试数据，加载失败仅打印日志，卡片保持空白
  })

// 初始化页面 - 完全还原原始逻辑，无自动加载、无默认值
document.addEventListener('DOMContentLoaded', () => {
  console.log('页面加载完成，初始化随机音色按钮')
  
  // 移除：endId默认值5，输入框保持空白
  const list = ['showArabic','showIpa','showCn','showEn','showId','showCefr','showFreq']
  list.forEach(id => {
    const el = document.getElementById(id)
    if (el) el.addEventListener('change', showCard)
  })
  
  const rangeSelect = document.getElementById('rangeSelect')
  if (rangeSelect) rangeSelect.addEventListener('change', updateRangeFromSelect)
  
  // 初始化随机音色按钮状态 - 原始逻辑保留
  const randomBtn = document.getElementById('randomVoiceBtn')
  if (randomBtn) {
    randomBtn.textContent = '随机音色'
    randomBtn.classList.remove('active')
    console.log('随机音色按钮初始化完成')
  }
  
  // 为音色选择下拉框添加事件监听器
  const voiceSelect = document.getElementById('voice')
  if (voiceSelect) {
    voiceSelect.addEventListener('change', () => {
      console.log('音色切换，清理缓存并重新预加载')
      cleanupAudioCache()
      setTimeout(() => {
        smartPreload().catch(console.error)
      }, 300)
    })
  }
  
  // 取消自动勾选autoPlay - 原始逻辑保留（避免页面加载触发自动播放）
  const autoPlayCheckbox = document.getElementById('autoPlay')
  if (autoPlayCheckbox) {
    autoPlayCheckbox.checked = false
  }
  
  // 新增：监听用户首次交互来初始化音频
  const initAudioOnUserGesture = () => {
    console.log('检测到用户手势，初始化音频')
    initAudio()
    // 移除事件监听，只初始化一次
    document.removeEventListener('click', initAudioOnUserGesture)
    document.removeEventListener('touchstart', initAudioOnUserGesture)
    document.removeEventListener('keydown', initAudioOnUserGesture)
  }
  
  document.addEventListener('click', initAudioOnUserGesture)
  document.addEventListener('touchstart', initAudioOnUserGesture)
  document.addEventListener('keydown', initAudioOnUserGesture)
  
  // 彻底移除：自动生成范围、自动设置startId/endId、自动调用startRange
  // 移除：setTimeout自动加载逻辑，必须手动操作
})

function startRange() {
  const startInput = document.getElementById('startId')
  const endInput = document.getElementById('endId')
  
  if (!startInput || !endInput) return
  
  const start = parseInt(startInput.value)
  const end = parseInt(endInput.value)
  
  if (isNaN(start) || isNaN(end)) {
    alert('请输入有效的数字')
    return
  }
  
  if (start > end) {
    alert('开始ID不能大于结束ID')
    return
  }
  
  if (words.length === 0) {
    alert('单词数据尚未加载完成')
    return
  }
  
  // 过滤逻辑 - 原始逻辑保留，仅修复语法错
  queue = words.filter(word => {
    const wordId = parseInt(word.id)
    return wordId >= start && wordId <= end
  })
  
  console.log(`范围 ${start}-${end}: 找到 ${queue.length} 个单词`, queue)
  
  if (queue.length === 0) {
    alert(`ID ${start} 到 ${end} 范围内没有找到单词`)
    if (words.length > 0) {
      const firstId = parseInt(words[0].id)
      const lastId = parseInt(words[words.length-1].id)
      alert(`实际数据范围: ${firstId} - ${lastId}`)
    }
    return
  }
  
  currentIndex = 0
  showCard() // 手动点击后才刷新卡片，原始逻辑
  
  // 开始预加载第一个单词附近的音频
  setTimeout(() => {
    smartPreload().catch(console.error)
  }, 500)
  
  // 原始逻辑：勾选autoPlay则启动，无额外检查
  const autoPlay = document.getElementById('autoPlay')
  if (autoPlay && autoPlay.checked) {
    startAutoPlay()
  }
}

// showCard - 原始逻辑保留，无额外修改
function showCard() {
  if (queue.length === 0) {
    document.getElementById('currentCard').textContent = '当前: 0/0'
    return
  }
  
  const word = queue[currentIndex]
  if (!word) return
  
  const arabicEl = document.getElementById('arabic')
  const ipaEl = document.getElementById('ipa')
  const cnEl = document.getElementById('cn')
  const enEl = document.getElementById('en')
  const metaEl = document.getElementById('meta')
  const currentCardEl = document.getElementById('currentCard')
  
  const showArabic = document.getElementById('showArabic').checked
  const showIpa = document.getElementById('showIpa').checked
  const showCn = document.getElementById('showCn').checked
  const showEn = document.getElementById('showEn').checked
  const showId = document.getElementById('showId').checked
  const showCefr = document.getElementById('showCefr').checked
  const showFreq = document.getElementById('showFreq').checked
  
  arabicEl.textContent = word.word_diac || word.word || ''
  arabicEl.style.display = showArabic ? 'block' : 'none'
  
  ipaEl.textContent = word.ipa || ''
  ipaEl.style.display = showIpa ? 'block' : 'none'
  
  cnEl.textContent = word.meaning_cn || ''
  cnEl.style.display = showCn ? 'block' : 'none'
  
  enEl.textContent = word.meaning_en || ''
  enEl.style.display = showEn ? 'block' : 'none'
  
  const metaParts = []
  if (showId) metaParts.push(`#${word.id}`)
  if (showCefr && word.cefr) metaParts.push(word.cefr)
  if (showFreq && word.freq) metaParts.push(`freq:${word.freq.toFixed(2)}`)
  metaEl.textContent = metaParts.join(' ')
  metaEl.style.display = metaParts.length > 0 ? 'block' : 'none'
  
  currentCardEl.textContent = `当前: ${currentIndex + 1}/${queue.length}`
  
  console.log(`展示单词ID: ${word.id}`, word)
}

// 停止音频 - 完全原始逻辑
function stopCurrentAudio() {
  if (sharedAudio) {
    sharedAudio.pause()
    sharedAudio.currentTime = 0
  }
  isPlayingAudio = false
}

// nextCard - 增强版，支持预加载
function nextCard() {
  if (queue.length === 0) return
  
  stopCurrentAudio();

  if (autoTimer) {
    clearTimeout(autoTimer)
    autoTimer = null
  }
  
  currentIndex++
  if (currentIndex >= queue.length) {
    currentIndex = 0
    if (isAutoPlaying) {
      stopAutoPlay()
      return
    }
  }
  
  showCard()
  
  // 切换卡片后触发预加载
  setTimeout(() => {
    smartPreload().catch(console.error)
  }, 100)
  
  if (isAutoPlaying) {
    playAudio().catch(e => {
      console.error('自动播放失败:', e)
      stopAutoPlay()
    })
  }
}

// prevCard - 增强版，支持预加载
function prevCard() {
  if (queue.length === 0) return
  
  stopCurrentAudio();
  
  if (autoTimer) {
    clearTimeout(autoTimer)
    autoTimer = null
  }
  
  currentIndex--
  if (currentIndex < 0) {
    currentIndex = queue.length - 1
  }
  
  showCard()
  
  // 切换卡片后触发预加载
  setTimeout(() => {
    smartPreload().catch(console.error)
  }, 100)
  
  if (isAutoPlaying) {
    playAudio().catch(e => {
      console.error('自动播放失败:', e)
      stopAutoPlay()
    })
  }
}

// 随机音色 - 增强版，切换时清理缓存并重新预加载
function toggleRandomVoice() {
  isRandomVoice = !isRandomVoice
  const btn = document.getElementById('randomVoiceBtn')
  if (btn) {
    if (isRandomVoice) {
      btn.classList.add('active')
      btn.textContent = '随机音色√'
    } else {
      btn.classList.remove('active')
      btn.textContent = '随机音色'
    }
  }
  console.log(`随机音色功能已${isRandomVoice ? '开启' : '关闭'}，当前状态:`, isRandomVoice)
  
  // 音色切换时清理缓存并重新预加载
  cleanupAudioCache()
  setTimeout(() => {
    smartPreload().catch(console.error)
  }, 300)
}

// 获取音色 - 增强版：在随机音色模式下为每个单词ID返回固定的随机音色
function getCurrentVoice(wordId = null) {
  let voiceType
  
  if (isRandomVoice) {
    // 如果有传入wordId，为这个ID生成固定的随机音色
    if (wordId !== null) {
      // 使用简单的哈希函数为每个wordId生成固定的随机索引
      const hash = Math.abs(wordId.toString().split('').reduce((acc, char) => {
        return ((acc << 5) - acc) + char.charCodeAt(0)
      }, 0))
      const randomIndex = hash % voiceList.length
      voiceType = voiceList[randomIndex]
      console.log(`为单词ID ${wordId} 分配固定音色: ${voiceType} (哈希索引: ${randomIndex})`)
    } else {
      // 如果没有传入wordId，返回当前单词的随机音色
      const currentWord = queue[currentIndex]
      if (currentWord) {
        const hash = Math.abs(currentWord.id.toString().split('').reduce((acc, char) => {
          return ((acc << 5) - acc) + char.charCodeAt(0)
        }, 0))
        const randomIndex = hash % voiceList.length
        voiceType = voiceList[randomIndex]
        console.log(`为当前单词ID ${currentWord.id} 分配固定音色: ${voiceType} (哈希索引: ${randomIndex})`)
      } else {
        // 如果没有当前单词，随机选择一个
        const randomIndex = Math.floor(Math.random() * voiceList.length)
        voiceType = voiceList[randomIndex]
        console.log(`随机选择音色: ${voiceType} (索引: ${randomIndex})`)
      }
    }
  } else {
    const voiceSelect = document.getElementById('voice')
    voiceType = voiceSelect ? voiceSelect.value : 'google_TTS'
    console.log(`使用手动选择音色: ${voiceType}`)
  }
  return voiceType
}

// 新增：带用户手势检查的播放函数
async function playAudioWithGestureCheck() {
  // 检查音频是否已初始化
  if (!isAudioInitialized) {
    console.log('音频未初始化，尝试初始化')
    initAudio()
    // 给一点时间初始化
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  
  // 如果是移动端且音频上下文被挂起，尝试恢复
  if (audioContext && audioContext.state === 'suspended') {
    try {
      await audioContext.resume()
      console.log('音频上下文已恢复')
    } catch (e) {
      console.warn('无法恢复音频上下文', e)
    }
  }
  
  // 调用原始播放函数
  return playAudio()
}

// 播放音频 
// 全局单一 audio 实例 - 按照方案一实现
let sharedAudio = new Audio()
sharedAudio.preload = 'auto'
let isAudioPlaying = false
let currentRepeatCount = 0
let currentRepeatIndex = 0

// 播放音频（移动端安全版，按照方案一重构）
async function playAudio() {
  const word = queue[currentIndex]
  if (!word) return

  // 停止当前播放
  if (isAudioPlaying) {
    sharedAudio.pause()
    sharedAudio.currentTime = 0
    isAudioPlaying = false
  }

  const repeatEl = document.getElementById('repeat')
  const repeatCount = repeatEl ? parseInt(repeatEl.value) || 1 : 1
  currentRepeatCount = repeatCount
  currentRepeatIndex = 0

  const voiceType = getCurrentVoice()
  const cacheKey = `${voiceType}_${word.id}`

  // 尝试从缓存获取预加载的音频
  let audioToPlay = sharedAudio
  if (audioCache.has(cacheKey)) {
    const cachedAudio = audioCache.get(cacheKey)
    if (cachedAudio && cachedAudio.src) {
      console.log(`使用缓存的音频: ${cacheKey}`)
      audioToPlay = cachedAudio
    }
  }

  // 设置音频源
  const audioPath = getAudioPath(word.id, voiceType)
  if (audioToPlay.src !== audioPath) {
    audioToPlay.src = audioPath
  }

  isAudioPlaying = true
  isPlayingAudio = true

  try {
    await audioToPlay.play()
    console.log(`开始播放: ${word.id}, 重复次数: ${repeatCount}`)
    
    // 设置播放结束监听器 - 按照方案一模式
    audioToPlay.onended = () => {
      currentRepeatIndex++
      
      if (currentRepeatIndex < currentRepeatCount) {
        // 重复播放当前单词
        console.log(`重复播放第 ${currentRepeatIndex + 1} 次`)
        audioToPlay.currentTime = 0
        audioToPlay.play().catch(e => {
          console.error('重复播放失败:', e)
          handlePlaybackEnd()
        })
      } else {
        // 当前单词播放完成
        handlePlaybackEnd()
      }
    }
    
    return Promise.resolve()
  } catch (err) {
    console.error('播放失败:', err)
    isAudioPlaying = false
    isPlayingAudio = false
    
    // 如果是移动端自动播放限制
    if (err.name === 'NotAllowedError') {
      alert('请先点击屏幕任意位置激活音频播放功能')
      // 停止自动播放
      if (isAutoPlaying) {
        stopAutoPlay()
      }
    }
    
    return Promise.reject(err)
  }
}

// 处理播放结束
function handlePlaybackEnd() {
  isAudioPlaying = false
  isPlayingAudio = false
  
  // 触发智能预加载
  setTimeout(() => {
    smartPreload().catch(console.error)
  }, 100)
  
  // 如果是自动播放模式，播放下一个单词
  if (isAutoPlaying) {
    // 不使用setTimeout，直接播放下一个
    setTimeout(() => {
      playNextInAutoPlay()
    }, 0)
  }
}

// 自动播放模式下播放下一个单词（支持间隔时间）
function playNextInAutoPlay() {
  if (!isAutoPlaying || queue.length === 0) return
  
  // 获取间隔时间
  const intervalEl = document.getElementById('interval')
  const intervalSeconds = intervalEl ? parseInt(intervalEl.value) || 0 : 0
  
  if (intervalSeconds > 0) {
    // 如果有间隔时间，使用setTimeout
    if (autoTimer) clearTimeout(autoTimer)
    autoTimer = setTimeout(() => {
      playNextWordInAutoPlay()
    }, intervalSeconds * 1000)
  } else {
    // 没有间隔时间，直接播放下一个
    playNextWordInAutoPlay()
  }
}

// 实际播放下一个单词
function playNextWordInAutoPlay() {
  if (!isAutoPlaying || queue.length === 0) return
  
  // 移动到下一个单词
  currentIndex++
  if (currentIndex >= queue.length) {
    currentIndex = 0
    // 如果循环完成，停止自动播放
    stopAutoPlay()
    return
  }
  
  // 显示卡片
  showCard()
  
  // 播放音频
  playAudio().catch(e => {
    console.error('自动播放失败:', e)
    // 如果播放失败，停止自动播放
    stopAutoPlay()
  })
}

// 开始自动播放 - 按照方案一重构
function startAutoPlay() {
  if (isAutoPlaying) return
  if (queue.length === 0) {
    alert('请先选择单词范围')
    return
  }
  
  // 先尝试初始化音频
  if (!isAudioInitialized) {
    initAudio()
  }
  
  isAutoPlaying = true
  const playBtn = document.getElementById('playBtn')
  if (playBtn) playBtn.textContent = '停止'
  const autoPlay = document.getElementById('autoPlay')
  if (autoPlay) autoPlay.checked = true

  // 开始播放当前单词
  playAudio().catch(err => {
    console.error('自动播放失败:', err)
    // 如果失败，关闭自动播放
    stopAutoPlay()
  })
}

// 停止自动播放 - 完全原始逻辑
function stopAutoPlay() {
  isAutoPlaying = false
  stopCurrentAudio()
  const playBtn = document.getElementById('playBtn')
  if (playBtn) playBtn.textContent = '自动播放'
  const autoPlay = document.getElementById('autoPlay')
  if (autoPlay) autoPlay.checked = false
  if (autoTimer) {
    clearTimeout(autoTimer)
    autoTimer = null
  }
}

// 切换自动播放 - 完全原始逻辑
function toggleAutoPlay() {
  if (isAutoPlaying) {
    stopAutoPlay()
  } else {
    startAutoPlay()
  }
}

// 生成范围 - 原始逻辑保留
function generateRanges() {
  const dailyPlan = parseInt(document.getElementById('dailyPlan').value)
  const cycleDays = parseInt(document.getElementById('cycleDays').value)
  const baseStartId = parseInt(document.getElementById('baseStartId').value)
  
  if (isNaN(dailyPlan) || isNaN(cycleDays) || isNaN(baseStartId) || dailyPlan<=0 || cycleDays<=0 || baseStartId<=0) {
    alert('请输入有效的大于0的数字')
    return
  }
  
  const rangeSelect = document.getElementById('rangeSelect')
  while (rangeSelect.options.length > 1) rangeSelect.remove(1)
  
  for (let i = 0; i < cycleDays; i++) {
    const start = baseStartId + i * dailyPlan
    const end = start + dailyPlan - 1
    const opt = document.createElement('option')
    opt.value = `${start}-${end}`
    opt.textContent = `第${i+1}天: ${start}-${end}`
    rangeSelect.appendChild(opt)
  }
}

// 更新范围 - 原始逻辑保留
function updateRangeFromSelect() {
  const val = document.getElementById('rangeSelect').value
  if (!val) return
  const [s, e] = val.split('-').map(Number)
  if (!isNaN(s) && !isNaN(e)) {
    document.getElementById('startId').value = s
    document.getElementById('endId').value = e
  }
}

// 折叠控制面板 - 原始逻辑保留
function toggleControls() {
  const c = document.getElementById('controlsContent')
  const icon = document.querySelector('.collapse-icon')
  if (c && icon) {
    if (c.style.display === 'none') {
      c.style.display = 'block'
      icon.textContent = '▼'
    } else {
      c.style.display = 'none'
      icon.textContent = '▶'
    }
  }
}

// 新增：单词列表功能 - 直接读取开始ID和结束ID，不依赖queue
function showWordList() {
  // 检查单词数据是否已加载
  if (words.length === 0) {
    alert('单词数据尚未加载完成，请稍后再试');
    return;
  }
  
  // 直接读取开始ID和结束ID输入框的值
  const startInput = document.getElementById('startId');
  const endInput = document.getElementById('endId');
  
  if (!startInput || !endInput) {
    console.error('找不到开始ID或结束ID输入框');
    return;
  }
  
  const start = parseInt(startInput.value);
  const end = parseInt(endInput.value);
  
  if (isNaN(start) || isNaN(end)) {
    alert('请输入有效的开始ID和结束ID数字');
    return;
  }
  
  if (start > end) {
    alert('开始ID不能大于结束ID');
    return;
  }
  
  // 根据输入框的值过滤单词
  const filteredWords = words.filter(word => {
    const wordId = parseInt(word.id);
    return wordId >= start && wordId <= end;
  });
  
  console.log(`范围 ${start}-${end}: 找到 ${filteredWords.length} 个单词`);
  
  if (filteredWords.length === 0) {
    alert(`ID ${start} 到 ${end} 范围内没有找到单词`);
    if (words.length > 0) {
      const firstId = parseInt(words[0].id);
      const lastId = parseInt(words[words.length-1].id);
      alert(`实际数据范围: ${firstId} - ${lastId}`);
    }
    return;
  }
  
  const listBody = document.getElementById('wordListBody');
  if (!listBody) {
    console.error('找不到wordListBody元素');
    return;
  }
  
  listBody.innerHTML = '';
  
  // 限制显示数量，避免性能问题
  const maxDisplay = 1000;
  const displayWords = filteredWords.length > maxDisplay ? filteredWords.slice(0, maxDisplay) : filteredWords;
  
  if (filteredWords.length > maxDisplay) {
    console.log(`单词数量过多(${filteredWords.length})，仅显示前${maxDisplay}个`);
  }
  
  displayWords.forEach(word => {
    const row = document.createElement('tr');
    
    const idCell = document.createElement('td');
    idCell.textContent = word.id;
    row.appendChild(idCell);
    
    const arabicCell = document.createElement('td');
    arabicCell.textContent = word.word_diac || word.word;
    arabicCell.className = 'arabic-cell';
    row.appendChild(arabicCell);
    
    const cnCell = document.createElement('td');
    cnCell.textContent = word.meaning_cn || '';
    row.appendChild(cnCell);
    
    const enCell = document.createElement('td');
    enCell.textContent = word.meaning_en || '';
    row.appendChild(enCell);
    
    listBody.appendChild(row);
  });
  
  // 如果截断了显示，添加提示行
  if (filteredWords.length > maxDisplay) {
    const row = document.createElement('tr');
    const infoCell = document.createElement('td');
    infoCell.colSpan = 4;
    infoCell.style.textAlign = 'center';
    infoCell.style.color = '#fbbf24';
    infoCell.style.padding = '15px';
    infoCell.textContent = `... 还有 ${filteredWords.length - maxDisplay} 个单词未显示（共 ${filteredWords.length} 个）`;
    row.appendChild(infoCell);
    listBody.appendChild(row);
  }
  
  const modal = document.getElementById('wordListModal');
  if (modal) {
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
  } else {
    console.error('找不到wordListModal元素');
  }
}

// 新增：关闭单词列表
function closeWordList() {
  const modal = document.getElementById('wordListModal');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
  }
}

// 新增：点击外部关闭列表
window.addEventListener('click', function(event) {
  const modal = document.getElementById('wordListModal');
  if (event.target === modal) {
    closeWordList();
  }
});

// 暴露全局函数 - 原始函数+新增列表函数
window.startRange = startRange
window.nextCard = nextCard
window.prevCard = prevCard
window.playAudio = playAudio
window.toggleAutoPlay = toggleAutoPlay
window.generateRanges = generateRanges
window.updateRangeFromSelect = updateRangeFromSelect
window.toggleControls = toggleControls
window.toggleRandomVoice = toggleRandomVoice
window.getCurrentVoice = getCurrentVoice
window.showWordList = showWordList
window.closeWordList = closeWordList