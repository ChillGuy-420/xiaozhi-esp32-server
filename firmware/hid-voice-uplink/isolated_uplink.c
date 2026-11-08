/*
 * Device-side capture upload. Not compiled in the cloud HID image.
 * The capture pointer belongs to app_audio until app_audio_release().
 * The reply WAV belongs to app_tts_play_wav(), which must free it.
 * app_tts_cancel() must drop a reply that has not started playing.
 * This file never calls ntfy, a webhook, or hid_remote.
 */

#include "isolated_uplink.h"

#include "app_audio.h"
#include "app_tts.h"
#include "app_wifi.h"
#include "ima_adpcm.h"
#include "iso_voice.h"
#include "uplink_policy.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "iso_uplink";
static char s_url[256];
static char s_device_id[32];
static char s_credential[129];
static const char *s_ca;
static size_t s_ca_len;
static iso_voice_t *s_voice;
static int s_use_ima = 1;

static int post_wav(void *ctx, const uint8_t *wav, size_t len, uint8_t **resp, size_t *resp_len, int *http_status) {
    esp_http_client_config_t cfg = {
        .url = s_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 20000,
        .cert_pem = s_ca,
    };
    esp_http_client_handle_t client;
    int status;
    int read_len;
    uint8_t *body;
    (void)ctx;
    (void)s_ca_len;
    *resp = NULL;
    *resp_len = 0;
    *http_status = 0;
    if (!app_wifi_wait_connected(pdMS_TO_TICKS(10000))) {
        return -1;
    }
    client = esp_http_client_init(&cfg);
    if (client == NULL) {
        return -1;
    }
    esp_http_client_set_header(client, "Device-Id", s_device_id);
    esp_http_client_set_header(client, "Device-Credential", s_credential);
    esp_http_client_set_header(client, "Content-Type", "audio/wav");
    if (esp_http_client_open(client, len) != ESP_OK) {
        esp_http_client_cleanup(client);
        return -1;
    }
    if (esp_http_client_write(client, (const char *)wav, len) != (int)len) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return -1;
    }
    if (esp_http_client_fetch_headers(client) < 0) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return -1;
    }
    status = esp_http_client_get_status_code(client);
    *http_status = status;
    body = malloc(256 * 1024);
    if (body == NULL) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return -1;
    }
    read_len = esp_http_client_read_response(client, (char *)body, 256 * 1024);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    if (status != 200 || read_len < 44) {
        free(body);
        return 0;
    }
    *resp = body;
    *resp_len = (size_t)read_len;
    return 0;
}

static int play_owned(void *ctx, uint8_t *wav, size_t len) {
    (void)ctx;
    if (!app_tts_play_wav(wav, len)) {
        return -1;
    }
    return 0;
}

static void cancel_owned(void *ctx) {
    (void)ctx;
    app_tts_cancel();
}

static void release_owned(void *ctx) {
    (void)ctx;
    app_audio_release();
}

void iso_uplink_configure(const char *https_url, const char *device_id, const char *credential, const char *ca_pem,
                          size_t ca_len, int use_ima) {
    iso_voice_ops_t ops;
    memset(&ops, 0, sizeof(ops));
    ops.post_wav = post_wav;
    ops.play_wav = play_owned;
    ops.cancel_play = cancel_owned;
    ops.release_capture = release_owned;
    s_use_ima = use_ima;
    snprintf(s_url, sizeof(s_url), "%s", https_url ? https_url : "");
    snprintf(s_device_id, sizeof(s_device_id), "%s", device_id ? device_id : "");
    snprintf(s_credential, sizeof(s_credential), "%s", credential ? credential : "");
    s_ca = ca_pem;
    s_ca_len = ca_len;
    iso_voice_destroy(s_voice);
    s_voice = iso_voice_create(&ops, s_url, s_credential, s_ca, s_ca_len);
    if (uplink_check(s_url, s_credential, s_ca, s_ca_len) != UPLINK_OK) {
        ESP_LOGE(TAG, "isolated uplink refused before any network call");
    }
}

void iso_uplink_on_capture(const uint8_t *wav, size_t len) {
    uint8_t *upload = NULL;
    size_t upload_len = 0;
    size_t samples;
    if (s_voice == NULL) {
        app_audio_release();
        return;
    }
    if (s_use_ima && len > WAV_HEADER_LEN) {
        samples = (len - WAV_HEADER_LEN) / sizeof(int16_t);
        upload_len = ima_adpcm_wav_size(samples);
        upload = malloc(upload_len);
        if (upload != NULL &&
            ima_adpcm_wav_encode((const int16_t *)(wav + WAV_HEADER_LEN), samples, AUDIO_SAMPLE_RATE, upload,
                                 upload_len) == upload_len) {
            iso_voice_submit(s_voice, wav, len, upload, upload_len);
            free(upload);
            return;
        }
        free(upload);
    }
    iso_voice_submit(s_voice, wav, len, wav, len);
}

void iso_uplink_cancel(void) {
    if (s_voice != NULL) {
        iso_voice_cancel(s_voice);
    }
}
