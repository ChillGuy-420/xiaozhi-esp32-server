# 尚未可燒錄

這個映像即使建置成功，也還沒有私人 CA、裝置憑據、OTA 位址或 Wi-Fi。嵌入的 `private_ca.pem` 只有 `UNPROVISIONED`。空的端點、空權杖、`tenclass.net` 與公共憑證包都會被拒絕。

現有啟動程式的二進位不在雲端。沒有讀取完整備份。啟動程式、NVS、eFuse 與整片清除都沒有寫入核准，所以這裡不提供燒錄指令。

分割表沿用已核對的讀回：nvs `0x9000`/`0x6000`，phy_init `0xf000`/`0x1000`，factory `0x10000`/`0x600000`，model `0x610000`/`0x400000`。沒有 otadata，因此關閉 rollback。快閃是 quad；PSRAM 沿用這塊板上游的 octal 8MB 設定，讀回沒有給 PSRAM 匯流排模式。

語音五張圖不在這個小智映像裡。它們屬於既有 HID 韌體的語音畫面，而且 `app_face.c` / `app_face.h` 還沒有提供。
