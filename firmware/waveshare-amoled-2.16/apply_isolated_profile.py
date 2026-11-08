#!/usr/bin/env python3
"""Copy the isolated profile into a cloud checkout of 78/xiaozhi-esp32.

The checkout stays outside this repository. No endpoint, credential, or CA
is written. The embedded CA file is the UNPROVISIONED marker.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

APPEND = [
    "CONFIG_XIAOZHI_ISOLATED_PROFILE=y",
    'CONFIG_OTA_URL=""',
    "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=n",
    'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/isolated/waveshare_factory_16m.csv"',
    "CONFIG_FLASH_NONE_ASSETS=y",
]


def patch_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor missing in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_sources(root: Path) -> None:
    isolation = root / "main" / "isolation"
    isolation.mkdir(parents=True, exist_ok=True)
    for name in ("isolation_policy.h", "isolation_policy.c", "isolation_provision.cc", "private_ca.pem"):
        shutil.copyfile(HERE / name, isolation / name)
    partition_dir = root / "partitions" / "isolated"
    partition_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        HERE / "partitions" / "waveshare_factory_16m.csv",
        partition_dir / "waveshare_factory_16m.csv",
    )

    cmake = root / "main" / "CMakeLists.txt"
    patch_once(
        cmake,
        '            "main.cc"\n            )',
        '            "main.cc"\n'
        '            "isolation/isolation_policy.c"\n'
        '            "isolation/isolation_provision.cc"\n'
        "            )",
    )
    patch_once(
        cmake,
        'set(INCLUDE_DIRS "." "display"',
        'set(INCLUDE_DIRS "." "isolation" "display"',
    )
    patch_once(
        cmake,
        "idf_component_register(SRCS ${SOURCES}\n"
        "                    EMBED_FILES ${LANG_SOUNDS} ${COMMON_SOUNDS}",
        "idf_component_register(SRCS ${SOURCES}\n"
        '                    EMBED_FILES ${LANG_SOUNDS} ${COMMON_SOUNDS} "isolation/private_ca.pem"',
    )

    kconfig = root / "main" / "Kconfig.projbuild"
    patch_once(
        kconfig,
        '        The application will access this URL to check for new firmwares and server address.\n',
        '        The application will access this URL to check for new firmwares and server address.\n'
        "\n"
        "config XIAOZHI_ISOLATED_PROFILE\n"
        '    bool "Fail-closed isolated profile"\n'
        "    default n\n"
        "    help\n"
        "        Ignore the compiled OTA URL, require a private CA, and refuse an empty token.\n",
    )

    ota = root / "main" / "ota.cc"
    patch_once(ota, '#include "ota.h"\n', '#include "ota.h"\n#include "isolation_policy.h"\n')
    patch_once(
        ota,
        """std::string Ota::GetCheckVersionUrl() {
    Settings settings("wifi", false);
    std::string url = settings.GetString("ota_url");
    if (url.empty()) {
        url = CONFIG_OTA_URL;
    }
    return url;
}""",
        """std::string Ota::GetCheckVersionUrl() {
    Settings settings("wifi", false);
    std::string url = settings.GetString("ota_url");
#ifndef CONFIG_XIAOZHI_ISOLATED_PROFILE
    if (url.empty()) {
        url = CONFIG_OTA_URL;
    }
#endif
    return url;
}""",
    )
    patch_once(
        ota,
        """    std::string url = GetCheckVersionUrl();
    if (url.length() < 10) {""",
        """    std::string url = GetCheckVersionUrl();
#ifdef CONFIG_XIAOZHI_ISOLATED_PROFILE
    Settings isolated_settings("isolated", false);
    std::string device_credential = isolated_settings.GetString("device_credential");
    const char *allowed_url = nullptr;
    iso_result_t isolated_decision = isolation_check_ota(
        url.c_str(), CONFIG_OTA_URL, device_credential.c_str(), &allowed_url);
    if (isolated_decision != ISO_OK || allowed_url == nullptr) {
        ESP_LOGE(TAG, "isolated ota refused: %s", iso_result_name(isolated_decision));
        return std::unexpected(NetworkError::InvalidArgument());
    }
    url = allowed_url;
#endif
    if (url.length() < 10) {""",
    )
    patch_once(
        ota,
        """    auto http = SetupHttp();

    std::string data = board.GetSystemInfoJson();""",
        """    auto http = SetupHttp();
#ifdef CONFIG_XIAOZHI_ISOLATED_PROFILE
    http->SetHeader("Device-Credential", device_credential.c_str());
#endif

    std::string data = board.GetSystemInfoJson();""",
    )
    patch_once(
        ota,
        """    has_websocket_config_ = false;
    cJSON *websocket = cJSON_GetObjectItem(root, "websocket");
    if (cJSON_IsObject(websocket)) {""",
        """    has_websocket_config_ = false;
    cJSON *websocket = cJSON_GetObjectItem(root, "websocket");
#ifdef CONFIG_XIAOZHI_ISOLATED_PROFILE
    {
        const char *ws_url = "";
        const char *ws_token = "";
        if (cJSON_IsObject(websocket)) {
            cJSON *url_item = cJSON_GetObjectItem(websocket, "url");
            cJSON *token_item = cJSON_GetObjectItem(websocket, "token");
            if (cJSON_IsString(url_item)) {
                ws_url = url_item->valuestring;
            }
            if (cJSON_IsString(token_item)) {
                ws_token = token_item->valuestring;
            }
        }
        iso_result_t ws_decision = isolation_check_websocket(ws_url, ws_token);
        if (ws_decision != ISO_OK) {
            cJSON_Delete(root);
            ESP_LOGE(TAG, "isolated ota websocket refused: %s", iso_result_name(ws_decision));
            return std::unexpected(NetworkError::ProtocolError());
        }
    }
#endif
    if (cJSON_IsObject(websocket)) {""",
    )

    ws = root / "main" / "protocols" / "websocket_protocol.cc"
    patch_once(
        ws,
        '#include "websocket_protocol.h"\n',
        '#include "websocket_protocol.h"\n#include "isolation_policy.h"\n',
    )
    patch_once(
        ws,
        """    error_occurred_ = false;

    auto network = Board::GetInstance().GetNetwork();""",
        """    error_occurred_ = false;

#ifdef CONFIG_XIAOZHI_ISOLATED_PROFILE
    iso_result_t isolated_decision = isolation_check_websocket(url.c_str(), token.c_str());
    if (isolated_decision != ISO_OK) {
        ESP_LOGE(TAG, "isolated websocket refused: %s", iso_result_name(isolated_decision));
        return false;
    }
#endif

    auto network = Board::GetInstance().GetNetwork();""",
    )
    patch_once(
        ws,
        '    ESP_LOGI(TAG, "Connecting to websocket server: %s with version: %d", url.c_str(), version_);\n',
        """#ifdef CONFIG_XIAOZHI_ISOLATED_PROFILE
    ESP_LOGI(TAG, "isolated websocket connect version: %d", version_);
#else
    ESP_LOGI(TAG, "Connecting to websocket server: %s with version: %d", url.c_str(), version_);
#endif
""",
    )

    board = root / "main" / "boards" / "waveshare" / "esp32-s3-touch-amoled-2.16" / "config.json"
    config = json.loads(board.read_text(encoding="utf-8"))
    current = config["builds"][0]["sdkconfig_append"]
    for item in APPEND:
        if item not in current:
            current.append(item)
    board.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")


def patch_ssl(root: Path) -> None:
    matches = list(root.glob("managed_components/*esp-ml307*/src/esp/esp_ssl.cc"))
    if len(matches) != 1:
        raise SystemExit(f"esp_ssl.cc not downloaded yet: {matches}")
    path = matches[0]
    old = "    esp_tls_cfg_t cfg = {};\n    cfg.crt_bundle_attach = esp_crt_bundle_attach;\n"
    new = """    esp_tls_cfg_t cfg = {};
    const unsigned char *isolated_ca = nullptr;
    size_t isolated_ca_len = 0;
    if (isolation_private_ca != nullptr) {
        if (!isolation_private_ca(&isolated_ca, &isolated_ca_len) || isolated_ca == nullptr || isolated_ca_len == 0) {
            ESP_LOGE(TAG, "isolated tls refused: private CA missing");
            destroy_tls();
            return Fail(NetworkError::TlsFailed());
        }
        cfg.cacert_buf = isolated_ca;
        cfg.cacert_bytes = isolated_ca_len;
    } else {
        cfg.crt_bundle_attach = esp_crt_bundle_attach;
    }
"""
    text = path.read_text(encoding="utf-8")
    if "isolation_private_ca" not in text:
        if old not in text:
            raise SystemExit("ssl anchor missing")
        text = text.replace(old, new, 1)
        needle = "static const char *TAG = \"EspSsl\";\n"
        insert = needle + (
            "\nextern \"C\" __attribute__((weak)) int isolation_private_ca("
            "const unsigned char **buf, size_t *len);\n"
        )
        if needle not in text:
            raise SystemExit("ssl tag anchor missing")
        text = text.replace(needle, insert, 1)
        path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"sources", "ssl"}:
        raise SystemExit("usage: apply_isolated_profile.py sources|ssl <checkout>")
    root = Path(sys.argv[2]).resolve()
    if sys.argv[1] == "sources":
        apply_sources(root)
    else:
        patch_ssl(root)


if __name__ == "__main__":
    main()
