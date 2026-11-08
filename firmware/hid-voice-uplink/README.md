# HID 語音上傳，不是小智 WebSocket

裝置現在把 WAV 用 HTTPS PUT 到 ntfy，再等 webhook 或 ACK。那不是 Opus，也不是小智的 hello/listen。只加 `Device-Credential` 不會讓兩邊通。

隔離路徑改成：裝置把同一份單聲道 WAV（PCM16 或文件所述的 IMA ADPCM）POST 到自己的 `https://<私有主機>/xiaozhi/isolated/hid-voice`，帶 `Device-Id` 與 `Device-Credential`。伺服器只在隔離模式、憑據相符、而且本機模型已設定時接受，回傳 16 kHz PCM WAV。沒有憑據是 401。不是 WAV 是 415。網址若是 ntfy、tenclass 或 placeholder，裝置端政策直接拒絕，沒有退回舊 webhook。

這個交換已在雲端用本機 Vosk、Qwen 與 MeloTTS 跑過一句合成普通話。IMA 只對文件上的 256 位元組區塊做了往返，裝置上的 `ima_adpcm.c` 沒有在這次來源裡，所以還沒有用裝置編碼器的位元組比對。

雲端不能把整份 HID 韌體編成映像。要接到現有上傳點而不再呼叫 ntfy，還需要下面這些檔一次到齊，不是逐個再要：

- `main/app_audio.h`：取樣率、WAV 標頭長度、釋放緩衝，以及回覆音能不能直接播 PCM
- `main/app_tts.h`：現在的回覆是下載 URL；要知道有沒有播緩衝的函式
- `main/app_wifi.h`：連上之後才上傳，且不能印出密碼
- `main/hid_remote.h`：舊程式會連到它；隔離模式不能呼叫
- `main/app_mem.h`：`app_net.c` 已經呼叫 `app_mem_log`
- `main/ima_adpcm.c`：裝置實際的編碼器，用來核對 IMA 位元組

桌面壁紙與五張語音圖的 patch 維持不變。不要把 sanitize 過的 ntfy 位址當成可運行的設定。
